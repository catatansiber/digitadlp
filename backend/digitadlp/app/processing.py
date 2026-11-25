"""Pemrosesan dokumen: deteksi temuan dan pembuatan tiga versi."""
from __future__ import annotations

import json
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..detect.employees import EmployeeDirectory
from ..detect.ner import NerDetector
from ..detect.pipeline import detect
from ..models import Finding, Kind, Label, Version
from ..policy import suggest_label
from ..redact.docx import detect_docx, redact_docx
from ..redact.pdf import extract_pdf_extras, extract_pdf_text, redact_pdf
from .audit import record
from .corrections import apply_corrections, corrected_detect_fn
from .models import Correction, Document, LabelRule, Status
from .storage import FileStore

VERSIONS = ("publik", "internal", "rahasia")


class Engine:
    """NER + direktori pegawai. Direktori bisa diganti saat berjalan (impor
    admin); penggantian memakai kunci dan referensi objek baru yang tidak
    diubah lagi, jadi job cukup membaca `directory` sekali di awal."""

    def __init__(self, ner: NerDetector, directory: EmployeeDirectory):
        self.ner = ner
        self._directory = directory
        self._lock = threading.Lock()

    @property
    def directory(self) -> EmployeeDirectory:
        with self._lock:
            return self._directory

    def set_directory(self, directory: EmployeeDirectory) -> None:
        with self._lock:
            self._directory = directory


Touch = Callable[[], None]


def _noop() -> None:
    pass


def _ext(doc: Document) -> str:
    return doc.ext.lower().lstrip(".")


def load_corrections(db: Session, doc_id: str) -> list[SimpleNamespace]:
    """Salinan koreksi (bukan objek ORM) agar aman dipakai lintas commit."""
    return [
        SimpleNamespace(kind=c.kind, page=c.page, text=c.text, op=c.op)
        for c in db.scalars(
            select(Correction)
            .where(Correction.document_id == doc_id)
            .order_by(Correction.created_at)
        )
    ]


def label_rules(db: Session) -> dict[Kind, Label]:
    rules: dict[Kind, Label] = {}
    for r in db.scalars(select(LabelRule)):
        try:
            rules[Kind(r.kind)] = Label(r.label)
        except ValueError:
            continue
    return rules


def _analyze(src: Path, ext: str, engine: Engine, corrections, directory=None):
    """Temuan (sudah dikoreksi) per halaman, temuan ekstra PDF, dan detect_fn."""
    directory = directory if directory is not None else engine.directory

    def base(text: str) -> list[Finding]:
        return detect(text, engine.ner, directory)

    fn = corrected_detect_fn(base, corrections)
    if ext == "pdf":
        raw = [base(t) for t in extract_pdf_text(src)]
        pages = apply_corrections(raw, corrections)
        extras = [f for t in extract_pdf_extras(src) for f in fn(t)]
        return pages, extras, fn
    return [detect_docx(src, fn)], [], fn


def _entry(f: Finding, page: int | None) -> dict:
    return {
        "kind": f.kind.value, "text": f.text, "page": page,
        "start": f.start, "end": f.end, "source": f.source,
    }


def serialize(pages: list[list[Finding]], extras: list[Finding] = ()) -> str:
    """List per halaman. Temuan ekstra PDF (metadata, anotasi) ikut di daftar
    halaman pertama dengan page=null, supaya jumlah halaman tetap."""
    out = [[_entry(f, i) for f in page] for i, page in enumerate(pages)]
    if extras:
        if not out:
            out.append([])
        out[0].extend(_entry(f, None) for f in extras)
    return json.dumps(out, ensure_ascii=False)


@dataclass
class DeteksiResult:
    findings_json: str
    label: Label


def compute_deteksi(
    db: Session, store: FileStore, engine: Engine, doc: Document, touch: Touch = _noop
) -> DeteksiResult:
    """Hitung temuan tanpa menulis apa pun ke DB."""
    ext, doc_id = _ext(doc), doc.id
    corrections = load_corrections(db, doc_id)
    rules = label_rules(db)
    with store.decrypted(doc_id, f"source.{ext}") as src:
        pages, extras, _ = _analyze(src, ext, engine, corrections)
    touch()
    label = suggest_label([f for p in pages for f in p] + extras, rules)
    return DeteksiResult(serialize(pages, extras), label)


def apply_deteksi(db: Session, doc: Document, result: DeteksiResult) -> None:
    doc.findings_json = result.findings_json
    doc.suggested_label = result.label.value
    if not doc.label_set_by_reviewer:
        doc.label = result.label.value
    doc.status = Status.MENUNGGU_CEK
    record(db, None, "deteksi_selesai", doc, detail=f"label={result.label.value}")


def render_versi(
    db: Session, store: FileStore, engine: Engine, doc: Document, tmpdir: Path,
    touch: Touch = _noop,
) -> dict[str, Path]:
    """Buat ketiga versi ke tmpdir (tidak menyentuh store atau DB)."""
    ext, doc_id = _ext(doc), doc.id
    corrections = load_corrections(db, doc_id)
    directory = engine.directory  # sekali per job
    out: dict[str, Path] = {}
    with store.decrypted(doc_id, f"source.{ext}") as src:
        # Selalu hitung ulang dari sumber; findings_json tidak dipercaya.
        if ext == "pdf":
            pages, _, fn = _analyze(src, ext, engine, corrections, directory)
        else:
            fn = corrected_detect_fn(
                lambda t: detect(t, engine.ner, directory), corrections
            )
        touch()
        for v in VERSIONS:
            dst = tmpdir / f"{v}.{ext}"
            if ext == "pdf":
                redact_pdf(src, dst, pages, Version(v), fn)
            else:
                redact_docx(src, dst, fn, Version(v))
            out[v] = dst
            touch()
    return out


def store_versi(store: FileStore, doc: Document, files: dict[str, Path]) -> None:
    ext = _ext(doc)
    store.delete_versions(doc.id)
    try:
        for v in VERSIONS:
            store.put_file(doc.id, f"{v}.{ext}", files[v])
    except BaseException:
        store.delete_versions(doc.id)
        raise
    doc.status = Status.DISETUJUI
