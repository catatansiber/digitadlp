import pytest
from sqlalchemy import select

from digitadlp.app.audit import ACTIONS, record
from digitadlp.app.models import AuditEvent, Role, Unit, User


@pytest.fixture
def user(db):
    unit = Unit(name="U")
    db.add(unit)
    db.flush()
    u = User(username="a", password_hash="x", full_name="A", role=Role.ADMIN, unit_id=unit.id)
    db.add(u)
    db.flush()
    return u


def test_record_ok(db, user):
    ev = record(db, user, "masuk", detail="ok")
    db.commit()
    got = db.scalars(select(AuditEvent)).one()
    assert got.id == ev.id and got.actor_id == user.id and got.action == "masuk"
    assert got.document_id is None and got.detail == "ok"


def test_record_no_actor(db):
    ev = record(db, None, "gagal_masuk")
    assert ev.actor_id is None


def test_record_does_not_commit(db, user):
    record(db, user, "masuk")
    db.rollback()
    assert db.scalars(select(AuditEvent)).all() == []


def test_record_rejects_pii_in_detail(db, user):
    with pytest.raises(ValueError):
        record(db, user, "koreksi", detail="NIK 6474015203880002")


def test_record_unknown_action(db, user):
    with pytest.raises(ValueError):
        record(db, user, "hapus_semua")


def test_record_detail_too_long(db, user):
    with pytest.raises(ValueError):
        record(db, user, "masuk", detail="a" * 201)
    record(db, user, "masuk", detail="a" * 200)


def test_actions_complete():
    assert len(ACTIONS) == 18
