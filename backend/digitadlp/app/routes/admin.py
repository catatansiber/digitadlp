"""Endpoint Admin: unit, pengguna, daftar pegawai, aturan label, audit."""
import io

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ...detect.employees import EmployeeDirectory
from ...models import Finding, Kind, Label
from ...policy import default_label_for
from ..audit import record
from ..models import AuditEvent, AuthSession, LabelRule, Role, Unit, User
from ..processing import label_rules
from ..security import COOKIE_NAME, _digest, get_db, hash_password, require_role

router = APIRouter(prefix="/api/admin", tags=["admin"],
                   dependencies=[Depends(require_role(Role.ADMIN))])
admin_user = require_role(Role.ADMIN)

EMPLOYEES_BLOB = "employees.xlsx"
MAX_XLSX = 10 * 1024 * 1024
MIN_PASSWORD = 10
MSG_PASSWORD = f"Kata sandi minimal {MIN_PASSWORD} karakter."
MSG_UNIT_EXISTS = "Unit kerja sudah ada."
MSG_UNIT_MISSING = "Unit kerja tidak ditemukan."
MSG_USER_EXISTS = "Nama pengguna sudah dipakai."
MSG_USER_MISSING = "Pengguna tidak ditemukan."
MSG_SELF = "Admin tidak bisa menonaktifkan atau menurunkan peran akunnya sendiri."
MSG_XLSX_EXT = "Format file tidak didukung. Gunakan .xlsx."
MSG_XLSX_SIZE = "Ukuran file melebihi batas 10 MB."
MSG_XLSX_BAD = "File daftar pegawai tidak bisa dibaca. Gunakan .xlsx dengan kolom Nama."
MSG_RULES = "Aturan label tidak valid."


def _audit(db: Session, actor: User, action: str, detail: str = "") -> None:
    try:
        record(db, actor, action, None, detail)
    except ValueError as exc:  # pesan record() tidak memuat isi detail
        db.rollback()
        raise HTTPException(422, str(exc)) from None


# ---- units -----------------------------------------------------------------

class UnitIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)


def _unit_out(u: Unit) -> dict:
    return {"id": u.id, "name": u.name}


@router.get("/units")
def list_units(db: Session = Depends(get_db)):
    return [_unit_out(u) for u in db.scalars(select(Unit).order_by(Unit.name))]


@router.post("/units", status_code=201)
def create_unit(body: UnitIn, actor: User = Depends(admin_user), db: Session = Depends(get_db)):
    name = body.name.strip()
    if not name:
        raise HTTPException(422, "Nama unit kerja wajib diisi.")
    unit = Unit(name=name)
    db.add(unit)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, MSG_UNIT_EXISTS) from None
    _audit(db, actor, "unit_dibuat", f"unit={unit.id}")
    db.commit()
    return _unit_out(unit)


# ---- users -----------------------------------------------------------------

class UserIn(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    full_name: str = Field(min_length=1, max_length=200)
    role: Role
    unit_id: str
    password: str = Field(max_length=1024)


class UserPatch(BaseModel):
    role: Role | None = None
    unit_id: str | None = None
    active: bool | None = None
    password: str | None = Field(default=None, max_length=1024)
    full_name: str | None = Field(default=None, min_length=1, max_length=200)


def _user_out(u: User) -> dict:
    return {"id": u.id, "username": u.username, "full_name": u.full_name,
            "role": u.role.value, "unit_id": u.unit_id, "unit": u.unit.name,
            "active": u.active}


def _check_password(pw: str) -> None:
    if len(pw) < MIN_PASSWORD:
        raise HTTPException(422, MSG_PASSWORD)


def _unit(db: Session, unit_id: str) -> Unit:
    unit = db.get(Unit, unit_id)
    if unit is None:
        raise HTTPException(422, MSG_UNIT_MISSING)
    return unit


@router.get("/users")
def list_users(db: Session = Depends(get_db)):
    return [_user_out(u) for u in db.scalars(select(User).order_by(User.username))]


@router.post("/users", status_code=201)
def create_user(body: UserIn, actor: User = Depends(admin_user), db: Session = Depends(get_db)):
    _check_password(body.password)
    _unit(db, body.unit_id)
    username = body.username.strip()
    if not username:
        raise HTTPException(422, "Nama pengguna wajib diisi.")
    user = User(username=username, full_name=body.full_name.strip() or username,
                password_hash=hash_password(body.password), role=body.role,
                unit_id=body.unit_id)
    db.add(user)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, MSG_USER_EXISTS) from None
    # Hanya id dan peran: nama pengguna bisa saja berupa NIP.
    _audit(db, actor, "user_dibuat", f"user={user.id} role={user.role.value}")
    db.commit()
    db.refresh(user)
    return _user_out(user)


@router.patch("/users/{user_id}")
def patch_user(user_id: str, body: UserPatch, request: Request, actor: User = Depends(admin_user),
               db: Session = Depends(get_db)):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(404, MSG_USER_MISSING)
    if user.id == actor.id and (body.active is False
                                or (body.role is not None and body.role != Role.ADMIN)):
        raise HTTPException(409, MSG_SELF)
    changed: list[str] = []
    kill_sessions = False
    if body.role is not None and body.role != user.role:
        user.role = body.role
        kill_sessions = True
        changed.append(f"role={body.role.value}")
    if body.unit_id is not None and body.unit_id != user.unit_id:
        _unit(db, body.unit_id)
        user.unit_id = body.unit_id
        changed.append(f"unit={body.unit_id}")
    if body.full_name is not None:
        new_name = body.full_name.strip() or user.full_name
        if new_name != user.full_name:
            user.full_name = new_name
            changed.append("nama")
    if body.password is not None:
        _check_password(body.password)
        user.password_hash = hash_password(body.password)
        kill_sessions = True
        changed.append("password=reset")
    if body.active is not None and body.active != user.active:
        user.active = body.active
        kill_sessions = kill_sessions or not body.active
        changed.append(f"active={int(body.active)}")
    if kill_sessions:
        q = delete(AuthSession).where(AuthSession.user_id == user.id)
        if user.id == actor.id:  # reset sandi sendiri: sesi saat ini tetap
            q = q.where(AuthSession.token_hash != _digest(request.cookies.get(COOKIE_NAME, "")))
        db.execute(q)
    _audit(db, actor, "user_diubah", f"user={user.id} " + " ".join(changed))
    db.commit()
    db.refresh(user)
    return _user_out(user)


# ---- employees -------------------------------------------------------------

def load_directory(data: bytes) -> EmployeeDirectory:
    return EmployeeDirectory.from_xlsx(io.BytesIO(data))


@router.post("/employees")
async def import_employees(request: Request, file: UploadFile = File(...),
                           actor: User = Depends(admin_user), db: Session = Depends(get_db)):
    if not (file.filename or "").lower().endswith(".xlsx"):
        raise HTTPException(415, MSG_XLSX_EXT)
    data = await file.read(MAX_XLSX + 1)
    if len(data) > MAX_XLSX:
        raise HTTPException(413, MSG_XLSX_SIZE)
    # Parse di memori dulu: file buruk tidak mengganti daftar yang berlaku.
    try:
        directory = load_directory(data)
    except Exception:  # noqa: BLE001 - openpyxl melempar berbagai tipe
        raise HTTPException(422, MSG_XLSX_BAD) from None
    if directory.name_count == 0:
        raise HTTPException(422, MSG_XLSX_BAD)
    request.app.state.store.put_blob(EMPLOYEES_BLOB, data)
    request.app.state.engine.set_directory(directory)
    counts = {"names": directory.name_count, "nips": directory.nip_count}
    _audit(db, actor, "impor_pegawai", f"nama={counts['names']} nip={counts['nips']}")
    db.commit()
    return counts


# ---- label rules -----------------------------------------------------------

def _effective_rules(db: Session) -> dict[str, str]:
    stored = label_rules(db)
    return {k.value: stored.get(k, default_label_for(Finding(k, 0, 0, "", ""))).value
            for k in Kind}


@router.get("/label-rules")
def get_label_rules(db: Session = Depends(get_db)):
    return _effective_rules(db)


@router.put("/label-rules")
def put_label_rules(body: dict[str, str], actor: User = Depends(admin_user),
                    db: Session = Depends(get_db)):
    try:
        rules = {Kind(k): Label(v) for k, v in body.items()}
    except ValueError:
        raise HTTPException(422, MSG_RULES) from None
    db.execute(delete(LabelRule))
    db.add_all(LabelRule(kind=k.value, label=v.value) for k, v in rules.items())
    _audit(db, actor, "aturan_label", f"jumlah={len(rules)}")
    db.commit()
    return _effective_rules(db)


# ---- audit -----------------------------------------------------------------

@router.get("/audit")
def list_audit(document_id: str | None = None, actor_id: str | None = None,
               limit: int = Query(100, ge=1, le=500), db: Session = Depends(get_db)):
    q = select(AuditEvent)
    if document_id:
        q = q.where(AuditEvent.document_id == document_id)
    if actor_id:
        q = q.where(AuditEvent.actor_id == actor_id)
    q = q.order_by(AuditEvent.at.desc(), AuditEvent.id.desc()).limit(limit)
    return [{"id": e.id, "at": e.at.isoformat(), "actor_id": e.actor_id,
             "action": e.action, "document_id": e.document_id, "detail": e.detail}
            for e in db.scalars(q)]
