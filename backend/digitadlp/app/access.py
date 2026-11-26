"""Aturan akses dokumen: siapa boleh melihat dan mengunduh versi mana."""

from .models import Document, Status, User

VERSIONS = ("publik", "internal", "rahasia")
_READY = (Status.DISETUJUI, Status.DIRILIS)


def can_view(user: User, doc: Document) -> bool:
    return doc.owner_id == user.id or doc.unit_id == user.unit_id


def can_see_rahasia(user: User, doc: Document) -> bool:
    return doc.unit_id == user.unit_id


def can_download(user: User, doc: Document, version: str) -> bool:
    if version == "publik":
        if doc.status == Status.DIRILIS:
            return True
        return doc.status == Status.DISETUJUI and doc.unit_id == user.unit_id
    if doc.status not in _READY:
        return False
    if version == "internal":
        return True
    if version == "rahasia":
        return can_see_rahasia(user, doc)
    return False
