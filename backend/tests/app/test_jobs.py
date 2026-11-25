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


# --- race / review fixes ---------------------------------------------------
from sqlalchemy import update as _update
from sqlalchemy.orm import Session as _Session

import digitadlp.app.processing as _processing
from digitadlp.redact.pdf import DocumentError as _DocumentError


def _bump_revision(db, doc_id):
    with _Session(db.get_bind()) as other:
        other.execute(
            _update(Document).where(Document.id == doc_id)
            .values(revision=Document.revision + 1, status=Status.MENUNGGU_CEK)
        )
        other.commit()


def _approved_with_versions(db, store, engine, make_pdf):
    doc = _doc(db, store, make_pdf(TEXT))
    _run(db, store, engine, JobKind.DETEKSI, doc)
    _run(db, store, engine, JobKind.VERSI, doc)
    return doc, {v: store.get(doc.id, f"{v}.pdf") for v in ("publik", "internal", "rahasia")}


def _sentinel_versions(store, doc):
    for v in ("publik", "internal", "rahasia"):
        store.put(doc.id, f"{v}.pdf", b"NEWER-" + v.encode())


def test_revision_bump_during_versi_leaves_versions_and_state(db, store, engine, make_pdf, monkeypatch):
    doc, _ = _approved_with_versions(db, store, engine, make_pdf)
    _sentinel_versions(store, doc)  # stands in for versions of the newer revision
    real = _processing.redact_pdf
    calls = {"n": 0}

    def bumping(*a, **k):
        calls["n"] += 1
        if calls["n"] == 2:
            _bump_revision(db, doc.id)
        return real(*a, **k)

    monkeypatch.setattr(_processing, "redact_pdf", bumping)
    job = _run(db, store, engine, JobKind.VERSI, doc)
    assert job.state == JobState.SELESAI
    assert doc.status == Status.MENUNGGU_CEK  # not overwritten to disetujui
    for v in ("publik", "internal", "rahasia"):
        assert store.get(doc.id, f"{v}.pdf") == b"NEWER-" + v.encode()


def test_stale_failing_versi_keeps_newer_versions(db, store, engine, make_pdf, monkeypatch):
    doc, _ = _approved_with_versions(db, store, engine, make_pdf)
    _sentinel_versions(store, doc)

    def failing(*a, **k):
        _bump_revision(db, doc.id)
        raise _DocumentError("rusak")

    monkeypatch.setattr(_processing, "redact_pdf", failing)
    job = _run(db, store, engine, JobKind.VERSI, doc)
    assert job.state == JobState.GAGAL
    assert doc.status == Status.MENUNGGU_CEK
    for v in ("publik", "internal", "rahasia"):
        assert store.get(doc.id, f"{v}.pdf") == b"NEWER-" + v.encode()


def test_revision_bump_during_deteksi_no_write(db, store, engine, make_pdf, monkeypatch):
    doc = _doc(db, store, make_pdf(TEXT))
    real = _processing.extract_pdf_text

    def bumping(*a, **k):
        _bump_revision(db, doc.id)
        return real(*a, **k)

    monkeypatch.setattr(_processing, "extract_pdf_text", bumping)
    job = _run(db, store, engine, JobKind.DETEKSI, doc)
    assert job.state == JobState.SELESAI
    assert doc.findings_json == "[]" and doc.label is None
    assert db.query(AuditEvent).count() == 0


def test_reclaimed_job_original_runner_cannot_commit(db, store, engine, make_pdf):
    doc = _doc(db, store, make_pdf(TEXT))
    enqueue(db, JobKind.DETEKSI, doc)
    db.commit()
    first = claim(db, 30)
    old_token = first.claim_token
    assert old_token
    db.execute(_update(Job).where(Job.id == first.id)
               .values(claimed_at=utcnow() - timedelta(minutes=31)))
    db.commit()
    second = claim(db, 30)
    new_token, job_id, doc_id = second.claim_token, first.id, doc.id
    assert new_token != old_token
    db.expunge_all()
    stale = Job(id=job_id, kind=JobKind.DETEKSI, document_id=doc_id,
                revision=0, state=JobState.BERJALAN, claim_token=old_token)
    run_job(db, store, engine, stale)
    d = db.get(Document, doc_id)
    j = db.get(Job, job_id)
    assert d.status == Status.DIPROSES and d.findings_json == "[]"
    assert j.state == JobState.BERJALAN and j.claim_token == new_token
    assert db.query(AuditEvent).count() == 0


def test_lost_claim_failure_has_no_side_effects(db, store, engine, make_pdf, monkeypatch):
    doc, _ = _approved_with_versions(db, store, engine, make_pdf)
    enqueue(db, JobKind.VERSI, doc)
    db.commit()
    job = claim(db, 30)

    def steal_and_fail(*a, **k):
        with _Session(db.get_bind()) as other:
            other.execute(_update(Job).where(Job.id == job.id).values(claim_token="x" * 32))
            other.commit()
        raise _DocumentError("rusak")

    monkeypatch.setattr(_processing, "redact_pdf", steal_and_fail)
    run_job(db, store, engine, job)
    db.refresh(doc)
    db.refresh(job)
    assert job.state == JobState.BERJALAN
    assert doc.status == Status.DISETUJUI
    assert store.exists(doc.id, "publik.pdf")


def test_touch_called_during_job(db, store, engine, make_pdf):
    doc = _doc(db, store, make_pdf(TEXT))
    _run(db, store, engine, JobKind.DETEKSI, doc)
    enqueue(db, JobKind.VERSI, doc)
    db.commit()
    job = claim(db, 30)
    n = {"c": 0}
    run_job(db, store, engine, job, touch=lambda: n.__setitem__("c", n["c"] + 1))
    assert n["c"] >= 3


def test_heartbeat_refreshes_claimed_at(db, store, make_pdf):
    from digitadlp.app.jobs import heartbeat
    doc = _doc(db, store, make_pdf(TEXT))
    enqueue(db, JobKind.DETEKSI, doc)
    db.commit()
    job = claim(db, 30)
    old = utcnow() - timedelta(minutes=20)
    db.execute(_update(Job).where(Job.id == job.id).values(claimed_at=old))
    db.commit()
    heartbeat(db, job.id, job.claim_token, interval=0)()
    db.refresh(job)
    assert job.claimed_at > old + timedelta(minutes=19)


def test_pdf_extras_stored_with_null_page(db, store, engine, make_pdf):
    doc = _doc(db, store, make_pdf("Surat biasa", metadata={"author": NIK, "title": "x"}))
    _run(db, store, engine, JobKind.DETEKSI, doc)
    entries = [f for p in json.loads(doc.findings_json) for f in p]
    assert any(f["page"] is None and f["text"] == NIK for f in entries)


def test_deteksi_keeps_reviewer_label(db, store, engine, make_pdf):
    doc = _doc(db, store, make_pdf(TEXT))
    doc.label = "publik"
    doc.label_set_by_reviewer = True
    db.commit()
    _run(db, store, engine, JobKind.DETEKSI, doc)
    assert doc.suggested_label == "rahasia" and doc.label == "publik"


def test_engine_directory_swap_is_atomic_and_read_once(db, store, make_pdf, monkeypatch):
    from digitadlp.app import processing
    from digitadlp.detect.employees import EmployeeDirectory
    eng = processing.Engine(FakeNer({}), EmployeeDirectory(set()))
    old = eng.directory
    new = EmployeeDirectory.from_names(["Siti Rahmawati"])
    eng.set_directory(new)
    assert eng.directory is new and eng.directory is not old
    seen = []
    real = processing.detect

    def spy(text, ner, directory):
        seen.append(directory)
        eng.set_directory(EmployeeDirectory(set()))  # diganti di tengah job
        return real(text, ner, directory)

    monkeypatch.setattr(processing, "detect", spy)
    doc = _doc(db, store, make_pdf(TEXT))
    processing.compute_deteksi(db, store, eng, doc)
    assert seen and all(d is new for d in seen)
