from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import record
from ..models import AuthSession, User
from ..security import (
    COOKIE_NAME,
    MSG_BAD_LOGIN,
    MSG_LOCKED,
    DUMMY_HASH,
    _digest,
    create_session,
    current_user,
    delete_session,
    get_db,
    purge_expired,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginIn(BaseModel):
    username: str
    password: str


def _out(user: User) -> dict:
    return {
        "id": user.id,
        "full_name": user.full_name,
        "role": user.role.value,
        "unit": user.unit.name,
    }


@router.post("/login")
def login(
    body: LoginIn,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    settings = request.app.state.settings
    throttle = request.app.state.login_throttle
    if not throttle.reserve(body.username):
        # Tanpa nama pengguna/kata sandi: bisa berisi data pribadi.
        record(db, None, "gagal_masuk", detail="terkunci")
        db.commit()
        raise HTTPException(429, MSG_LOCKED)
    user = db.scalar(select(User).where(User.username == body.username))
    ok = verify_password(body.password, user.password_hash if user else DUMMY_HASH)
    if user is None or not ok or not user.active:
        record(db, None, "gagal_masuk")
        db.commit()
        raise HTTPException(401, MSG_BAD_LOGIN)
    throttle.reset(body.username)
    old = request.cookies.get(COOKIE_NAME)
    if old:
        delete_session(db, old)
    purge_expired(db, user.id)
    record(db, user, "masuk")
    token = create_session(db, user, settings.session_hours)  # commit
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=settings.session_hours * 3600,
        httponly=True,
        samesite="strict",
        secure=settings.cookie_secure,
        path="/",
    )
    return _out(user)


@router.post("/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    token = request.cookies.get(COOKIE_NAME)
    if token:
        row = db.get(AuthSession, _digest(token))
        if row is not None:
            user = db.get(User, row.user_id)
            if user is not None:
                record(db, user, "keluar")
        delete_session(db, token)  # commit
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": True}


@router.get("/me")
def me(user: User = Depends(current_user)):
    return _out(user)
