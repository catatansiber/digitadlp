"""Kasus Rencana 1 (tests/test_api.py) dipindah ke API baru dengan login."""
import threading
import time

import pymupdf as fitz
import pytest
from fastapi.testclient import TestClient

from digitadlp.app import workflow
from digitadlp.app.main import create_app
from digitadlp.app.models import Base, Document, Status
from digitadlp.app.processing import Engine
from digitadlp.detect.employees import EmployeeDirectory
from digitadlp.detect.ner import FakeNer

from .conftest import make_user

NIK = "6474015203880002"
MSG = "Dokumen terenkripsi atau rusak. Buka kunci atau simpan ulang file, lalu upload lagi."
PDF = "application/pdf"


@pytest.fixture
def up(app):
    with app.state.session_factory() as db:
        make_user(db, "up")
    c = TestClient(app)
    assert c.post("/api/auth/login", json={"username": "up", "password": "rahasia123"}).status_code == 200
    yield c
    c.close()


def _docs_dir(app):
    root = app.state.store.root
    return [p for p in root.iterdir() if not p.name.startswith((".", "_"))] if root.exists() else []


def _count(app):
    with app.state.session_factory() as db:
        return db.query(Document).count()


def test_txt_415(up, app):
    r = up.post("/api/documents", files={"file": ("a.txt", b"hello", "text/plain")})
    assert r.status_code == 415
    assert r.json()["detail"] == "Format file tidak didukung. Gunakan PDF atau DOCX."
    assert _count(app) == 0


def test_too_large_413(up, app, monkeypatch):
    monkeypatch.setattr(workflow, "MAX_UPLOAD", 1000)
    r = up.post("/api/documents", files={"file": ("a.pdf", b"x" * 2000, PDF)})
    assert r.status_code == 413
    assert _count(app) == 0 and _docs_dir(app) == []


def test_encrypted_pdf_422(up, app, make_pdf, tmp_path):
    src = fitz.open(make_pdf(f"NIK {NIK}"))
    enc = tmp_path / "enc.pdf"
    src.save(enc, encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw="o", user_pw="u")
    r = up.post("/api/documents", files={"file": ("enc.pdf", enc.read_bytes(), PDF)})
    assert r.status_code == 422
    assert r.json() == {"detail": MSG}
    assert _count(app) == 0 and _docs_dir(app) == []


def test_corrupt_upload_422(up, app):
    for name in ("a.pdf", "a.docx"):
        r = up.post("/api/documents", files={"file": (name, b"not a document", PDF)})
        assert r.status_code == 422 and r.json() == {"detail": MSG}
    assert _count(app) == 0 and _docs_dir(app) == []


def test_unknown_and_malicious_ids_404(up):
    assert up.get("/api/documents/" + "0" * 32).status_code == 404
    assert up.get("/api/documents/" + "0" * 32 + "/versions/publik").status_code == 404
    assert up.get("/api/documents/..%2F..%2Fetc/versions/publik").status_code == 404
    assert up.get("/api/documents/not-hex/versions/publik").status_code == 404
    assert up.post("/api/documents/" + "0" * 32 + "/approve").status_code == 404


def test_bad_version_404(up, make_pdf):
    r = up.post("/api/documents", files={"file": ("s.pdf", make_pdf("halo").read_bytes(), PDF)})
    doc_id = r.json()["id"]
    for v in ("..%2Fsource.pdf", "source", "bogus"):
        assert up.get(f"/api/documents/{doc_id}/versions/{v}").status_code == 404
    # belum disetujui: versi ada di daftar tapi belum boleh diunduh
    assert up.get(f"/api/documents/{doc_id}/versions/rahasia").status_code == 403


def test_filename_not_used_in_storage(up, app, make_pdf):
    r = up.post("/api/documents", files={"file": ("../../evil.pdf", make_pdf("halo").read_bytes(), PDF)})
    assert r.status_code == 201
    d = app.state.store.root / r.json()["id"]
    assert sorted(x.name for x in d.iterdir()) == ["source.pdf.enc"]
    assert not (app.state.store.root.parent / "evil.pdf").exists()


def test_validation_error_does_not_echo_input(up):
    r = up.post("/api/documents/" + "0" * 32 + "/corrections", json={"op": NIK})
    assert r.status_code == 422
    assert r.json() == {"detail": "Data yang dikirim tidak lengkap atau tidak valid."}
    assert NIK not in r.text
    r = up.post("/api/auth/login", json={"username": NIK})
    assert r.status_code == 422 and NIK not in r.text


def test_lifespan_starts_and_stops_worker(app_settings, tmp_path, make_pdf):
    from dataclasses import replace
    s = replace(app_settings, run_worker=True, database_url=f"sqlite:///{tmp_path}/w.db")
    app = create_app(s, Engine(FakeNer({}), EmployeeDirectory(set())))
    Base.metadata.create_all(app.state.db_engine)
    with app.state.session_factory() as db:
        make_user(db, "up")
    with TestClient(app) as c:
        assert app.state.worker is not None
        c.post("/api/auth/login", json={"username": "up", "password": "rahasia123"})
        doc_id = c.post("/api/documents", files={"file": ("s.pdf", make_pdf(f"NIK {NIK}").read_bytes(), PDF)}).json()["id"]
        for _ in range(100):
            if c.get(f"/api/documents/{doc_id}").json()["status"] == Status.MENUNGGU_CEK:
                break
            time.sleep(0.1)
        assert c.get(f"/api/documents/{doc_id}").json()["status"] == "menunggu_cek"
    assert app.state.worker is None
    assert not any(t.name == "digitadlp-worker" and t.is_alive() for t in threading.enumerate())
    app.state.db_engine.dispose()
