"""Reviewer corrections applied on top of detected findings."""

import re
from collections.abc import Callable

from ..models import Finding, Kind
from .models import Correction, CorrectionOp


def _norm(text: str) -> str:
    return " ".join(text.split()).casefold()


def apply_corrections(
    findings_per_page: list[list[Finding]], corrections: list[Correction]
) -> list[list[Finding]]:
    pages = [list(p) for p in findings_per_page]
    for c in corrections:
        if c.op == CorrectionOp.TAMBAH and (
            c.page is None or not 0 <= c.page < len(pages)
        ):
            raise ValueError("Halaman koreksi di luar jangkauan.")
    # Ignores first, then adds, so an add always wins over an ignore.
    for c in corrections:
        if c.op != CorrectionOp.ABAIKAN:
            continue
        target = _norm(c.text)
        idx = range(len(pages)) if c.page is None else [c.page]
        for i in idx:
            if 0 <= i < len(pages):
                pages[i] = [f for f in pages[i] if _norm(f.text) != target]
    for c in corrections:
        if c.op == CorrectionOp.TAMBAH:
            pages[c.page].append(Finding(Kind(c.kind), -1, -1, c.text, "manual"))
    return pages


def corrected_detect_fn(
    detect_fn: Callable[[str], list[Finding]], corrections: list[Correction]
) -> Callable[[str], list[Finding]]:
    ignores = {_norm(c.text) for c in corrections if c.op == CorrectionOp.ABAIKAN}
    adds = [c for c in corrections if c.op == CorrectionOp.TAMBAH]

    def fn(text: str) -> list[Finding]:
        out = [f for f in detect_fn(text) if _norm(f.text) not in ignores]
        for c in adds:
            if not c.text:
                continue
            for m in re.finditer(re.escape(c.text), text, re.IGNORECASE):
                out.append(Finding(Kind(c.kind), m.start(), m.end(), m.group(), "manual"))
        return sorted(out, key=lambda f: (f.start, f.end))

    return fn
