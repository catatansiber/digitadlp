import re
import shutil

import pymupdf as fitz
import pytest

from digitadlp.detect.pipeline import detect
from digitadlp.models import Finding, Kind, Version
from digitadlp.redact.pdf import DocumentError, extract_pdf_text, redact_pdf

NIK = "6474015203880002"
TEXT = f"Nama Siti Rahmawati NIK {NIK}"


def with_names(text, names):
    """detect(text) plus manual NAME_CITIZEN findings for every occurrence of names."""
    found = list(detect(text))
    for n in names:
        for m in re.finditer(re.escape(n), text):
            found.append(Finding(Kind.NAME_CITIZEN, m.start(), m.end(), n, "manual"))
    return sorted(found, key=lambda f: f.start)


def _findings(pages):
    return [with_names(p, ["Siti Rahmawati"]) for p in pages]


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


# ---- review fixes ----
import io

from PIL import Image, ImageDraw

from digitadlp.models import Finding
from digitadlp.redact import pdf as pdfmod


def test_fallback_every_token_must_hit(make_pdf, tmp_path):
    src = make_pdf("NIK 6474 0152\n0388 0002 terdaftar")
    f = Finding(Kind.NIK, 0, 19, "6474 0152\n9999 0002", "test")
    with pytest.raises(DocumentError):
        redact_pdf(src, tmp_path / "out.pdf", [[f]], Version.PUBLIK)


@pytest.mark.skipif(shutil.which("tesseract") is None, reason="tesseract missing")
def test_scanned_fallback_every_token_must_hit(make_scanned_pdf, tmp_path):
    src = make_scanned_pdf(TEXT)
    f = Finding(Kind.NAME_CITIZEN, 0, 10, "Siti\nZzqxwv", "test")
    with pytest.raises(DocumentError):
        redact_pdf(src, tmp_path / "out.pdf", [[f]], Version.PUBLIK)


def test_leak_check_digits_only_for_digit_kinds():
    f = Finding(Kind.NIK, 0, 16, NIK, "test")
    assert pdfmod._leaks("NIK 6474.0152.0388.0002", [f])
    assert not pdfmod._leaks("NIK 6474********0002", [f])
    name = Finding(Kind.NAME_CITIZEN, 0, 4, "Siti Rahmawati", "test")
    assert pdfmod._leaks("nama SITI\nrahmawati", [name])


def test_punctuated_nik_removed(make_pdf, tmp_path):
    src = make_pdf("NIK 6474.0152.0388.0002 terdaftar")
    f = Finding(Kind.NIK, 4, 23, "6474.0152.0388.0002", "test")
    out = tmp_path / "out.pdf"
    redact_pdf(src, out, [[f]], Version.PUBLIK)
    text = fitz.open(out)[0].get_text()
    assert "6474015203880002" not in "".join(c for c in text if c.isdigit())


def _hybrid_pdf(tmp_path):
    from tests.conftest import _font
    img = Image.new("RGB", (1400, 400), "white")
    ImageDraw.Draw(img).text((40, 150), f"NIK {NIK}", fill="black", font=_font(64))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    path = tmp_path / "hybrid.pdf"
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 72), "SURAT KETERANGAN DOMISILI", fontsize=14)
    page.insert_image(fitz.Rect(40, 120, 555, 267), stream=buf.getvalue())
    page.insert_image(fitz.Rect(40, 300, 555, 600), stream=buf.getvalue())
    doc.save(path)
    return path


@pytest.mark.skipif(shutil.which("tesseract") is None, reason="tesseract missing")
def test_hybrid_page_image_nik_removed(tmp_path):
    src = _hybrid_pdf(tmp_path)
    pages = extract_pdf_text(src)
    assert "SURAT" in pages[0] and NIK in pages[0].replace(" ", "")
    out = _run(src, tmp_path, Version.PUBLIK)
    doc = fitz.open(out)
    assert NIK not in pdfmod._ocr_text(doc[0]).replace(" ", "")
    assert "SURAT" in doc[0].get_text()


def test_publik_strips_attachments_widgets_js(make_pdf, tmp_path):
    src = make_pdf(TEXT)
    doc = fitz.open(src)
    doc.embfile_add("ktp.txt", NIK.encode())
    w = fitz.Widget()
    w.field_name, w.field_type = "nik", fitz.PDF_WIDGET_TYPE_TEXT
    w.field_value, w.rect = NIK, fitz.Rect(72, 300, 300, 320)
    doc[0].add_widget(w)
    doc.xref_set_key(doc.pdf_catalog(), "OpenAction",
                     "<</S/JavaScript/JS(app.alert\\(1\\))>>")
    rich = tmp_path / "rich.pdf"
    doc.save(rich)
    out = _run(rich, tmp_path, Version.PUBLIK)
    res = fitz.open(out)
    assert res.embfile_count() == 0
    assert not list(res[0].widgets())
    assert b"JavaScript" not in out.read_bytes()
    assert NIK.encode() not in out.read_bytes()


def test_tessdata_env(monkeypatch):
    monkeypatch.setenv("TESSDATA_PREFIX", "/x/tessdata")
    assert pdfmod._tessdata() == "/x/tessdata"


def test_tessdata_discovered(monkeypatch):
    monkeypatch.delenv("TESSDATA_PREFIX", raising=False)
    assert pdfmod._tessdata().rstrip("/").endswith("tessdata")


def test_tessdata_missing_raises(monkeypatch):
    monkeypatch.delenv("TESSDATA_PREFIX", raising=False)
    def boom(*a, **k):
        raise FileNotFoundError("tesseract")
    monkeypatch.setattr(pdfmod.subprocess, "run", boom)
    with pytest.raises(DocumentError, match="tessdata"):
        pdfmod._tessdata()


# ---------------------------------------------------------------- final review fixes


def _all_bytes(path):
    d = fitz.open(path)
    out = [path.read_bytes()]
    for x in range(1, d.xref_length()):
        try:
            out.append(d.xref_object(x).encode())
            s = d.xref_stream(x)
            if s:
                out.append(s)
        except Exception:
            pass
    d.close()
    return b"\n".join(out)


@pytest.mark.parametrize("version", [Version.PUBLIK, Version.INTERNAL])
def test_outline_and_annotation_pii_removed(make_pdf, tmp_path, version):
    src = make_pdf("Surat edaran biasa")
    d = fitz.open(src)
    d.set_toc([[1, f"Lampiran NIK {NIK}", 1]])
    a = d[0].add_text_annot((300, 300), f"Catatan NIK {NIK}")
    a.set_info(title=f"NIK {NIK}")
    a.update()
    d.set_metadata({"author": f"NIK {NIK}", "title": "x"})
    d.embfile_add(f"nik-{NIK}.txt", b"data")
    w = fitz.Widget()
    w.field_name = "nik"
    w.field_type = fitz.PDF_WIDGET_TYPE_TEXT
    w.field_value = NIK
    w.rect = fitz.Rect(300, 400, 500, 420)
    d[0].add_widget(w)
    tmp = tmp_path / "in.pdf"
    d.save(tmp)
    d.close()
    out = tmp_path / "out.pdf"
    redact_pdf(tmp, out, _findings(extract_pdf_text(tmp)), version)
    r = fitz.open(out)
    assert all(NIK not in t[1] for t in r.get_toc())
    for an in r[0].annots() or []:
        assert NIK not in an.info.get("content", "") and NIK not in an.info.get("title", "")
    assert not list(r[0].widgets() or [])
    assert NIK not in str(r.metadata) and NIK not in (r.get_xml_metadata() or "")
    assert not r.embfile_names()
    if version == Version.INTERNAL:
        assert any("6474********0002" in t[1] for t in r.get_toc())
    r.close()
    assert NIK.encode() not in _all_bytes(out)


def _text_page_with_small_image(tmp_path, img_text):
    import io

    from PIL import Image, ImageDraw

    from tests.conftest import _font
    img = Image.new("RGB", (1200, 140), "white")
    ImageDraw.Draw(img).text((20, 30), img_text, fill="black", font=_font(64))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    path = tmp_path / "small.pdf"
    d = fitz.open()
    page = d.new_page(width=595, height=842)
    page.insert_text((72, 72), "Surat keterangan biasa tanpa data", fontsize=12)
    page.insert_image(fitz.Rect(72, 300, 372, 335), stream=buf.getvalue())
    d.save(path)
    d.close()
    return path


def test_small_image_on_text_page_ocrd(tmp_path):
    from digitadlp.redact.pdf import _kind, _ocr_text
    src = _text_page_with_small_image(tmp_path, f"NIK {NIK}")
    d = fitz.open(src)
    assert _kind(d[0]) == "text"
    d.close()
    pages = extract_pdf_text(src)
    assert NIK in pages[0].replace(" ", "")
    out = tmp_path / "out.pdf"
    redact_pdf(src, out, _findings(pages), Version.PUBLIK)
    r = fitz.open(out)
    assert NIK not in _ocr_text(r[0]).replace(" ", "")


def test_short_address_tokens_removed(make_pdf, tmp_path):
    from digitadlp.models import Finding
    src = make_pdf("Alamat Jl. Pupuk Raya\nRT 05 No 7\nPasal 12 berlaku")
    t = extract_pdf_text(src)[0]
    s = t.index("Jl.")
    e = t.index("No 7") + 4
    f = Finding(Kind.ADDRESS, s, e, t[s:e], "test")
    out = tmp_path / "out.pdf"
    redact_pdf(src, out, [[f]], Version.PUBLIK)
    text = fitz.open(out)[0].get_text()
    assert "RT 05" not in text and "No 7" not in text and "Pupuk" not in text
    assert "Pasal 12" in text


def test_short_token_unlocatable_fails_closed(make_pdf, tmp_path):
    from digitadlp.models import Finding
    src = make_pdf("Alamat Jl. Pupuk Raya")
    f = Finding(Kind.ADDRESS, 0, 10, "Pupuk Raya\nRT 99", "test")
    with pytest.raises(DocumentError):
        redact_pdf(src, tmp_path / "o.pdf", [[f]], Version.PUBLIK)


@pytest.mark.parametrize("exc", ["notfound", "tess", "os"])
def test_ocr_errors_become_document_error(make_scanned_pdf, monkeypatch, exc):
    import pytesseract

    def boom(*a, **k):
        if exc == "notfound":
            raise pytesseract.TesseractNotFoundError()
        if exc == "tess":
            raise pytesseract.TesseractError(1, "bad")
        raise OSError("x")
    monkeypatch.setattr(pytesseract, "image_to_string", boom)
    with pytest.raises(DocumentError):
        extract_pdf_text(make_scanned_pdf(f"NIK {NIK}"))


def test_internal_link_uri_with_nik_removed(make_pdf, tmp_path):
    src = make_pdf("Hubungi kami di sini")
    d = fitz.open(src)
    d[0].insert_link({"kind": fitz.LINK_URI, "from": fitz.Rect(72, 60, 200, 75),
                      "uri": f"mailto:{NIK}@contoh.go.id"})
    tmp = tmp_path / "in.pdf"
    d.save(tmp)
    d.close()
    out = tmp_path / "out.pdf"
    redact_pdf(tmp, out, _findings(extract_pdf_text(tmp)), Version.INTERNAL)
    r = fitz.open(out)
    assert not r[0].get_links()
    r.close()
    assert NIK.encode() not in _all_bytes(out)


def test_word_equal_to_a_placeholder_is_not_a_false_leak(make_pdf, tmp_path):
    # Real IndoBERT tagged the label word "NIK" as a person name; its
    # replacement must not be mistaken for a leak because "[NIK]" contains it.
    src = make_pdf(TEXT)
    pages = [with_names(p, ["Siti Rahmawati", "NIK"]) for p in extract_pdf_text(src)]
    out = tmp_path / "out.pdf"
    redact_pdf(src, out, pages, Version.PUBLIK)
    text = fitz.open(out)[0].get_text()
    assert NIK not in text and "Rahmawati" not in text
