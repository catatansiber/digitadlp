import re
from pathlib import Path

from openpyxl import load_workbook

# Titles compared lowercase with surrounding dots removed.
_HONORIFICS = frozenset({"drs", "dra", "dr", "ir", "prof", "h", "hj", "kh"})
_ACADEMIC = frozenset(
    {
        "s.kom", "s.h", "s.t", "s.e", "s.pd", "s.pd.i", "s.sos", "s.ip", "s.si",
        "s.ag", "s.farm", "s.kep", "s.psi", "s.hut", "s.pt", "s.stp", "s.kom.i",
        "m.si", "m.t", "m.m", "m.kom", "m.h", "m.pd", "m.pd.i", "m.sc", "m.ak",
        "m.ap", "m.eng", "m.kes", "m.ag", "m.sos", "m.ikom", "ph.d", "mba",
    }
)  # fmt: skip
# Dotless forms are only recognised in trailing position.
_DOTLESS = frozenset(
    {"sh", "st", "se", "skom", "spd", "sos", "sip", "ssi", "msi", "mt", "mm",
     "mkom", "mh", "mpd", "msc", "sag"}
)  # fmt: skip
_LEADING = _HONORIFICS | _ACADEMIC
_TRAILING = _ACADEMIC | _DOTLESS


def _norm(tok: str) -> str:
    return tok.strip(".")


def normalize_name(name: str) -> str:
    tokens = [t for t in re.split(r"[\s,]+", name.lower()) if _norm(t)]
    while tokens and _norm(tokens[0]) in _LEADING:
        tokens.pop(0)
    while tokens:
        if _norm(tokens[-1]) in _TRAILING:
            tokens.pop()
        elif len(tokens) >= 2 and _norm(_norm(tokens[-2]) + "." + _norm(tokens[-1])) in _TRAILING:
            tokens.pop()
            tokens.pop()
        else:
            break
    return " ".join(_norm(t) for t in tokens)


def _digits(s: str) -> str:
    return re.sub(r"\D", "", s)


class EmployeeDirectory:
    def __init__(self, names: set[str], nips: set[str] | None = None):
        self._names = names
        self._nips = nips or set()

    @classmethod
    def from_names(
        cls, names: list[str], nips: list[str] | None = None
    ) -> "EmployeeDirectory":
        return cls(
            {n for n in (normalize_name(x) for x in names) if n},
            {d for d in (_digits(x) for x in (nips or [])) if d},
        )

    @classmethod
    def from_xlsx(cls, path: str | Path) -> "EmployeeDirectory":
        wb = load_workbook(path, read_only=True, data_only=True)
        names: list[str] = []
        nips: list[str] = []
        try:
            for ws in wb.worksheets:
                rows = ws.iter_rows(values_only=True)
                header = next(rows, None)
                if not header:
                    continue
                cols = [str(h).strip().lower() if h is not None else "" for h in header]
                if "nama" not in cols:
                    continue
                idx = cols.index("nama")
                nip_idx = cols.index("nip") if "nip" in cols else None
                for row in rows:
                    if idx < len(row) and row[idx]:
                        names.append(str(row[idx]))
                    if nip_idx is not None and nip_idx < len(row) and row[nip_idx]:
                        nips.append(str(row[nip_idx]))
        finally:
            wb.close()
        return cls.from_names(names, nips)

    def is_employee(self, name: str) -> bool:
        n = normalize_name(name)
        return bool(n) and n in self._names

    def is_employee_nip(self, nip: str) -> bool:
        d = _digits(nip)
        return bool(d) and d in self._nips
