# DigitaDLP — satu image berisi tampilan web, backend, dan OCR.
#
#   docker compose up -d --build
#
# Build butuh internet (npm, pip). Saat berjalan, aplikasi tidak
# menghubungi layanan luar.

# ---------- 1. Build tampilan web ----------
FROM node:22-bookworm-slim AS web
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---------- 2. Image akhir ----------
FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
 && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-ind \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app/backend
COPY backend/pyproject.toml ./
COPY backend/digitadlp ./digitadlp
RUN pip install ".[postgres]"
COPY backend/alembic.ini ./
COPY backend/alembic ./alembic
COPY docker/entrypoint.sh docker/bootstrap.py /app/docker/

COPY --from=web /src/frontend/dist /app/frontend/dist

RUN useradd --system --uid 10001 --home /data digitadlp \
 && mkdir -p /data && chown digitadlp /data \
 && sed -i 's/\r$//' /app/docker/entrypoint.sh /app/docker/bootstrap.py \
 && chmod +x /app/docker/entrypoint.sh

ENV DIGITADLP_HOST=0.0.0.0 \
    DIGITADLP_PORT=8000 \
    DIGITADLP_STORAGE=/data/storage \
    DIGITADLP_FRONTEND_DIR=/app/frontend/dist

USER digitadlp
VOLUME ["/data"]
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=60s --retries=5 \
  CMD python -c "import urllib.request,sys; r=urllib.request.urlopen('http://127.0.0.1:8000/', timeout=4); sys.exit(0 if r.status==200 else 1)"
ENTRYPOINT ["/app/docker/entrypoint.sh"]
