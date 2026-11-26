from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, select

from digitadlp.app.models import AreaRedaction, AuditEvent

from .test_workflow import TEXT, _ready, _reup, _upload, client_as, wapp, work  # noqa: F401

BOX = {"page": 0, "x0": 0.1, "y0": 0.1, "x1": 0.4, "y1": 0.3}


def _events(wapp, action):
    with wapp.state.session_factory() as db:
        return db.scalars(select(AuditEvent).where(AuditEvent.action == action)).all()


def test_pages_count_and_png_owner_unit(client_as, work, make_pdf, wapp):
    up, doc_id = _ready(client_as, work, make_pdf)
    r = up.get(f"/api/documents/{doc_id}/pages")
    assert r.status_code == 200
    assert r.json()["count"] == 1 and len(r.json()["sizes"]) == 1
    mate = client_as("pengguna")
    for c in (up, mate):
        r = c.get(f"/api/documents/{doc_id}/pages/0.png")
        assert r.status_code == 200
        assert r.headers["content-type"] == "image/png"
        assert r.headers["cache-control"] == "no-store"
        assert r.content.startswith(b"\x89PNG")
    ev = _events(wapp, "lihat_halaman")
    assert len(ev) == 2 and all(e.detail == "hal=0" for e in ev)
    assert up.get(f"/api/documents/{doc_id}/pages/1.png").status_code == 404


def test_pages_other_unit_404_audited(client_as, work, make_pdf, wapp):
    up, doc_id = _ready(client_as, work, make_pdf)
    up.post(f"/api/documents/{doc_id}/areas", json=BOX)
    for role in ("pengguna", "admin"):
        other = client_as(role, unit="Unit B")
        assert other.get(f"/api/documents/{doc_id}/pages").status_code == 404
        assert other.get(f"/api/documents/{doc_id}/pages/0.png").status_code == 404
        assert other.get(f"/api/documents/{doc_id}/areas").status_code == 404
        assert other.post(f"/api/documents/{doc_id}/areas", json=BOX).status_code == 404
    assert len(_events(wapp, "akses_ditolak")) >= 8
    assert _events(wapp, "lihat_halaman") == []


def test_pages_docx_404(client_as, work, make_docx):
    up = client_as("pengguna")
    r = _upload(up, make_docx(), name="s.docx")
    doc_id = r.json()["id"]
    work()
    assert up.get(f"/api/documents/{doc_id}/pages").status_code == 404
    assert up.get(f"/api/documents/{doc_id}/pages/0.png").status_code == 404
    assert up.get(f"/api/documents/{doc_id}/areas").status_code == 404
    assert up.post(f"/api/documents/{doc_id}/areas", json=BOX).status_code == 404


def test_add_list_delete_area_owner(client_as, work, make_pdf, wapp):
    up, doc_id = _ready(client_as, work, make_pdf)
    r = up.post(f"/api/documents/{doc_id}/areas", json=BOX)
    assert r.status_code == 201, r.text
    aid = r.json()["id"]
    lst = up.get(f"/api/documents/{doc_id}/areas")
    assert lst.headers["cache-control"] == "no-store"
    assert [(a["id"], a["page"], a["x0"]) for a in lst.json()] == [(aid, 0, 0.1)]
    mate = client_as("pengguna")
    assert len(mate.get(f"/api/documents/{doc_id}/areas").json()) == 1
    ev = _events(wapp, "area_tambah")
    assert [e.detail for e in ev] == ["hal=0"]
    assert up.delete(f"/api/documents/{doc_id}/areas/{aid}").status_code == 204
    assert up.get(f"/api/documents/{doc_id}/areas").json() == []
    assert [e.detail for e in _events(wapp, "area_hapus")] == ["hal=0"]
    assert up.delete(f"/api/documents/{doc_id}/areas/{aid}").status_code == 404


def test_unit_mate_cannot_add_area_403(client_as, work, make_pdf, wapp):
    up, doc_id = _ready(client_as, work, make_pdf)
    aid = up.post(f"/api/documents/{doc_id}/areas", json=BOX).json()["id"]
    mate = client_as("pengguna")
    assert mate.post(f"/api/documents/{doc_id}/areas", json=BOX).status_code == 403
    assert mate.delete(f"/api/documents/{doc_id}/areas/{aid}").status_code == 403
    assert len(up.get(f"/api/documents/{doc_id}/areas").json()) == 1


def test_area_validation(client_as, work, make_pdf, wapp):
    up, doc_id = _ready(client_as, work, make_pdf)
    bad = [
        {**BOX, "x0": 0.5, "x1": 0.4},
        {**BOX, "y0": 0.3, "y1": 0.1},
        {**BOX, "x1": 1.2},
        {**BOX, "x0": -0.1},
        {**BOX, "x1": 0.103},
        {**BOX, "y1": 0.104},
        {**BOX, "page": 1},
        {**BOX, "page": -1},
    ]
    for b in bad:
        r = up.post(f"/api/documents/{doc_id}/areas", json=b)
        assert r.status_code == 422, b
    from digitadlp.app.models import Document
    with wapp.state.session_factory() as db:
        owner = db.get(Document, doc_id).owner_id
        for _ in range(200):
            db.add(AreaRedaction(document_id=doc_id, page=0, x0=0.1, y0=0.1, x1=0.2,
                                 y1=0.2, author_id=owner))
        db.commit()
    r = up.post(f"/api/documents/{doc_id}/areas", json=BOX)
    assert r.status_code == 422 and "200" in r.json()["detail"]


def test_area_after_approval_invalidates(client_as, work, make_pdf, wapp):
    up, doc_id = _ready(client_as, work, make_pdf)
    up.post(f"/api/documents/{doc_id}/approve")
    work()
    assert up.get(f"/api/documents/{doc_id}").json()["status"] == "disetujui"
    rev = up.get(f"/api/documents/{doc_id}").json()["revision"]
    r = up.post(f"/api/documents/{doc_id}/areas", json=BOX)
    assert r.status_code == 201
    d = up.get(f"/api/documents/{doc_id}").json()
    assert d["status"] == "menunggu_cek" and d["revision"] == rev + 1
    assert d["approved_at"] is None
    assert not wapp.state.store.exists(doc_id, "publik.pdf")
    up.post(f"/api/documents/{doc_id}/approve")
    work()
    assert wapp.state.store.exists(doc_id, "publik.pdf")
    assert up.delete(f"/api/documents/{doc_id}/areas/{r.json()['id']}").status_code == 204
    d = up.get(f"/api/documents/{doc_id}").json()
    assert d["status"] == "menunggu_cek" and d["revision"] == rev + 2
    assert not wapp.state.store.exists(doc_id, "publik.pdf")
    up.post(f"/api/documents/{doc_id}/approve")  # membuat_versi
    assert up.post(f"/api/documents/{doc_id}/areas", json=BOX).status_code == 409


def test_reupload_clears_areas(client_as, work, make_pdf, wapp):
    up, doc_id = _ready(client_as, work, make_pdf)
    up.post(f"/api/documents/{doc_id}/areas", json=BOX)
    assert _reup(up, doc_id, make_pdf).status_code == 200
    with wapp.state.session_factory() as db:
        assert db.scalars(select(AreaRedaction)
                          .where(AreaRedaction.document_id == doc_id)).all() == []


def test_migration_0005_upgrade(tmp_path):
    url = f"sqlite:///{tmp_path / 'm.db'}"
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "0004")
    command.upgrade(cfg, "0005")
    insp = inspect(create_engine(url))
    cols = {c["name"] for c in insp.get_columns("area_redactions")}
    assert cols == {"id", "document_id", "page", "x0", "y0", "x1", "y1",
                    "author_id", "created_at"}
    command.downgrade(cfg, "0004")
    assert "area_redactions" not in inspect(create_engine(url)).get_table_names()


def test_area_change_discards_stale_versi_job(client_as, work, make_pdf, wapp):
    from digitadlp.app.jobs import enqueue
    from digitadlp.app.models import Document, JobKind

    up, doc_id = _ready(client_as, work, make_pdf)
    # a versi job enqueued at the current revision (approve racing an area add)
    with wapp.state.session_factory() as db:
        doc = db.get(Document, doc_id)
        rev = doc.revision
        enqueue(db, JobKind.VERSI, doc)
        db.commit()
    r = up.post(f"/api/documents/{doc_id}/areas", json=BOX)
    assert r.status_code == 201
    assert up.get(f"/api/documents/{doc_id}").json()["revision"] == rev + 1
    work()
    assert not wapp.state.store.exists(doc_id, "publik.pdf")
    assert up.delete(f"/api/documents/{doc_id}/areas/{r.json()['id']}").status_code == 204
    assert up.get(f"/api/documents/{doc_id}").json()["revision"] == rev + 2
