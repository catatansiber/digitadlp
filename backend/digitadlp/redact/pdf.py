"""True PDF redaction for text and scanned pages.

Text is removed from the content stream (not just covered), image pixels
under redaction boxes are blanked, and the result is verified: if any
REDACT/MASK finding text is still extractable, DocumentError is raised.
"""

import os
import re
from dataclasses import replace
from pathlib import Path

import pymupdf as fitz
import pytesseract
from PIL import Image

from ..models import Action, Finding, Version
from ..policy import action_for, mask_value, placeholder

OCR_DPI = 200
OCR_LANG = "ind"
_TESSDATA = "/usr/share/tesseract-ocr/5/tessdata"
_NON_ALNUM = re.compile(r"[^0-9A-Za-z]")
_WS = re.compile(r"\s+")


class DocumentError(Exception):
    """Encrypted, corrupt, or un-redactable document."""


def _open(path: Path) -> fitz.Document:
    try:
        doc = fitz.open(path)
    except Exception as e:  # pymupdf raises various types for corrupt files
        raise DocumentError(f"cannot open PDF: {e}") from e
    if doc.needs_pass or doc.is_encrypted:
        doc.close()
        raise DocumentError("PDF is encrypted")
    if not doc.is_pdf:
        doc.close()
        raise DocumentError("not a PDF")
    return doc


def _is_scanned(page: fitz.Page) -> bool:
    return not page.get_text().strip()


def _pil(page: fitz.Page) -> Image.Image:
    pix = page.get_pixmap(dpi=OCR_DPI)
    return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)


def _ocr_text(page: fitz.Page) -> str:
    return pytesseract.image_to_string(_pil(page), lang=OCR_LANG)


def extract_pdf_text(path: Path) -> list[str]:
    doc = _open(Path(path))
    try:
        return [_ocr_text(p) if _is_scanned(p) else p.get_text() for p in doc]
    finally:
        doc.close()


def _norm(s: str) -> str:
    return _NON_ALNUM.sub("", s).lower()


def _tokens(text: str) -> list[str]:
    return [t for t in text.split() if len(t) >= 3]


def _locate_text(page: fitz.Page, f: Finding) -> list[tuple[fitz.Rect, str]]:
    """(rect, token_text) pairs for every occurrence of the finding."""
    if "\n" not in f.text and "\r" not in f.text:
        hits = page.search_for(f.text)
        if hits:
            return [(r, f.text) for r in hits]
    out = []
    for tok in _tokens(f.text):
        out += [(r, tok) for r in page.search_for(tok)]
    return out


def _ocr_words(page: fitz.Page) -> list[tuple[str, fitz.Rect]]:
    data = pytesseract.image_to_data(
        _pil(page), lang=OCR_LANG, output_type=pytesseract.Output.DICT
    )
    scale = 72 / OCR_DPI
    words = []
    for i, w in enumerate(data["text"]):
        n = _norm(w)
        if not n:
            continue
        x, y, ww, hh = (data[k][i] for k in ("left", "top", "width", "height"))
        rect = fitz.Rect(x, y, x + ww, y + hh) * scale
        words.append((n, rect))
    return words


def _locate_scanned(words, f: Finding) -> list[tuple[fitz.Rect, str]]:
    out = []
    whole = _norm(f.text)
    for n, rect in words:
        if n == whole:
            out.append((rect, f.text))
    if out:
        return out
    toks = {_norm(t): t for t in f.text.split() if len(_norm(t)) >= 2}
    for n, rect in words:
        if n in toks:
            out.append((rect, toks[n]))
    return out


def _label(f: Finding, action: Action, tok: str) -> str:
    if action == Action.REDACT:
        return placeholder(f.kind)
    return mask_value(f if tok == f.text else replace(f, text=tok))


def _add(page, rect, f, action, tok):
    rect = fitz.Rect(rect)
    size = max(4.0, min(11.0, rect.height * 0.8))
    if action == Action.REDACT:
        page.add_redact_annot(rect, text=_label(f, action, tok), fontsize=size,
                              fill=(0, 0, 0), text_color=(1, 1, 1))
    else:
        page.add_redact_annot(rect, text=_label(f, action, tok), fontsize=size,
                              fill=(1, 1, 1), text_color=(0, 0, 0))


def _squash(s: str) -> str:
    return _WS.sub("", s)


def _leaks(text: str, targets: list[Finding]) -> list[str]:
    hay = _squash(text)
    return [f.text for f in targets if _squash(f.text) and _squash(f.text) in hay]


def _reocr_page(doc: fitz.Document, idx: int) -> None:
    """Replace a scanned page by an image + invisible OCR text layer."""
    os.environ.setdefault("TESSDATA_PREFIX", _TESSDATA)
    page = doc[idx]
    rect = page.rect
    pix = page.get_pixmap(dpi=OCR_DPI)
    ocr = fitz.open("pdf", pix.pdfocr_tobytes(language=OCR_LANG))
    doc.delete_page(idx)
    doc.insert_pdf(ocr, start_at=idx)
    new = doc[idx]
    if new.rect != rect:
        new.set_mediabox(fitz.Rect(0, 0, new.rect.width, new.rect.height))
    ocr.close()


def redact_pdf(
    src: Path,
    dst: Path,
    findings_per_page: list[list[Finding]],
    version: Version,
) -> None:
    doc = _open(Path(src))
    try:
        if len(findings_per_page) > doc.page_count:
            raise DocumentError("more finding pages than PDF pages")
        scanned = []
        for i, page in enumerate(doc):
            is_scan = _is_scanned(page)
            if is_scan:
                scanned.append(i)
            if version == Version.PUBLIK:
                for annot in list(page.annots() or []):
                    page.delete_annot(annot)
                for link in page.get_links():
                    page.delete_link(link)
            findings = findings_per_page[i] if i < len(findings_per_page) else []
            targets = [
                (f, a) for f in findings
                if (a := action_for(f, version)) in (Action.REDACT, Action.MASK)
            ]
            if not targets:
                continue
            words = _ocr_words(page) if is_scan else None
            for f, action in targets:
                hits = _locate_scanned(words, f) if is_scan else _locate_text(page, f)
                if not hits:
                    raise DocumentError(
                        f"cannot locate {f.kind} finding on page {i + 1}"
                    )
                for rect, tok in hits:
                    _add(page, rect, f, action, tok)
            page.apply_redactions(
                images=fitz.PDF_REDACT_IMAGE_PIXELS,
                graphics=fitz.PDF_REDACT_LINE_ART_NONE,
            )
            check = _ocr_text(page) if is_scan else page.get_text()
            leaked = _leaks(check, [f for f, _ in targets])
            if leaked:
                raise DocumentError(
                    f"{len(leaked)} finding(s) still extractable on page {i + 1}"
                )
        if version != Version.RAHASIA:
            for i in scanned:
                _reocr_page(doc, i)
        if version == Version.PUBLIK:
            doc.set_metadata({})
            doc.del_xml_metadata()
        doc.save(Path(dst), garbage=4, deflate=True)
    finally:
        doc.close()
