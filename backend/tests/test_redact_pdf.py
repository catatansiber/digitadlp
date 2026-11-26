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


# ---- orientation, vicinity ----
needs_tess = pytest.mark.skipif(shutil.which("tesseract") is None, reason="tesseract missing")
ROT_NIP = "197402192001121004"
ROT_TEXT = (
    "DAFTAR HADIR PEGAWAI\n"
    "No   Uraian            Keterangan\n"
    "1    Rapat koordinasi  hadir\n"
    f"Pemohon NIK {NIK}\n"
    "Mengetahui, Kepala Dinas\n"
    "Budi Santoso\n"
    "NIP. 19740219 200112 1 004"
)


def _upright_digits(path):
    """digits of an orientation-aware OCR of every page of path"""
    doc = fitz.open(path)
    try:
        return "".join(re.sub(r"\D", "", pdfmod._ocr_text(p)) for p in doc)
    finally:
        doc.close()


@needs_tess
@pytest.mark.parametrize("angle", [90, 270])
def test_rotated_scan_extracted_and_redacted(make_rotated_scanned_pdf, tmp_path, angle):
    src = make_rotated_scanned_pdf(ROT_TEXT, angle)
    text = extract_pdf_text(src)[0]
    assert "Kepala" in text and "DAFTAR" in text
    assert NIK in text.replace(" ", "")
    assert ROT_NIP in re.sub(r"\D", "", text)
    out = _run(src, tmp_path, Version.PUBLIK)
    digits = _upright_digits(out)
    assert NIK not in digits and ROT_NIP not in digits
    layer = "".join(extract_pdf_text(out))
    assert NIK not in re.sub(r"\D", "", layer)
    assert "Kepala" in layer


def test_osd_failure_falls_back_to_best_rotation(make_rotated_scanned_pdf, monkeypatch):
    import pytesseract

    if shutil.which("tesseract") is None:
        pytest.skip("tesseract missing")

    def no_osd(*a, **k):
        raise pytesseract.TesseractError(1, "Too few characters")
    monkeypatch.setattr(pytesseract, "image_to_osd", no_osd)
    text = extract_pdf_text(make_rotated_scanned_pdf(ROT_TEXT, 90))[0]
    assert NIK in text.replace(" ", "")


def test_fallback_tokens_only_near_anchor(make_pdf, tmp_path):
    text = ("PEMERINTAH KOTA CONTOH\n\n\n\n\n\n\n\n"
            "Alamat Jl. Mawar Indah No. 5\nKota Contoh")
    src = make_pdf(text)
    s = text.index("Jl.")
    f = Finding(Kind.ADDRESS, s, len(text), text[s:], "test")
    out = tmp_path / "o.pdf"
    redact_pdf(src, out, [[f]], Version.PUBLIK)
    got = fitz.open(out)[0].get_text()
    assert "PEMERINTAH KOTA CONTOH" in got
    assert "Mawar" not in got and "Contoh" not in got.split("PEMERINTAH KOTA CONTOH")[1]


def test_fallback_token_only_far_away_fails_closed(make_pdf, tmp_path):
    text = "Kota Contoh\n\n\n\n\n\n\n\n\nJl. Mawar Indah No. 5"
    src = make_pdf(text)
    f = Finding(Kind.ADDRESS, 0, 10, "Jl. Mawar Indah No. 5\nKota Contoh", "test")
    with pytest.raises(DocumentError):
        redact_pdf(src, tmp_path / "o.pdf", [[f]], Version.PUBLIK)


@needs_tess
def test_letterhead_page_end_to_end(make_scanned_pdf, tmp_path):
    text = ("PEMERINTAH KOTA CONTOH\nDINAS KOMUNIKASI\n"
            "Jl. Merdeka No. 1 Telp (0548) 123 Kode Pos 75311\n\n"
            "Nama : Budi Santoso\nAlamat : Jl. Mawar Indah No. 5")
    src = make_scanned_pdf(text)
    found = detect(extract_pdf_text(src)[0])
    kinds = {f.kind for f in found}
    assert Kind.NAME_CITIZEN in kinds and Kind.ADDRESS in kinds
    assert not any("Merdeka" in f.text for f in found)
    out = tmp_path / "o.pdf"
    redact_pdf(src, out, [found], Version.PUBLIK)
    got = "".join(extract_pdf_text(out))
    assert "Merdeka" in got and "CONTOH" in got
    assert "Santoso" not in got and "Mawar" not in got


@pytest.mark.parametrize("split", ["", "\n"])
def test_lone_word_elsewhere_does_not_fail(make_pdf, tmp_path, split):
    addr = f"Jl. Mawar No. 5{split or ' '}Bontang"
    text = f"Taman Mawar Indah\n\n\n\n\n\n\nAlamat {addr}\n\n\n\n\n\n\nBontang, 4 November 2024"
    src = make_pdf(text)
    s = text.index("Jl.")
    f = Finding(Kind.ADDRESS, s, s + len(addr), addr, "test")
    out = tmp_path / "o.pdf"
    redact_pdf(src, out, [[f]], Version.PUBLIK)
    got = fitz.open(out)[0].get_text()
    assert "Bontang, 4 November 2024" in got and "Taman Mawar Indah" in got
    assert "Jl. Mawar" not in got and got.count("Bontang") == 1


# --- area redactions -------------------------------------------------------

def _text_pdf(path, lines, rotation=0):
    d = fitz.open()
    p = d.new_page()
    for pos, s in lines:
        p.insert_text(pos, s, fontsize=12)
    if rotation:
        p.set_rotation(rotation)
    d.save(path)
    d.close()
    return path


def _area_of(path, needle):
    """Display-space fractional box around `needle` on page 0."""
    d = fitz.open(path)
    p = d[0]
    r = p.search_for(needle)[0] * p.rotation_matrix
    W, H = p.rect.width, p.rect.height
    d.close()
    r.normalize()
    return (0, ((r.x0 - 2) / W, (r.y0 - 2) / H, (r.x1 + 2) / W, (r.y1 + 2) / H))


def test_area_removes_text_publik_internal_not_rahasia(tmp_path):
    src = _text_pdf(tmp_path / "a.pdf", [((72, 100), "RAHASIAKOTAK"),
                                         ((72, 300), "TETAPADA")])
    area = _area_of(src, "RAHASIAKOTAK")
    for v in (Version.PUBLIK, Version.INTERNAL, Version.RAHASIA):
        out = tmp_path / f"{v.value}.pdf"
        redact_pdf(src, out, [[]], v, areas=[area])
        text = fitz.open(out)[0].get_text()
        assert "TETAPADA" in text
        if v == Version.RAHASIA:
            assert "RAHASIAKOTAK" in text
        else:
            assert "RAHASIAKOTAK" not in text
            assert b"RAHASIAKOTAK" not in out.read_bytes()


def test_area_wipes_image_pixels(tmp_path):
    img = Image.new("RGB", (200, 200), (255, 0, 0))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    d = fitz.open()
    p = d.new_page()
    p.insert_image(fitz.Rect(100, 100, 300, 300), stream=buf.getvalue())
    src = tmp_path / "img.pdf"
    d.save(src)
    W, H = p.rect.width, p.rect.height
    d.close()
    box = (150 / W, 150 / H, 250 / W, 250 / H)
    out = tmp_path / "out.pdf"
    redact_pdf(src, out, [[]], Version.PUBLIK, areas=[(0, box)])
    page = fitz.open(out)[0]
    pix = page.get_pixmap(dpi=72, clip=fitz.Rect(152, 152, 248, 248))
    assert pix.pixel(pix.width // 2, pix.height // 2) == (0, 0, 0)
    for y in range(pix.height):
        for x in range(pix.width):
            r, g, b = pix.pixel(x, y)
            assert not (r > 200 and g < 80 and b < 80)
    # embedded image itself no longer carries red pixels in that region
    xref = page.get_images()[0][0]
    raw = fitz.Pixmap(page.parent, xref)
    assert raw.pixel(raw.width // 2, raw.height // 2)[:3] != (255, 0, 0)


def test_area_on_rotated_page(tmp_path):
    # unrotated coords: text near top-left; after /Rotate 90 it appears top-right
    src = _text_pdf(tmp_path / "rot.pdf", [((72, 100), "SUDUTKIRI"),
                                           ((72, 700), "LAINNYA")], rotation=90)
    area = _area_of(src, "SUDUTKIRI")
    assert area[1][0] > 0.5  # display space: on the right half
    out = tmp_path / "out.pdf"
    redact_pdf(src, out, [[]], Version.PUBLIK, areas=[area])
    text = fitz.open(out)[0].get_text()
    assert "SUDUTKIRI" not in text and "LAINNYA" in text


def test_area_on_scanned_page_survives_reocr(make_scanned_pdf, tmp_path):
    src = make_scanned_pdf(TEXT)
    out = tmp_path / "out.pdf"
    # cover the whole top half: NIK line goes black even with no findings
    redact_pdf(src, out, [[]], Version.PUBLIK, areas=[(0, (0.0, 0.0, 1.0, 0.5))])
    page = fitz.open(out)[0]
    assert NIK not in page.get_text().replace(" ", "")
    assert NIK not in "".join(extract_pdf_text(out)).replace(" ", "")
    pix = page.get_pixmap(dpi=30)
    assert pix.pixel(pix.width // 2, pix.height // 4) == (0, 0, 0)
