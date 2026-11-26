import uuid
from datetime import datetime, timezone
from enum import StrEnum

from sqlalchemy import (
    false,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    TypeDecorator,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Role(StrEnum):
    PENGGUNA = "pengguna"
    ADMIN = "admin"


class Status(StrEnum):
    DIPROSES = "diproses"
    MENUNGGU_CEK = "menunggu_cek"
    MEMBUAT_VERSI = "membuat_versi"
    DISETUJUI = "disetujui"
    DIRILIS = "dirilis"
    GAGAL = "gagal"


class JobKind(StrEnum):
    DETEKSI = "deteksi"
    VERSI = "versi"


class JobState(StrEnum):
    ANTRI = "antri"
    BERJALAN = "berjalan"
    SELESAI = "selesai"
    GAGAL = "gagal"


class CorrectionOp(StrEnum):
    TAMBAH = "tambah"
    ABAIKAN = "abaikan"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return uuid.uuid4().hex


class UTCDateTime(TypeDecorator):
    """Timezone-aware UTC datetime; SQLite drops tzinfo so restore it on read."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None:
            if value.tzinfo is None:
                raise ValueError("datetime harus memiliki zona waktu (UTC)")
            value = value.astimezone(timezone.utc)
        return value

    def process_result_value(self, value, dialect):
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value


def _enum(cls: type[StrEnum]) -> Enum:
    return Enum(
        cls,
        native_enum=False,
        length=32,
        values_callable=lambda e: [m.value for m in e],
        validate_strings=True,
    )


class Base(DeclarativeBase):
    pass


class Unit(Base):
    __tablename__ = "units"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    username: Mapped[str] = mapped_column(String(100), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(200))
    role: Mapped[Role] = mapped_column(_enum(Role))
    unit_id: Mapped[str] = mapped_column(ForeignKey("units.id"))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    unit: Mapped[Unit] = relationship()


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    title: Mapped[str] = mapped_column(String(300))
    ext: Mapped[str] = mapped_column(String(16))
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    unit_id: Mapped[str] = mapped_column(ForeignKey("units.id"))
    status: Mapped[Status] = mapped_column(_enum(Status), default=Status.DIPROSES)
    suggested_label: Mapped[str | None] = mapped_column(String(32), nullable=True)
    label: Mapped[str | None] = mapped_column(String(32), nullable=True)
    reviewer_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    approved_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    released_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    findings_json: Mapped[str] = mapped_column(Text, default="[]")
    label_set_by_reviewer: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false()
    )
    revision: Mapped[int] = mapped_column(Integer, default=0)
    return_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Correction(Base):
    __tablename__ = "corrections"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"))
    kind: Mapped[str] = mapped_column(String(64))
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    text: Mapped[str] = mapped_column(Text)
    op: Mapped[CorrectionOp] = mapped_column(_enum(CorrectionOp))
    author_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class AreaRedaction(Base):
    __tablename__ = "area_redactions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), index=True)
    page: Mapped[int] = mapped_column(Integer)
    x0: Mapped[float] = mapped_column(Float)
    y0: Mapped[float] = mapped_column(Float)
    x1: Mapped[float] = mapped_column(Float)
    y1: Mapped[float] = mapped_column(Float)
    author_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    kind: Mapped[JobKind] = mapped_column(_enum(JobKind))
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"))
    revision: Mapped[int] = mapped_column(Integer, default=0)
    state: Mapped[JobState] = mapped_column(
        _enum(JobState), default=JobState.ANTRI, index=True
    )
    claimed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    claim_token: Mapped[str | None] = mapped_column(String(32), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    actor_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    action: Mapped[str] = mapped_column(String(64))
    document_id: Mapped[str | None] = mapped_column(
        ForeignKey("documents.id"), nullable=True, index=True
    )
    detail: Mapped[str] = mapped_column(Text, default="")


class LabelRule(Base):
    __tablename__ = "label_rules"

    kind: Mapped[str] = mapped_column(String(64), primary_key=True)
    label: Mapped[str] = mapped_column(String(32))
