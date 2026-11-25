import json

from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .. import workflow
from ..access import VERSIONS, can_download, can_see_rahasia, can_view
from ..audit import record
from ..models import Correction, Document, Role, Status, Unit, User
from ..storage import StoreError
from ...redact.docx import extract_docx_text
from ...redact.pdf import extract_pdf_text
from ..security import current_user, get_db

router = APIRouter(prefix="/api/documents", tags=["documents"])
MSG_NOT_FOUND = "Dokumen tidak ditemukan."


def _load(db: Session, user: User, doc_id: str, allow_admin: bool = False) -> Document:
    doc = db.get(Document, doc_id)
    if doc is None or not (can_view(user, doc) or (allow_admin and user.role == Role.ADMIN)):
        raise HTTPException(404, MSG_NOT_FOUND)
    return doc


def _iso(dt):
    return dt.isoformat() if dt else None


def _out(doc: Document, db: Session, detail: bool = False) -> dict:
    owner = db.get(User, doc.owner_id)
    unit = db.get(Unit, doc.unit_id)
    out = {
        "id": doc.id, "title": doc.title, "ext": doc.ext, "status": doc.status.value,
        "owner_id": doc.owner_id, "unit_id": doc.unit_id, "label": doc.label,
        "suggested_label": doc.suggested_label, "reviewer_id": doc.reviewer_id,
        "approved_at": _iso(doc.approved_at), "released_at": _iso(doc.released_at),
        "revision": doc.revision, "created_at": _iso(doc.created_at),
        "owner_name": owner.full_name if owner else None,
        "unit_name": unit.name if unit else None,
    }
    if detail:
        out["return_reason"] = doc.return_reason
        out["findings"] = json.loads(doc.findings_json or "[]")
        out["corrections"] = [
            {"id": c.id, "op": c.op.value, "kind": c.kind, "text": c.text, "page": c.page,
             "author_id": c.author_id, "created_at": _iso(c.created_at)}
            for c in db.scalars(select(Correction).where(Correction.document_id == doc.id)
                                .order_by(Correction.created_at))
        ]
    return out


def _run(fn, *args, **kw):
    try:
        return fn(*args, **kw)
    except workflow.WorkflowError as e:
        raise HTTPException(e.status, e.message) from None


async def _read(file: UploadFile) -> bytes:
    data = await file.read(workflow.MAX_UPLOAD + 1)
    if len(data) > workflow.MAX_UPLOAD:
        raise HTTPException(413, workflow.MSG_SIZE)
    return data


@router.post("", status_code=201)
async def upload_doc(request: Request, file: UploadFile = File(...),
                     user: User = Depends(current_user), db: Session = Depends(get_db)):
    if user.role not in (Role.PENGUNGGAH, Role.PEMERIKSA):
        raise HTTPException(403, workflow.MSG_FORBIDDEN)
    data = await _read(file)
    doc = _run(workflow.upload, db, request.app.state.store, user, file.filename or "", data)
    return _out(doc, db)


@router.get("")
def list_docs(status: str | None = None, mine: bool = False,
              user: User = Depends(current_user), db: Session = Depends(get_db)):
    q = (select(Document, User.full_name, Unit.name)
         .join(User, User.id == Document.owner_id).join(Unit, Unit.id == Document.unit_id)
         .order_by(Document.created_at.desc()))
    if status is not None:
        if status not in {s.value for s in Status}:
            raise HTTPException(422, "Status tidak dikenal.")
        q = q.where(Document.status == Status(status))
    if mine:
        q = q.where(Document.owner_id == user.id)
    elif user.role != Role.PEMERIKSA:
        q = q.where(or_(Document.owner_id == user.id, Document.unit_id == user.unit_id))
    return [
        {"id": d.id, "title": d.title, "ext": d.ext, "status": d.status.value,
         "label": d.label, "suggested_label": d.suggested_label,
         "owner": owner, "unit": unit, "owner_name": owner, "unit_name": unit,
         "created_at": _iso(d.created_at)}
        for d, owner, unit in db.execute(q)
    ]


MSG_DENIED = "Anda tidak punya akses ke versi ini."
MIME = {"pdf": "application/pdf",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}


@router.get("/{doc_id}/versions/{version}")
def download_version(doc_id: str, version: str, request: Request,
                     user: User = Depends(current_user), db: Session = Depends(get_db)):
    doc = db.get(Document, doc_id)
    if doc is None:
        raise HTTPException(404, MSG_NOT_FOUND)
    if version not in VERSIONS:
        raise HTTPException(404, "Versi tidak ditemukan.")
    if not can_download(user, doc, version):
        record(db, user, "akses_ditolak", doc, detail=f"versi={version}")
        db.commit()
        # 404 hanya bila pengguna tidak bisa melihat dokumen dan tidak punya versi apa pun.
        if not can_view(user, doc) and not any(can_download(user, doc, v) for v in VERSIONS):
            raise HTTPException(404, MSG_NOT_FOUND)
        raise HTTPException(403, MSG_DENIED)
    store = request.app.state.store
    try:
        data = store.get(doc.id, f"{version}.{doc.ext}")
    except StoreError:
        raise HTTPException(404, "Versi belum tersedia.") from None
    record(db, user, "unduh", doc, detail=f"versi={version}")
    db.commit()
    return Response(
        data, media_type=MIME.get(doc.ext, "application/octet-stream"),
        headers={"Content-Disposition": f'attachment; filename="{doc.id}-{version}.{doc.ext}"',
                 "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})


@router.get("/{doc_id}")
def get_doc(doc_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    doc = _load(db, user, doc_id)
    return _out(doc, db, detail=can_see_rahasia(user, doc))


MSG_DOC_ERROR = "Teks dokumen tidak dapat dibaca."


@router.get("/{doc_id}/text")
def get_text(doc_id: str, request: Request, user: User = Depends(current_user),
             db: Session = Depends(get_db)):
    doc = _load(db, user, doc_id)
    if not can_see_rahasia(user, doc):
        raise HTTPException(404, MSG_NOT_FOUND)
    try:
        with request.app.state.store.decrypted(doc.id, f"source.{doc.ext}") as src:
            pages = extract_pdf_text(src) if doc.ext == "pdf" else extract_docx_text(src)
    except Exception:  # noqa: BLE001 - jangan bocorkan isi/galat ekstraksi
        raise HTTPException(422, MSG_DOC_ERROR) from None
    record(db, user, "unduh", doc, detail="versi=teks")
    db.commit()
    return JSONResponse({"pages": list(pages)}, headers={"Cache-Control": "no-store"})


class LabelIn(BaseModel):
    label: str


class CorrectionIn(BaseModel):
    op: str
    kind: str
    text: str
    page: int | None = None


class ReasonIn(BaseModel):
    reason: str = ""


@router.put("/{doc_id}/label")
def put_label(doc_id: str, body: LabelIn, user: User = Depends(current_user),
              db: Session = Depends(get_db)):
    doc = _load(db, user, doc_id)
    return _out(_run(workflow.set_label, db, user, doc, body.label), db)


@router.post("/{doc_id}/corrections")
def post_correction(doc_id: str, body: CorrectionIn, request: Request,
                    user: User = Depends(current_user), db: Session = Depends(get_db)):
    doc = _load(db, user, doc_id)
    _run(workflow.add_correction, db, user, doc, body.op, body.kind, body.text, body.page,
         store=request.app.state.store)
    return _out(doc, db, detail=True)


@router.post("/{doc_id}/approve")
def post_approve(doc_id: str, user: User = Depends(current_user),
                 db: Session = Depends(get_db)):
    doc = _load(db, user, doc_id)
    return _out(_run(workflow.approve, db, user, doc), db)


@router.post("/{doc_id}/return")
def post_return(doc_id: str, body: ReasonIn, user: User = Depends(current_user),
                db: Session = Depends(get_db)):
    doc = _load(db, user, doc_id)
    return _out(_run(workflow.return_to_owner, db, user, doc, body.reason), db)


@router.post("/{doc_id}/reupload")
async def post_reupload(doc_id: str, request: Request, file: UploadFile = File(...),
                        user: User = Depends(current_user), db: Session = Depends(get_db)):
    doc = _load(db, user, doc_id)
    data = await _read(file)
    return _out(_run(workflow.reupload, db, request.app.state.store, user, doc,
                     file.filename or "", data), db)


@router.post("/{doc_id}/release")
def post_release(doc_id: str, user: User = Depends(current_user),
                 db: Session = Depends(get_db)):
    doc = _load(db, user, doc_id, allow_admin=True)
    return _out(_run(workflow.release, db, user, doc), db)
