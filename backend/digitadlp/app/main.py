from fastapi import FastAPI
from sqlalchemy.engine import Engine

from .config import Settings
from .db import make_engine, make_session_factory
from .routes import auth
from .security import LoginThrottle


def create_app(settings: Settings, engine=None) -> FastAPI:
    """`engine` is the detection engine (Plan 1); unused until a later task."""
    app = FastAPI(title="DigitaDLP")
    db_engine: Engine = make_engine(settings.database_url)
    app.state.settings = settings
    app.state.db_engine = db_engine
    app.state.session_factory = make_session_factory(db_engine)
    app.state.login_throttle = LoginThrottle()
    app.include_router(auth.router)
    return app
