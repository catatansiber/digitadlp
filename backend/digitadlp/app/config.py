import os
from dataclasses import dataclass


def _bool(value: str | None, default: bool) -> bool:
    if value is None or value == "":
        return default
    return value.strip().lower() in ("1", "true", "yes", "ya", "on")


@dataclass(frozen=True)
class Settings:
    fernet_key: str
    database_url: str = "sqlite:///./digitadlp.db"
    storage_dir: str = "./storage"
    session_hours: int = 8
    job_stale_minutes: int = 30
    cookie_secure: bool = True
    run_worker: bool = True

    @classmethod
    def from_env(cls) -> "Settings":
        env = os.environ
        key = env.get("DIGITADLP_FERNET_KEY")
        if not key:
            raise RuntimeError(
                "DIGITADLP_FERNET_KEY wajib diisi (kunci Fernet untuk enkripsi file)."
            )
        return cls(
            fernet_key=key,
            database_url=env.get("DIGITADLP_DATABASE_URL", cls.database_url),
            storage_dir=env.get("DIGITADLP_STORAGE", cls.storage_dir),
            session_hours=int(env.get("DIGITADLP_SESSION_HOURS", cls.session_hours)),
            job_stale_minutes=int(
                env.get("DIGITADLP_JOB_STALE_MINUTES", cls.job_stale_minutes)
            ),
            cookie_secure=_bool(env.get("DIGITADLP_COOKIE_SECURE"), True),
            run_worker=_bool(env.get("DIGITADLP_RUN_WORKER"), True),
        )
