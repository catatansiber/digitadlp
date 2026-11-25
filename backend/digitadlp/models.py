from dataclasses import dataclass
from enum import StrEnum


class Kind(StrEnum):
    NIK = "NIK"
    KK = "KK"
    NPWP = "NPWP"
    PHONE = "PHONE"
    EMAIL = "EMAIL"
    ACCOUNT = "ACCOUNT"
    NAME_CITIZEN = "NAME_CITIZEN"
    NAME_EMPLOYEE = "NAME_EMPLOYEE"
    NIP = "NIP"
    ADDRESS = "ADDRESS"
    BIRTHDATE = "BIRTHDATE"


class Strength(StrEnum):
    STRONG = "STRONG"
    MEDIUM = "MEDIUM"
    EMPLOYEE = "EMPLOYEE"


class Label(StrEnum):
    PUBLIK = "publik"
    INTERNAL = "internal"
    RAHASIA = "rahasia"


class Version(StrEnum):
    PUBLIK = "publik"
    INTERNAL = "internal"
    RAHASIA = "rahasia"


class Action(StrEnum):
    KEEP = "KEEP"
    MASK = "MASK"
    REDACT = "REDACT"


_STRONG = frozenset({Kind.NIK, Kind.KK, Kind.ACCOUNT, Kind.NPWP})
_EMPLOYEE = frozenset({Kind.NAME_EMPLOYEE, Kind.NIP})


@dataclass(frozen=True)
class Finding:
    kind: Kind
    start: int
    end: int
    text: str
    source: str

    @property
    def strength(self) -> Strength:
        if self.kind in _STRONG:
            return Strength.STRONG
        if self.kind in _EMPLOYEE:
            return Strength.EMPLOYEE
        return Strength.MEDIUM
