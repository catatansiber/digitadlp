"""Audit log. record() adds to the session; the caller commits."""

from sqlalchemy.orm import Session

from ..detect.patterns import find_patterns
from .models import AuditEvent, Document, User

ACTIONS = frozenset(
    {
        "masuk", "gagal_masuk", "keluar", "upload", "deteksi_selesai",
        "ubah_label", "koreksi", "setujui", "kembalikan", "rilis", "unduh", "lihat_teks",
        "akses_ditolak", "user_dibuat", "user_diubah", "impor_pegawai",
        "aturan_label", "unit_dibuat",
    }
)
MAX_DETAIL = 200


def record(
    db: Session,
    actor: User | None,
    action: str,
    document: Document | None = None,
    detail: str = "",
) -> AuditEvent:
    if action not in ACTIONS:
        raise ValueError("Aksi audit tidak dikenal.")
    if len(detail) > MAX_DETAIL:
        raise ValueError("Rincian audit terlalu panjang (maksimal 200 karakter).")
    if find_patterns(detail):
        raise ValueError("Rincian audit tidak boleh memuat data pribadi.")
    event = AuditEvent(
        actor_id=actor.id if actor else None,
        action=action,
        document_id=document.id if document else None,
        detail=detail,
    )
    db.add(event)
    return event
