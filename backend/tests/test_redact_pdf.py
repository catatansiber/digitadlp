import shutil

import pymupdf as fitz
import pytest

from digitadlp.detect.employees import EmployeeDirectory
from digitadlp.detect.ner import FakeNer
from digitadlp.detect.pipeline import detect
from digitadlp.models import Kind, Version
from digitadlp.redact.pdf import DocumentError, extract_pdf_text, redact_pdf

NIK = "6474015203880002"
TEXT = f"Nama Siti Rahmawati NIK {NIK}"


def _findings(pages):
    ner = FakeNer({"Siti Rahmawati": Kind.NAME_CITIZEN})
    directory = EmployeeDirectory.from_names([])
    return [detect(p, ner, directory) for p in pages]


def _run(src, tmp_path, version):
    out = tmp_path / "out.pdf"
    redact_pdf(src, out, _findings(extract_pdf_text(src)), version)
    return out


def test_text_really_removed(make_pdf, tmp_path):
    out = _run(make_pdf(TEXT), tmp_path, Version.PUBLIK)
    text = fitz.open(out)[0].get_text()
    assert NIK not in text and "[NIK]" in text
    assert "Rahmawati" not in text
    raw = out.read_bytes()
    assert NIK.encode() not in raw


def test_internal_masks(make_pdf, tmp_path):
    out = _run(make_pdf(TEXT), tmp_path, Version.INTERNAL)
    text = fitz.open(out)[0].get_text()
    assert NIK not in text
    assert "6474********0002" in text


def test_rahasia_unchanged(make_pdf, tmp_path):
    out = _run(make_pdf(TEXT), tmp_path, Version.RAHASIA)
    assert NIK in fitz.open(out)[0].get_text()


def test_metadata_stripped(make_pdf, tmp_path):
    out = _run(make_pdf(TEXT), tmp_path, Version.PUBLIK)
    assert fitz.open(out).metadata["author"] == ""


def test_nik_twice_both_removed(make_pdf, tmp_path):
    src = make_pdf(f"NIK {NIK}\nNIK pelapor {NIK}")
    pages = extract_pdf_text(src)
    findings = _findings(pages)
    # only the first occurrence is passed in: every occurrence must still go
    first = [f for f in findings[0] if f.kind == Kind.NIK][:1]
    out = tmp_path / "out.pdf"
    redact_pdf(src, out, [first], Version.PUBLIK)
    assert NIK not in fitz.open(out)[0].get_text()


def test_nik_spanning_line_break(make_pdf, tmp_path):
    src = make_pdf("NIK 6474 0152\n0388 0002 terdaftar")
    pages = extract_pdf_text(src)
    start = pages[0].index("6474")
    end = pages[0].index("0002") + 4
    from digitadlp.models import Finding
    f = Finding(Kind.NIK, start, end, pages[0][start:end], "test")
    out = tmp_path / "out.pdf"
    redact_pdf(src, out, [[f]], Version.PUBLIK)
    text = fitz.open(out)[0].get_text()
    for tok in ("6474", "0152", "0388", "0002"):
        assert tok not in text


def test_unlocatable_finding_fails_closed(make_pdf, tmp_path):
    from digitadlp.models import Finding
    src = make_pdf(TEXT)
    f = Finding(Kind.NIK, 0, 16, "9999888877776666", "test")
    with pytest.raises(DocumentError):
        redact_pdf(src, tmp_path / "out.pdf", [[f]], Version.PUBLIK)


@pytest.mark.skipif(shutil.which("tesseract") is None, reason="tesseract missing")
def test_scanned_pdf_redacted(make_scanned_pdf, tmp_path):
    src = make_scanned_pdf(TEXT)
    pages = extract_pdf_text(src)
    assert NIK in pages[0].replace(" ", "")
    out = _run(src, tmp_path, Version.PUBLIK)
    assert NIK not in "".join(extract_pdf_text(out)).replace(" ", "")
    # searchable after re-OCR
    assert "Nama" in fitz.open(out)[0].get_text()


def test_encrypted_raises(make_pdf, tmp_path):
    src = make_pdf(TEXT)
    enc = tmp_path / "enc.pdf"
    doc = fitz.open(src)
    doc.save(enc, encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw="o", user_pw="u")
    with pytest.raises(DocumentError):
        extract_pdf_text(enc)


def test_corrupt_raises(tmp_path):
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"not a pdf at all")
    with pytest.raises(DocumentError):
        extract_pdf_text(bad)
