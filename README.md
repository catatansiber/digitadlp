# DigitaDLP

DigitaDLP membantu instansi pemerintahan menemukan dan menyensor data pribadi (NIK, NIP, nomor rekening, alamat, dan lain-lain; nama orang ditandai manual oleh pemilik dokumen) pada dokumen PDF dan DOCX sebelum dokumen dibagikan. Setiap dokumen yang dibuatkan versinya oleh pemiliknya menghasilkan tiga versi: **Publik**, **Internal**, dan **Rahasia**. Semua pemrosesan berjalan di server instansi, tanpa layanan luar.

## Isi repo

| Folder | Isi |
|---|---|
| `backend/` | Aplikasi FastAPI (Python): deteksi, sensor, alur kerja, API `/api`, dan penyaji antarmuka web. Rincian di [`backend/README.md`](backend/README.md). |
| `frontend/` | Antarmuka web React + Vite (TypeScript). Hasil build ada di `frontend/dist`. |
| `frontend/e2e/` | Tes end-to-end Playwright terhadap backend sungguhan. |
| `Dockerfile`, `docker-compose.yml`, `docker/` | Paket siap jalan dengan Docker. |

## Cara tercepat: Docker

Yang dibutuhkan: [Docker Desktop](https://www.docker.com/products/docker-desktop/) (Windows/macOS) atau Docker Engine dengan plugin Compose (Linux), ruang disk sekitar 5 GB, dan internet untuk build pertama.

1. Siapkan konfigurasi:

   ```bash
   cp .env.example .env
   ```

   Buka `.env`, lalu isi `POSTGRES_PASSWORD` dan `DIGITADLP_ADMIN_PASSWORD`. Kata sandi admin minimal 10 karakter.

2. Build dan jalankan:

   ```bash
   docker compose up -d --build
   ```

   Build pertama memakan waktu beberapa menit. Prosesnya mengunduh tampilan web dan OCR bahasa Indonesia. Tidak ada model AI yang diunduh.

3. Buka **http://localhost:8000**, lalu masuk dengan `admin` dan kata sandi dari `.env`. Setelah itu, buat unit kerja dan pengguna di menu **Admin**.

Perintah lain:

```bash
docker compose logs -f app
```

```bash
docker compose down
```

`docker compose down` menghentikan aplikasi tanpa menghapus data. Data tersimpan di volume `db-data` (basis data) dan `app-data` (file terenkripsi dan kunci).

**Penting, kunci enkripsi:**

- Kalau `DIGITADLP_FERNET_KEY` di `.env` kosong, kunci dibuat otomatis saat pertama jalan dan disimpan di volume, di `/data/fernet.key`.
- Kalau kunci hilang, semua dokumen yang tersimpan tidak bisa dibuka lagi. Salin kunci ke tempat aman:

  ```bash
  docker compose cp app:/data/fernet.key ./fernet.key.backup
  ```

- Jangan jalankan `docker compose down -v` kecuali Anda memang ingin menghapus semua data. Opsi `-v` menghapus volume.

Catatan:

- Aplikasi hanya bisa dibuka dari komputer ini, karena port terikat ke `127.0.0.1`. Untuk dibuka dari jaringan kantor, ubah `ports` di `docker-compose.yml`, pasang HTTPS (misalnya lewat reverse proxy), lalu set `DIGITADLP_COOKIE_SECURE=true`.

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
export DIGITADLP_FRONTEND_DIR=/opt/digitadlp/dist    # folder hasil build frontend
python -m digitadlp    # satu proses (--workers 1); host/port: DIGITADLP_HOST, DIGITADLP_PORT
```

Antarmuka tersedia di `/`, API di `/api`. Jalankan tepat **satu** proses aplikasi (`--workers 1`) dan letakkan reverse proxy HTTPS di depannya. `DIGITADLP_COOKIE_SECURE=false` hanya untuk percobaan lewat http.

## Mode pengembangan

Jalankan backend di port 8000 (mis. `DIGITADLP_COOKIE_SECURE=false python -m digitadlp`), lalu:

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

Tes e2e (`frontend/e2e/flow.spec.ts`) menjalankan `frontend/e2e/start-backend.sh`: backend dengan SQLite dan storage di folder sementara, kunci Fernet baru, di port 8765. Skenario: Admin membuat unit dan satu Pengguna, Pengguna mengunggah PDF ber-NIK dan bernama "Siti Rahmawati", menandai nama itu secara manual, memilih Buat versi, versi Publik yang diunduh dipastikan tanpa NIK dan tanpa nama, dokumen dirilis, lalu aksi unduh terlihat di Audit. Screenshot disimpan di `frontend/test-results/` (tidak di-commit). Butuh `backend/.venv` yang sudah terpasang dan browser Chromium untuk Playwright (`npx playwright install chromium` bila belum ada).
