# DigitaDLP Backend (Engine Deteksi dan Sensor)

Mesin Python yang menemukan dan menyensor data pribadi (NIK, NIP, nama pegawai, dll.) pada dokumen PDF dan DOCX pemerintahan, lalu menghasilkan tiga versi: `publik`, `internal`, `rahasia`.

## Persyaratan

- Python >= 3.11
- Tesseract OCR dengan paket bahasa Indonesia (`ind`), mis. di Debian/Ubuntu:
  `sudo apt install tesseract-ocr tesseract-ocr-ind`
  (cek dengan `tesseract --list-langs`)

## Pemasangan

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -e .[ner]      # tambahkan ,dev untuk pytest: pip install -e .[ner,dev]
```

## Model IndoBERT NER (sekali unduh)

Deteksi nama orang memakai model token-classification bahasa Indonesia yang disimpan di folder lokal (server tidak mengunduh apa pun saat berjalan). Pada mesin yang punya internet:

```bash
pip install huggingface_hub
huggingface-cli download cahya/bert-base-indonesian-NER --local-dir ./models/indobert-ner
```

lalu salin folder itu ke server. `cahya/bert-base-indonesian-NER` hanyalah contoh kandidat yang perlu Anda evaluasi sendiri; model harus berupa model *token classification* bahasa Indonesia dengan label entitas orang (PER).

## Basis data (PostgreSQL) dan migrasi

Produksi memakai PostgreSQL (SQLite hanya untuk dev/tes):

```bash
pip install -e .[ner,postgres]
export DIGITADLP_DATABASE_URL=postgresql+psycopg://digitadlp:SANDI@127.0.0.1/digitadlp
alembic upgrade head          # jalankan dari folder backend/, juga setiap kali update
```

## Kunci enkripsi file

File sumber, ketiga versi, dan daftar pegawai disimpan terenkripsi (Fernet). Buat kunci sekali:

```bash
python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())"
export DIGITADLP_FERNET_KEY=...hasil di atas...
```

> **Peringatan: cadangkan kunci ini di tempat aman, terpisah dari cadangan folder penyimpanan.**
> Kunci hilang = semua file tersimpan tidak bisa dibuka lagi. Kunci bocor = siapa pun yang punya
> salinan folder penyimpanan bisa membaca dokumen.

## Akun Admin pertama

```bash
python -m digitadlp.app create-admin --username admin --unit "Sekretariat"
```

Kata sandi diminta dua kali di terminal. Pengguna lain, unit kerja, daftar pegawai, dan aturan label dikelola Admin lewat `/api/admin/...`.

## Variabel lingkungan

| Variabel | Keterangan |
|---|---|
| `DIGITADLP_FERNET_KEY` | Wajib. Kunci Fernet (lihat di atas). |
| `DIGITADLP_DATABASE_URL` | Default `sqlite:///./digitadlp.db`. Produksi: PostgreSQL. |
| `DIGITADLP_NER_PATH` | Wajib di produksi. Folder model IndoBERT NER. |
| `DIGITADLP_STORAGE` | Folder penyimpanan terenkripsi. Default `./storage`. |
| `DIGITADLP_SESSION_HOURS` | Lama sesi login. Default 8. |
| `DIGITADLP_COOKIE_SECURE` | Default `1` (cookie hanya lewat HTTPS). Set `0` hanya untuk dev lewat http. |
| `DIGITADLP_RUN_WORKER` | Default `1`: worker pemrosesan berjalan di dalam proses aplikasi. |
| `DIGITADLP_FRONTEND_DIR` | Folder hasil build antarmuka web (default `frontend/dist` di repo bila ada). Disajikan di `/`; API di `/api`. |
| `DIGITADLP_JOB_STALE_MINUTES` | Job berjalan tanpa heartbeat selama ini diambil ulang. Default 30. |
| `DIGITADLP_NER=fake` | **Hanya dev/test**: NER palsu tanpa model, nama orang tidak terdeteksi. Jangan dipakai di produksi. |

Daftar pegawai tidak lagi dibaca dari variabel lingkungan: Admin mengunggahnya lewat `POST /api/admin/employees` (xlsx, kolom `Nama` dan opsional `NIP`). File disimpan terenkripsi di `storage/_config/` dan dimuat lagi saat aplikasi mulai.

## Menjalankan

```bash
python -m digitadlp
# sama dengan: uvicorn digitadlp.app.main:app --host 127.0.0.1 --port 8000 --workers 1
```

**Jalankan tepat satu proses aplikasi** (`--workers 1`, jangan `gunicorn -w N`). Alasannya:

- Worker pemrosesan dokumen berjalan sebagai thread di dalam proses aplikasi.
- Daftar pegawai yang diimpor Admin dimuat ulang di memori proses yang menerima permintaan itu saja; proses lain tetap memakai daftar lama sampai restart.
- Pembatas percobaan login juga disimpan di memori proses.

Letakkan reverse proxy HTTPS (mis. nginx) di depan `127.0.0.1:8000`.

## API (ringkas)

Semua endpoint butuh login (cookie sesi dari `POST /api/auth/login`), kecuali login itu sendiri.

- `POST /api/auth/login`, `POST /auth/logout`, `GET /auth/me`
- `POST /api/documents` (multipart `file`, PDF/DOCX, maks. 50 MB), `GET /documents`, `GET /documents/{id}`
- `PUT /api/documents/{id}/label`, `POST /documents/{id}/corrections`, `/approve`, `/return`, `/reupload`, `/release`
- `GET /api/documents/{id}/versions/{publik|internal|rahasia}`
- `GET /api/documents/{id}/text` (teks sumber per halaman; hak akses sama dengan melihat temuan, diaudit)
- Admin: `GET/POST /api/admin/units`, `GET/POST /admin/users`, `PATCH /admin/users/{id}`, `POST /admin/employees`, `GET/PUT /admin/label-rules`, `GET /admin/audit?document_id=&actor_id=&limit=100` (maks. 500, terbaru dulu)

## Tes

```bash
pytest -v
```

## Keterbatasan yang diketahui

- Gambar yang luasnya < 20% halaman pada halaman PDF bertext tidak di-OCR.
- Gambar EMF/WMF/SVG serta objek tertanam, makro, dan altChunk pada DOCX ditolak.
- NIK hanya dikenali jika ditulis 16 digit berurutan atau dikelompokkan 4-4-4-4.
