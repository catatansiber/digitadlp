"""Antrean kerja berbasis database dan worker thread."""
from __future__ import annotations

import logging
import threading
import traceback
from collections.abc import Callable
from datetime import timedelta

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from ..redact.pdf import DocumentError
from .config import Settings
from .models import Document, Job, JobKind, JobState, Status, utcnow
from .processing import Engine, run_deteksi, run_versi
from .storage import FileStore

__all__ = ["Engine", "Worker", "claim", "enqueue", "run_job", "run_pending"]

log = logging.getLogger("digitadlp.jobs")


def enqueue(db: Session, kind: JobKind | str, document: Document) -> Job:
    """Tambah job ke sesi; pemanggil yang commit."""
    job = Job(kind=JobKind(kind), document_id=document.id, revision=document.revision)
    db.add(job)
    db.flush()
    return job


def _claimable(cutoff):
    return or_(
        Job.state == JobState.ANTRI,
        (Job.state == JobState.BERJALAN)
        & (or_(Job.claimed_at.is_(None), Job.claimed_at < cutoff)),
    )


def claim(db: Session, stale_minutes: int) -> Job | None:
    """Ambil satu job lalu tandai berjalan (commit). None bila tidak ada."""
    now = utcnow()
    cond = _claimable(now - timedelta(minutes=stale_minutes))
    if db.get_bind().dialect.name == "postgresql":
        job = db.scalars(
            select(Job).where(cond).order_by(Job.created_at)
            .limit(1).with_for_update(skip_locked=True)
        ).first()
        if job is None:
            db.rollback()
            return None
        job.state = JobState.BERJALAN
        job.claimed_at = now
        db.commit()
        return job
    for _ in range(5):
        job_id = db.scalar(select(Job.id).where(cond).order_by(Job.created_at).limit(1))
        if job_id is None:
            db.rollback()
            return None
        res = db.execute(
            update(Job)
            .where(Job.id == job_id, cond)
            .values(state=JobState.BERJALAN, claimed_at=now)
            .execution_options(synchronize_session=False)
        )
        db.commit()
        if res.rowcount == 1:
            job = db.get(Job, job_id)
            db.refresh(job)
            return job
    return None


def _log_failure(job_id: str, kind: str, code: str, exc: BaseException) -> None:
    # Hanya tipe exception dan frame; pesan exception bisa memuat isi dokumen.
    frames = "".join(traceback.format_tb(exc.__traceback__))
    log.error(
        "job gagal id=%s kind=%s error_code=%s exc=%s\n%s",
        job_id, kind, code, type(exc).__name__, frames,
    )


def run_job(db: Session, store: FileStore, engine: Engine, job: Job) -> None:
    job_id, kind = job.id, JobKind(job.kind)
    try:
        doc = db.get(Document, job.document_id)
        if doc is None or doc.revision != job.revision:
            job.state = JobState.SELESAI
            db.commit()
            log.info("job basi id=%s kind=%s", job_id, kind.value)
            return
        if kind == JobKind.DETEKSI:
            run_deteksi(db, store, engine, doc)
        else:
            run_versi(db, store, engine, doc)
        job.state = JobState.SELESAI
        job.error_code = None
        db.commit()
        log.info("job selesai id=%s kind=%s", job_id, kind.value)
        return
    except Exception as exc:  # noqa: BLE001
        code = "dokumen_rusak" if isinstance(exc, DocumentError) else "galat_internal"
        failure = exc
    db.rollback()
    _log_failure(job_id, kind.value, code, failure)
    try:
        job = db.get(Job, job_id)
        doc = db.get(Document, job.document_id)
        if kind == JobKind.VERSI and doc is not None:
            store.delete_versions(doc.id)
        job.state = JobState.GAGAL
        job.error_code = code
        if doc is not None and doc.revision == job.revision:
            doc.status = Status.GAGAL
        db.commit()
    except Exception as exc2:  # noqa: BLE001
        db.rollback()
        _log_failure(job_id, kind.value, "galat_internal", exc2)


def run_pending(
    db_factory: Callable[[], Session], store: FileStore, engine: Engine,
    stale_minutes: int = 30,
) -> int:
    """Jalankan semua job yang bisa diklaim secara sinkron. Mengembalikan jumlahnya."""
    n = 0
    while True:
        with db_factory() as db:
            job = claim(db, stale_minutes)
            if job is None:
                return n
            run_job(db, store, engine, job)
            n += 1


class Worker:
    def __init__(self, session_factory, store: FileStore, engine: Engine,
                 settings: Settings, interval: float = 1.0):
        self._factory = session_factory
        self._store = store
        self._engine = engine
        self._stale = settings.job_stale_minutes
        self._interval = interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="digitadlp-worker", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 10.0) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout)
            self._thread = None

    def _loop(self) -> None:
        while not self._stop.is_set():
            ran = False
            try:
                with self._factory() as db:
                    job = claim(db, self._stale)
                    if job is not None:
                        run_job(db, self._store, self._engine, job)
                        ran = True
            except Exception as exc:  # noqa: BLE001
                log.error("worker galat exc=%s", type(exc).__name__)
            if not ran:
                self._stop.wait(self._interval)
