import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
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


class SecurityHeadersMiddleware:
    """ASGI murni: header keamanan juga terpasang pada respons 500 yang tak tertangani."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                headers = [(k, v) for k, v in message.get("headers", [])
                           if k.decode("latin-1").lower() not in {h.lower() for h in SECURITY_HEADERS}]
                headers += [(k.lower().encode("latin-1"), v.encode("latin-1"))
                            for k, v in SECURITY_HEADERS.items()]
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_headers)


SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; img-src 'self' data:; style-src 'self'; "
        "script-src 'self'; frame-ancestors 'none'"),
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
}
ASSET_CACHE = "public, max-age=31536000, immutable"


def _frontend_dir(settings: Settings) -> Path | None:
    if settings.frontend_dir:
        d = Path(settings.frontend_dir)
    else:  # <repo>/frontend/dist relatif ke paket (backend/digitadlp/app/main.py)
        d = Path(__file__).resolve().parents[3] / "frontend" / "dist"
    return d.resolve() if d.is_dir() else None


def _mount_frontend(app: FastAPI, dist: Path) -> None:
    index = dist / "index.html"

    def _inside(rel: str) -> Path | None:
        p = (dist / rel).resolve()
        return p if p.is_relative_to(dist) and p.is_file() else None

    @app.get("/assets/{path:path}", include_in_schema=False)
    def asset(path: str):
        p = _inside(f"assets/{path}")
        if p is None:
            raise HTTPException(404, "Tidak ditemukan.")
        return FileResponse(p, headers={"Cache-Control": ASSET_CACHE})

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path == "api" or path.startswith("api/"):
            raise HTTPException(404, "Tidak ditemukan.")
        p = _inside(path) if path else None
        if p is not None and p != index:
            return FileResponse(p)
        if Path(path).suffix:  # berkas yang tidak ada: jangan balas index.html
            raise HTTPException(404, "Tidak ditemukan.")
        return FileResponse(index, headers={"Cache-Control": "no-store"})


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

    # Pembungkus terluar (di luar ServerErrorMiddleware) agar respons 500 pun berheader.
    _build = app.build_middleware_stack
    app.build_middleware_stack = lambda: SecurityHeadersMiddleware(_build())  # type: ignore[method-assign]

    app.include_router(auth.router)
    app.include_router(documents.router)
    app.include_router(admin.router)
    dist = _frontend_dir(settings)
    if dist is not None and (dist / "index.html").is_file():
        _mount_frontend(app, dist)
    return app


def __getattr__(name: str):
    # `uvicorn digitadlp.app.main:app`: dibangun saat diminta, bukan saat impor.
    if name == "app":
        global app
        app = create_app(Settings.from_env())
        return app
    raise AttributeError(name)
