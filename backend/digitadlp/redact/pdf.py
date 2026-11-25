"""True PDF redaction for text and scanned pages.

Text is removed from the content stream (not just covered), image pixels
under redaction boxes are blanked, and the result is verified: if any
REDACT/MASK finding text is still extractable, DocumentError is raised.
"""

import os
import re
import subprocess
from dataclasses import replace
from pathlib import Path

import pymupdf as fitz
import pytesseract
from PIL import Image

from ..models import Action, Finding, Kind, Version
from ..policy import action_for, mask_value, placeholder

OCR_DPI = 200
OCR_LANG = "ind"
HYBRID_IMAGE_RATIO = 0.20
_DIGIT_KINDS = frozenset(
    {Kind.NIK, Kind.KK, Kind.ACCOUNT, Kind.NPWP, Kind.NIP, Kind.PHONE}
)
_NON_DIGIT = re.compile(r"[^0-9]")
_TESSDIR = re.compile(r'"([^"]+)"')
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


def _image_ratio(page: fitz.Page) -> float:
    area = abs(page.rect)
    if not area:
        return 0.0
    covered = 0.0
    for info in page.get_image_info():
        covered += abs(fitz.Rect(info["bbox"]) & page.rect)
    return min(covered / area, 1.0)


def _kind(page: fitz.Page) -> str:
    """'scan' (no text layer), 'hybrid' (text + images >= 20%) or 'text'."""
    if _is_scanned(page):
        return "scan"
    if _image_ratio(page) >= HYBRID_IMAGE_RATIO:
        return "hybrid"
    return "text"


def _page_text(page: fitz.Page) -> str:
    k = _kind(page)
    if k == "scan":
        return _ocr_text(page)
    if k == "hybrid":
        return page.get_text() + "\n" + _ocr_text(page)
    return page.get_text()


def _tessdata() -> str:
    env = os.environ.get("TESSDATA_PREFIX")
    if env:
        return env
    try:
        res = subprocess.run(
            ["tesseract", "--list-langs"], capture_output=True, text=True, timeout=30
        )
        m = _TESSDIR.search(res.stdout + res.stderr)
    except (OSError, subprocess.SubprocessError):
        m = None
    if not m:
        raise DocumentError(
            "cannot find tessdata directory: set TESSDATA_PREFIX or install tesseract"
        )
    return m.group(1)


def _pil(page: fitz.Page) -> Image.Image:
    pix = page.get_pixmap(dpi=OCR_DPI)
    return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)


def _ocr_text(page: fitz.Page) -> str:
    return pytesseract.image_to_string(_pil(page), lang=OCR_LANG)


def extract_pdf_text(path: Path) -> list[str]:
    doc = _open(Path(path))
    try:
        return [_page_text(p) for p in doc]
    finally:
        doc.close()


def _norm(s: str) -> str:
    return _NON_ALNUM.sub("", s).lower()


def _tokens(text: str) -> list[str]:
    return [t for t in text.split() if len(_norm(t)) >= 3]


def _locate(page: fitz.Page, words, f: Finding) -> list[tuple[fitz.Rect, str]]:
    """(rect, token) for every occurrence of f, in the text layer (if any)
    and in OCR words (if given). Fallback per token: each token with
    normalized length >= 3 must be found at least once, else DocumentError."""
    out = []
    single_line = "\n" not in f.text and "\r" not in f.text
    if page is not None and single_line:
        out += [(r, f.text) for r in page.search_for(f.text)]
    if words is not None:
        whole = _norm(f.text)
        out += [(r, f.text) for n, r in words if n == whole]
    if out:
        return out
    toks = _tokens(f.text)
    if not toks:
        return []
    for tok in toks:
        hits = []
        if page is not None:
            hits += [(r, tok) for r in page.search_for(tok)]
        if words is not None:
            nt = _norm(tok)
            hits += [(r, tok) for n, r in words if n == nt]
        if not hits:
            raise DocumentError(f"cannot locate part of {f.kind} finding")
        out += hits
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
    digits = _NON_DIGIT.sub("", text)
    hay = _squash(text).casefold()
    out = []
    for f in targets:
        if f.kind in _DIGIT_KINDS:
            needle = _NON_DIGIT.sub("", f.text)
            if needle and needle in digits:
                out.append(f.text)
        else:
            needle = _squash(f.text).casefold()
            if needle and needle in hay:
                out.append(f.text)
    return out


def _strip_active_content(doc: fitz.Document) -> None:
    for name in list(doc.embfile_names()):
        doc.embfile_del(name)
    for page in doc:
        for w in list(page.widgets() or []):
            page.delete_widget(w)
    cat = doc.pdf_catalog()
    for key in ("OpenAction", "AA", "AcroForm"):
        doc.xref_set_key(cat, key, "null")
    # drop the whole name tree (JavaScript, EmbeddedFiles, Dests) for PUBLIK
    for key in ("Names", "PageMode"):
        doc.xref_set_key(cat, key, "null")
    if hasattr(doc, "scrub"):
        doc.scrub(
            attached_files=True, clean_pages=True, embedded_files=True,
            hidden_text=False, javascript=True, metadata=True,
            redactions=False, remove_links=True, reset_fields=True,
            reset_responses=True, thumbnails=True, xml_metadata=True,
        )
    for page in doc:
        doc.xref_set_key(page.xref, "Thumb", "null")
        doc.xref_set_key(page.xref, "AA", "null")


def _reocr_page(doc: fitz.Document, idx: int) -> None:
    """Replace a scanned page by an image + invisible OCR text layer."""
    tessdata = _tessdata()
    page = doc[idx]
    rect = page.rect
    pix = page.get_pixmap(dpi=OCR_DPI)
    ocr = fitz.open("pdf", pix.pdfocr_tobytes(language=OCR_LANG, tessdata=tessdata))
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
            kind = _kind(page)
            is_scan = kind == "scan"
            if is_scan:
                scanned.append(i)
            if version == Version.PUBLIK:
                for annot in list(page.annots() or []):
                    page.delete_annot(annot)
                for w in list(page.widgets() or []):
                    page.delete_widget(w)
                for link in page.get_links():
                    page.delete_link(link)
            findings = findings_per_page[i] if i < len(findings_per_page) else []
            targets = [
                (f, a) for f in findings
                if (a := action_for(f, version)) in (Action.REDACT, Action.MASK)
            ]
            if not targets:
                continue
            words = _ocr_words(page) if kind != "text" else None
            for f, action in targets:
                hits = _locate(None if is_scan else page, words, f)
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
            if kind == "hybrid":
                check += "\n" + _ocr_text(page)
            leaked = _leaks(check, [f for f, _ in targets])
            if leaked:
                raise DocumentError(
                    f"{len(leaked)} finding(s) still extractable on page {i + 1}"
                )
        if version != Version.RAHASIA:
            for i in scanned:
                _reocr_page(doc, i)
        if version == Version.PUBLIK:
            _strip_active_content(doc)
            doc.set_metadata({})
            doc.del_xml_metadata()
        doc.save(Path(dst), garbage=4, deflate=True)
    finally:
        doc.close()
