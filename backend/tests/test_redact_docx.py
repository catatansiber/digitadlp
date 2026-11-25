import io
import re
import zipfile

import pytest
from PIL import Image

from digitadlp.detect.employees import EmployeeDirectory
from digitadlp.detect.ner import FakeNer
from digitadlp.detect.pipeline import detect
from digitadlp.models import Finding, Kind, Version
from digitadlp.redact import docx as docxmod
from digitadlp.redact.docx import extract_docx_text, redact_docx
from digitadlp.redact.pdf import DocumentError

from .conftest import DOCX_NIK

NIKS = [DOCX_NIK] + [f"32010101010100{i:02d}" for i in range(1, 12)]


def detect_fn(text):
    return detect(text, FakeNer({"Siti Rahmawati": Kind.NAME_CITIZEN}),
                  EmployeeDirectory.from_names([]))


def _run(src, tmp_path, version):
    out = tmp_path / f"out-{version}.docx"
    redact_docx(src, out, detect_fn, version)
    return out


def _all_text(path):
    with zipfile.ZipFile(path) as z:
        return {n: z.read(n) for n in z.namelist()}


def _xml_text(path):
    parts = _all_text(path)
    return "".join(
        re.sub(rb"<[^>]+>", b"", b).decode("utf-8", "replace")
        for n, b in parts.items() if n.endswith((".xml", ".rels"))
    )


def test_extract_includes_all_locations(make_docx):
    text = "\n".join(extract_docx_text(make_docx()))
    assert f"NIK {DOCX_NIK}" in text  # split runs joined
    for n in NIKS[1:10]:
        assert n in text, n


def test_split_run_nik_removed(make_docx, tmp_path):
    out = _run(make_docx(), tmp_path, Version.PUBLIK)
    raw = b"".join(_all_text(out).values())
    assert DOCX_NIK[:8].encode() not in raw
    assert DOCX_NIK[8:].encode() not in raw
    assert "Rahmawati" not in _xml_text(out)
    paras = extract_docx_text(out)
    assert any("[NIK]" in p and "[NAMA]" in p for p in paras)
    # bold formatting of the starting run preserved
    from docx import Document
    p0 = Document(out).paragraphs[0]
    assert any(r.bold and "[NIK]" in r.text for r in p0.runs)


@pytest.mark.parametrize("version", [Version.PUBLIK, Version.INTERNAL])
def test_header_footer_table_textbox(make_docx, tmp_path, version):
    out = _run(make_docx(), tmp_path, version)
    text = _xml_text(out)
    for n in NIKS:
        assert n not in re.sub(r"\D", "", text) or False, n
    if version == Version.INTERNAL:
        assert "3201********0003" in text  # header masked, not removed


def test_comments_and_tracked_changes_removed(make_docx, tmp_path):
    src = make_docx()
    assert "word/comments.xml" in _all_text(src)
    out = _run(src, tmp_path, Version.PUBLIK)
    parts = _all_text(out)
    assert "word/comments.xml" not in parts
    doc = parts["word/document.xml"].decode()
    for tag in ("w:del ", "w:del>", "w:delText", "w:ins ", "w:commentRangeStart",
                "w:commentReference"):
        assert tag not in doc, tag
    assert "Tambahan resmi" in doc
    assert "comments" not in parts["word/_rels/document.xml.rels"].decode()
    assert "comments" not in parts["[Content_Types].xml"].decode()
    for n in ("3201010101010010", "3201010101010011"):
        assert n.encode() not in b"".join(parts.values())


def test_internal_keeps_comment_but_masks(make_docx, tmp_path):
    out = _run(make_docx(), tmp_path, Version.INTERNAL)
    parts = _all_text(out)
    assert "word/comments.xml" in parts
    assert b"3201010101010010" not in parts["word/comments.xml"]


def test_core_props_cleared(make_docx, tmp_path):
    from docx import Document
    out = _run(make_docx(), tmp_path, Version.PUBLIK)
    cp = Document(out).core_properties
    assert cp.author == "" and cp.last_modified_by == "" and cp.comments == ""


def test_publik_removes_custom_parts(make_docx, tmp_path):
    src = make_docx()
    tmp = tmp_path / "custom.docx"
    with zipfile.ZipFile(src) as zi, zipfile.ZipFile(tmp, "w") as zo:
        for n in zi.namelist():
            zo.writestr(n, zi.read(n))
        zo.writestr("customXml/item99.xml", "<x>NIK data</x>")
        zo.writestr("docProps/custom.xml", "<Properties>rahasia</Properties>")
    parts = _all_text(_run(tmp, tmp_path, Version.PUBLIK))
    assert not any(n.startswith("customXml/") for n in parts)
    assert "docProps/custom.xml" not in parts


def test_rahasia_unchanged(make_docx, tmp_path):
    src = make_docx()
    out = _run(src, tmp_path, Version.RAHASIA)
    assert out.read_bytes() == src.read_bytes()


def test_image_with_nik_blacked_out(make_docx, tmp_path):
    out = _run(make_docx(image=True), tmp_path, Version.PUBLIK)
    media = {n: b for n, b in _all_text(out).items() if n.startswith("word/media/")}
    assert media
    for b in media.values():
        img = Image.open(io.BytesIO(b))
        assert img.size == (900, 120)
        assert img.convert("L").getextrema() == (0, 0)


def test_corrupt_raises(tmp_path):
    bad = tmp_path / "bad.docx"
    bad.write_bytes(b"not a zip at all")
    with pytest.raises(DocumentError):
        redact_docx(bad, tmp_path / "o.docx", detect_fn, Version.PUBLIK)
    with pytest.raises(DocumentError):
        extract_docx_text(bad)


def test_zip_without_document_raises(tmp_path):
    bad = tmp_path / "bad.docx"
    with zipfile.ZipFile(bad, "w") as z:
        z.writestr("x.txt", "hi")
    with pytest.raises(DocumentError):
        redact_docx(bad, tmp_path / "o.docx", detect_fn, Version.PUBLIK)


def test_guard_raises_on_leak(make_docx, tmp_path):
    out = tmp_path / "leak.docx"
    import shutil
    shutil.copy(make_docx(), out)
    f = Finding(Kind.NIK, 0, 16, DOCX_NIK, "regex")
    with pytest.raises(DocumentError):
        docxmod._verify(out, [f])
    g = Finding(Kind.NAME_CITIZEN, 0, 14, "SITI  rahmawati", "ner")
    with pytest.raises(DocumentError):
        docxmod._verify(out, [g])
    docxmod._verify(out, [Finding(Kind.NIK, 0, 16, "9999999999999999", "regex")])


def test_guard_runs_in_redact(make_docx, tmp_path, monkeypatch):
    """If the rewrite misses something, redact_docx must fail closed."""
    monkeypatch.setattr(docxmod, "_redact_paragraph", lambda *a, **k: None)
    with pytest.raises(DocumentError):
        _run(make_docx(), tmp_path, Version.PUBLIK)
    assert not (tmp_path / "out-publik.docx").exists()


def test_clean_image_untouched(tmp_path):
    from docx import Document
    from .conftest import _nik_image
    src = tmp_path / "clean.docx"
    d = Document()
    d.add_paragraph("Laporan")
    d.add_picture(io.BytesIO(_nik_image("Laporan Kegiatan")))
    d.save(src)
    before = {n: b for n, b in _all_text(src).items() if n.startswith("word/media/")}
    out = _run(src, tmp_path, Version.PUBLIK)
    after = {n: b for n, b in _all_text(out).items() if n.startswith("word/media/")}
    assert before == after


# ---- review fixes (A-E) ----

W_NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def _patch(src, tmp_path, edits, name="patched.docx"):
    """edits: {part: bytes | callable(old_bytes)->bytes}"""
    dst = tmp_path / name
    with zipfile.ZipFile(src) as zi:
        parts = {n: zi.read(n) for n in zi.namelist()}
    for n, v in edits.items():
        parts[n] = v(parts[n]) if callable(v) else v
    with zipfile.ZipFile(dst, "w") as zo:
        for n, b in parts.items():
            zo.writestr(n, b)
    return dst


def _body_insert(xml):
    return lambda b: b.replace(b"<w:body>", b"<w:body>" + xml.encode(), 1)


def _all_values(path):
    """every text node and attribute value of every XML part, decoded"""
    from lxml import etree
    out = []
    for n, b in _all_text(path).items():
        if n.endswith((".xml", ".rels")):
            root = etree.fromstring(b)
            for el in root.iter():
                out += [el.text or "", el.tail or ""] + list(el.attrib.values())
    return "\n".join(out)


NIK2 = "3201010101019999"
EMAIL = "budi.santoso@contoh.co.id"


@pytest.mark.parametrize("version", [Version.PUBLIK, Version.INTERNAL])
def test_alt_text_nik(make_docx, tmp_path, version):
    from docx import Document
    from .conftest import _nik_image
    src = tmp_path / "alt.docx"
    d = Document()
    d.add_paragraph("Laporan")
    d.add_picture(io.BytesIO(_nik_image("Laporan Kegiatan")))
    d.save(src)
    src = _patch(src, tmp_path, {"word/document.xml": lambda b: re.sub(
        rb'descr="[^"]*"|(<wp:docPr )', lambda m: m.group(0) if m.group(1) is None
        else b'<wp:docPr descr="NIK ' + NIK2.encode() + b'" title="NIK ' + NIK2.encode() + b'" ', b)})
    assert NIK2 in _all_values(src)
    out = _run(src, tmp_path, version)
    assert NIK2 not in re.sub(r"\D", "", _all_values(out))


def test_mailto_hyperlink(make_docx, tmp_path):
    src = _patch(make_docx(), tmp_path, {
        "word/_rels/document.xml.rels": lambda b: b.replace(
            b"</Relationships>",
            b'<Relationship Id="rIdMail" Type="http://schemas.openxmlformats.org/'
            b'officeDocument/2006/relationships/hyperlink" Target="mailto:'
            + EMAIL.encode() + b'" TargetMode="External"/></Relationships>'),
        "word/document.xml": _body_insert(
            '<w:p><w:hyperlink r:id="rIdMail" xmlns:r="http://schemas.openxmlformats.org/'
            'officeDocument/2006/relationships"><w:r><w:t>kirim surel</w:t></w:r>'
            '</w:hyperlink></w:p>')})
    for v in (Version.PUBLIK, Version.INTERNAL):
        out = _run(src, tmp_path, v)
        assert EMAIL not in _all_values(out).casefold()


def test_glossary_and_chart_nik(make_docx, tmp_path):
    src = _patch(make_docx(), tmp_path, {
        "word/glossary/document.xml":
            f'<w:glossaryDocument {W_NS}><w:docParts><w:docPart><w:docPartBody>'
            f'<w:p><w:r><w:t>NIK {NIK2}</w:t></w:r></w:p></w:docPartBody></w:docPart>'
            '</w:docParts></w:glossaryDocument>'.encode(),
        "word/charts/chart1.xml":
            b'<c:chartSpace xmlns:c="http://schemas.openxmlformats.org/drawingml/2006/chart">'
            b'<c:v>NIK 3201010101018888</c:v></c:chartSpace>'})
    for v in (Version.PUBLIK, Version.INTERNAL):
        digits = re.sub(r"\D", "", _all_values(_run(src, tmp_path, v)))
        assert NIK2 not in digits and "3201010101018888" not in digits


def test_app_xml_company_cleared(make_docx, tmp_path):
    src = _patch(make_docx(), tmp_path, {"docProps/app.xml": lambda b: re.sub(
        rb"</Properties>", b"<Company>Diskominfo Bontang</Company>"
        b"<Manager>Pak Kepala</Manager></Properties>", b)})
    parts = _all_text(_run(src, tmp_path, Version.PUBLIK))
    app = parts["docProps/app.xml"]
    assert b"Diskominfo Bontang" not in app and b"Pak Kepala" not in app


def test_numeric_char_ref_nik(make_docx, tmp_path):
    enc = "".join(f"&#{ord(c)};" for c in NIK2)
    src = _patch(make_docx(), tmp_path, {"word/document.xml": _body_insert(
        f'<w:p><w:r><w:t>NIK {enc}</w:t></w:r></w:p>'
        f'<w:p><w:sdt><w:sdtPr><w:alias w:val="NIK {enc}"/></w:sdtPr>'
        '<w:sdtContent><w:p><w:r><w:t>isi</w:t></w:r></w:p></w:sdtContent></w:sdt></w:p>')})
    for v in (Version.PUBLIK, Version.INTERNAL):
        assert NIK2 not in re.sub(r"\D", "", _all_values(_run(src, tmp_path, v)))


def test_instrtext_nik(make_docx, tmp_path):
    src = _patch(make_docx(), tmp_path, {"word/document.xml": _body_insert(
        '<w:p><w:r><w:fldChar w:fldCharType="begin"/></w:r>'
        f'<w:r><w:instrText xml:space="preserve"> HYPERLINK "x" \\o "NIK {NIK2}" </w:instrText></w:r>'
        '<w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>'
        f'<w:p><w:fldSimple w:instr=" AUTHOR NIK {NIK2} "><w:r><w:t>a</w:t></w:r></w:fldSimple></w:p>')})
    for v in (Version.PUBLIK, Version.INTERNAL):
        assert NIK2 not in re.sub(r"\D", "", _all_values(_run(src, tmp_path, v)))


def test_embedding_rejected(make_docx, tmp_path):
    src = _patch(make_docx(), tmp_path, {"word/embeddings/oleObject1.bin": b"\xd0\xcf\x11\xe0"})
    for v in (Version.PUBLIK, Version.INTERNAL):
        with pytest.raises(DocumentError, match="objek tersemat"):
            _run(src, tmp_path, v)


def test_publik_removes_format_revisions_and_authors(make_docx, tmp_path):
    src = _patch(make_docx(), tmp_path, {"word/document.xml": _body_insert(
        '<w:p><w:r><w:rPr><w:b/><w:rPrChange w:id="5" w:author="Budi Santoso"><w:rPr/>'
        '</w:rPrChange></w:rPr><w:t>teks</w:t></w:r></w:p>')})
    doc = _all_text(_run(src, tmp_path, Version.PUBLIK))["word/document.xml"]
    assert b"rPrChange" not in doc and b"Budi Santoso" not in doc and b"w:author" not in doc


def test_guard_checks_attributes(make_docx, tmp_path):
    src = _patch(make_docx(), tmp_path, {"word/document.xml": _body_insert(
        f'<w:p><w:sdt><w:sdtPr><w:tag w:val="&#51;201010101019999"/></w:sdtPr></w:sdt></w:p>')})
    with pytest.raises(DocumentError):
        docxmod._verify(src, [Finding(Kind.NIK, 0, 16, NIK2, "regex")])


def test_image_outside_media_ocrd(make_docx, tmp_path):
    from .conftest import _nik_image
    src = _patch(make_docx(), tmp_path, {
        "word/other/pic.png": _nik_image(f"NIK {DOCX_NIK}"),
        "[Content_Types].xml": lambda b: b if b'Extension="png"' in b else b.replace(
            b"</Types>", b'<Default Extension="png" ContentType="image/png"/></Types>')})
    out = _all_text(_run(src, tmp_path, Version.PUBLIK))
    assert Image.open(io.BytesIO(out["word/other/pic.png"])).convert("L").getextrema() == (0, 0)


# ---- review round 2 ----

def _add_ct(override_part, ctype):
    return lambda b: b.replace(b"</Types>", f'<Override PartName="/{override_part}" '
                               f'ContentType="{ctype}"/></Types>'.encode())


@pytest.mark.parametrize("part,ctype,data", [
    ("word/afchunk.mht", "message/rfc822", b"MIME-Version: 1.0\r\n\r\nNIK"),
    ("word/vbaProject.bin", "application/vnd.ms-office.vbaProject", b"\xd0\xcf\x11\xe0"),
])
def test_unsupported_parts_rejected(make_docx, tmp_path, part, ctype, data):
    src = _patch(make_docx(), tmp_path, {part: data,
                                         "[Content_Types].xml": _add_ct(part, ctype)})
    for v in (Version.PUBLIK, Version.INTERNAL):
        with pytest.raises(DocumentError, match="tidak didukung"):
            _run(src, tmp_path, v)


def test_ner_does_not_touch_structural_attributes(make_docx, tmp_path):
    from docx import Document
    style = ('<w:style w:type="paragraph" w:styleId="Siti Rahmawati">'
             '<w:name w:val="Siti Rahmawati"/><w:rPr><w:rFonts w:ascii="Siti Rahmawati"/>'
             '</w:rPr></w:style>')
    src = _patch(make_docx(), tmp_path, {"word/styles.xml": lambda b: b.replace(
        b"</w:styles>", style.encode() + b"</w:styles>")})
    out = _run(src, tmp_path, Version.PUBLIK)
    styles = _all_text(out)["word/styles.xml"].decode()
    assert styles.count('"Siti Rahmawati"') == 3
    Document(out)  # still opens


# ---- review round 3 ----

@pytest.mark.parametrize("part,ctype", [("word/afchunk.dat", "application/xml"),
                                        ("word/afchunk.txt", "text/xml")])
def test_xml_part_by_content_type_rewritten(make_docx, tmp_path, part, ctype):
    data = f"<x><y>NIK {NIK2}</y><z a=\"{NIK2}\"/></x>".encode()
    src = _patch(make_docx(), tmp_path, {part: data,
                                         "[Content_Types].xml": _add_ct(part, ctype)})
    out = _all_text(_run(src, tmp_path, Version.PUBLIK))
    assert NIK2.encode() not in out[part]


def test_xhtml_altchunk_rejected(make_docx, tmp_path):
    part = "word/afchunk.html"
    src = _patch(make_docx(), tmp_path, {
        part: b"<html><body>NIK</body></html>",
        "[Content_Types].xml": _add_ct(part, "application/xhtml+xml")})
    with pytest.raises(DocumentError, match="tidak didukung"):
        _run(src, tmp_path, Version.PUBLIK)


def test_redact_string_overlapping_findings():
    s = "x 3201010101019999 y"
    a = Finding(Kind.NIK, 2, 18, "3201010101019999", "regex")
    b = Finding(Kind.PHONE, 10, 20, "01019999 y", "regex")
    out = docxmod._redact_string(s, lambda t: [a, b], Version.PUBLIK, [])
    assert out == "x [NIK][HP]"
    assert not re.search(r"\d", out)


def test_detect_docx_covers_core_props_and_images(make_docx):
    from digitadlp.redact.docx import detect_docx
    from digitadlp.detect.patterns import find_patterns
    p = make_docx(image=True)
    found = detect_docx(p, find_patterns)
    texts = {f.text.replace(" ", "") for f in found}
    assert "3201010101010003" in texts
    assert any(DOCX_NIK in t for t in texts)
