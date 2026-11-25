import hashlib
import secrets
import threading
import time
from datetime import timedelta

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import Depends, HTTPException, Request
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .models import AuthSession, Role, User, utcnow

COOKIE_NAME = "digitadlp_session"
MSG_SESSION = "Sesi berakhir. Silakan masuk lagi."
MSG_FORBIDDEN = "Anda tidak punya akses untuk tindakan ini."
MSG_BAD_LOGIN = "Nama pengguna atau kata sandi salah."
MSG_LOCKED = "Terlalu banyak percobaan. Coba lagi dalam 15 menit."

_hasher = PasswordHasher()  # argon2id by default


def hash_password(pw: str) -> str:
    return _hasher.hash(pw)


def verify_password(pw: str, h: str) -> bool:
    try:
        return _hasher.verify(h, pw)
    except (VerificationError, InvalidHashError):
        return False


# Verified against when the username is unknown, so timing does not reveal it.
DUMMY_HASH = _hasher.hash("digitadlp-dummy-password")


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(db: Session, user: User, hours: int) -> str:
    token = secrets.token_urlsafe(32)
    db.add(
        AuthSession(
            token_hash=_digest(token),
            user_id=user.id,
            expires_at=utcnow() + timedelta(hours=hours),
        )
    )
    db.commit()
    return token


def purge_expired(db: Session, user_id: str) -> None:
    db.execute(
        delete(AuthSession).where(
            AuthSession.user_id == user_id, AuthSession.expires_at <= utcnow()
        )
    )
    db.commit()


def delete_session(db: Session, token: str) -> None:
    row = db.get(AuthSession, _digest(token))
    if row is not None:
        db.delete(row)
        db.commit()


class LoginThrottle:
    """In-memory failed-login counter per lowercased username."""

    def __init__(self, max_failures: int = 5, window_seconds: int = 15 * 60):
        self.max_failures = max_failures
        self.window = window_seconds
        self._failures: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def _recent(self, key: str) -> list[float]:
        cutoff = time.time() - self.window
        recent = [t for t in self._failures.get(key, []) if t > cutoff]
        if recent:
            self._failures[key] = recent
        else:
            self._failures.pop(key, None)
        return recent

    def reserve(self, username: str) -> bool:
        """Atomically check the limit and count this attempt as a failure.

        Returns False when locked. Call reset() on a successful login.
        """
        key = username.lower()
        with self._lock:
            if len(self._recent(key)) >= self.max_failures:
                return False
            self._failures.setdefault(key, []).append(time.time())
            return True

    def reset(self, username: str) -> None:
        with self._lock:
            self._failures.pop(username.lower(), None)


def get_db(request: Request):
    with request.app.state.session_factory() as session:
        yield session


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(401, MSG_SESSION)
    row = db.scalar(select(AuthSession).where(AuthSession.token_hash == _digest(token)))
    if row is None or row.expires_at <= utcnow():
        raise HTTPException(401, MSG_SESSION)
    user = db.get(User, row.user_id)
    if user is None or not user.active:
        raise HTTPException(401, MSG_SESSION)
    return user


def require_role(*roles: Role):
    allowed = {Role(r) for r in roles}

    def dep(user: User = Depends(current_user)) -> User:
        if user.role not in allowed:
            raise HTTPException(403, MSG_FORBIDDEN)
        return user

    return dep
