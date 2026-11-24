import re
from pathlib import Path

from openpyxl import load_workbook

# Titles compared lowercase with trailing dots removed.
_TITLES = frozenset(
    {
        "drs", "dra", "dr", "ir", "prof", "h", "hj", "kh",
        "s.kom", "s.h", "s.t", "s.e", "s.pd", "s.sos", "s.ip", "s.si", "s.ag",
        "s.farm", "s.kep", "s.psi", "s.hut", "s.pt", "s.stp",
        "m.si", "m.t", "m.m", "m.kom", "m.h", "m.pd", "m.sc", "m.ak", "m.ap",
        "m.eng", "m.kes", "m.ag", "m.sos", "m.ikom", "ph.d", "mba",
    }
)  # fmt: skip


def normalize_name(name: str) -> str:
    tokens = []
    for tok in re.split(r"[\s,]+", name.lower()):
        tok = tok.strip(".")
        if tok and tok not in _TITLES:
            tokens.append(tok)
    return " ".join(tokens)


class EmployeeDirectory:
    def __init__(self, names: set[str]):
        self._names = names

    @classmethod
    def from_names(cls, names: list[str]) -> "EmployeeDirectory":
        return cls({n for n in (normalize_name(x) for x in names) if n})

    @classmethod
    def from_xlsx(cls, path: str | Path) -> "EmployeeDirectory":
        wb = load_workbook(path, read_only=True, data_only=True)
        names: list[str] = []
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
                for row in rows:
                    if idx < len(row) and row[idx]:
                        names.append(str(row[idx]))
        finally:
            wb.close()
        return cls.from_names(names)

    def is_employee(self, name: str) -> bool:
        n = normalize_name(name)
        return bool(n) and n in self._names
