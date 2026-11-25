from fastapi import FastAPI
from sqlalchemy.engine import Engine

from .config import Settings
from .db import make_engine, make_session_factory
from .routes import auth, documents
from .security import LoginThrottle
from .storage import FileStore


def create_app(settings: Settings, engine=None) -> FastAPI:
    """`engine` is the detection Engine (processing.Engine) used by the worker."""
    app = FastAPI(title="DigitaDLP")
    db_engine: Engine = make_engine(settings.database_url)
    app.state.settings = settings
    app.state.db_engine = db_engine
    app.state.session_factory = make_session_factory(db_engine)
    app.state.login_throttle = LoginThrottle()
    app.state.store = FileStore(settings.storage_dir, settings.fernet_key)
    app.state.engine = engine
    app.include_router(auth.router)
    app.include_router(documents.router)
    return app
