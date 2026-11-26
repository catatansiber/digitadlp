"""Antrean kerja berbasis database dan worker thread."""
from __future__ import annotations

import logging
import threading
import time
import traceback
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from ..redact.pdf import DocumentError
from .config import Settings
from .models import Document, Job, JobKind, JobState, Status, new_id, utcnow
from .processing import (
    Touch, apply_deteksi, compute_deteksi, render_versi, store_versi,
)
from .storage import FileStore

__all__ = ["Worker", "claim", "heartbeat", "enqueue", "run_job", "run_pending"]

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
    """Ambil satu job, tandai berjalan dengan claim_token baru (commit)."""
    now = utcnow()
    cond = _claimable(now - timedelta(minutes=stale_minutes))
    token = new_id()
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
        job.claim_token = token
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
            .values(state=JobState.BERJALAN, claimed_at=now, claim_token=token)
            .execution_options(synchronize_session=False)
        )
        db.commit()
        if res.rowcount == 1:
            job = db.get(Job, job_id)
            db.refresh(job)
            return job
    return None


class ClaimLost(Exception):
    """Klaim job sudah diambil alih runner lain."""


def heartbeat(db: Session, job_id: str, token: str | None, interval: float = 60.0) -> Touch:
    """touch(): perbarui claimed_at paling sering tiap `interval` detik."""
    last = {"t": time.monotonic()}

    def touch() -> None:
        now = time.monotonic()
        if interval > 0 and now - last["t"] < interval:
            return
        res = db.execute(
            update(Job)
            .where(Job.id == job_id, Job.claim_token == token, Job.state == JobState.BERJALAN)
            .values(claimed_at=utcnow())
            .execution_options(synchronize_session=False)
        )
        db.commit()
        if res.rowcount != 1:
            raise ClaimLost()
        last["t"] = now

    return touch


def _log_failure(job_id: str, kind: str, code: str, exc: BaseException) -> None:
    # Hanya tipe exception dan frame; pesan exception bisa memuat isi dokumen.
    frames = "".join(traceback.format_tb(exc.__traceback__))
    log.error(
        "job gagal id=%s kind=%s error_code=%s exc=%s\n%s",
        job_id, kind, code, type(exc).__name__, frames,
    )


def _fresh_doc(db: Session, doc_id: str) -> Document | None:
    return db.scalars(
        select(Document).where(Document.id == doc_id)
        .with_for_update().execution_options(populate_existing=True)
    ).first()


def _finalize(db, job_id, token, revision, doc_id, state, code, apply) -> bool:
    """Tulis hasil job secara atomik. Job ditulis lewat UPDATE bersyarat pada
    claim_token (juga mengunci tulis di SQLite); dokumen dikunci lalu revisinya
    diperiksa ulang. apply(doc) hanya dipanggil bila revisi masih sama.
    False bila klaim hilang (tanpa efek apa pun)."""
    res = db.execute(
        update(Job)
        .where(Job.id == job_id, Job.claim_token == token, Job.state == JobState.BERJALAN)
        .values(state=state, error_code=code)
        .execution_options(synchronize_session=False)
    )
    if res.rowcount != 1:
        db.rollback()
        return False
    doc = _fresh_doc(db, doc_id)
    if doc is not None and doc.revision == revision and apply is not None:
        try:
            apply(doc)
        except BaseException:
            db.rollback()
            raise
    elif state == JobState.SELESAI and apply is not None:
        log.info("job basi id=%s", job_id)
    db.commit()
    return True


def run_job(
    db: Session, store: FileStore, job: Job, touch: Touch | None = None
) -> None:
    job_id, kind = job.id, JobKind(job.kind)
    token, revision, doc_id = job.claim_token, job.revision, job.document_id
    if touch is None:
        touch = heartbeat(db, job_id, token)
    try:
        doc = _fresh_doc(db, doc_id)
        if doc is None or doc.revision != revision:
            db.rollback()
            if _finalize(db, job_id, token, revision, doc_id, JobState.SELESAI, None, None):
                log.info("job basi id=%s kind=%s", job_id, kind.value)
            return
        db.rollback()  # jangan tahan kunci selama pemrosesan panjang
        if kind == JobKind.DETEKSI:
            result = compute_deteksi(db, store, doc, touch)
            db.rollback()
            ok = _finalize(db, job_id, token, revision, doc_id, JobState.SELESAI, None,
                           lambda d: apply_deteksi(db, d, result))
        else:
            with store.scratch_dir() as tmp:
                files = render_versi(db, store, doc, tmp, touch)
                db.rollback()
                ok = _finalize(db, job_id, token, revision, doc_id, JobState.SELESAI, None,
                               lambda d: store_versi(store, d, files))
        if ok:
            log.info("job selesai id=%s kind=%s", job_id, kind.value)
        else:
            log.warning("klaim hilang id=%s kind=%s", job_id, kind.value)
        return
    except ClaimLost:
        db.rollback()
        log.warning("klaim hilang id=%s kind=%s", job_id, kind.value)
        return
    except Exception as exc:  # noqa: BLE001
        code = "dokumen_rusak" if isinstance(exc, DocumentError) else "galat_internal"
        failure = exc
    db.rollback()
    _log_failure(job_id, kind.value, code, failure)

    def mark_failed(d: Document) -> None:
        if kind == JobKind.VERSI:
            store.delete_versions(d.id)
        d.status = Status.GAGAL

    try:
        _finalize(db, job_id, token, revision, doc_id, JobState.GAGAL, code, mark_failed)
    except Exception as exc2:  # noqa: BLE001
        db.rollback()
        _log_failure(job_id, kind.value, "galat_internal", exc2)


def run_pending(
    db_factory: Callable[[], Session], store: FileStore,
    stale_minutes: int = 30,
) -> int:
    """Jalankan semua job yang bisa diklaim secara sinkron. Mengembalikan jumlahnya."""
    n = 0
    while True:
        with db_factory() as db:
            job = claim(db, stale_minutes)
            if job is None:
                return n
            run_job(db, store, job)
            n += 1


class Worker:
    def __init__(self, session_factory, store: FileStore,
                 settings: Settings, interval: float = 1.0):
        self._factory = session_factory
        self._store = store
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
                        run_job(db, self._store, job)
                        ran = True
            except Exception as exc:  # noqa: BLE001
                log.error("worker galat exc=%s", type(exc).__name__)
            if not ran:
                self._stop.wait(self._interval)
