from dataclasses import replace

from digitadlp.detect.employees import EmployeeDirectory
from digitadlp.detect.ner import NerDetector
from digitadlp.detect.patterns import find_patterns
from digitadlp.models import Finding, Kind, Strength

_RANK = {Strength.STRONG: 2, Strength.MEDIUM: 1, Strength.EMPLOYEE: 0}


def _promote(f: Finding, directory: EmployeeDirectory) -> Finding:
    if f.kind == Kind.NAME_CITIZEN and directory.is_employee(f.text):
        return replace(f, kind=Kind.NAME_EMPLOYEE)
    return f


def _span(f: Finding, start: int, end: int, text: str) -> Finding:
    return replace(f, start=start, end=end, text=text[start:end])


def detect(text: str, ner: NerDetector, directory: EmployeeDirectory) -> list[Finding]:
    candidates = [_promote(f, directory) for f in [*find_patterns(text), *ner.find(text)]]
    candidates.sort(key=lambda f: (-_RANK[f.strength], -(f.end - f.start), f.start))
    accepted: list[Finding] = []
    dropped: list[Finding] = []
    for c in candidates:
        if all(c.end <= a.start or c.start >= a.end for a in accepted):
            accepted.append(c)
        else:
            dropped.append(c)
    # Grow winners over partially overlapping losers so no part leaks;
    # merge winners that end up overlapping (higher priority one is kept).
    changed = True
    while changed:
        changed = False
        for d in dropped:
            for i, a in enumerate(accepted):
                if d.start < a.end and a.start < d.end and (d.start < a.start or d.end > a.end):
                    accepted[i] = _span(a, min(a.start, d.start), max(a.end, d.end), text)
                    changed = True
        i = 0
        while i < len(accepted):
            j = i + 1
            while j < len(accepted):
                a, b = accepted[i], accepted[j]
                if a.start < b.end and b.start < a.end:
                    accepted[i] = _span(a, min(a.start, b.start), max(a.end, b.end), text)
                    del accepted[j]
                    changed = True
                else:
                    j += 1
            i += 1
    accepted.sort(key=lambda f: f.start)
    return accepted
