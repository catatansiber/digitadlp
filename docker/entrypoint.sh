#!/bin/sh
set -eu
cd /app/backend

# Kunci enkripsi: pakai DIGITADLP_FERNET_KEY bila diisi; kalau tidak, buat
# sekali dan simpan di volume /data. KUNCI HILANG = FILE TIDAK BISA DIBUKA.
KEY_FILE=/data/fernet.key
if [ -z "${DIGITADLP_FERNET_KEY:-}" ]; then
  if [ ! -s "$KEY_FILE" ]; then
    umask 077
    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())" > "$KEY_FILE"
    echo "[digitadlp] Kunci enkripsi baru dibuat di volume ($KEY_FILE). Cadangkan file ini!"
  fi
  DIGITADLP_FERNET_KEY=$(cat "$KEY_FILE")
  export DIGITADLP_FERNET_KEY
fi

# Tunggu basis data, jalankan migrasi, lalu buat admin pertama bila perlu.
python /app/docker/bootstrap.py wait-db
alembic upgrade head
python /app/docker/bootstrap.py ensure-admin

exec python -m digitadlp
