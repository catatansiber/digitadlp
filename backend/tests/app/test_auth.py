import hashlib
from datetime import timedelta

from fastapi import Depends

from digitadlp.app.models import AuthSession, Role, User, utcnow
from digitadlp.app.security import current_user, require_role

from .conftest import make_user

SALAH = "Nama pengguna atau kata sandi salah."


def login(client, username="budi", password="rahasia123"):
    return client.post("/api/auth/login", json={"username": username, "password": password})


def test_login_ok_sets_httponly_cookie(client, app_db):
    make_user(app_db, "budi", Role.PENGGUNA, "Biro Umum")
    r = login(client)
    assert r.status_code == 200
    body = r.json()
    assert body["role"] == "pengguna" and body["unit"] == "Biro Umum"
    assert body["full_name"] == "Budi" and body["id"]
    h = r.headers["set-cookie"].lower()
    assert "digitadlp_session=" in h and "httponly" in h and "samesite=strict" in h
    assert "secure" not in h  # cookie_secure=False in test settings
    assert client.get("/api/auth/me").json()["id"] == body["id"]


def test_cookie_secure_when_enabled(app_settings, app_db):
    from dataclasses import replace

    from fastapi.testclient import TestClient

    from digitadlp.app.main import create_app
    from digitadlp.app.models import Base

    app = create_app(replace(app_settings, cookie_secure=True))
    Base.metadata.create_all(app.state.db_engine)
    with app.state.session_factory() as s:
        make_user(s, "budi")
    with TestClient(app) as c:
        r = login(c)
    assert "secure" in r.headers["set-cookie"].lower()


def test_wrong_password_same_message_as_unknown_user(client, app_db):
    make_user(app_db, "budi")
    a = login(client, "budi", "salah")
    b = login(client, "tidakada", "salah")
    assert a.status_code == b.status_code == 401
    assert a.json()["detail"] == b.json()["detail"] == SALAH


def test_me_without_session_401(client):
    r = client.get("/api/auth/me")
    assert r.status_code == 401
    assert r.json()["detail"] == "Sesi berakhir. Silakan masuk lagi."


def test_expired_session_401(client, app_db):
    make_user(app_db, "budi")
    login(client)
    sess = app_db.query(AuthSession).one()
    sess.expires_at = utcnow() - timedelta(minutes=1)
    app_db.commit()
    r = client.get("/api/auth/me")
    assert r.status_code == 401
    assert r.json()["detail"] == "Sesi berakhir. Silakan masuk lagi."


def test_session_expiry_uses_settings_hours(client, app_db, app_settings):
    make_user(app_db, "budi")
    login(client)
    sess = app_db.query(AuthSession).one()
    delta = sess.expires_at - sess.created_at
    assert abs(delta - timedelta(hours=app_settings.session_hours)) < timedelta(seconds=5)


def test_inactive_user_401(client, app_db):
    u = make_user(app_db, "budi")
    login(client)
    u.active = False
    app_db.commit()
    assert client.get("/api/auth/me").status_code == 401


def test_inactive_user_cannot_login(client, app_db):
    u = make_user(app_db, "budi")
    u.active = False
    app_db.commit()
    r = login(client)
    assert r.status_code == 401 and r.json()["detail"] == SALAH


def test_lockout_after_5_failures(client, app_db):
    make_user(app_db, "budi")
    for _ in range(5):
        assert login(client, "Budi", "salah").status_code == 401
    r = login(client, "budi", "rahasia123")  # even correct password is blocked
    assert r.status_code == 429
    assert r.json()["detail"] == "Terlalu banyak percobaan. Coba lagi dalam 15 menit."


def test_success_resets_failure_counter(client, app_db):
    make_user(app_db, "budi")
    for _ in range(4):
        login(client, "budi", "salah")
    assert login(client).status_code == 200
    for _ in range(4):
        assert login(client, "budi", "salah").status_code == 401


def test_lockout_window_expires(client, app, app_db):
    make_user(app_db, "budi")
    for _ in range(5):
        login(client, "budi", "salah")
    app.state.login_throttle._failures["budi"] = [
        t - 16 * 60 for t in app.state.login_throttle._failures["budi"]
    ]
    assert login(client).status_code == 200


def test_require_role_403(app, client, app_db):
    @app.get("/_only_admin")
    def only_admin(user: User = Depends(require_role(Role.ADMIN))):
        return {"ok": True}

    @app.get("/_any")
    def any_user(user: User = Depends(current_user)):
        return {"ok": True}

    make_user(app_db, "budi", Role.PENGGUNA)
    make_user(app_db, "ani", Role.ADMIN)
    assert client.get("/_only_admin").status_code == 401
    login(client, "budi")
    r = client.get("/_only_admin")
    assert r.status_code == 403
    assert r.json()["detail"] == "Anda tidak punya akses untuk tindakan ini."
    assert client.get("/_any").status_code == 200
    login(client, "ani", "rahasia123")
    assert client.get("/_only_admin").status_code == 200


def test_token_not_stored_plain(client, app_db):
    make_user(app_db, "budi")
    login(client)
    token = client.cookies.get("digitadlp_session")
    sess = app_db.query(AuthSession).one()
    assert sess.token_hash != token
    assert sess.token_hash == hashlib.sha256(token.encode()).hexdigest()


def test_logout_deletes_session(client, app_db):
    make_user(app_db, "budi")
    login(client)
    assert client.post("/api/auth/logout").status_code == 200
    assert app_db.query(AuthSession).count() == 0
    assert client.get("/api/auth/me").status_code == 401


def test_password_is_argon2id(app_db):
    u = make_user(app_db, "budi")
    assert u.password_hash.startswith("$argon2id$")


def test_create_admin_cli(tmp_path, monkeypatch, capsys):
    from sqlalchemy import select

    from digitadlp.app.__main__ import main
    from digitadlp.app.db import make_engine, make_session_factory
    from digitadlp.app.models import Base, Unit
    from digitadlp.app.security import verify_password

    url = f"sqlite:///{tmp_path / 'cli.db'}"
    engine = make_engine(url)
    Base.metadata.create_all(engine)
    monkeypatch.setenv("DIGITADLP_DATABASE_URL", url)
    monkeypatch.delenv("DIGITADLP_FERNET_KEY", raising=False)
    monkeypatch.setattr("getpass.getpass", lambda prompt="": "kata-sandi-kuat")
    rc = main(["create-admin", "--username", "root", "--unit", "Diskominfo"])
    assert rc == 0
    with make_session_factory(engine)() as s:
        u = s.scalar(select(User).where(User.username == "root"))
        assert u.role == Role.ADMIN and u.unit.name == "Diskominfo"
        assert verify_password("kata-sandi-kuat", u.password_hash)
        assert s.query(Unit).count() == 1
    # second run with existing unit reuses it; duplicate username fails cleanly
    assert main(["create-admin", "--username", "root2", "--unit", "Diskominfo"]) == 0
    assert main(["create-admin", "--username", "root", "--unit", "Diskominfo"]) == 1
    with make_session_factory(engine)() as s:
        assert s.query(Unit).count() == 1


def test_unknown_user_still_runs_argon2_verify(client, monkeypatch):
    calls = []
    monkeypatch.setattr(
        "digitadlp.app.routes.auth.verify_password",
        lambda pw, h: calls.append(h) or False,
    )
    assert login(client, "tidakada", "x").status_code == 401
    assert len(calls) == 1


def test_inactive_user_runs_verify_too(client, app_db, monkeypatch):
    u = make_user(app_db, "budi")
    u.active = False
    app_db.commit()
    calls = []
    monkeypatch.setattr(
        "digitadlp.app.routes.auth.verify_password",
        lambda pw, h: calls.append(h) or True,
    )
    assert login(client).status_code == 401
    assert len(calls) == 1


def test_reserve_is_atomic_under_concurrency():
    import threading

    from digitadlp.app.security import LoginThrottle

    t = LoginThrottle()
    results = []
    threads = [threading.Thread(target=lambda: results.append(t.reserve("a"))) for _ in range(50)]
    [x.start() for x in threads]
    [x.join() for x in threads]
    assert results.count(True) == 5


def test_login_drops_old_cookie_session_and_expired_rows(client, app_db):
    u = make_user(app_db, "budi")
    login(client)
    old_hash = app_db.query(AuthSession).one().token_hash
    app_db.add(AuthSession(token_hash="e" * 64, user_id=u.id, expires_at=utcnow() - timedelta(hours=1)))
    app_db.commit()
    login(client)  # cookie from first login still sent
    hashes = {s.token_hash for s in app_db.query(AuthSession).all()}
    assert len(hashes) == 1 and old_hash not in hashes and "e" * 64 not in hashes


def test_create_session_requires_hours(app_db):
    import pytest

    from digitadlp.app.security import create_session

    u = make_user(app_db, "budi")
    with pytest.raises(TypeError):
        create_session(app_db, u)


def test_login_logout_audited(client, app_db):
    from sqlalchemy import select as _s
    from digitadlp.app.models import AuditEvent
    from .conftest import make_user as _mk
    u = _mk(app_db, "audituser")
    client.post("/api/auth/login", json={"username": "audituser", "password": "salah-sekali"})
    client.post("/api/auth/login", json={"username": "audituser", "password": "rahasia123"})
    client.post("/api/auth/logout")
    for _ in range(6):
        client.post("/api/auth/login", json={"username": "audituser", "password": "x"})
    app_db.expire_all()
    ev = list(app_db.scalars(_s(AuditEvent).order_by(AuditEvent.at)))
    acts = [e.action for e in ev]
    assert acts[:3] == ["gagal_masuk", "masuk", "keluar"]
    assert ev[1].actor_id == u.id and ev[2].actor_id == u.id
    fails = [e for e in ev if e.action == "gagal_masuk"]
    assert all(e.actor_id is None for e in fails)
    assert fails[0].detail == "" and fails[-1].detail == "terkunci"
    assert all("audituser" not in e.detail and "salah" not in e.detail for e in ev)
