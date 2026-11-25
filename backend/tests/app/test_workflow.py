import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from digitadlp.app.jobs import run_pending
from digitadlp.app.main import create_app
from digitadlp.app.models import AuditEvent, Base, Correction, Document, Role, Status
from digitadlp.app.processing import Engine
from digitadlp.detect.employees import EmployeeDirectory
from digitadlp.detect.ner import FakeNer
from digitadlp.models import Kind

from .conftest import make_user

NIK = "6474015203880002"
TEXT = f"Pemohon: Siti Rahmawati\nNIK {NIK}\nDisampaikan oleh Bu Rina"


@pytest.fixture
def wapp(app_settings):
    engine = Engine(FakeNer({"Siti Rahmawati": Kind.NAME_CITIZEN}), EmployeeDirectory(set()))
    app = create_app(app_settings, engine)
    Base.metadata.create_all(app.state.db_engine)
    yield app
    app.state.db_engine.dispose()


@pytest.fixture
def client_as(wapp):
    clients = []
    n = {"i": 0}

    def _make(role, unit="Unit A"):
        n["i"] += 1
        name = f"{role}{n['i']}"
        with wapp.state.session_factory() as db:
            make_user(db, name, role=role, unit_name=unit)
        c = TestClient(wapp)
        clients.append(c)
        r = c.post("/auth/login", json={"username": name, "password": "rahasia123"})
        assert r.status_code == 200
        return c

    yield _make
    for c in clients:
        c.close()


@pytest.fixture
def work(wapp):
    def _run():
        return run_pending(wapp.state.session_factory, wapp.state.store, wapp.state.engine)
    return _run


def _upload(c, path, name="surat.pdf"):
    return c.post("/documents", files={"file": (name, path.read_bytes(), "application/pdf")})


def _publik_text(wapp, doc_id):
    import pymupdf
    data = wapp.state.store.get(doc_id, "publik.pdf")
    d = pymupdf.open(stream=data, filetype="pdf")
    return "".join(p.get_text() for p in d)


def _ready(client_as, work, make_pdf):
    up = client_as("pengunggah")
    r = _upload(up, make_pdf(TEXT))
    assert r.status_code == 201, r.text
    doc_id = r.json()["id"]
    assert r.json()["status"] == "diproses"
    work()
    return up, doc_id


def test_full_flow(client_as, work, make_pdf, wapp):
    up, doc_id = _ready(client_as, work, make_pdf)
    rev = client_as("pemeriksa", unit="Unit B")
    d = rev.get(f"/documents/{doc_id}").json()
    assert d["status"] == "menunggu_cek" and d["findings"]
    assert rev.post(f"/documents/{doc_id}/approve").json()["status"] == "membuat_versi"
    work()
    assert rev.get(f"/documents/{doc_id}").json()["status"] == "disetujui"
    assert rev.post(f"/documents/{doc_id}/release").json()["status"] == "dirilis"
    with wapp.state.session_factory() as db:
        actions = {e.action for e in db.scalars(select(AuditEvent))}
    assert {"upload", "deteksi_selesai", "setujui", "rilis"} <= actions


def test_self_approval_403(client_as, work, make_pdf):
    rev = client_as("pemeriksa")
    r = _upload(rev, make_pdf(TEXT))
    work()
    r = rev.post(f"/documents/{r.json()['id']}/approve")
    assert r.status_code == 403
    assert r.json()["detail"] == "Pemeriksa tidak boleh menyetujui dokumen yang ia upload sendiri."


def test_correction_after_approval_resets(client_as, work, make_pdf, wapp):
    up, doc_id = _ready(client_as, work, make_pdf)
    rev = client_as("pemeriksa")
    rev.post(f"/documents/{doc_id}/approve")
    work()
    assert wapp.state.store.exists(doc_id, "publik.pdf")
    rev_before = rev.get(f"/documents/{doc_id}").json()["revision"]
    r = rev.post(f"/documents/{doc_id}/corrections",
                 json={"op": "abaikan", "kind": "NAME_CITIZEN", "text": "Siti Rahmawati"})
    assert r.status_code == 200, r.text
    d = rev.get(f"/documents/{doc_id}").json()
    assert d["status"] == "menunggu_cek" and d["revision"] == rev_before + 1
    assert d["approved_at"] is None
    assert not wapp.state.store.exists(doc_id, "publik.pdf")
    assert all(f["text"] != "Siti Rahmawati" for p in d["findings"] for f in p)
    with wapp.state.session_factory() as db:
        ev = db.scalars(select(AuditEvent).where(AuditEvent.action == "koreksi")).one()
        assert "Siti" not in ev.detail


def test_ignore_correction_keeps_text_in_publik(client_as, work, make_pdf, wapp):
    up, doc_id = _ready(client_as, work, make_pdf)
    rev = client_as("pemeriksa")
    rev.post(f"/documents/{doc_id}/corrections",
             json={"op": "abaikan", "kind": "NAME_CITIZEN", "text": "Siti Rahmawati"})
    rev.post(f"/documents/{doc_id}/approve")
    work()
    text = _publik_text(wapp, doc_id)
    assert "Siti Rahmawati" in text and NIK not in text


def test_manual_add_redacted_in_publik(client_as, work, make_pdf, wapp):
    up, doc_id = _ready(client_as, work, make_pdf)
    rev = client_as("pemeriksa")
    r = rev.post(f"/documents/{doc_id}/corrections",
                 json={"op": "tambah", "kind": "NAME_CITIZEN", "text": "Bu Rina", "page": 0})
    assert r.status_code == 200, r.text
    d = rev.get(f"/documents/{doc_id}").json()
    assert any(f["text"] == "Bu Rina" and f["page"] == 0 for f in d["findings"][0])
    rev.post(f"/documents/{doc_id}/approve")
    work()
    assert "Bu Rina" not in _publik_text(wapp, doc_id)


def test_correction_validation_422(client_as, work, make_pdf):
    up, doc_id = _ready(client_as, work, make_pdf)
    rev = client_as("pemeriksa")
    for body in ({"op": "tambah", "kind": "XX", "text": "a", "page": 0},
                 {"op": "tambah", "kind": "NIK", "text": "", "page": 0},
                 {"op": "tambah", "kind": "NIK", "text": "a" * 201, "page": 0},
                 {"op": "tambah", "kind": "NIK", "text": "abc", "page": 9}):
        r = rev.post(f"/documents/{doc_id}/corrections", json=body)
        assert r.status_code == 422, body


def test_label_kept_after_redetect(client_as, work, make_pdf, wapp):
    up, doc_id = _ready(client_as, work, make_pdf)
    rev = client_as("pemeriksa")
    r = rev.put(f"/documents/{doc_id}/label", json={"label": "internal"})
    assert r.status_code == 200 and r.json()["label"] == "internal"
    rev.post(f"/documents/{doc_id}/return", json={"reason": "Lampiran kurang"})
    _reup(up, doc_id, make_pdf)
    work()
    d = rev.get(f"/documents/{doc_id}").json()
    assert d["label"] == "internal" and d["suggested_label"] == "rahasia"


def _reup(c, doc_id, make_pdf):
    return c.post(f"/documents/{doc_id}/reupload",
                  files={"file": ("surat.pdf", make_pdf(TEXT).read_bytes(), "application/pdf")})


def test_return_and_reupload(client_as, work, make_pdf, wapp):
    up, doc_id = _ready(client_as, work, make_pdf)
    rev = client_as("pemeriksa")
    rev.post(f"/documents/{doc_id}/corrections",
             json={"op": "tambah", "kind": "NAME_CITIZEN", "text": "Bu Rina", "page": 0})
    r = rev.post(f"/documents/{doc_id}/return", json={"reason": "Lampiran kurang"})
    assert r.status_code == 200 and r.json()["status"] == "dikembalikan"
    other = client_as("pengunggah")
    assert _reup(other, doc_id, make_pdf).status_code == 403
    before = up.get(f"/documents/{doc_id}").json()["revision"]
    r = _reup(up, doc_id, make_pdf)
    assert r.status_code == 200 and r.json()["status"] == "diproses"
    assert r.json()["revision"] == before + 1
    with wapp.state.session_factory() as db:
        assert db.scalars(select(Correction).where(Correction.document_id == doc_id)).all() == []
    work()
    assert up.get(f"/documents/{doc_id}").json()["status"] == "menunggu_cek"


def test_wrong_state_409(client_as, work, make_pdf):
    up, doc_id = _ready(client_as, work, make_pdf)
    rev = client_as("pemeriksa")
    r = rev.post(f"/documents/{doc_id}/release")
    assert r.status_code == 409
    assert r.json()["detail"] == (
        "Dokumen sedang berstatus menunggu_cek; tindakan ini tidak bisa dilakukan.")
    assert _reup(up, doc_id, make_pdf).status_code == 409


def test_admin_cannot_upload(client_as, make_pdf):
    adm = client_as("admin")
    assert _upload(adm, make_pdf(TEXT)).status_code == 403


def test_upload_bad_ext_415(client_as):
    up = client_as("pengunggah")
    r = up.post("/documents", files={"file": ("a.txt", b"hi", "text/plain")})
    assert r.status_code == 415


def test_reason_with_pii_rejected(client_as, work, make_pdf):
    up, doc_id = _ready(client_as, work, make_pdf)
    rev = client_as("pemeriksa")
    r = rev.post(f"/documents/{doc_id}/return", json={"reason": f"NIK {NIK} salah"})
    assert r.status_code == 422
    assert NIK not in r.text
    assert rev.get(f"/documents/{doc_id}").json()["status"] == "menunggu_cek"


def test_visibility(client_as, work, make_pdf):
    up, doc_id = _ready(client_as, work, make_pdf)
    same = client_as("pengunggah", unit="Unit A")
    d = same.get(f"/documents/{doc_id}").json()
    assert "findings" in d and "corrections" in d
    stranger = client_as("pengunggah", unit="Unit Z")
    assert stranger.get(f"/documents/{doc_id}").status_code == 404
    assert stranger.post(f"/documents/{doc_id}/approve").status_code == 404
    ids = [x["id"] for x in stranger.get("/documents").json()]
    assert doc_id not in ids


def test_reupload_other_ext_deletes_old_source(client_as, work, make_pdf, make_docx, wapp):
    up, doc_id = _ready(client_as, work, make_pdf)
    rev = client_as("pemeriksa")
    rev.post(f"/documents/{doc_id}/return", json={"reason": "Ganti format"})
    r = up.post(f"/documents/{doc_id}/reupload",
                files={"file": ("surat.docx", make_docx().read_bytes(), "application/octet-stream")})
    assert r.status_code == 200, r.text
    store = wapp.state.store
    assert store.exists(doc_id, "source.docx")
    assert not store.exists(doc_id, "source.pdf")
