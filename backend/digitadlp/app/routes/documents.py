import json

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .. import workflow
from ..models import Correction, Document, Role, User
from ..security import current_user, get_db

router = APIRouter(prefix="/documents", tags=["documents"])
MSG_NOT_FOUND = "Dokumen tidak ditemukan."


def can_view(user: User, doc: Document) -> bool:
    return (user.role == Role.PEMERIKSA or doc.owner_id == user.id
            or doc.unit_id == user.unit_id)


def can_see_rahasia(user: User, doc: Document) -> bool:
    return user.role == Role.PEMERIKSA or doc.unit_id == user.unit_id


def _load(db: Session, user: User, doc_id: str, allow_admin: bool = False) -> Document:
    doc = db.get(Document, doc_id)
    if doc is None or not (can_view(user, doc) or (allow_admin and user.role == Role.ADMIN)):
        raise HTTPException(404, MSG_NOT_FOUND)
    return doc


def _iso(dt):
    return dt.isoformat() if dt else None


def _out(doc: Document, db: Session | None = None, detail: bool = False) -> dict:
    out = {
        "id": doc.id, "title": doc.title, "ext": doc.ext, "status": doc.status.value,
        "owner_id": doc.owner_id, "unit_id": doc.unit_id, "label": doc.label,
        "suggested_label": doc.suggested_label, "reviewer_id": doc.reviewer_id,
        "approved_at": _iso(doc.approved_at), "released_at": _iso(doc.released_at),
        "revision": doc.revision, "created_at": _iso(doc.created_at),
    }
    if detail:
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
    return _out(doc)


@router.get("")
def list_docs(user: User = Depends(current_user), db: Session = Depends(get_db)):
    q = select(Document).order_by(Document.created_at.desc())
    if user.role != Role.PEMERIKSA:
        q = q.where(or_(Document.owner_id == user.id, Document.unit_id == user.unit_id))
    return [_out(d) for d in db.scalars(q)]


@router.get("/{doc_id}")
def get_doc(doc_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    doc = _load(db, user, doc_id)
    return _out(doc, db, detail=can_see_rahasia(user, doc))


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
    return _out(_run(workflow.set_label, db, user, doc, body.label))


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
    return _out(_run(workflow.approve, db, user, doc))


@router.post("/{doc_id}/return")
def post_return(doc_id: str, body: ReasonIn, user: User = Depends(current_user),
                db: Session = Depends(get_db)):
    doc = _load(db, user, doc_id)
    return _out(_run(workflow.return_to_owner, db, user, doc, body.reason))


@router.post("/{doc_id}/reupload")
async def post_reupload(doc_id: str, request: Request, file: UploadFile = File(...),
                        user: User = Depends(current_user), db: Session = Depends(get_db)):
    doc = _load(db, user, doc_id)
    data = await _read(file)
    return _out(_run(workflow.reupload, db, request.app.state.store, user, doc,
                     file.filename or "", data))


@router.post("/{doc_id}/release")
def post_release(doc_id: str, user: User = Depends(current_user),
                 db: Session = Depends(get_db)):
    doc = _load(db, user, doc_id, allow_admin=True)
    return _out(_run(workflow.release, db, user, doc))
