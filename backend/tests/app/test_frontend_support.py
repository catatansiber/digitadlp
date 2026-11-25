import dataclasses

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from digitadlp.app.jobs import run_pending
from digitadlp.app.main import create_app
from digitadlp.app.models import AuditEvent, Base, Role
from digitadlp.app.processing import Engine
from digitadlp.detect.employees import EmployeeDirectory
from digitadlp.detect.ner import FakeNer

from .conftest import make_user

NIK = "6474015203880002"
TEXT = f"Pemohon: Siti Rahmawati\nNIK {NIK}\nDisampaikan oleh Bu Rina"
INDEX = "<!doctype html><title>DigitaDLP</title><div id=root></div>"


def _mk(settings):
    app = create_app(settings, Engine(FakeNer({}), EmployeeDirectory(set())))
    Base.metadata.create_all(app.state.db_engine)
    return app


@pytest.fixture
def dist(tmp_path):
    d = tmp_path / "dist"
    (d / "assets").mkdir(parents=True)
    (d / "index.html").write_text(INDEX)
    (d / "assets" / "app.js").write_text("console.log(1)")
    return d


@pytest.fixture
def spa(app_settings, dist):
    app = _mk(dataclasses.replace(app_settings, frontend_dir=str(dist)))
    with TestClient(app) as c:
        yield c
    app.state.db_engine.dispose()


@pytest.fixture
def mk_client(app, app_db):
    clients = []
    n = {"i": 0}

    def _make(role, unit="Unit A"):
        n["i"] += 1
        name = f"{role}{n['i']}"
        make_user(app_db, name, role=role, unit_name=unit)
        c = TestClient(app)
        clients.append(c)
        assert c.post("/api/auth/login",
                      json={"username": name, "password": "rahasia123"}).status_code == 200
        return c

    yield _make
    for c in clients:
        c.close()


@pytest.fixture
def ready(mk_client, app, make_pdf):
    up = mk_client("pengunggah")
    r = up.post("/api/documents", files={"file": ("s.pdf", make_pdf(TEXT).read_bytes(),
                                                  "application/pdf")})
    assert r.status_code == 201, r.text
    run_pending(app.state.session_factory, app.state.store, app.state.engine)
    return up, r.json()["id"]


def test_api_prefix(client):
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/auth/me").status_code == 404


def test_spa_fallback_serves_index(spa):
    r = spa.get("/dokumen/abc")
    assert r.status_code == 200 and r.text == INDEX
    assert r.headers["cache-control"] == "no-store"
    assert spa.get("/").text == INDEX


def test_assets_immutable_and_missing(spa):
    r = spa.get("/assets/app.js")
    assert r.status_code == 200
    assert r.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert spa.get("/assets/nope.js").status_code == 404
    assert spa.get("/favicon.ico").status_code == 404
    assert spa.get("/%2e%2e/%2e%2e/etc/passwd").status_code in (200, 404)
    assert "root:" not in spa.get("/..%2f..%2f..%2fetc/passwd").text


def test_unknown_api_404_json(spa):
    r = spa.get("/api/tidak-ada")
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/json")
    assert INDEX not in r.text


def test_no_frontend_dir_no_fallback(client):
    assert client.get("/dokumen/abc").status_code == 404


def test_security_headers(spa, client):
    for c, path in ((spa, "/dokumen/abc"), (spa, "/api/auth/me"), (client, "/api/auth/me")):
        h = c.get(path).headers
        assert h["content-security-policy"] == (
            "default-src 'self'; img-src 'self' data:; style-src 'self'; "
            "script-src 'self'; frame-ancestors 'none'")
        assert h["x-frame-options"] == "DENY"
        assert h["referrer-policy"] == "no-referrer"


def test_text_endpoint_access(ready, mk_client):
    up, doc_id = ready
    rev = mk_client("pemeriksa", unit="Unit B")
    r = rev.get(f"/api/documents/{doc_id}/text")
    assert r.status_code == 200
    assert r.headers["cache-control"] == "no-store"
    pages = r.json()["pages"]
    assert len(pages) == 1 and NIK in pages[0]
    assert up.get(f"/api/documents/{doc_id}/text").status_code == 200
    other = mk_client("pengunggah", unit="Unit C")
    assert other.get(f"/api/documents/{doc_id}/text").status_code == 404
    assert other.get("/api/documents/xyz/text").status_code == 404


def test_text_endpoint_docx(mk_client, app, make_docx):
    up = mk_client("pengunggah")
    p = make_docx()
    r = up.post("/api/documents", files={"file": ("a.docx", p.read_bytes(), "application/octet-stream")})
    assert r.status_code == 201, r.text
    r = up.get(f"/api/documents/{r.json()['id']}/text")
    assert r.status_code == 200 and isinstance(r.json()["pages"], list)


def test_text_endpoint_extraction_error_422(ready, app):
    up, doc_id = ready
    app.state.store.put(doc_id, "source.pdf", b"bukan pdf")
    r = up.get(f"/api/documents/{doc_id}/text")
    assert r.status_code == 422
    assert "bukan pdf" not in r.text


def test_text_endpoint_audited(ready, mk_client, app_db):
    up, doc_id = ready
    rev = mk_client("pemeriksa", unit="Unit B")
    assert rev.get(f"/api/documents/{doc_id}/text").status_code == 200
    ev = app_db.scalars(select(AuditEvent).where(
        AuditEvent.document_id == doc_id, AuditEvent.action == "lihat_teks")).all()
    assert [e.detail for e in ev] == [""]


def test_return_reason_visible_to_owner_unit_only(ready, mk_client):
    up, doc_id = ready
    rev = mk_client("pemeriksa", unit="Unit B")
    r = rev.post(f"/api/documents/{doc_id}/return", json={"reason": "Lampiran kurang"})
    assert r.status_code == 200
    assert rev.get(f"/api/documents/{doc_id}").json()["return_reason"] == "Lampiran kurang"
    assert up.get(f"/api/documents/{doc_id}").json()["return_reason"] == "Lampiran kurang"
    mate = mk_client("pengunggah", unit="Unit A")
    assert mate.get(f"/api/documents/{doc_id}").json()["return_reason"] == "Lampiran kurang"
    other = mk_client("pengunggah", unit="Unit C")
    assert other.get(f"/api/documents/{doc_id}").status_code == 404
    # daftar tidak memuat alasan
    assert all("return_reason" not in d for d in up.get("/api/documents").json())


def test_reupload_clears_reason(ready, mk_client, make_pdf):
    up, doc_id = ready
    rev = mk_client("pemeriksa")
    rev.post(f"/api/documents/{doc_id}/return", json={"reason": "Lampiran kurang"})
    r = up.post(f"/api/documents/{doc_id}/reupload",
                files={"file": ("s.pdf", make_pdf(TEXT).read_bytes(), "application/pdf")})
    assert r.status_code == 200
    assert up.get(f"/api/documents/{doc_id}").json()["return_reason"] is None


def test_owner_and_unit_names(ready):
    up, doc_id = ready
    d = up.get(f"/api/documents/{doc_id}").json()
    assert d["owner_name"] == "Pengunggah1" and d["unit_name"] == "Unit A"
    row = up.get("/api/documents").json()[0]
    assert row["owner_name"] == "Pengunggah1" and row["unit_name"] == "Unit A"


def test_security_headers_on_unhandled_500(app):
    @app.get("/api/boom")
    def boom():
        raise RuntimeError("rusak")

    with TestClient(app, raise_server_exceptions=False) as c:
        r = c.get("/api/boom")
    assert r.status_code == 500
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["referrer-policy"] == "no-referrer"
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
