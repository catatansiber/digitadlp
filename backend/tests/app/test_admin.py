import io

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook
from sqlalchemy import select

from digitadlp.app.jobs import run_pending
from digitadlp.app.main import create_app
from digitadlp.app.models import AuditEvent, AuthSession, Base, Document, User
from digitadlp.app.processing import Engine
from digitadlp.detect.employees import EmployeeDirectory
from digitadlp.detect.ner import FakeNer
from digitadlp.models import Kind

from .conftest import make_user

NAME = "Budi Santoso"
TEXT = f"Disposisi oleh {NAME}\nNomor surat 12/2026"


def _engine():
    return Engine(FakeNer({NAME: Kind.NAME_CITIZEN}), EmployeeDirectory(set()))


@pytest.fixture
def aapp(app_settings):
    app = create_app(app_settings, _engine())
    Base.metadata.create_all(app.state.db_engine)
    yield app
    app.state.db_engine.dispose()


@pytest.fixture
def login(aapp):
    clients = []

    def _login(username, password="rahasia123"):
        c = TestClient(aapp)
        clients.append(c)
        r = c.post("/auth/login", json={"username": username, "password": password})
        assert r.status_code == 200, r.text
        return c

    yield _login
    for c in clients:
        c.close()


@pytest.fixture
def admin(aapp, login):
    with aapp.state.session_factory() as db:
        make_user(db, "admin", role="admin", unit_name="Sekretariat")
    return login("admin")


def _xlsx(names):
    wb = Workbook()
    ws = wb.active
    ws.append(["Nama", "NIP"])
    for n in names:
        ws.append([n, ""])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _actions(aapp):
    with aapp.state.session_factory() as db:
        return [e.action for e in db.scalars(select(AuditEvent))]


def test_units_crud(admin, aapp):
    r = admin.post("/admin/units", json={"name": "Bidang IKP"})
    assert r.status_code == 201, r.text
    names = [u["name"] for u in admin.get("/admin/units").json()]
    assert "Bidang IKP" in names and "Sekretariat" in names
    r = admin.post("/admin/units", json={"name": "Bidang IKP"})
    assert r.status_code == 409
    assert "unit_dibuat" in _actions(aapp)


def test_admin_crud_user(admin, aapp, login):
    unit = admin.post("/admin/units", json={"name": "Bidang IKP"}).json()
    r = admin.post("/admin/users", json={"username": "rina", "full_name": "Rina",
                                          "role": "pengunggah", "unit_id": unit["id"],
                                          "password": "pendek"})
    assert r.status_code == 422
    assert r.json()["detail"] == "Kata sandi minimal 10 karakter."
    r = admin.post("/admin/users", json={"username": "rina", "full_name": "Rina",
                                          "role": "pengunggah", "unit_id": unit["id"],
                                          "password": "rahasia12345"})
    assert r.status_code == 201, r.text
    uid = r.json()["id"]
    assert "password" not in r.text and "password_hash" not in r.json()
    assert r.json()["unit"] == "Bidang IKP" and r.json()["active"] is True
    r = admin.post("/admin/users", json={"username": "rina", "full_name": "X",
                                          "role": "pengunggah", "unit_id": unit["id"],
                                          "password": "rahasia12345"})
    assert r.status_code == 409
    assert any(u["id"] == uid for u in admin.get("/admin/users").json())
    r = admin.patch(f"/admin/users/{uid}", json={"role": "pemeriksa"})
    assert r.status_code == 200 and r.json()["role"] == "pemeriksa"
    r = admin.patch(f"/admin/users/{uid}", json={"password": "kataSandiBaru1"})
    assert r.status_code == 200
    c = login("rina", "kataSandiBaru1")
    assert c.get("/auth/me").json()["role"] == "pemeriksa"
    assert admin.patch("/admin/users/" + "0" * 32, json={"active": False}).status_code == 404
    assert admin.patch(f"/admin/users/{uid}", json={"unit_id": "0" * 32}).status_code == 422
    assert admin.patch(f"/admin/users/{uid}", json={"role": "raja"}).status_code == 422
    acts = _actions(aapp)
    assert "user_dibuat" in acts and acts.count("user_diubah") >= 2
    with aapp.state.session_factory() as db:
        for e in db.scalars(select(AuditEvent)):
            assert "rina" not in e.detail and "Rina" not in e.detail


def test_deactivate_kills_sessions(admin, aapp, login):
    with aapp.state.session_factory() as db:
        u = make_user(db, "siti")
        uid = u.id
    c = login("siti")
    assert c.get("/auth/me").status_code == 200
    r = admin.patch(f"/admin/users/{uid}", json={"active": False})
    assert r.status_code == 200 and r.json()["active"] is False
    with aapp.state.session_factory() as db:
        assert db.scalars(select(AuthSession).where(AuthSession.user_id == uid)).all() == []
    admin.patch(f"/admin/users/{uid}", json={"active": True})
    assert c.get("/auth/me").status_code == 401  # sesi lama tetap mati


def test_admin_cannot_lock_self_out(admin, aapp):
    me = admin.get("/auth/me").json()["id"]
    for body in ({"active": False}, {"role": "pemeriksa"}):
        r = admin.patch(f"/admin/users/{me}", json=body)
        assert r.status_code == 409
        assert r.json()["detail"] == "Admin tidak bisa menonaktifkan atau menurunkan peran akunnya sendiri."
    assert admin.get("/auth/me").json()["role"] == "admin"


ROUTES = [
    ("get", "/admin/units", None), ("post", "/admin/units", {"name": "x"}),
    ("get", "/admin/users", None), ("post", "/admin/users", {}),
    ("patch", "/admin/users/" + "0" * 32, {}), ("get", "/admin/label-rules", None),
    ("put", "/admin/label-rules", {}), ("get", "/admin/audit", None),
    ("post", "/admin/employees", None),
]


@pytest.mark.parametrize("role", ["pengunggah", "pemeriksa"])
@pytest.mark.parametrize("method,path,body", ROUTES)
def test_non_admin_403(aapp, login, role, method, path, body):
    with aapp.state.session_factory() as db:
        make_user(db, role, role=role)
    c = login(role)
    kw = {"json": body} if body is not None else {}
    r = getattr(c, method)(path, **kw)
    assert r.status_code == 403


def test_anonymous_401(aapp):
    with TestClient(aapp) as c:
        assert c.get("/admin/users").status_code == 401


def _detect(aapp, login):
    with aapp.state.session_factory() as db:
        if db.scalar(select(User).where(User.username == "up")) is None:
            make_user(db, "up")
    up = login("up")
    return up


def _findings(aapp, up, pdf):
    r = up.post("/documents", files={"file": ("s.pdf", pdf.read_bytes(), "application/pdf")})
    assert r.status_code == 201, r.text
    run_pending(aapp.state.session_factory, aapp.state.store, aapp.state.engine)
    return up.get(f"/documents/{r.json()['id']}").json()


def test_employee_import_reloads_directory(admin, aapp, login, make_pdf, app_settings):
    up = _detect(aapp, login)
    before = _findings(aapp, up, make_pdf(TEXT))
    assert any(f["kind"] == "NAME_CITIZEN" for p in before["findings"] for f in p)
    r = admin.post("/admin/employees", files={"file": ("pegawai.xlsx", _xlsx([NAME]), XLSX)})
    assert r.status_code == 200, r.text
    assert r.json() == {"names": 1, "nips": 0}
    after = _findings(aapp, up, make_pdf(TEXT))
    kinds = {f["kind"] for p in after["findings"] for f in p}
    assert "NAME_EMPLOYEE" in kinds and "NAME_CITIZEN" not in kinds
    # tersimpan terenkripsi, bukan plaintext
    raw = (aapp.state.store.root / "_config" / "employees.xlsx.enc").read_bytes()
    assert not raw.startswith(b"PK")
    assert "impor_pegawai" in _actions(aapp)
    # restart: aplikasi baru pada storage yang sama memuat daftar pegawai
    app2 = create_app(app_settings, _engine())
    assert app2.state.engine.directory.is_employee(NAME)
    app2.state.db_engine.dispose()


def test_employee_import_bad_file_keeps_old(admin, aapp):
    admin.post("/admin/employees", files={"file": ("p.xlsx", _xlsx([NAME]), XLSX)})
    r = admin.post("/admin/employees", files={"file": ("p.xlsx", b"bukan xlsx", XLSX)})
    assert r.status_code == 422
    assert r.json()["detail"] == "File daftar pegawai tidak bisa dibaca. Gunakan .xlsx dengan kolom Nama."
    assert aapp.state.engine.directory.is_employee(NAME)
    r = admin.post("/admin/employees", files={"file": ("p.txt", b"x", "text/plain")})
    assert r.status_code == 415


def test_label_rules_applied(admin, aapp, login, make_pdf):
    rules = admin.get("/admin/label-rules").json()
    assert set(rules) == {k.value for k in Kind}
    assert rules["NAME_CITIZEN"] == "internal" and rules["NIK"] == "rahasia"
    up = _detect(aapp, login)
    assert _findings(aapp, up, make_pdf(TEXT))["suggested_label"] == "internal"
    new = {k: "publik" for k in rules}
    r = admin.put("/admin/label-rules", json=new)
    assert r.status_code == 200 and r.json() == new
    assert admin.get("/admin/label-rules").json() == new
    assert _findings(aapp, up, make_pdf(TEXT))["suggested_label"] == "publik"
    assert "aturan_label" in _actions(aapp)


def test_label_rules_validation_atomic(admin):
    before = admin.get("/admin/label-rules").json()
    r = admin.put("/admin/label-rules", json={"NIK": "publik", "BOGUS": "publik"})
    assert r.status_code == 422
    r = admin.put("/admin/label-rules", json={"NIK": "rahasiaa"})
    assert r.status_code == 422
    assert admin.get("/admin/label-rules").json() == before
    r = admin.put("/admin/label-rules", json={"NIK": "internal"})
    assert r.status_code == 200
    got = admin.get("/admin/label-rules").json()
    assert got["NIK"] == "internal" and got["NAME_CITIZEN"] == before["NAME_CITIZEN"]


def test_audit_list(admin, aapp, login, make_pdf):
    up = _detect(aapp, login)
    d = _findings(aapp, up, make_pdf(TEXT))
    with aapp.state.session_factory() as db:
        up_id = db.scalar(select(User.id).where(User.username == "up"))
    r = admin.get("/admin/audit", params={"document_id": d["id"]})
    assert r.status_code == 200
    ev = r.json()
    assert [e["action"] for e in ev] == ["deteksi_selesai", "upload"]  # terbaru dulu
    assert set(ev[0]) >= {"id", "at", "actor_id", "action", "document_id", "detail"}
    r = admin.get("/admin/audit", params={"actor_id": up_id})
    assert {e["action"] for e in r.json()} == {"masuk", "upload"}
    assert len(admin.get("/admin/audit", params={"limit": 1}).json()) == 1
    assert admin.get("/admin/audit", params={"limit": 501}).status_code == 422
    assert admin.get("/admin/audit", params={"limit": 0}).status_code == 422


def _sessions(aapp, uid):
    with aapp.state.session_factory() as db:
        return db.scalars(select(AuthSession).where(AuthSession.user_id == uid)).all()


def test_password_reset_and_role_change_kill_target_sessions(admin, aapp, login):
    with aapp.state.session_factory() as db:
        uid = make_user(db, "siti").id
    c = login("siti")
    admin.patch(f"/admin/users/{uid}", json={"password": "SandiBaru12345"})
    assert _sessions(aapp, uid) == [] and c.get("/auth/me").status_code == 401
    c = login("siti", "SandiBaru12345")
    admin.patch(f"/admin/users/{uid}", json={"role": "pemeriksa"})
    assert _sessions(aapp, uid) == [] and c.get("/auth/me").status_code == 401


def test_admin_self_password_reset_keeps_current_session(admin, aapp, login):
    other = login("admin")
    me = admin.get("/auth/me").json()["id"]
    assert len(_sessions(aapp, me)) == 2
    r = admin.patch(f"/admin/users/{me}", json={"password": "AdminBaru12345"})
    assert r.status_code == 200
    assert admin.get("/auth/me").status_code == 200
    assert other.get("/auth/me").status_code == 401
    assert len(_sessions(aapp, me)) == 1


def test_full_name_only_logged_when_changed(admin, aapp):
    me = admin.get("/auth/me").json()
    admin.patch(f"/admin/users/{me['id']}", json={"full_name": me["full_name"]})
    with aapp.state.session_factory() as db:
        ev = db.scalars(select(AuditEvent).where(AuditEvent.action == "user_diubah")).one()
    assert "nama" not in ev.detail
