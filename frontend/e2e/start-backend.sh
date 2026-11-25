#!/usr/bin/env bash
# Menyiapkan backend sekali pakai untuk tes e2e: SQLite + storage di folder sementara.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
PY="$ROOT/backend/.venv/bin/python"
TMP="$(mktemp -d "${TMPDIR:-/tmp}/digitadlp-e2e.XXXXXX")"
trap 'rm -rf "$TMP"' EXIT

export DIGITADLP_DATABASE_URL="sqlite:///$TMP/e2e.db"
export DIGITADLP_STORAGE="$TMP/storage"
export DIGITADLP_FERNET_KEY="$("$PY" -c 'from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())')"
export DIGITADLP_COOKIE_SECURE=false
export DIGITADLP_NER=fake
export DIGITADLP_FRONTEND_DIR="$ROOT/frontend/dist"
export DIGITADLP_HOST=127.0.0.1
export DIGITADLP_PORT=8765

cd "$ROOT/backend"
"$ROOT/backend/.venv/bin/alembic" upgrade head
# create-admin membaca kata sandi dari prompt, jadi admin dibuat langsung di sini.
"$PY" - <<'PY'
from digitadlp.app.config import Settings
from digitadlp.app.db import make_engine, make_session_factory
from digitadlp.app.models import Role, Unit, User
from digitadlp.app.security import hash_password

s = Settings.from_env(require_fernet=False)
with make_session_factory(make_engine(s.database_url))() as db:
    unit = Unit(name="Sekretariat")
    db.add(unit)
    db.flush()
    db.add(User(username="admin", password_hash=hash_password("admin-e2e-123"),
                full_name="Admin E2E", role=Role.ADMIN, unit_id=unit.id))
    db.commit()
PY
"$PY" -m digitadlp &
PID=$!
trap 'kill $PID 2>/dev/null; wait $PID 2>/dev/null; rm -rf "$TMP"' EXIT INT TERM
wait $PID
