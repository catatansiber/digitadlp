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

from ..detect.patterns import find_patterns
from ..models import Action, Finding, Kind, Version
from ..policy import action_for, mask_value, placeholder

OCR_DPI = 200
OCR_REGION_DPI = 300
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


_OCR_ERRORS = (pytesseract.TesseractError, pytesseract.TesseractNotFoundError,
               OSError, RuntimeError)


def _tess(name: str, *a, **k):
    """call pytesseract.<name>, turning any OCR failure into DocumentError"""
    try:
        return getattr(pytesseract, name)(*a, **k)
    except _OCR_ERRORS as e:
        raise DocumentError(f"OCR failed: {e}") from e


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


def _image_rects(page: fitz.Page) -> list[fitz.Rect]:
    out = []
    for info in page.get_image_info():
        r = fitz.Rect(info["bbox"]) & page.rect
        if not r.is_empty and r.width > 1 and r.height > 1:
            out.append(r)
    return out


def _region_pil(page: fitz.Page, rect: fitz.Rect) -> Image.Image:
    pix = page.get_pixmap(dpi=OCR_REGION_DPI, clip=rect)
    return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)


def _region_text(page: fitz.Page) -> str:
    """OCR of every embedded image region (used on text pages, where small
    images are not covered by a full-page OCR)"""
    return "\n".join(_tess("image_to_string", _region_pil(page, r), lang=OCR_LANG)
                     for r in _image_rects(page))


def _region_words(page: fitz.Page) -> list[tuple[str, fitz.Rect]]:
    words = []
    for r in _image_rects(page):
        words += _words_from(_region_pil(page, r), OCR_REGION_DPI, r.tl)
    return words


def _page_text(page: fitz.Page) -> str:
    k = _kind(page)
    if k == "scan":
        return _ocr_text(page)
    if k == "hybrid":
        return page.get_text() + "\n" + _ocr_text(page)
    if _image_rects(page):
        return page.get_text() + "\n" + _region_text(page)
    return page.get_text()


def _strip_widgets(doc: fitz.Document) -> None:
    for page in doc:
        for w in list(page.widgets() or []):
            page.delete_widget(w)


def _extra_texts(doc: fitz.Document) -> list[str]:
    """PII-capable text outside page content: outline, annotations, form
    fields, metadata, XMP and embedded file names"""
    out = [t[1] for t in doc.get_toc(simple=True)]
    for page in doc:
        for a in page.annots() or []:
            info = a.info
            out += [info.get(k, "") for k in ("content", "title", "subject")]
        for w in page.widgets() or []:
            out += [str(w.field_value or ""), w.field_name or "", w.field_label or ""]
        for link in page.get_links():
            out += [str(link.get(k) or "") for k in ("uri", "file", "nameddest")]
    out += [str(v) for v in (doc.metadata or {}).values() if v]
    out.append(doc.get_xml_metadata() or "")
    for name in doc.embfile_names():
        info = doc.embfile_info(name)
        out += [name, info.get("filename", ""), info.get("ufilename", ""),
                info.get("desc", "")]
    return [t for t in out if t and t.strip()]


def extract_pdf_extras(path: Path) -> list[str]:
    doc = _open(Path(path))
    try:
        return _extra_texts(doc)
    finally:
        doc.close()


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


_TRANSPOSE = {90: Image.Transpose.ROTATE_90, 180: Image.Transpose.ROTATE_180,
              270: Image.Transpose.ROTATE_270}
OSD_MIN_CONF = 1.0
_CONF_MIN = 60


def _rotated(img: Image.Image, angle: int) -> Image.Image:
    """img turned counter-clockwise by angle (0/90/180/270)"""
    return img.transpose(_TRANSPOSE[angle]) if angle else img


def _confident_words(img: Image.Image) -> int:
    data = _tess("image_to_data", img, lang=OCR_LANG,
                 output_type=pytesseract.Output.DICT)
    return sum(1 for w, c in zip(data["text"], data["conf"])
               if len(_norm(w)) >= 2 and float(c) >= _CONF_MIN)


def _orientation(img: Image.Image) -> int:
    """counter-clockwise turn (0/90/180/270) that makes img upright: tesseract
    OSD, or, when OSD cannot decide (too little text), the turn with the most
    confident OCR words"""
    try:
        osd = _tess("image_to_osd", img, output_type=pytesseract.Output.DICT)
        rot = int(osd.get("rotate", 0)) % 360
        if rot in (0, 90, 180, 270) and float(osd.get("orientation_conf", 0)) >= OSD_MIN_CONF:
            # OSD "rotate" is clockwise; PIL turns counter-clockwise
            return (360 - rot) % 360
    except (DocumentError, ValueError, TypeError):
        pass
    scores = {a: _confident_words(_rotated(img, a)) for a in (0, 90, 180, 270)}
    best = max(scores.values())
    return 0 if scores[0] == best else max(scores, key=scores.get)


def _upright(img: Image.Image) -> tuple[Image.Image, int]:
    a = _orientation(img)
    return _rotated(img, a), a


def _unrotate_rect(r: fitz.Rect, angle: int, w: float, h: float) -> fitz.Rect:
    """map a rect in an image turned counter-clockwise by angle back to the
    original w x h image"""
    def pt(u, v):
        if angle == 90:
            return w - v, u
        if angle == 180:
            return w - u, h - v
        if angle == 270:
            return v, h - u
        return u, v
    (x0, y0), (x1, y1) = pt(r.x0, r.y0), pt(r.x1, r.y1)
    return fitz.Rect(min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))


def _ocr_text(page: fitz.Page) -> str:
    img, _ = _upright(_pil(page))
    return _tess("image_to_string", img, lang=OCR_LANG)


def extract_pdf_text(path: Path) -> list[str]:
    """page texts; form-field values are not page content (they go to
    extract_pdf_extras and widgets are dropped from every output)"""
    doc = _open(Path(path))
    try:
        _strip_widgets(doc)
        return [_page_text(p) for p in doc]
    finally:
        doc.close()


def _norm(s: str) -> str:
    return _NON_ALNUM.sub("", s).lower()


def _tokens(text: str) -> list[str]:
    return [t for t in text.split() if len(_norm(t)) >= 3]


def _must_locate(tok: str) -> bool:
    n = _norm(tok)
    return bool(n) and (len(n) >= 2 or any(c.isdigit() for c in n))


def _vicinity(rects) -> fitz.Rect | None:
    rects = [fitz.Rect(r) for r in rects]
    if not rects:
        return None
    u = fitz.Rect(rects[0])
    for r in rects[1:]:
        u |= r
    pad = 3 * max(r.height for r in rects)
    return fitz.Rect(u.x0 - pad, u.y0 - pad, u.x1 + pad, u.y1 + pad)


def _token_hits(page, words, tok):
    hits = []
    if page is not None:
        hits += [(r, tok) for r in page.search_for(tok)]
    if words is not None:
        nt = _norm(tok)
        hits += [(r, tok) for n, r in words if n == nt]
    return hits


def _locate(page: fitz.Page, words, f: Finding) -> list[tuple[fitz.Rect, str]]:
    """(rect, token) for every occurrence of f, in the text layer (if any)
    and in OCR words (if given). Fallback per token: every token with a
    digit or normalized length >= 2 must be found (short tokens near the
    long ones), else DocumentError."""
    out = []
    single_line = "\n" not in f.text and "\r" not in f.text
    if page is not None and single_line:
        out += [(r, f.text) for r in page.search_for(f.text)]
    if words is not None:
        whole = _norm(f.text)
        out += [(r, f.text) for n, r in words if n == whole]
    if out:
        return out
    toks = [t for t in f.text.split() if _must_locate(t)]
    if not toks:
        return []
    # Anchor on the first long token (else the first token); every other
    # token is accepted only near an anchor hit (a few lines above/below,
    # across the page width), never page-wide. An anchor hit whose
    # surroundings miss any required token is dropped; none left -> fail.
    long_toks = [t for t in toks if len(_norm(t)) >= 3]
    anchor = (long_toks or toks)[0]
    rest = list(toks)
    rest.remove(anchor)
    hits = {t: _token_hits(page, words, t) for t in dict.fromkeys(toks)}
    for ar, _ in hits[anchor]:
        near = _line_vicinity(ar)
        group = [(ar, anchor)]
        for tok in dict.fromkeys(rest):
            th = [(r, t) for r, t in hits[tok] if fitz.Rect(r).intersects(near)]
            if not th:
                break
            group += th
        else:
            out += [h for h in group if h not in out]
    if not out:
        raise DocumentError(f"cannot locate part of {f.kind} finding")
    return out


def _line_vicinity(r) -> fitz.Rect:
    r = fitz.Rect(r)
    pad = 3 * r.height
    return fitz.Rect(-1e6, r.y0 - pad, 1e6, r.y1 + pad)


def _words_from(img: Image.Image, dpi: int, offset=(0, 0), orient: bool = False):
    angle = 0
    w0, h0 = img.size
    if orient:
        img, angle = _upright(img)
    data = _tess("image_to_data", img, lang=OCR_LANG,
                 output_type=pytesseract.Output.DICT)
    scale = 72 / dpi
    ox, oy = offset
    words = []
    for i, w in enumerate(data["text"]):
        n = _norm(w)
        if not n:
            continue
        x, y, ww, hh = (data[k][i] for k in ("left", "top", "width", "height"))
        rect = _unrotate_rect(fitz.Rect(x, y, x + ww, y + hh), angle, w0, h0)
        rect = rect * scale + (ox, oy, ox, oy)
        words.append((n, rect))
    return words


def _ocr_words(page: fitz.Page) -> list[tuple[str, fitz.Rect]]:
    return _words_from(_pil(page), OCR_DPI, orient=True)


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


_PLACEHOLDERS = re.compile("|".join(re.escape(placeholder(k)) for k in Kind))


def _leaks(text: str, targets: list[Finding]) -> list[str]:
    # Our own placeholders (e.g. "[NIK]") are not leaks, even when a finding's
    # text happens to equal the word inside one.
    text = _PLACEHOLDERS.sub(" ", text)
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
    img, angle = _upright(_pil(page))
    pix = fitz.Pixmap(fitz.csRGB, img.width, img.height, img.tobytes(), False)
    pix.set_dpi(OCR_DPI, OCR_DPI)
    try:
        data = pix.pdfocr_tobytes(language=OCR_LANG, tessdata=tessdata)
    except _OCR_ERRORS as e:
        raise DocumentError(f"OCR failed: {e}") from e
    ocr = fitz.open("pdf", data)
    # OCR ran on the upright image; /Rotate (clockwise) restores the look
    ocr[0].set_rotation(angle)
    doc.delete_page(idx)
    doc.insert_pdf(ocr, start_at=idx)
    new = doc[idx]
    if new.rect != rect and not angle:
        new.set_mediabox(fitz.Rect(0, 0, new.rect.width, new.rect.height))
    ocr.close()


def _rewrite(s: str, detect_fn, version: Version, hits: list) -> str:
    todo = [(f, a) for f in detect_fn(s) if (a := action_for(f, version)) != Action.KEEP]
    floor = len(s) + 1
    for f, a in sorted(todo, key=lambda x: (x[0].start, -x[0].end), reverse=True):
        hits.append(f)
        repl = placeholder(f.kind) if a == Action.REDACT else mask_value(f)
        s = s[:f.start] + repl + s[min(f.end, floor):]
        floor = f.start
    return s


def _rewrite_extras(doc: fitz.Document, detect_fn, version: Version, hits) -> None:
    """INTERNAL: mask/redact outline titles and annotation texts in place"""
    toc = doc.get_toc(simple=False)
    if toc:
        doc.set_toc([[e[0], _rewrite(e[1], detect_fn, version, hits), *e[2:]]
                     for e in toc])
    for page in doc:
        for a in list(page.annots() or []):
            info = a.info
            new = {k: _rewrite(info.get(k, ""), detect_fn, version, hits)
                   for k in ("content", "title", "subject")}
            if any(new[k] != info.get(k, "") for k in new):
                a.set_info(**new)
                if a.type[0] == fitz.PDF_ANNOT_FREE_TEXT:
                    doc.xref_set_key(a.xref, "RC", "null")
                a.update()


def _clear_extras(doc: fitz.Document, version: Version) -> None:
    """both redacted versions: no form fields, metadata, XMP or attachments;
    PUBLIK also loses the outline (annotations are dropped per page)"""
    _strip_widgets(doc)
    for name in list(doc.embfile_names()):
        doc.embfile_del(name)
    doc.set_metadata({})
    doc.del_xml_metadata()
    if version == Version.PUBLIK:
        doc.set_toc([])


def _vicinity_words(page: fitz.Page, near: fitz.Rect, ocr_words) -> list[str]:
    out = [_norm(w[4]) for w in page.get_text("words")
           if fitz.Rect(w[:4]).intersects(near)]
    out += [n for n, r in (ocr_words or []) if r.intersects(near)]
    return [n for n in out if n]


def _token_leaks(page, f: Finding, rects, ocr_words, labels=()) -> bool:
    """multi-token non-digit finding: any long token, or any digit-bearing
    token, still present as a word near where the finding was"""
    toks = [_norm(t) for t in f.text.split()]
    shown = {_norm(w) for lab in labels for w in lab.split()}
    toks = [t for t in toks if (len(t) >= 3 or any(c.isdigit() for c in t))
            and t not in shown]
    if len(toks) < 2 or f.kind in _DIGIT_KINDS:
        return False
    near = _vicinity(rects)
    if near is None:
        return False
    words = set(_vicinity_words(page, near, ocr_words))
    return any(t in words for t in toks)


def redact_pdf(
    src: Path,
    dst: Path,
    findings_per_page: list[list[Finding]],
    version: Version,
    detect_fn=find_patterns,
) -> None:
    doc = _open(Path(src))
    try:
        if len(findings_per_page) > doc.page_count:
            raise DocumentError("more finding pages than PDF pages")
        if version == Version.RAHASIA:
            doc.save(Path(dst), garbage=4, deflate=True)
            return
        extra_targets = [f for t in _extra_texts(doc) for f in detect_fn(t)
                         if action_for(f, version) != Action.KEEP]
        all_targets = list(extra_targets)
        _strip_widgets(doc)
        if version == Version.INTERNAL:
            _rewrite_extras(doc, detect_fn, version, extra_targets)
        scanned = []
        for i, page in enumerate(doc):
            kind = _kind(page)
            is_scan = kind == "scan"
            if is_scan:
                scanned.append(i)
            for link in page.get_links():
                page.delete_link(link)
            for annot in list(page.annots() or []):
                if (version == Version.PUBLIK
                        or annot.type[0] == fitz.PDF_ANNOT_FILE_ATTACHMENT):
                    page.delete_annot(annot)
            findings = findings_per_page[i] if i < len(findings_per_page) else []
            targets = [
                (f, a) for f in findings
                if (a := action_for(f, version)) in (Action.REDACT, Action.MASK)
            ]
            if not targets:
                continue
            all_targets += [f for f, _ in targets]
            has_regions = kind == "text" and bool(_image_rects(page))
            if kind != "text":
                words = _ocr_words(page)
            elif has_regions:
                words = _region_words(page)
            else:
                words = None
            placed = []
            for f, action in targets:
                hits = _locate(None if is_scan else page, words, f)
                if not hits:
                    raise DocumentError(
                        f"cannot locate {f.kind} finding on page {i + 1}"
                    )
                for rect, tok in hits:
                    _add(page, rect, f, action, tok)
                placed.append((f, [r for r, _ in hits],
                               [_label(f, action, tok) for _, tok in hits]))
            page.apply_redactions(
                images=fitz.PDF_REDACT_IMAGE_PIXELS,
                graphics=fitz.PDF_REDACT_LINE_ART_NONE,
            )
            check = _ocr_text(page) if is_scan else page.get_text()
            if kind == "hybrid":
                check += "\n" + _ocr_text(page)
            if has_regions:
                check += "\n" + _region_text(page)
            leaked = _leaks(check, [f for f, _ in targets])
            post_words = (_ocr_words(page) if kind != "text"
                          else _region_words(page) if has_regions else None)
            leaked += [f.text for f, rects, labels in placed
                       if _token_leaks(page, f, rects, post_words, labels)]
            if leaked:
                raise DocumentError(
                    f"{len(leaked)} finding(s) still extractable on page {i + 1}"
                )
        for i in scanned:
            _reocr_page(doc, i)
        _clear_extras(doc, version)
        if version == Version.PUBLIK:
            _strip_active_content(doc)
        out = doc.tobytes(garbage=4, deflate=True)
    finally:
        doc.close()
    check = fitz.open("pdf", out)
    try:
        leaked = _leaks("\n".join(_extra_texts(check)), all_targets)
    finally:
        check.close()
    if leaked:
        raise DocumentError(f"{len(leaked)} finding(s) left outside page content")
    Path(dst).write_bytes(out)
