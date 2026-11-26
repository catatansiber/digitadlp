import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import IntegrityError

from digitadlp.app.config import Settings
from digitadlp.app.models import Base, Role, Unit, User


def _user(unit, username="budi", **kw):
    return User(
        username=username,
        password_hash="x",
        full_name="Budi",
        role=kw.get("role", Role.PENGGUNA),
        unit_id=unit.id,
    )


def test_create_user_with_unit(db):
    unit = Unit(name="Bagian Umum")
    db.add(unit)
    db.flush()
    db.add(_user(unit))
    db.commit()
    db.expire_all()
    user = db.query(User).one()
    assert user.role == Role.PENGGUNA
    assert user.unit.name == "Bagian Umum"
    assert len(user.id) == 32
    assert user.created_at.tzinfo is not None
    assert user.active is True


def test_username_unique(db):
    unit = Unit(name="U")
    db.add(unit)
    db.flush()
    db.add(_user(unit))
    db.commit()
    db.add(_user(unit))
    with pytest.raises(IntegrityError):
        db.commit()


def test_settings_requires_fernet_key(monkeypatch):
    monkeypatch.delenv("DIGITADLP_FERNET_KEY", raising=False)
    with pytest.raises(RuntimeError, match="DIGITADLP_FERNET_KEY"):
        Settings.from_env()
    monkeypatch.setenv("DIGITADLP_FERNET_KEY", "k")
    s = Settings.from_env()
    assert s.session_hours == 8 and s.job_stale_minutes == 30
    assert s.cookie_secure is True and s.run_worker is True
    assert s.database_url == "sqlite:///./digitadlp.db"


def test_alembic_upgrade_head(tmp_path):
    url = f"sqlite:///{tmp_path / 'm.db'}"
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")
    insp = inspect(create_engine(url))
    assert set(Base.metadata.tables) <= set(insp.get_table_names())
    assert "alembic_version" in insp.get_table_names()
    idx = {i["name"] for t in ("jobs", "audit_events") for i in insp.get_indexes(t)}
    assert {"ix_jobs_state", "ix_audit_events_document_id"} <= idx


def test_roles_and_statuses():
    from digitadlp.app.models import Status
    assert {r.value for r in Role} == {"pengguna", "admin"}
    assert "dikembalikan" not in {s.value for s in Status}


def test_migration_0004_maps_roles_and_status(tmp_path, monkeypatch):
    from cryptography.fernet import Fernet
    from fastapi.testclient import TestClient
    from sqlalchemy import text

    from digitadlp.app.main import create_app
    from digitadlp.app.security import hash_password

    url = f"sqlite:///{tmp_path / 'm.db'}"
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "0003")
    eng = create_engine(url)
    now = "2026-01-01 00:00:00.000000"
    with eng.begin() as c:
        c.execute(text("INSERT INTO units (id, name, created_at) VALUES ('u1', 'Unit A', :t)"),
                  {"t": now})
        for uid, name, role in (("a1", "dedi", "pemeriksa"), ("a2", "rina", "pengunggah"),
                                ("a3", "boss", "admin")):
            c.execute(text(
                "INSERT INTO users (id, username, password_hash, full_name, role, unit_id,"
                " active, created_at) VALUES (:i, :n, :h, :n, :r, 'u1', 1, :t)"),
                {"i": uid, "n": name, "h": hash_password("rahasia12345"), "r": role, "t": now})
        cols = {col["name"] for col in inspect(eng).get_columns("documents")}
        assert "return_reason" in cols
        c.execute(text(
            "INSERT INTO documents (id, title, ext, owner_id, unit_id, status, label,"
            " suggested_label, label_set_by_reviewer, findings_json, revision, created_at,"
            " return_reason) VALUES ('d1', 'surat.pdf', 'pdf', 'a2', 'u1', 'dikembalikan',"
            " 'rahasia', 'rahasia', 0, '[]', 1, :t, 'Lampiran kurang')"), {"t": now})
    command.upgrade(cfg, "head")
    with eng.connect() as c:
        roles = dict(c.execute(text("SELECT username, role FROM users")).all())
        doc = c.execute(text("SELECT status, return_reason FROM documents")).one()
    assert roles == {"dedi": "pengguna", "rina": "pengguna", "boss": "admin"}
    assert tuple(doc) == ("menunggu_cek", "Lampiran kurang")
    eng.dispose()

    settings = Settings(fernet_key=Fernet.generate_key().decode(), database_url=url,
                        storage_dir=str(tmp_path / "s"), cookie_secure=False, run_worker=False,
                        frontend_dir=str(tmp_path / "no-dist"))
    app = create_app(settings)
    with TestClient(app) as cl:
        r = cl.post("/api/auth/login", json={"username": "dedi", "password": "rahasia12345"})
        assert r.status_code == 200, r.text
        assert cl.get("/api/auth/me").json()["role"] == "pengguna"
        assert cl.get("/api/documents/d1").json()["status"] == "menunggu_cek"
    app.state.db_engine.dispose()


def test_migration_0004_has_no_downgrade(tmp_path):
    url = f"sqlite:///{tmp_path / 'm.db'}"
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")
    with pytest.raises(NotImplementedError, match="migrasi data satu arah"):
        command.downgrade(cfg, "0003")
