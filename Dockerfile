# DigitaDLP — satu image berisi tampilan web, backend, OCR, dan model NER.
#
#   docker compose up -d --build
#
# Build butuh internet (npm, pip, model). Saat berjalan, aplikasi tidak
# menghubungi layanan luar.

# ---------- 1. Build tampilan web ----------
FROM node:22-bookworm-slim AS web
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---------- 2. Unduh model NER (sekali, saat build) ----------
FROM python:3.12-slim-bookworm AS model
ARG NER_MODEL=cahya/bert-base-indonesian-NER
RUN pip install --no-cache-dir "huggingface_hub>=0.24"
RUN python -c "from huggingface_hub import snapshot_download as d; \
d('${NER_MODEL}', local_dir='/model', allow_patterns=['config.json','pytorch_model.bin','*.safetensors','vocab.txt','tokenizer*','special_tokens_map.json'])"

# ---------- 3. Image akhir ----------
FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1

RUN apt-get update \
 && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-ind \
 && rm -rf /var/lib/apt/lists/*

# torch versi CPU (jauh lebih kecil daripada versi GPU)
RUN pip install --index-url https://download.pytorch.org/whl/cpu torch

WORKDIR /app/backend
COPY backend/pyproject.toml ./
COPY backend/digitadlp ./digitadlp
RUN pip install ".[postgres,ner]"
COPY backend/alembic.ini ./
COPY backend/alembic ./alembic
COPY docker/entrypoint.sh docker/bootstrap.py /app/docker/

COPY --from=web /src/frontend/dist /app/frontend/dist
COPY --from=model /model /app/model

RUN useradd --system --uid 10001 --home /data digitadlp \
 && mkdir -p /data && chown digitadlp /data \
 && chmod +x /app/docker/entrypoint.sh

ENV DIGITADLP_HOST=0.0.0.0 \
    DIGITADLP_PORT=8000 \
    DIGITADLP_STORAGE=/data/storage \
    DIGITADLP_FRONTEND_DIR=/app/frontend/dist \
    DIGITADLP_NER_PATH=/app/model

USER digitadlp
VOLUME ["/data"]
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=60s --retries=5 \
  CMD python -c "import urllib.request,sys; r=urllib.request.urlopen('http://127.0.0.1:8000/', timeout=4); sys.exit(0 if r.status==200 else 1)"
ENTRYPOINT ["/app/docker/entrypoint.sh"]
