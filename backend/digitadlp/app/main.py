import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.engine import Engine as DbEngine

from ..detect.employees import EmployeeDirectory
from .config import Settings
from .db import make_engine, make_session_factory
from .jobs import Worker
from .processing import Engine
from .routes import admin, auth, documents
from .security import LoginThrottle
from .storage import FileStore

log = logging.getLogger("digitadlp.app")
MSG_INVALID = "Data yang dikirim tidak lengkap atau tidak valid."


def build_engine() -> Engine:
    """Engine dari lingkungan: IndoBERT di DIGITADLP_NER_PATH, atau FakeNer bila
    DIGITADLP_NER=fake (khusus dev/test, nama orang tidak terdeteksi)."""
    if os.environ.get("DIGITADLP_NER") == "fake":
        from ..detect.ner import FakeNer

        log.warning("DIGITADLP_NER=fake: deteksi nama mati. Jangan dipakai di produksi.")
        return Engine(FakeNer({}), EmployeeDirectory(set()))
    from ..detect.ner import IndoBertNer

    path = os.environ.get("DIGITADLP_NER_PATH")
    if not path:
        raise RuntimeError(
            "DIGITADLP_NER_PATH belum diatur (folder model IndoBERT NER). "
            "Untuk dev/test tanpa model: DIGITADLP_NER=fake."
        )
    return Engine(IndoBertNer(path), EmployeeDirectory(set()))


def create_app(settings: Settings, engine: Engine | None = None) -> FastAPI:
    """`engine` adalah Engine deteksi yang dipakai worker; None = dari lingkungan."""
    if engine is None:
        engine = build_engine()
    store = FileStore(settings.storage_dir, settings.fernet_key)
    blob = store.get_blob(admin.EMPLOYEES_BLOB)
    if blob is not None:
        engine.set_directory(admin.load_directory(blob))

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if settings.run_worker:
            app.state.worker = Worker(app.state.session_factory, store, engine, settings)
            app.state.worker.start()
        try:
            yield
        finally:
            if app.state.worker is not None:
                app.state.worker.stop()
                app.state.worker = None

    app = FastAPI(title="DigitaDLP", lifespan=lifespan)
    db_engine: DbEngine = make_engine(settings.database_url)
    app.state.settings = settings
    app.state.db_engine = db_engine
    app.state.session_factory = make_session_factory(db_engine)
    app.state.login_throttle = LoginThrottle()
    app.state.store = store
    app.state.engine = engine
    app.state.worker = None

    @app.exception_handler(RequestValidationError)
    async def _invalid(request: Request, exc: RequestValidationError):
        # Jangan memantulkan nilai input (bisa berisi data pribadi).
        return JSONResponse({"detail": MSG_INVALID}, status_code=422)

    app.include_router(auth.router)
    app.include_router(documents.router)
    app.include_router(admin.router)
    return app


def __getattr__(name: str):
    # `uvicorn digitadlp.app.main:app`: dibangun saat diminta, bukan saat impor.
    if name == "app":
        global app
        app = create_app(Settings.from_env())
        return app
    raise AttributeError(name)
