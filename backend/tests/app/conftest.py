import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from digitadlp.app.models import Base


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


from fastapi.testclient import TestClient

from digitadlp.app.config import Settings
from digitadlp.app.main import create_app
from digitadlp.app.models import Role, Unit, User
from digitadlp.app.security import hash_password


@pytest.fixture
def app_settings(tmp_path):
    return Settings(
        fernet_key="x",
        database_url="sqlite://",
        storage_dir=str(tmp_path / "storage"),
        cookie_secure=False,
        run_worker=False,
    )


@pytest.fixture
def app(app_settings):
    app = create_app(app_settings)
    Base.metadata.create_all(app.state.db_engine)
    yield app
    app.state.db_engine.dispose()


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        yield c


@pytest.fixture
def app_db(app):
    with app.state.session_factory() as session:
        yield session


def make_user(db, username, role=Role.PENGUNGGAH, unit_name="Unit A", password="rahasia123"):
    from sqlalchemy import select

    unit = db.scalar(select(Unit).where(Unit.name == unit_name))
    if unit is None:
        unit = Unit(name=unit_name)
        db.add(unit)
        db.flush()
    user = User(
        username=username,
        password_hash=hash_password(password),
        full_name=username.title(),
        role=Role(role),
        unit_id=unit.id,
    )
    db.add(user)
    db.commit()
    return user
