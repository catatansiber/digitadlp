import pymupdf as fitz
import pytest
from fastapi.testclient import TestClient

from digitadlp.api import create_app
from digitadlp.detect.employees import EmployeeDirectory
from digitadlp.detect.ner import FakeNer

NIK = "6474015203880002"
MSG = "Dokumen terenkripsi atau rusak. Buka kunci atau simpan ulang file, lalu upload lagi."
PDF = "application/pdf"


@pytest.fixture
def storage(tmp_path):
    return tmp_path / "storage"


@pytest.fixture
def client(storage):
    app = create_app(FakeNer({}), EmployeeDirectory.from_names([]), storage)
    return TestClient(app)


def _upload(client, path, name=None, ctype=PDF):
    return client.post("/documents", files={"file": (name or path.name, path.read_bytes(), ctype)})


def test_upload_pdf_suggests_rahasia(client, make_pdf, storage):
    r = _upload(client, make_pdf(f"NIK {NIK}"))
    assert r.status_code == 201
    body = r.json()
    assert body["suggested_label"] == "rahasia"
    f = body["findings"][0]
    assert set(f) == {"kind", "text", "start", "end", "page"}
    assert f["kind"] == "NIK" and f["page"] == 0
    assert (storage / body["id"] / "source.pdf").exists()


def test_versions_and_download_publik_has_no_nik(client, make_pdf, tmp_path, storage):
    doc_id = _upload(client, make_pdf(f"NIK {NIK}")).json()["id"]
    r = client.post(f"/documents/{doc_id}/versions")
    assert r.status_code == 200
    assert r.json() == {"versions": ["publik", "internal", "rahasia"]}
    for v in ("publik", "internal", "rahasia"):
        assert (storage / doc_id / f"{v}.pdf").exists()
    r = client.get(f"/documents/{doc_id}/versions/publik")
    assert r.status_code == 200
    out = tmp_path / "out.pdf"
    out.write_bytes(r.content)
    d = fitz.open(out)
    text = "".join(p.get_text() for p in d)
    assert NIK not in text


def test_docx_upload_and_versions(client, make_docx, tmp_path):
    p = make_docx()
    r = client.post("/documents", files={"file": ("a.docx", p.read_bytes(), "application/octet-stream")})
    assert r.status_code == 201
    assert r.json()["suggested_label"] == "rahasia"
    assert r.json()["findings"][0]["page"] == 0
    doc_id = r.json()["id"]
    assert client.post(f"/documents/{doc_id}/versions").status_code == 200
    assert client.get(f"/documents/{doc_id}/versions/publik").status_code == 200


def test_txt_415(client):
    r = client.post("/documents", files={"file": ("a.txt", b"hello", "text/plain")})
    assert r.status_code == 415


def test_encrypted_pdf_422(client, make_pdf, tmp_path):
    src = fitz.open(make_pdf("x"))
    enc = tmp_path / "enc.pdf"
    src.save(enc, encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw="o", user_pw="u")
    r = _upload(client, enc)
    assert r.status_code == 422
    assert r.json() == {"detail": MSG}


def test_corrupt_upload_leaves_no_files(client, storage):
    r = client.post("/documents", files={"file": ("a.pdf", b"not a pdf", PDF)})
    assert r.status_code == 422
    assert not storage.exists() or not any(storage.iterdir())


def test_unknown_and_malicious_ids_404(client, storage):
    assert client.get("/documents/" + "0" * 32 + "/versions/publik").status_code == 404
    assert client.post("/documents/" + "0" * 32 + "/versions").status_code == 404
    assert client.get("/documents/..%2F..%2Fetc/versions/publik").status_code == 404
    assert client.get("/documents/not-hex/versions/publik").status_code == 404


def test_bad_version_404_and_missing_version_404(client, make_pdf):
    doc_id = _upload(client, make_pdf("halo")).json()["id"]
    assert client.get(f"/documents/{doc_id}/versions/rahasia").status_code == 404  # not generated yet
    assert client.get(f"/documents/{doc_id}/versions/..").status_code == 404
    assert client.get(f"/documents/{doc_id}/versions/source").status_code == 404


def test_too_large_413(storage, monkeypatch):
    import digitadlp.api as api
    monkeypatch.setattr(api, "MAX_UPLOAD_BYTES", 1000)
    app = create_app(FakeNer({}), EmployeeDirectory.from_names([]), storage)
    r = TestClient(app).post("/documents", files={"file": ("a.pdf", b"x" * 2000, PDF)})
    assert r.status_code == 413
    assert not storage.exists() or not any(storage.iterdir())


def test_filename_not_used_in_storage(client, make_pdf, storage):
    p = make_pdf("halo")
    r = client.post("/documents", files={"file": ("../../evil.pdf", p.read_bytes(), PDF)})
    assert r.status_code == 201
    d = storage / r.json()["id"]
    assert sorted(x.name for x in d.iterdir()) == ["source.pdf"]


def test_versions_docerror_422_no_partial(client, make_pdf, storage, monkeypatch):
    import digitadlp.api as api
    from digitadlp.redact.pdf import DocumentError
    doc_id = _upload(client, make_pdf(f"NIK {NIK}")).json()["id"]
    calls = {"n": 0}
    real = api.redact_pdf

    def boom(src, dst, fpp, version, *a):
        calls["n"] += 1
        real(src, dst, fpp, version, *a)
        if calls["n"] == 2:
            raise DocumentError(f"leak {NIK}")

    monkeypatch.setattr(api, "redact_pdf", boom)
    r = client.post(f"/documents/{doc_id}/versions")
    assert r.status_code == 422
    assert r.json() == {"detail": MSG}
    assert NIK not in r.text
    assert sorted(x.name for x in (storage / doc_id).iterdir()) == ["source.pdf"]


def test_docx_core_title_only_suggests_rahasia(client, tmp_path):
    from docx import Document
    doc = Document()
    doc.add_paragraph("Surat biasa")
    doc.core_properties.title = f"NIK {NIK}"
    p = tmp_path / "t.docx"
    doc.save(p)
    r = client.post("/documents", files={"file": ("a.docx", p.read_bytes(), "application/octet-stream")})
    assert r.status_code == 201
    assert r.json()["suggested_label"] == "rahasia"
    assert any(f["kind"] == "NIK" for f in r.json()["findings"])


def test_ocr_missing_upload_422(client, make_scanned_pdf, monkeypatch, storage):
    import pytesseract

    def boom(*a, **k):
        raise pytesseract.TesseractNotFoundError()
    monkeypatch.setattr(pytesseract, "image_to_string", boom)
    r = _upload(client, make_scanned_pdf(f"NIK {NIK}"))
    assert r.status_code == 422 and r.json()["detail"] == MSG


def test_ocr_missing_docx_versions_422(client, make_docx, monkeypatch):
    import pytesseract
    p = make_docx(image=True)
    r = client.post("/documents", files={"file": ("a.docx", p.read_bytes(), "application/octet-stream")})
    doc_id = r.json()["id"]

    def boom(*a, **k):
        raise OSError("no tesseract")
    monkeypatch.setattr(pytesseract, "image_to_string", boom)
    r = client.post(f"/documents/{doc_id}/versions")
    assert r.status_code == 422 and r.json()["detail"] == MSG
