import pytest
from sqlalchemy import select

from digitadlp.app.access import can_download
from digitadlp.app.models import AuditEvent, Document, Role, Status, User

from .test_workflow import (  # noqa: F401  (fixtures)
    _ready, _upload, client_as, wapp, work,
)

ALL = ("publik", "internal", "rahasia")


def _prep(client_as, work, make_pdf, wapp, status):
    up, doc_id = _ready(client_as, work, make_pdf)
    rev = client_as("pemeriksa", unit="Unit B")
    rev.post(f"/documents/{doc_id}/approve")
    work()
    if status == "dirilis":
        assert rev.post(f"/documents/{doc_id}/release").status_code == 200
    return up, rev, doc_id


# (actor, expected per version) for each status; unit of doc = Unit A, owner = pengunggah
def _expect(actor, status, version):
    rel = status == "dirilis"
    same = actor in ("owner", "unit_mate", "admin_same")
    rev = actor == "pemeriksa"
    if version == "publik":
        return rel or (same or rev)
    if version == "internal":
        return True
    return same or rev


@pytest.mark.parametrize("status", ["disetujui", "dirilis"])
@pytest.mark.parametrize("version", ALL)
@pytest.mark.parametrize(
    "actor", ["owner", "unit_mate", "admin_same", "other_up", "admin_other", "pemeriksa"])
def test_matrix(client_as, work, make_pdf, wapp, actor, version, status):
    up, rev, doc_id = _prep(client_as, work, make_pdf, wapp, status)
    c = {
        "owner": up,
        "unit_mate": lambda: client_as("pengunggah", unit="Unit A"),
        "admin_same": lambda: client_as("admin", unit="Unit A"),
        "other_up": lambda: client_as("pengunggah", unit="Unit C"),
        "admin_other": lambda: client_as("admin", unit="Unit C"),
        "pemeriksa": rev,
    }[actor]
    c = c() if callable(c) and not hasattr(c, "get") else c
    r = c.get(f"/documents/{doc_id}/versions/{version}")
    # internal is downloadable for everyone at these statuses, so a denial is never 404
    want = 200 if _expect(actor, status, version) else 403
    assert r.status_code == want, (actor, version, status, r.text)


def test_not_ready_status_denied(client_as, work, make_pdf, wapp):
    up, doc_id = _ready(client_as, work, make_pdf)  # menunggu_cek
    r = up.get(f"/documents/{doc_id}/versions/publik")
    assert r.status_code == 403


def test_other_unit_disetujui_is_403(client_as, work, make_pdf, wapp):
    _up, _rev, doc_id = _prep(client_as, work, make_pdf, wapp, "disetujui")
    other = client_as("pengunggah", unit="Unit C")
    assert other.get(f"/documents/{doc_id}/versions/publik").status_code == 403
    assert other.get(f"/documents/{doc_id}/versions/internal").status_code == 200


def test_non_viewer_404_and_audited(client_as, work, make_pdf, wapp):
    up, doc_id = _ready(client_as, work, make_pdf)  # menunggu_cek
    other = client_as("pengunggah", unit="Unit C")
    assert other.get(f"/documents/{doc_id}/versions/publik").status_code == 404
    with wapp.state.session_factory() as db:
        ev = db.scalars(select(AuditEvent).where(AuditEvent.action == "akses_ditolak")).all()
    assert len(ev) == 1 and ev[0].document_id == doc_id and ev[0].detail == "versi=publik"


def test_inactive_user_401(client_as, work, make_pdf, wapp):
    up, _rev, doc_id = _prep(client_as, work, make_pdf, wapp, "dirilis")
    with wapp.state.session_factory() as db:
        for u in db.scalars(select(User).where(User.id == db.get(Document, doc_id).owner_id)):
            u.active = False
        db.commit()
    assert up.get(f"/documents/{doc_id}/versions/publik").status_code == 401


def test_denied_is_audited(client_as, work, make_pdf, wapp):
    _up, _rev, doc_id = _prep(client_as, work, make_pdf, wapp, "dirilis")
    other = client_as("pengunggah", unit="Unit C")
    r = other.get(f"/documents/{doc_id}/versions/rahasia")
    assert r.status_code == 403 and r.json()["detail"] == "Anda tidak punya akses ke versi ini."
    with wapp.state.session_factory() as db:
        ev = db.scalars(select(AuditEvent).where(AuditEvent.action == "akses_ditolak")).all()
    assert len(ev) == 1 and ev[0].document_id == doc_id


def test_download_audited_and_headers(client_as, work, make_pdf, wapp):
    up, _rev, doc_id = _prep(client_as, work, make_pdf, wapp, "dirilis")
    r = up.get(f"/documents/{doc_id}/versions/rahasia")
    assert r.status_code == 200
    assert r.headers["cache-control"] == "no-store"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["content-type"] == "application/pdf"
    assert r.headers["content-disposition"] == f'attachment; filename="{doc_id}-rahasia.pdf"'
    assert r.content.startswith(b"%PDF")
    with wapp.state.session_factory() as db:
        ev = db.scalars(select(AuditEvent).where(AuditEvent.action == "unduh")).all()
    assert len(ev) == 1 and ev[0].detail == "versi=rahasia" and ev[0].document_id == doc_id


def test_admin_other_unit_rahasia_403(client_as, work, make_pdf, wapp):
    _up, _rev, doc_id = _prep(client_as, work, make_pdf, wapp, "dirilis")
    adm = client_as("admin", unit="Unit C")
    assert adm.get(f"/documents/{doc_id}/versions/publik").status_code == 200
    assert adm.get(f"/documents/{doc_id}/versions/rahasia").status_code == 403


def test_unknown_version_and_missing_file(client_as, work, make_pdf, wapp):
    up, _rev, doc_id = _prep(client_as, work, make_pdf, wapp, "dirilis")
    assert up.get(f"/documents/{doc_id}/versions/xyz").status_code == 404
    assert up.get("/documents/nonexistent/versions/publik").status_code == 404
    wapp.state.store.delete_versions(doc_id)
    r = up.get(f"/documents/{doc_id}/versions/publik")
    assert r.status_code == 404 and r.json()["detail"] == "Versi belum tersedia."


def test_list_filters(client_as, work, make_pdf, wapp):
    up, rev, doc_id = _prep(client_as, work, make_pdf, wapp, "dirilis")
    r = up.get("/documents").json()
    assert [d["id"] for d in r] == [doc_id]
    d = r[0]
    assert d["owner"] == "Pengunggah1" and d["unit"] == "Unit A" and "findings" not in d
    assert up.get("/documents?status=dirilis").json()
    assert up.get("/documents?status=diproses").json() == []
    bad = up.get("/documents?status=ngawur")
    assert bad.status_code == 422
    assert rev.get("/documents").json()
    assert rev.get("/documents?mine=true").json() == []
    mate = client_as("pengunggah", unit="Unit A")
    assert len(mate.get("/documents").json()) == 1
    assert mate.get("/documents?mine=true").json() == []
    assert client_as("pengunggah", unit="Unit C").get("/documents").json() == []
    assert client_as("admin", unit="Unit C").get("/documents").json() == []
    assert client_as("admin", unit="Unit A").get("/documents").json()


@pytest.mark.parametrize("role,same,version,status,exp", [
    (Role.ADMIN, False, "rahasia", Status.DIRILIS, False),
    (Role.ADMIN, True, "rahasia", Status.DISETUJUI, True),
    (Role.PEMERIKSA, False, "rahasia", Status.DISETUJUI, True),
    (Role.PENGUNGGAH, False, "publik", Status.DISETUJUI, False),
    (Role.PENGUNGGAH, False, "internal", Status.DIRILIS, True),
    (Role.PENGUNGGAH, True, "internal", Status.MENUNGGU_CEK, False),
])
def test_can_download_unit(role, same, version, status, exp):
    from types import SimpleNamespace as N
    u = N(id="u1", role=role, unit_id="A")
    d = N(owner_id="o", unit_id="A" if same else "B", status=status)
    assert can_download(u, d, version) is exp
