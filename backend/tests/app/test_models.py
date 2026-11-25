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
        role=kw.get("role", Role.PEMERIKSA),
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
    assert user.role == Role.PEMERIKSA
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
