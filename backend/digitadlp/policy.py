"""Label, action and masking policy."""

import re
from collections.abc import Mapping

from .models import Action, Finding, Kind, Label, Strength, Version

_DIGIT_KINDS = frozenset(
    {Kind.NIK, Kind.KK, Kind.ACCOUNT, Kind.NPWP, Kind.NIP, Kind.PHONE}
)
_DIGIT = re.compile(r"[0-9]")
_ADDRESS_STOP = frozenset({"RT", "RW", "NO", "NO."})

_PLACEHOLDERS = {
    Kind.NIK: "[NIK]",
    Kind.KK: "[KK]",
    Kind.NPWP: "[NPWP]",
    Kind.PHONE: "[HP]",
    Kind.EMAIL: "[EMAIL]",
    Kind.ACCOUNT: "[REKENING]",
    Kind.NAME_CITIZEN: "[NAMA]",
    Kind.NAME_EMPLOYEE: "[NAMA]",
    Kind.NIP: "[NIP]",
    Kind.ADDRESS: "[ALAMAT]",
    Kind.BIRTHDATE: "[TGL LAHIR]",
}


_LABEL_ORDER = {Label.PUBLIK: 0, Label.INTERNAL: 1, Label.RAHASIA: 2}


def default_label_for(f: Finding) -> Label:
    if f.strength == Strength.STRONG:
        return Label.RAHASIA
    return Label.INTERNAL


def suggest_label(
    findings: list[Finding], rules: Mapping[Kind, Label] | None = None
) -> Label:
    if rules is not None:
        labels = [rules.get(f.kind, default_label_for(f)) for f in findings]
        return max(labels, key=_LABEL_ORDER.__getitem__, default=Label.PUBLIK)
    strengths = {f.strength for f in findings}
    if Strength.STRONG in strengths:
        return Label.RAHASIA
    if Strength.MEDIUM in strengths or Strength.EMPLOYEE in strengths:
        return Label.INTERNAL
    return Label.PUBLIK


def action_for(f: Finding, v: Version) -> Action:
    if v == Version.RAHASIA:
        return Action.KEEP
    if v == Version.PUBLIK:
        return Action.KEEP if f.kind == Kind.NAME_EMPLOYEE else Action.REDACT
    if f.kind in (Kind.NAME_EMPLOYEE, Kind.NIP):
        return Action.KEEP
    return Action.MASK


def placeholder(kind: Kind) -> str:
    return _PLACEHOLDERS[kind]


def _mask_digits(text: str) -> str:
    total = len(_DIGIT.findall(text))
    if total == 0:
        return "***"
    keep_head, keep_tail = (4, 4) if total > 8 else (0, 2 if total > 2 else 0)
    seen = 0

    def repl(m: re.Match) -> str:
        nonlocal seen
        seen += 1
        return m.group() if seen <= keep_head or seen > total - keep_tail else "*"

    return _DIGIT.sub(repl, text)


def _mask_word(w: str) -> str:
    if len(w) <= 4:
        return w
    return w[0] + "*" * (len(w) - 4) + w[-2:]


def _mask_name(text: str) -> str:
    out = re.sub(r"\S+", lambda m: _mask_word(m.group()), text)
    if out == text:
        out = re.sub(r"\S+", lambda m: m.group()[0] + "*" * (len(m.group()) - 1), text)
    return out


def _mask_address(text: str) -> str:
    kept = []
    for tok in text.split():
        if tok.upper() in _ADDRESS_STOP or _DIGIT.search(tok):
            break
        kept.append(tok)
    return " ".join(kept + ["***"])


def _mask_email(text: str) -> str:
    if "@" not in text:
        return _mask_name(text)
    local, _, domain = text.partition("@")
    return (local[:1] + "***@" + domain)


def mask_value(f: Finding) -> str:
    kind = f.kind
    if kind in _DIGIT_KINDS:
        return _mask_digits(f.text)
    if kind == Kind.BIRTHDATE:
        return _DIGIT.sub("*", f.text)
    if kind == Kind.ADDRESS:
        return _mask_address(f.text)
    if kind == Kind.EMAIL:
        return _mask_email(f.text)
    return _mask_name(f.text)
