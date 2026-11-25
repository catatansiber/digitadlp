import io
from pathlib import Path

import pymupdf as fitz
import pytest
from PIL import Image, ImageDraw, ImageFont


@pytest.fixture
def make_pdf(tmp_path):
    counter = {"n": 0}

    def _make(text: str, metadata: dict | None = None) -> Path:
        counter["n"] += 1
        path = tmp_path / f"doc{counter['n']}.pdf"
        doc = fitz.open()
        page = doc.new_page()
        y = 72
        for line in text.split("\n"):
            page.insert_text((72, y), line, fontsize=12)
            y += 18
        doc.set_metadata(metadata or {"author": "Pegawai Diskominfo", "title": "Surat"})
        doc.save(path)
        doc.close()
        return path

    return _make


def _font(size):
    for p in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ):
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    return ImageFont.load_default(size=size)


@pytest.fixture
def make_scanned_pdf(tmp_path):
    def _make(text: str) -> Path:
        dpi = 200
        w, h = int(8.27 * dpi), int(11.69 * dpi)
        img = Image.new("RGB", (w, h), "white")
        draw = ImageDraw.Draw(img)
        font = _font(48)
        y = 200
        for line in text.split("\n"):
            draw.text((150, y), line, fill="black", font=font)
            y += 90
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        path = tmp_path / "scan.pdf"
        doc = fitz.open()
        page = doc.new_page(width=595, height=842)
        page.insert_image(page.rect, stream=buf.getvalue())
        doc.save(path)
        doc.close()
        return path

    return _make


DOCX_NIK = "6474015203880002"
_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _nik_image(text: str) -> bytes:
    img = Image.new("RGB", (900, 120), "white")
    ImageDraw.Draw(img).text((20, 30), text, fill="black", font=_font(48))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def make_docx(tmp_path):
    """DOCX with body (NIK split across a bold + plain run), nested table,
    default/first/even headers and footers, a text box, a comment, tracked
    insertion/deletion, an image with a rendered NIK and core properties.
    Each location holds a distinct NIK-bearing sentence."""
    from docx import Document
    from docx.oxml import parse_xml
    from docx.shared import Inches

    def _make(image: bool = False) -> Path:
        doc = Document()
        p = doc.add_paragraph("Nama Siti Rahmawati NIK ")
        p.add_run(DOCX_NIK[:8]).bold = True
        p.add_run(DOCX_NIK[8:])
        table = doc.add_table(rows=1, cols=2)
        table.cell(0, 0).text = "NIK 3201010101010001"
        inner = table.cell(0, 1).add_table(rows=1, cols=1)
        inner.cell(0, 0).text = "NIK 3201010101010002"
        sec = doc.sections[0]
        sec.different_first_page_header_footer = True
        doc.settings.odd_and_even_pages_header_footer = True
        sec.header.paragraphs[0].text = "NIK 3201010101010003"
        sec.footer.paragraphs[0].text = "NIK 3201010101010004"
        sec.first_page_header.paragraphs[0].text = "NIK 3201010101010005"
        sec.first_page_footer.paragraphs[0].text = "NIK 3201010101010006"
        sec.even_page_header.paragraphs[0].text = "NIK 3201010101010007"
        sec.even_page_footer.paragraphs[0].text = "NIK 3201010101010008"
        tb = doc.add_paragraph()
        tb._p.append(parse_xml(
            f'<w:r xmlns:w="{_W}" xmlns:v="urn:schemas-microsoft-com:vml">'
            '<w:pict><v:shape><v:textbox><w:txbxContent>'
            '<w:p><w:r><w:t>NIK 3201010101010009</w:t></w:r></w:p>'
            '</w:txbxContent></v:textbox></v:shape></w:pict></w:r>'
        ))
        cp = doc.add_paragraph("Dikomentari")
        doc.add_comment(cp.runs, text="NIK 3201010101010010", author="Budi")
        tr = doc.add_paragraph()
        tr._p.append(parse_xml(
            f'<w:ins xmlns:w="{_W}" w:id="91" w:author="Budi" w:date="2026-01-01T00:00:00Z">'
            '<w:r><w:t>Tambahan resmi</w:t></w:r></w:ins>'
        ))
        tr._p.append(parse_xml(
            f'<w:del xmlns:w="{_W}" w:id="92" w:author="Budi" w:date="2026-01-01T00:00:00Z">'
            '<w:r><w:delText>NIK 3201010101010011</w:delText></w:r></w:del>'
        ))
        if image:
            doc.add_picture(io.BytesIO(_nik_image(f"NIK {DOCX_NIK}")), width=Inches(5))
        cpp = doc.core_properties
        cpp.author = "Pegawai Diskominfo"
        cpp.last_modified_by = "Operator"
        cpp.comments = "catatan rahasia"
        path = tmp_path / "doc.docx"
        doc.save(path)
        return path

    return _make
