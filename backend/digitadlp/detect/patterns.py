import re

from digitadlp.models import Finding, Kind

_NIP = re.compile(r"\bNIP(?![A-Za-z_])[\s:.\-]{0,5}(\d{8}\s?\d{6}\s?\d\s?\d{3})(?!\d)", re.I)
_NPWP_FMT = re.compile(r"(?<![\d.])\d{2}\.\d{3}\.\d{3}\.\d-\d{3}\.\d{3}(?![\d.]?\d)")
_NPWP_16 = re.compile(r"\bNPWP\b[^\d\n]{0,10}(\d{16})(?!\d)", re.I)
_ACCOUNT = re.compile(
    r"\b(?:rekening|rek)\b[^\d\n]{0,25}?(?<!\d)(\d(?:-?\d){9,15})(?![\d-]?\d)", re.I
)
# Lookahead so candidates may overlap (a preceding 4-digit group must not swallow the NIK).
_SIXTEEN = re.compile(r"(?<!\d)(?=(\d{4}([ .\-]?)\d{4}\2\d{4}\2\d{4}(?!\d)))")
_PHONE = re.compile(r"(?<![\d+])(?:\+62|62|0)8\d{1,2}[-\s]?\d{3,4}[-\s]?\d{3,5}(?!\d)")
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")
_KK_CONTEXT = re.compile(r"\bKK\b|Kartu\s+Keluarga", re.I)

# Addresses start at a street/housing cue; a kelurahan/desa counts only right after one.
_STREET_CUE = re.compile(
    r"(?<![\w-])(?:Jl\.|Jln\.?|Jalan|Gg\.|Gang|Perumahan|Perum|Komplek|Kompleks|Blok)(?![\w-])",
    re.I,
)
_AREA_CUE = re.compile(r"(?:Kelurahan|Kel\.|Desa)(?![\w-])", re.I)
_KEEP_AFTER_COMMA = re.compile(r"\s*(?:RT|RW|No|Nomor|Blok)(?![A-Za-z])", re.I)
_ADDR_MAX = 120


def _address_end(text: str, start: int) -> int:
    """End of an address segment beginning at start (exclusive, trimmed)."""
    i, limit = start, min(len(text), start + _ADDR_MAX)
    while i < limit:
        c = text[i]
        if c in "\r\n;()":
            break
        if c == "," and not _KEEP_AFTER_COMMA.match(text, i + 1):
            break
        if c == ".":
            rest = text[i + 1:]
            word = re.search(r"(\w+)$", text[start:i])
            initial = word is not None and len(word.group(1)) == 1 and word.group(1).isupper()
            if not rest.strip() or (re.match(r"\s+[A-Z]", rest) and not initial):
                break
        if i > start and text[i - 1].isspace() and _AREA_CUE.match(text, i):
            break
        i += 1
    while i > start and text[i - 1] in " \t,.":
        i -= 1
    return i


def _addresses(text: str) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for m in _STREET_CUE.finditer(text):
        if out and m.start() < out[-1][1]:
            continue
        end = _address_end(text, m.end())
        if end <= m.end() or not re.search(r"\w", text[m.end():end]):
            continue
        out.append((m.start(), end))
        gap = re.match(r"[ ,]{1,3}", text[end:])
        area_at = end + (gap.end() if gap else 0)
        area = _AREA_CUE.match(text, area_at)
        if gap and area:
            a_end = _address_end(text, area.end())
            if re.search(r"\w", text[area.end():a_end]):
                out.append((area_at, a_end))
    return out


def is_valid_nik(digits: str) -> bool:
    if len(digits) != 16 or not (digits.isascii() and digits.isdigit()):
        return False
    day, month = int(digits[6:8]), int(digits[8:10])
    return (
        (1 <= day <= 31 or 41 <= day <= 71)
        and 1 <= month <= 12
        and digits[12:16] != "0000"
    )


def _spans(pattern: re.Pattern, text: str, group: int = 0):
    for m in pattern.finditer(text):
        yield m.start(group), m.end(group)


def find_patterns(text: str) -> list[Finding]:
    # Candidates in priority order (email first); an earlier one wins any overlap.
    cands: list[tuple[Kind, int, int]] = []
    cands += [(Kind.EMAIL, s, e) for s, e in _spans(_EMAIL, text)]
    cands += [(Kind.NIP, s, e) for s, e in _spans(_NIP, text, 1)]
    cands += [(Kind.NPWP, s, e) for s, e in _spans(_NPWP_FMT, text)]
    cands += [(Kind.NPWP, s, e) for s, e in _spans(_NPWP_16, text, 1)]
    cands += [(Kind.ACCOUNT, s, e) for s, e in _spans(_ACCOUNT, text, 1)]
    sixteen = list(_spans(_SIXTEEN, text, 1))
    valid = [(s, e) for s, e in sixteen if is_valid_nik(re.sub(r"\D", "", text[s:e]))]
    cands += [(Kind.NIK, s, e) for s, e in valid]
    cands += [
        (Kind.KK, s, e)
        for s, e in sixteen
        if (s, e) not in valid and _KK_CONTEXT.search(text[max(0, s - 30):s])
    ]
    cands += [(Kind.PHONE, s, e) for s, e in _spans(_PHONE, text)]

    taken: list[tuple[int, int]] = []
    out: list[Finding] = []
    for kind, s, e in cands:
        if any(s < te and ts < e for ts, te in taken):
            continue
        taken.append((s, e))
        out.append(Finding(kind, s, e, text[s:e], "regex"))
    # Addresses are not dropped when they overlap a stronger pattern: the
    # pipeline grows the winner over the whole union so no part leaks.
    out += [Finding(Kind.ADDRESS, s, e, text[s:e], "regex") for s, e in _addresses(text)]
    return sorted(out, key=lambda f: f.start)
