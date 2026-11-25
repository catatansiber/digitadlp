"""Alur kerja dokumen: upload, label, koreksi, persetujuan, rilis."""
from __future__ import annotations

import io
import json
import zipfile
from pathlib import PurePath

import pymupdf
from sqlalchemy import delete
from sqlalchemy.orm import Session

from ..models import Finding, Kind, Label
from ..policy import suggest_label
from ..detect.patterns import find_patterns
from .audit import record
from .corrections import _norm
from .jobs import enqueue
from .models import (
    Correction, CorrectionOp, Document, JobKind, Role, Status, User, utcnow,
)
from .processing import label_rules
from .storage import FileStore

MAX_UPLOAD = 50 * 1024 * 1024
EXTS = ("pdf", "docx")
MAX_TEXT = 200

MSG_FORBIDDEN = "Anda tidak punya akses untuk tindakan ini."
MSG_SELF = "Pemeriksa tidak boleh menyetujui dokumen yang ia unggah sendiri."
MSG_EXT = "Format file tidak didukung. Gunakan PDF atau DOCX."
MSG_SIZE = "Ukuran file melebihi batas 50 MB."
MSG_EMPTY = "File kosong."
MSG_BROKEN = "Dokumen terenkripsi atau rusak. Buka kunci atau simpan ulang file, lalu unggah lagi."


class WorkflowError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def _role(user: User, *roles: Role) -> None:
    if user.role not in roles:
        raise WorkflowError(403, MSG_FORBIDDEN)


def _state(doc: Document, *states: Status) -> None:
    if doc.status not in states:
        raise WorkflowError(
            409, f"Dokumen sedang berstatus {Status(doc.status).value}; "
                 "tindakan ini tidak bisa dilakukan.")


def _record(db, user, action, doc, detail=""):
    try:
        record(db, user, action, doc, detail)
    except ValueError as exc:  # pesan record() tidak memuat isi detail
        db.rollback()
        raise WorkflowError(422, str(exc)) from None


def _ext_of(filename: str, data: bytes) -> str:
    ext = PurePath(filename or "").suffix.lower().lstrip(".")
    if ext not in EXTS:
        raise WorkflowError(415, MSG_EXT)
    if len(data) > MAX_UPLOAD:
        raise WorkflowError(413, MSG_SIZE)
    if not data:
        raise WorkflowError(422, MSG_EMPTY)
    if not _readable(ext, data):
        raise WorkflowError(422, MSG_BROKEN)
    return ext


def _readable(ext: str, data: bytes) -> bool:
    """Cek cepat di memori sebelum apa pun ditulis (PDF terenkripsi/rusak, DOCX bukan zip)."""
    if ext == "pdf":
        try:
            d = pymupdf.open(stream=data, filetype="pdf")
        except Exception:  # noqa: BLE001 - pymupdf melempar berbagai tipe
            return False
        try:
            return d.is_pdf and not (d.needs_pass or d.is_encrypted)
        finally:
            d.close()
    return zipfile.is_zipfile(io.BytesIO(data))


def upload(db: Session, store: FileStore, user: User, filename: str, data: bytes) -> Document:
    _role(user, Role.PENGUNGGAH, Role.PEMERIKSA)
    ext = _ext_of(filename, data)
    title = PurePath(filename).name[:300]
    doc = Document(title=title, ext=ext, owner_id=user.id, unit_id=user.unit_id,
                   status=Status.DIPROSES)
    db.add(doc)
    db.flush()
    store.put(doc.id, f"source.{ext}", data)
    enqueue(db, JobKind.DETEKSI, doc)
    _record(db, user, "upload", doc, detail=f"ext={ext}")
    db.commit()
    return doc


def set_label(db: Session, user: User, doc: Document, label: str) -> Document:
    _role(user, Role.PEMERIKSA)
    _state(doc, Status.MENUNGGU_CEK)
    try:
        label = Label(label).value
    except ValueError:
        raise WorkflowError(422, "Label tidak dikenal.") from None
    doc.label = label
    doc.label_set_by_reviewer = True
    _record(db, user, "ubah_label", doc, detail=f"label={label}")
    db.commit()
    return doc


def _apply_to_findings(pages: list[list[dict]], op, kind, text, page) -> list[list[dict]]:
    if op == CorrectionOp.ABAIKAN:
        target = _norm(text)
        return [[f for f in p if not (_norm(f["text"]) == target
                                      and (page is None or f.get("page") == page))]
                for p in pages]
    pages[page].append({"kind": kind, "text": text, "page": page,
                        "start": -1, "end": -1, "source": "manual"})
    return pages


def _findings(pages: list[list[dict]]) -> list[Finding]:
    out = []
    for p in pages:
        for f in p:
            try:
                out.append(Finding(Kind(f["kind"]), f["start"], f["end"], f["text"], f["source"]))
            except (KeyError, ValueError):
                continue
    return out


def add_correction(db: Session, user: User, doc: Document, op: str, kind: str,
                   text: str, page: int | None, *, store: FileStore | None = None
                   ) -> Correction:
    """`store` (opsional) dipakai untuk menghapus versi yang sudah dibuat."""
    _role(user, Role.PEMERIKSA)
    _state(doc, Status.MENUNGGU_CEK, Status.DISETUJUI)
    try:
        op = CorrectionOp(op)
        kind = Kind(kind).value
    except ValueError:
        raise WorkflowError(422, "Jenis koreksi atau jenis data tidak dikenal.") from None
    if not isinstance(text, str) or not 1 <= len(text.strip()) or len(text) > MAX_TEXT:
        raise WorkflowError(422, "Teks koreksi harus 1 sampai 200 karakter.")
    pages = json.loads(doc.findings_json or "[]")
    if op == CorrectionOp.TAMBAH and (page is None or not 0 <= page < len(pages)):
        raise WorkflowError(422, "Halaman koreksi di luar jangkauan.")
    if op == CorrectionOp.ABAIKAN and page is not None and not 0 <= page < len(pages):
        raise WorkflowError(422, "Halaman koreksi di luar jangkauan.")
    c = Correction(document_id=doc.id, kind=kind, page=page, text=text, op=op,
                   author_id=user.id)
    db.add(c)
    pages = _apply_to_findings(pages, op, kind, text, page)
    doc.findings_json = json.dumps(pages, ensure_ascii=False)
    doc.suggested_label = suggest_label(_findings(pages), label_rules(db)).value
    if not doc.label_set_by_reviewer:
        doc.label = doc.suggested_label
    _invalidate(doc)
    _record(db, user, "koreksi", doc, detail=f"op={op.value} kind={kind}")
    db.commit()
    if store is not None:
        store.delete_versions(doc.id)
    return c


def _invalidate(doc: Document) -> None:
    doc.revision += 1
    doc.approved_at = None
    doc.reviewer_id = None
    doc.status = Status.MENUNGGU_CEK


def approve(db: Session, user: User, doc: Document) -> Document:
    _role(user, Role.PEMERIKSA)
    _state(doc, Status.MENUNGGU_CEK)
    if doc.owner_id == user.id:
        raise WorkflowError(403, MSG_SELF)
    doc.reviewer_id = user.id
    doc.approved_at = utcnow()
    doc.status = Status.MEMBUAT_VERSI
    enqueue(db, JobKind.VERSI, doc)
    _record(db, user, "setujui", doc)
    db.commit()
    return doc


MAX_REASON = 200


def return_to_owner(db: Session, user: User, doc: Document, reason: str) -> Document:
    _role(user, Role.PEMERIKSA)
    _state(doc, Status.MENUNGGU_CEK)
    reason = reason or ""
    if len(reason) > MAX_REASON:
        raise WorkflowError(422, "Alasan terlalu panjang (maksimal 200 karakter).")
    if find_patterns(reason):  # alasan disimpan (hanya terlihat oleh pemeriksa/unit pemilik), jadi ditolak bila memuat data pribadi
        raise WorkflowError(422, "Rincian audit tidak boleh memuat data pribadi.")
    doc.status = Status.DIKEMBALIKAN
    doc.return_reason = reason or None
    _record(db, user, "kembalikan", doc, detail=f"alasan_len={len(reason or '')}")
    db.commit()
    return doc


def reupload(db: Session, store: FileStore, user: User, doc: Document,
             filename: str, data: bytes) -> Document:
    if doc.owner_id != user.id:
        raise WorkflowError(403, MSG_FORBIDDEN)
    _state(doc, Status.DIKEMBALIKAN, Status.GAGAL)
    ext = _ext_of(filename, data)
    store.delete_versions(doc.id)
    store.put(doc.id, f"source.{ext}", data)
    doc.ext = ext
    doc.revision += 1
    doc.approved_at = None
    doc.reviewer_id = None
    doc.findings_json = "[]"
    doc.return_reason = None
    doc.status = Status.DIPROSES
    db.execute(delete(Correction).where(Correction.document_id == doc.id))
    enqueue(db, JobKind.DETEKSI, doc)
    _record(db, user, "upload", doc, detail=f"ext={ext} ulang")
    db.commit()
    # Setelah commit: kegagalan hanya menyisakan file yatim, bukan dokumen tanpa sumber.
    store.delete_source(doc.id, keep=ext)
    return doc


def release(db: Session, user: User, doc: Document) -> Document:
    _role(user, Role.PEMERIKSA, Role.ADMIN)
    _state(doc, Status.DISETUJUI)
    doc.status = Status.DIRILIS
    doc.released_at = utcnow()
    _record(db, user, "rilis", doc)
    db.commit()
    return doc
