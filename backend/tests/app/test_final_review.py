import io

import pymupdf
from docx import Document as Docx

from digitadlp.app.models import Document, Unit, User

from .test_workflow import _publik_text, _ready, client_as, wapp, work  # noqa: F401


def _approved(client_as, work, make_pdf):
    up, doc_id = _ready(client_as, work, make_pdf)
    assert up.post(f"/api/documents/{doc_id}/approve").status_code == 200
    work()
    return up, doc_id


def test_admin_other_unit_sees_metadata_without_findings(client_as, work, make_pdf):
    up, doc_id = _approved(client_as, work, make_pdf)
    adm = client_as("admin", unit="Unit Z")
    assert doc_id in [d["id"] for d in adm.get("/api/documents").json()]
    d = adm.get(f"/api/documents/{doc_id}")
    assert d.status_code == 200
    assert "findings" not in d.json() and "corrections" not in d.json()
    assert adm.get(f"/api/documents/{doc_id}/text").status_code == 404
    assert adm.get(f"/api/documents/{doc_id}/versions/rahasia").status_code == 403
    r = adm.post(f"/api/documents/{doc_id}/release")
    assert r.status_code == 200 and r.json()["status"] == "dirilis"


def test_other_unit_user_still_cannot_view(client_as, work, make_pdf):
    up, doc_id = _approved(client_as, work, make_pdf)
    other = client_as("pengguna", unit="Unit Z")
    assert doc_id not in [d["id"] for d in other.get("/api/documents").json()]
    assert other.get(f"/api/documents/{doc_id}").status_code == 404


def test_owner_moved_unit_can_download_own_publik(client_as, work, make_pdf, wapp):
    up, doc_id = _approved(client_as, work, make_pdf)
    with wapp.state.session_factory() as db:
        doc = db.get(Document, doc_id)
        unit = Unit(name="Unit Baru")
        db.add(unit)
        db.flush()
        db.get(User, doc.owner_id).unit_id = unit.id
        db.commit()
    assert up.get(f"/api/documents/{doc_id}/versions/publik").status_code == 200


def _add_and_approve(up, work, doc_id, text):
    r = up.post(f"/api/documents/{doc_id}/corrections",
                json={"op": "tambah", "kind": "NAME_CITIZEN", "text": text, "page": 0})
    assert r.status_code == 200, r.text
    work()
    assert up.post(f"/api/documents/{doc_id}/approve").status_code == 200
    work()


def test_manual_name_across_line_break_pdf(client_as, work, make_pdf, wapp):
    up = client_as("pengguna")
    r = up.post("/api/documents", files={"file": (
        "s.pdf", make_pdf("Catatan rapat bersama Siti\nRahmawati tadi pagi").read_bytes(),
        "application/pdf")})
    doc_id = r.json()["id"]
    work()
    _add_and_approve(up, work, doc_id, "Siti Rahmawati")
    text = _publik_text(wapp, doc_id)
    assert "Siti" not in text and "Rahmawati" not in text, text


def test_manual_name_split_runs_docx(client_as, work, tmp_path, wapp):
    d = Docx()
    p = d.add_paragraph("Catatan rapat bersama Siti ")
    p.add_run("Rahma")
    p.add_run("wati tadi pagi")
    path = tmp_path / "s.docx"
    d.save(path)
    up = client_as("pengguna")
    r = up.post("/api/documents", files={"file": ("s.docx", path.read_bytes(),
                                                  "application/octet-stream")})
    doc_id = r.json()["id"]
    work()
    _add_and_approve(up, work, doc_id, "Siti  Rahmawati")
    out = Docx(io.BytesIO(wapp.state.store.get(doc_id, "publik.docx")))
    text = "\n".join(p.text for p in out.paragraphs)
    assert "Rahma" not in text and "Siti" not in text, text


def test_legacy_employees_blob_deleted(app_settings):
    from digitadlp.app.main import create_app
    from pathlib import Path
    root = Path(app_settings.storage_dir)
    legacy = root / "_config" / "employees.xlsx.enc"
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_bytes(b"x")
    app = create_app(app_settings)
    assert not legacy.exists()
    app.state.db_engine.dispose()
