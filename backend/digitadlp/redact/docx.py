"""DOCX redaction at the OOXML level.

Every ``w:p`` in every WordprocessingML part (body, tables, headers/footers of
all section variants, text boxes, footnotes/endnotes, comments) is detected on
its joined run text and rewritten back to front. PUBLIK additionally drops
comments, accepts tracked insertions, removes deletions, strips customXml and
custom/core properties. Embedded images containing PII are blacked out.
The written zip is re-read and any surviving REDACT/MASK finding raises
DocumentError (fail closed) and removes the output.
"""

import io
import posixpath
import re
import shutil
import zipfile
from pathlib import Path
from typing import Callable

import pytesseract
from lxml import etree
from PIL import Image

from ..detect.patterns import find_patterns
from ..models import Action, Finding, Kind, Version
from ..policy import action_for, mask_value, placeholder
from .pdf import OCR_LANG, DocumentError, _leaks

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"
_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
_CT_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
_P, _T, _DT = f"{{{W}}}p", f"{{{W}}}t", f"{{{W}}}delText"
_TAB, _BR, _CR = f"{{{W}}}tab", f"{{{W}}}br", f"{{{W}}}cr"
_COMMENT_PART = re.compile(r"^word/(comments[A-Za-z]*|people)\.xml$")
_IMAGE_EXT = (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff")

DetectFn = Callable[[str], list[Finding]]


# ---------------------------------------------------------------- reading


def _read(path: Path) -> dict[str, bytes]:
    try:
        with zipfile.ZipFile(path) as z:
            parts = {i.filename: z.read(i) for i in z.infolist() if not i.is_dir()}
    except (zipfile.BadZipFile, OSError, RuntimeError, ValueError) as e:
        raise DocumentError(f"cannot open DOCX: {e}") from e
    if "word/document.xml" not in parts or "[Content_Types].xml" not in parts:
        raise DocumentError("not a DOCX (word/document.xml missing)")
    return parts


def _parse(data: bytes, name: str) -> etree._Element:
    try:
        return etree.fromstring(data, etree.XMLParser(resolve_entities=False,
                                                      huge_tree=True))
    except etree.XMLSyntaxError as e:
        raise DocumentError(f"corrupt XML part {name}: {e}") from e


def _owner_p(el: etree._Element):
    a = el.getparent()
    while a is not None and a.tag != _P:
        a = a.getparent()
    return a


def _segments(p: etree._Element) -> list[tuple[etree._Element | None, str]]:
    """(node, text) in document order for text belonging directly to p
    (not to paragraphs nested inside text boxes)."""
    out = []
    for el in p.iter(_T, _DT, _TAB, _BR, _CR):
        if _owner_p(el) is not p:
            continue
        if el.tag in (_T, _DT):
            out.append((el, el.text or ""))
        else:
            out.append((None, "\t" if el.tag == _TAB else "\n"))
    return out


def _paragraphs(root: etree._Element):
    return root.iter(_P)


def _text_parts(parts: dict[str, bytes]) -> list[str]:
    names = [n for n in _xml_names(parts)
             if not n.endswith(".rels") and n != "[Content_Types].xml"]
    return sorted(names, key=lambda n: (n != "word/document.xml", n))


def extract_docx_text(path: Path) -> list[str]:
    return _paragraph_texts(_read(Path(path)))


def _paragraph_texts(parts: dict[str, bytes]) -> list[str]:
    out = []
    for name in _text_parts(parts):
        root = _parse(parts[name], name)
        for p in _paragraphs(root):
            out.append("".join(t for _, t in _segments(p)))
    return out


_PATTERN_KINDS = frozenset({Kind.NIK, Kind.KK, Kind.NPWP, Kind.PHONE, Kind.EMAIL,
                            Kind.ACCOUNT, Kind.NIP})
_HUMAN_ATTRS = frozenset({"descr", "title", "alt", "instr"})
_NAME_OWNERS = frozenset({"docPr", "cNvPr"})
_VAL_OWNERS = frozenset({"alias", "tag", "docVar"})


def _human_attr(el: etree._Element, key: str) -> bool:
    """attribute that holds human-written text (full detect incl. NER);
    every other attribute gets regex-only detection"""
    k = etree.QName(key).localname
    owner = etree.QName(el).localname
    return (k in _HUMAN_ATTRS
            or (k == "name" and owner in _NAME_OWNERS)
            or (k == "val" and owner in _VAL_OWNERS)
            or (k == "Target" and el.get("TargetMode") == "External"))


def _units(root: etree._Element):
    """(value, human) for every attribute value, text node and tail
    (entities/char refs decoded by lxml)"""
    for el in root.iter():
        if isinstance(el.tag, str):
            for k, v in el.attrib.items():
                yield v, _human_attr(el, k)
        yield el.text or "", True
        yield el.tail or "", True


def _values(root: etree._Element):
    for v, _ in _units(root):
        yield v


def _is_xml_type(t: str) -> bool:
    t = t.lower().split(";")[0].strip()
    return t.endswith("/xml") or t.endswith("+xml")


def _xml_names(parts: dict[str, bytes]) -> list[str]:
    """every XML part by [Content_Types].xml (plus .rels), not by extension"""
    types = _content_types(parts)
    return [n for n in parts
            if n.endswith(".rels") or n == "[Content_Types].xml"
            or _is_xml_type(types.get(n, ""))]


def _value_targets(parts, detect_fn, version) -> list[Finding]:
    out = []
    for name in _xml_names(parts):
        for v, human in _units(_parse(parts[name], name)):
            if len(v.strip()) >= 4:
                fn = detect_fn if human else find_patterns
                out += [f for f in fn(v) if action_for(f, version) != Action.KEEP]
    return out


def _content_types(parts: dict[str, bytes]) -> dict[str, str]:
    ct = _parse(parts["[Content_Types].xml"], "[Content_Types].xml")
    defaults, overrides = {}, {}
    for el in ct:
        local = etree.QName(el).localname
        if local == "Default":
            defaults[el.get("Extension", "").lower()] = el.get("ContentType", "")
        elif local == "Override":
            overrides[el.get("PartName", "").lstrip("/")] = el.get("ContentType", "")
    return {n: overrides.get(n, defaults.get(n.rsplit(".", 1)[-1].lower(), ""))
            for n in parts}


EMBED_MSG = ("Dokumen berisi objek tersemat (Excel/Word/OLE). Hapus atau ganti "
             "objek tersebut, lalu upload lagi.")


UNSUPPORTED_MSG = ("Dokumen berisi bagian yang tidak didukung (mis. altChunk/makro). "
                   "Simpan ulang sebagai .docx biasa, lalu upload lagi.")
_FONT_TYPES = ("application/x-font",
               "application/vnd.openxmlformats-officedocument.obfuscatedfont")


def _reject_unsupported(parts, types) -> None:
    for n in parts:
        t = types.get(n, "").lower().split(";")[0].strip()
        if t in ("application/xhtml+xml", "text/html") or "html" in t:
            raise DocumentError(UNSUPPORTED_MSG)
        if (n.endswith(".rels") or n == "[Content_Types].xml"
                or _is_xml_type(t)
                or (t.startswith("image/") and n.lower().endswith(_IMAGE_EXT))
                or t.startswith(_FONT_TYPES)
                or n.startswith("docProps/thumbnail")):
            continue
        raise DocumentError(UNSUPPORTED_MSG)


def _reject_embeddings(parts, types) -> None:
    for n in parts:
        t = types.get(n, "").lower()
        if (n.startswith("word/embeddings/") or "oleobject" in t
                or t.endswith(".package") or "/package" in t and "relationships" not in t
                or (n.lower().endswith(".bin") and "vbaproject" not in n.lower())):
            raise DocumentError(EMBED_MSG)


# ---------------------------------------------------------------- rewriting


def _replacement(f: Finding, action: Action) -> str:
    return placeholder(f.kind) if action == Action.REDACT else mask_value(f)


def _set(node: etree._Element, text: str) -> None:
    node.text = text
    node.set(_XML_SPACE, "preserve")


def _redact_paragraph(p, detect_fn: DetectFn, version: Version, hits: list) -> None:
    segs = _segments(p)
    text = "".join(t for _, t in segs)
    if not text.strip():
        return
    spans, pos = [], 0
    for node, t in segs:
        spans.append((pos, pos + len(t), node))
        pos += len(t)
    todo = []
    for f in detect_fn(text):
        action = action_for(f, version)
        if action != Action.KEEP:
            todo.append((f, action))
            hits.append(f)
    for f, action in sorted(todo, key=lambda x: x[0].start, reverse=True):
        repl = _replacement(f, action)
        placed = False
        for s, e, node in spans:
            if node is None or e <= f.start or s >= f.end:
                continue
            cur = node.text or ""
            ls, le = max(f.start - s, 0), min(f.end, e) - s
            if not placed:
                _set(node, cur[:ls] + repl + cur[le:])
                placed = True
            else:
                _set(node, cur[:ls] + cur[le:])
        if not placed:
            raise DocumentError(f"cannot place {f.kind} replacement")


def _redact_string(s: str, detect_fn, version, hits) -> str:
    if len(s.strip()) < 4:
        return s
    todo = [(f, a) for f in detect_fn(s) if (a := action_for(f, version)) != Action.KEEP]
    floor = len(s) + 1
    for f, a in sorted(todo, key=lambda x: (x[0].start, -x[0].end), reverse=True):
        hits.append(f)
        # an overlap with the span replaced just before: cover up to it
        s = s[:f.start] + _replacement(f, a) + s[min(f.end, floor):]
        floor = f.start
    return s


def _redact_values(root, detect_fn, version, hits) -> None:
    """generic per-node pass: every text node, tail and attribute value"""
    for el in root.iter():
        if isinstance(el.tag, str):
            for k, v in el.attrib.items():
                fn = detect_fn if _human_attr(el, k) else find_patterns
                nv = _redact_string(v, fn, version, hits)
                if nv != v:
                    el.set(k, nv)
        if el.text:
            el.text = _redact_string(el.text, detect_fn, version, hits)
        if el.tail:
            el.tail = _redact_string(el.tail, detect_fn, version, hits)


def _unwrap(el: etree._Element) -> None:
    parent = el.getparent()
    idx = parent.index(el)
    for child in list(el):
        parent.insert(idx, child)
        idx += 1
    parent.remove(el)


def _strip_revisions_and_comments(root: etree._Element) -> None:
    w = lambda t: f"{{{W}}}{t}"  # noqa: E731
    for tag in ("del", "moveFrom"):
        for el in list(root.iter(w(tag))):
            if el.getparent() is not None:
                el.getparent().remove(el)
    # paragraph-mark deletions inside rPr: drop the marker only
    for tag in ("ins", "moveTo"):
        for el in list(root.iter(w(tag))):
            if el.getparent() is not None and len(el):
                _unwrap(el)
            elif el.getparent() is not None:
                el.getparent().remove(el)
    for tag in ("moveFromRangeStart", "moveFromRangeEnd", "moveToRangeStart",
                "moveToRangeEnd", "commentRangeStart", "commentRangeEnd"):
        for el in list(root.iter(w(tag))):
            el.getparent().remove(el)
    for tag in ("rPrChange", "pPrChange", "sectPrChange", "tblPrChange",
                "trPrChange", "tcPrChange", "tblGridChange", "numberingChange"):
        for el in list(root.iter(w(tag))):
            el.getparent().remove(el)
    for el in root.iter():
        if isinstance(el.tag, str):
            for k in list(el.attrib):
                if etree.QName(k).localname in ("author", "initials"):
                    del el.attrib[k]
    for ref in list(root.iter(w("commentReference"))):
        run = ref.getparent()
        if run.tag == w("r") and run.getparent() is not None:
            run.getparent().remove(run)
        else:
            run.remove(ref)


def _drop_rels(parts: dict[str, bytes], removed: set[str]) -> None:
    for name in [n for n in parts if n.endswith(".rels")]:
        base = posixpath.dirname(posixpath.dirname(name))
        root = _parse(parts[name], name)
        changed = False
        for rel in list(root):
            if rel.get("TargetMode") == "External":
                continue
            target = rel.get("Target", "")
            full = (target.lstrip("/") if target.startswith("/")
                    else posixpath.normpath(posixpath.join(base, target)))
            if full in removed:
                root.remove(rel)
                changed = True
        if changed:
            parts[name] = etree.tostring(root, xml_declaration=True,
                                         encoding="UTF-8", standalone=True)
    ct = _parse(parts["[Content_Types].xml"], "[Content_Types].xml")
    for ov in list(ct):
        if ov.get("PartName", "").lstrip("/") in removed:
            ct.remove(ov)
    parts["[Content_Types].xml"] = etree.tostring(
        ct, xml_declaration=True, encoding="UTF-8", standalone=True)


def _clear_core(parts: dict[str, bytes]) -> None:
    name = "docProps/core.xml"
    if name not in parts:
        return
    root = _parse(parts[name], name)
    for el in root:
        local = etree.QName(el).localname
        if local in ("creator", "lastModifiedBy", "description", "keywords",
                     "subject", "title", "category", "contentStatus",
                     "identifier"):
            el.text = ""
    parts[name] = etree.tostring(root, xml_declaration=True, encoding="UTF-8",
                                 standalone=True)


def _clear_app(parts: dict[str, bytes]) -> None:
    name = "docProps/app.xml"
    if name not in parts:
        return
    root = _parse(parts[name], name)
    for el in root:
        if etree.QName(el).localname in ("Company", "Manager", "HyperlinkBase"):
            el.text = ""
    parts[name] = etree.tostring(root, xml_declaration=True, encoding="UTF-8",
                                 standalone=True)


def _redact_images(parts: dict[str, bytes], detect_fn: DetectFn,
                   version: Version, types: dict[str, str]) -> None:
    for name in [n for n in parts if types.get(n, "").lower().startswith("image/")
                 or n.startswith("word/media/")]:
        if not name.lower().endswith(_IMAGE_EXT):
            raise DocumentError(f"cannot inspect embedded media {name}")
        try:
            img = Image.open(io.BytesIO(parts[name]))
            img.load()
        except Exception as e:  # PIL raises many types
            raise DocumentError(f"cannot read embedded image {name}: {e}") from e
        text = pytesseract.image_to_string(img.convert("RGB"), lang=OCR_LANG)
        if not any(action_for(f, version) != Action.KEEP for f in detect_fn(text)):
            continue
        fmt = img.format or "PNG"
        black = Image.new("RGB", img.size, "black")
        buf = io.BytesIO()
        black.save(buf, format=fmt if fmt in ("PNG", "JPEG", "GIF", "BMP", "TIFF")
                   else "PNG")
        parts[name] = buf.getvalue()


def _write(parts: dict[str, bytes], dst: Path) -> None:
    order = ["[Content_Types].xml"] + [n for n in parts if n != "[Content_Types].xml"]
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as z:
        for n in order:
            z.writestr(n, parts[n])


def _verify(path: Path, targets: list[Finding]) -> None:
    parts = _read(Path(path))
    for name in _xml_names(parts):
        units = list(_units(_parse(parts[name], name)))
        human = "\n".join(v for v, h in units if h)
        structural = "\n".join(v for v, h in units if not h)
        # structural attributes only ever get regex detection, so only
        # regex-detectable kinds are required to be absent there
        leaked = _leaks(human, targets) + _leaks(
            structural, [f for f in targets if f.kind in _PATTERN_KINDS])
        if leaked:
            raise DocumentError(f"redaction verification failed in {name}: "
                                f"{len(leaked)} finding(s) still present")


def redact_docx(src: Path, dst: Path, detect_fn: DetectFn, version: Version) -> None:
    src, dst = Path(src), Path(dst)
    parts = _read(src)
    if version == Version.RAHASIA:
        shutil.copyfile(src, dst)
        return
    publik = version == Version.PUBLIK
    types = _content_types(parts)
    _reject_embeddings(parts, types)
    _reject_unsupported(parts, types)
    cache: dict[str, list[Finding]] = {}
    raw_detect = detect_fn

    def detect_fn(t: str) -> list[Finding]:  # noqa: F811 - memoized wrapper
        if t not in cache:
            cache[t] = raw_detect(t)
        return cache[t]

    # leak-check targets come from the untouched input, independent of rewrite
    targets = [f for t in _paragraph_texts(parts) for f in detect_fn(t)
               if action_for(f, version) != Action.KEEP]
    targets += _value_targets(parts, detect_fn, version)
    removed = {n for n in parts if n.startswith("docProps/thumbnail")}
    if publik:
        removed |= {n for n in parts
                    if _COMMENT_PART.match(n) or n.startswith("customXml/")
                    or n == "docProps/custom.xml"}
    if removed:
        for n in removed:
            del parts[n]
        _drop_rels(parts, removed)
    hits: list[Finding] = []
    for name in _text_parts(parts):
        root = _parse(parts[name], name)
        if publik:
            _strip_revisions_and_comments(root)
        for p in list(_paragraphs(root)):
            _redact_paragraph(p, detect_fn, version, hits)
        _redact_values(root, detect_fn, version, hits)
        parts[name] = etree.tostring(root, xml_declaration=True,
                                     encoding="UTF-8", standalone=True)
    for name in [n for n in parts if n.endswith(".rels")]:
        root = _parse(parts[name], name)
        _redact_values(root, detect_fn, version, hits)
        parts[name] = etree.tostring(root, xml_declaration=True,
                                     encoding="UTF-8", standalone=True)
    if publik:
        _clear_core(parts)
        _clear_app(parts)
    _redact_images(parts, detect_fn, version, types)
    _write(parts, dst)
    try:
        _verify(dst, targets + hits)
    except DocumentError:
        dst.unlink(missing_ok=True)
        raise
