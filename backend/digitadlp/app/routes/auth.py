from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import User
from ..security import (
    COOKIE_NAME,
    MSG_BAD_LOGIN,
    MSG_LOCKED,
    DUMMY_HASH,
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
        raise HTTPException(429, MSG_LOCKED)
    user = db.scalar(select(User).where(User.username == body.username))
    ok = verify_password(body.password, user.password_hash if user else DUMMY_HASH)
    if user is None or not ok or not user.active:
        raise HTTPException(401, MSG_BAD_LOGIN)
    throttle.reset(body.username)
    old = request.cookies.get(COOKIE_NAME)
    if old:
        delete_session(db, old)
    purge_expired(db, user.id)
    token = create_session(db, user, settings.session_hours)
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
        delete_session(db, token)
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": True}


@router.get("/me")
def me(user: User = Depends(current_user)):
    return _out(user)
