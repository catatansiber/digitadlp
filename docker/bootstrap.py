"""Langkah awal container: tunggu basis data dan buat admin pertama.

Admin dibuat hanya jika belum ada satu pun admin, dari variabel
DIGITADLP_ADMIN_USERNAME / DIGITADLP_ADMIN_PASSWORD / DIGITADLP_ADMIN_UNIT.
"""

import os
import sys
import time

from sqlalchemy import select, text

from digitadlp.app.config import Settings
from digitadlp.app.db import make_engine, make_session_factory
from digitadlp.app.models import Role, Unit, User
from digitadlp.app.security import hash_password


def wait_db(timeout: int = 60) -> int:
    engine = make_engine(Settings.from_env(require_fernet=False).database_url)
    deadline = time.monotonic() + timeout
    while True:
        try:
            with engine.connect() as c:
                c.execute(text("SELECT 1"))
            return 0
        except Exception as exc:  # noqa: BLE001 - keep retrying until timeout
            if time.monotonic() > deadline:
                print(f"[digitadlp] Basis data tidak bisa dihubungi: {type(exc).__name__}", file=sys.stderr)
                return 1
            time.sleep(2)


def ensure_admin() -> int:
    engine = make_engine(Settings.from_env(require_fernet=False).database_url)
    with make_session_factory(engine)() as db:
        if db.scalar(select(User).where(User.role == Role.ADMIN)) is not None:
            return 0
        username = os.environ.get("DIGITADLP_ADMIN_USERNAME", "").strip()
        password = os.environ.get("DIGITADLP_ADMIN_PASSWORD", "")
        unit_name = os.environ.get("DIGITADLP_ADMIN_UNIT", "Admin Sistem").strip() or "Admin Sistem"
        if not username or len(password) < 10:
            print(
                "[digitadlp] Belum ada admin. Isi DIGITADLP_ADMIN_USERNAME dan "
                "DIGITADLP_ADMIN_PASSWORD (minimal 10 karakter) di file .env, lalu jalankan ulang.",
                file=sys.stderr,
            )
            return 1
        unit = db.scalar(select(Unit).where(Unit.name == unit_name))
        if unit is None:
            unit = Unit(name=unit_name)
            db.add(unit)
            db.flush()
        db.add(User(username=username, password_hash=hash_password(password),
                    full_name="Administrator", role=Role.ADMIN, unit_id=unit.id))
        db.commit()
    print(f"[digitadlp] Admin '{username}' dibuat. Ganti kata sandinya setelah masuk.")
    return 0


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    sys.exit({"wait-db": wait_db, "ensure-admin": ensure_admin}.get(cmd, lambda: 2)())
