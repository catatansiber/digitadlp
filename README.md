# DigitaDLP

DigitaDLP membantu instansi pemerintahan menemukan dan menyensor data pribadi (NIK, NIP, nama, nomor rekening, dan lain-lain) pada dokumen PDF dan DOCX sebelum dokumen dibagikan. Setiap dokumen yang disetujui Pemeriksa menghasilkan tiga versi: **Publik**, **Internal**, dan **Rahasia**. Semua pemrosesan berjalan di server instansi, tanpa layanan luar.

## Isi repo

| Folder | Isi |
|---|---|
| `backend/` | Aplikasi FastAPI (Python): deteksi, sensor, alur kerja, API `/api`, dan penyaji antarmuka web. Rincian di [`backend/README.md`](backend/README.md). |
| `frontend/` | Antarmuka web React + Vite (TypeScript). Hasil build ada di `frontend/dist`. |
| `frontend/e2e/` | Tes end-to-end Playwright terhadap backend sungguhan. |

## Build antarmuka web

Di mesin build (butuh Node.js 20+):

```bash
cd frontend
npm ci && npm run build
```

Salin folder `frontend/dist` ke server. Saat runtime antarmuka tidak memuat apa pun dari CDN.

## Menjalankan

Siapkan backend sesuai [`backend/README.md`](backend/README.md) (venv, migrasi `alembic upgrade head`, kunci Fernet, akun Admin pertama), lalu:

```bash
cd backend
export DIGITADLP_FERNET_KEY=...
export DIGITADLP_DATABASE_URL=postgresql+psycopg://digitadlp:SANDI@127.0.0.1/digitadlp
export DIGITADLP_STORAGE=/var/lib/digitadlp
export DIGITADLP_NER_PATH=/opt/digitadlp/models/indobert-ner
export DIGITADLP_FRONTEND_DIR=/opt/digitadlp/dist    # folder hasil build frontend
python -m digitadlp    # satu proses (--workers 1); host/port: DIGITADLP_HOST, DIGITADLP_PORT
```

Antarmuka tersedia di `/`, API di `/api`. Jalankan tepat **satu** proses aplikasi (`--workers 1`) dan letakkan reverse proxy HTTPS di depannya. `DIGITADLP_COOKIE_SECURE=false` hanya untuk percobaan lewat http.

## Mode pengembangan

Jalankan backend di port 8000 (mis. `DIGITADLP_COOKIE_SECURE=false DIGITADLP_NER=fake python -m digitadlp`), lalu:

```bash
cd frontend
npm run dev
```

Vite meneruskan (proxy) permintaan `/api` ke `http://127.0.0.1:8000`, sehingga cookie sesi berlaku di origin yang sama.

## Tes

```bash
cd backend && .venv/bin/pytest -q          # backend
cd frontend && npx vitest run              # unit/komponen
cd frontend && npx tsc --noEmit            # cek tipe
cd frontend && npm run e2e                 # build + Playwright (trace mati)
```

Tes e2e (`frontend/e2e/flow.spec.ts`) menjalankan `frontend/e2e/start-backend.sh`: backend dengan SQLite dan storage di folder sementara, `DIGITADLP_NER=fake`, kunci Fernet baru, di port 8765. Skenario: Admin membuat unit dan pengguna, Pengunggah meng-upload PDF ber-NIK, Pemeriksa menyetujui, versi Publik yang diunduh dipastikan tanpa NIK, dokumen dirilis, lalu aksi unduh terlihat di Audit. Screenshot disimpan di `frontend/test-results/` (tidak di-commit). Butuh `backend/.venv` yang sudah terpasang dan browser Chromium untuk Playwright (`npx playwright install chromium` bila belum ada).
