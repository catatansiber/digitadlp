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


def detect(text: str, ner: NerDetector, directory: EmployeeDirectory) -> list[Finding]:
    candidates = [_promote(f, directory) for f in [*find_patterns(text), *ner.find(text)]]
    candidates.sort(key=lambda f: (-_RANK[f.strength], -(f.end - f.start), f.start))
    accepted: list[Finding] = []
    for c in candidates:
        if all(c.end <= a.start or c.start >= a.end for a in accepted):
            accepted.append(c)
    accepted.sort(key=lambda f: f.start)
    return accepted
