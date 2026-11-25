"""Pemrosesan dokumen: deteksi temuan dan pembuatan tiga versi."""
from __future__ import annotations

import json
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

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


@dataclass
class Engine:
    ner: NerDetector
    directory: EmployeeDirectory


def _ext(doc: Document) -> str:
    return doc.ext.lower().lstrip(".")


def _corrections(db: Session, doc: Document) -> list[Correction]:
    return list(
        db.scalars(
            select(Correction)
            .where(Correction.document_id == doc.id)
            .order_by(Correction.created_at)
        )
    )


def label_rules(db: Session) -> dict[Kind, Label]:
    rules: dict[Kind, Label] = {}
    for r in db.scalars(select(LabelRule)):
        try:
            rules[Kind(r.kind)] = Label(r.label)
        except ValueError:
            continue
    return rules


def _analyze(
    src: Path, ext: str, engine: Engine, corrections: list[Correction]
) -> tuple[list[list[Finding]], list[Finding], Callable[[str], list[Finding]]]:
    """Hitung temuan (sudah dikoreksi) per halaman + temuan ekstra PDF."""

    def base(text: str) -> list[Finding]:
        return detect(text, engine.ner, engine.directory)

    fn = corrected_detect_fn(base, corrections)
    if ext == "pdf":
        raw = [base(t) for t in extract_pdf_text(src)]
        pages = apply_corrections(raw, corrections)
        extras = [f for t in extract_pdf_extras(src) for f in fn(t)]
        return pages, extras, fn
    return [detect_docx(src, fn)], [], fn


def serialize(pages: list[list[Finding]]) -> str:
    return json.dumps(
        [
            [
                {
                    "kind": f.kind.value, "text": f.text, "page": i,
                    "start": f.start, "end": f.end, "source": f.source,
                }
                for f in page
            ]
            for i, page in enumerate(pages)
        ],
        ensure_ascii=False,
    )


def run_deteksi(db: Session, store: FileStore, engine: Engine, doc: Document) -> None:
    ext = _ext(doc)
    corrections = _corrections(db, doc)
    with store.decrypted(doc.id, f"source.{ext}") as src:
        pages, extras, _ = _analyze(src, ext, engine, corrections)
    label = suggest_label([f for p in pages for f in p] + extras, label_rules(db))
    doc.findings_json = serialize(pages)
    doc.suggested_label = label.value
    doc.label = label.value
    doc.status = Status.MENUNGGU_CEK
    record(db, None, "deteksi_selesai", doc, detail=f"label={label.value}")


def run_versi(db: Session, store: FileStore, engine: Engine, doc: Document) -> None:
    ext = _ext(doc)
    corrections = _corrections(db, doc)
    store.delete_versions(doc.id)
    with tempfile.TemporaryDirectory(prefix="digitadlp-") as tmp:
        tmpdir = Path(tmp)
        with store.decrypted(doc.id, f"source.{ext}") as src:
            if ext == "pdf":
                # Selalu hitung ulang dari sumber; findings_json tidak dipercaya.
                pages, _, fn = _analyze(src, ext, engine, corrections)
            else:
                fn = corrected_detect_fn(
                    lambda t: detect(t, engine.ner, engine.directory), corrections
                )
            for v in VERSIONS:
                dst = tmpdir / f"{v}.{ext}"
                if ext == "pdf":
                    redact_pdf(src, dst, pages, Version(v), fn)
                else:
                    redact_docx(src, dst, fn, Version(v))
        try:
            for v in VERSIONS:
                store.put_file(doc.id, f"{v}.{ext}", tmpdir / f"{v}.{ext}")
        except BaseException:
            store.delete_versions(doc.id)
            raise
    doc.status = Status.DISETUJUI
