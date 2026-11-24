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
