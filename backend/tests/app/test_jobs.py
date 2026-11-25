import json
import logging
from datetime import timedelta

import pytest
from cryptography.fernet import Fernet

from digitadlp.app.jobs import Engine, claim, enqueue, run_job, run_pending
from digitadlp.app.models import (
    AuditEvent, Document, Job, JobKind, JobState, Status, utcnow,
)
from digitadlp.app.storage import FileStore
from digitadlp.detect.employees import EmployeeDirectory
from digitadlp.detect.ner import FakeNer
from digitadlp.models import Kind

from .conftest import make_user

NIK = "6474015203880002"
TEXT = f"Pemohon: Siti Rahmawati\nNIK {NIK}\nTelepon 081234567890"


@pytest.fixture
def store(tmp_path):
    return FileStore(tmp_path / "store", Fernet.generate_key().decode())


@pytest.fixture
def engine():
    return Engine(FakeNer({"Siti Rahmawati": Kind.NAME_CITIZEN}), EmployeeDirectory(set()))


def _doc(db, store, path, ext="pdf"):
    user = make_user(db, "uploader")
    doc = Document(title="Surat", ext=ext, owner_id=user.id, unit_id=user.unit_id)
    db.add(doc)
    db.commit()
    store.put_file(doc.id, f"source.{ext}", path)
    return doc


def _run(db, store, engine, kind, doc):
    enqueue(db, kind, doc)
    db.commit()
    job = claim(db, 30)
    assert job is not None
    run_job(db, store, engine, job)
    db.refresh(doc)
    db.refresh(job)
    return job


def test_deteksi_sets_findings_and_label(db, store, engine, make_pdf):
    doc = _doc(db, store, make_pdf(TEXT))
    job = _run(db, store, engine, JobKind.DETEKSI, doc)
    assert job.state == JobState.SELESAI
    assert doc.status == Status.MENUNGGU_CEK
    assert doc.label == "rahasia" and doc.suggested_label == "rahasia"
    pages = json.loads(doc.findings_json)
    assert len(pages) == 1
    kinds = {f["kind"] for f in pages[0]}
    assert {"NIK", "NAME_CITIZEN"} <= kinds
    f = next(f for f in pages[0] if f["kind"] == "NIK")
    assert set(f) == {"kind", "text", "page", "start", "end", "source"}
    assert f["page"] == 0 and f["text"] == NIK


def test_deteksi_docx(db, store, engine, make_docx):
    doc = _doc(db, store, make_docx(), ext="docx")
    job = _run(db, store, engine, JobKind.DETEKSI, doc)
    assert job.state == JobState.SELESAI and doc.status == Status.MENUNGGU_CEK


def test_versi_creates_three_encrypted_files(db, store, engine, make_pdf):
    doc = _doc(db, store, make_pdf(TEXT))
    _run(db, store, engine, JobKind.DETEKSI, doc)
    job = _run(db, store, engine, JobKind.VERSI, doc)
    assert job.state == JobState.SELESAI
    assert doc.status == Status.DISETUJUI
    for v in ("publik", "internal", "rahasia"):
        raw = (store.root / doc.id / f"{v}.pdf.enc").read_bytes()
        assert not raw.startswith(b"%PDF")
        assert store.get(doc.id, f"{v}.pdf").startswith(b"%PDF")


def test_stale_running_job_reclaimed(db, store, make_pdf):
    doc = _doc(db, store, make_pdf(TEXT))
    job = enqueue(db, JobKind.DETEKSI, doc)
    job.state = JobState.BERJALAN
    job.claimed_at = utcnow() - timedelta(minutes=31)
    db.commit()
    got = claim(db, 30)
    assert got is not None and got.id == job.id
    assert got.state == JobState.BERJALAN
    assert got.claimed_at > utcnow() - timedelta(minutes=1)


def test_fresh_running_job_not_reclaimed(db, store, make_pdf):
    doc = _doc(db, store, make_pdf(TEXT))
    job = enqueue(db, JobKind.DETEKSI, doc)
    job.state = JobState.BERJALAN
    job.claimed_at = utcnow() - timedelta(minutes=5)
    db.commit()
    assert claim(db, 30) is None


def test_claim_does_not_double_claim(db, store, make_pdf):
    doc = _doc(db, store, make_pdf(TEXT))
    enqueue(db, JobKind.DETEKSI, doc)
    db.commit()
    assert claim(db, 30) is not None
    assert claim(db, 30) is None


def test_outdated_revision_job_noop(db, store, engine, make_pdf):
    doc = _doc(db, store, make_pdf(TEXT))
    enqueue(db, JobKind.DETEKSI, doc)
    doc.revision += 1
    db.commit()
    job = claim(db, 30)
    run_job(db, store, engine, job)
    db.refresh(doc)
    db.refresh(job)
    assert job.state == JobState.SELESAI
    assert doc.status == Status.DIPROSES and doc.findings_json == "[]"
    assert db.query(AuditEvent).count() == 0


def test_document_error_marks_gagal(db, store, engine, tmp_path, caplog):
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"%PDF-1.4 rusak " + NIK.encode())
    doc = _doc(db, store, bad)
    with caplog.at_level(logging.INFO):
        job = _run(db, store, engine, JobKind.VERSI, doc)
    assert job.state == JobState.GAGAL and job.error_code == "dokumen_rusak"
    assert doc.status == Status.GAGAL
    for v in ("publik", "internal", "rahasia"):
        assert not store.exists(doc.id, f"{v}.pdf")
    assert NIK not in caplog.text


def test_internal_error_logged_without_message(db, store, engine, make_pdf, caplog, monkeypatch):
    doc = _doc(db, store, make_pdf(TEXT))
    import digitadlp.app.processing as processing

    def boom(*a, **k):
        raise RuntimeError(f"bocor {NIK}")

    monkeypatch.setattr(processing, "extract_pdf_text", boom)
    with caplog.at_level(logging.INFO):
        job = _run(db, store, engine, JobKind.DETEKSI, doc)
    assert job.state == JobState.GAGAL and job.error_code == "galat_internal"
    assert NIK not in caplog.text
    assert "RuntimeError" in caplog.text


def test_findings_json_not_in_audit(db, store, engine, make_pdf):
    doc = _doc(db, store, make_pdf(TEXT))
    _run(db, store, engine, JobKind.DETEKSI, doc)
    events = db.query(AuditEvent).all()
    assert [e.action for e in events] == ["deteksi_selesai"]
    for e in events:
        assert NIK not in e.detail and "Siti" not in e.detail
        assert "{" not in e.detail


def test_run_pending_runs_all(db, store, engine, make_pdf):
    doc = _doc(db, store, make_pdf(TEXT))
    enqueue(db, JobKind.DETEKSI, doc)
    db.commit()
    factory = lambda: _Ctx(db)
    assert run_pending(factory, store, engine) == 1
    db.refresh(doc)
    assert doc.status == Status.MENUNGGU_CEK
    assert run_pending(factory, store, engine) == 0


class _Ctx:
    def __init__(self, db):
        self.db = db

    def __enter__(self):
        return self.db

    def __exit__(self, *a):
        return False


def test_worker_processes_job(tmp_path, store, engine, make_pdf, app_settings):
    import time
    from digitadlp.app.db import make_engine, make_session_factory
    from digitadlp.app.jobs import Worker
    from digitadlp.app.models import Base

    eng = make_engine(f"sqlite:///{tmp_path / 'w.db'}")
    Base.metadata.create_all(eng)
    factory = make_session_factory(eng)
    with factory() as db:
        doc = _doc(db, store, make_pdf(TEXT))
        enqueue(db, JobKind.DETEKSI, doc)
        db.commit()
        doc_id = doc.id
    w = Worker(factory, store, engine, app_settings)
    w.start()
    try:
        for _ in range(100):
            with factory() as db:
                if db.get(Document, doc_id).status == Status.MENUNGGU_CEK:
                    break
            time.sleep(0.05)
    finally:
        w.stop()
    with factory() as db:
        assert db.get(Document, doc_id).status == Status.MENUNGGU_CEK
    eng.dispose()
