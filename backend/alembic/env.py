import os

from alembic import context
from sqlalchemy import create_engine

from digitadlp.app.models import Base

config = context.config
target_metadata = Base.metadata


def _url() -> str:
    # Order: explicit config override (tests), env var, default.
    return (
        config.get_main_option("sqlalchemy.url")
        or os.environ.get("DIGITADLP_DATABASE_URL")
        or "sqlite:///./digitadlp.db"
    )


def run_migrations_offline() -> None:
    context.configure(
        url=_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(_url())
    with engine.connect() as conn:
        context.configure(
            connection=conn, target_metadata=target_metadata, render_as_batch=True
        )
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
