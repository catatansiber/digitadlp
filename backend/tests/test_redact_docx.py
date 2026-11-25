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
