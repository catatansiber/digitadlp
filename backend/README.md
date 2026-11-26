# DigitaDLP Backend (Engine Deteksi dan Sensor)

Mesin Python yang menemukan dan menyensor data pribadi (NIK, NIP, nomor rekening, alamat, dll.) pada dokumen PDF dan DOCX pemerintahan, lalu menghasilkan tiga versi: `publik`, `internal`, `rahasia`.

## Persyaratan

- Python >= 3.11
- Tesseract OCR dengan paket bahasa Indonesia (`ind`), mis. di Debian/Ubuntu:
  `sudo apt install tesseract-ocr tesseract-ocr-ind`
  (cek dengan `tesseract --list-langs`)

## Pemasangan

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -e .          # tambahkan [dev] untuk pytest: pip install -e .[dev]
```

## Deteksi nama dan alamat

Nama orang **tidak dideteksi otomatis**. Pemilik dokumen menandai nama yang perlu disensor lewat "Tandai manual" (jenis "Nama orang"); semua kemunculan teks yang sama ikut tersensor. Data pribadi berpola (NIK, NIP, nomor rekening, telepon, email, dan sejenisnya) tetap dideteksi otomatis.

Alamat dideteksi dari kata penanda. Aplikasi mengenali Jl., Jalan, Gg., Gang, Perumahan, Perum, Komplek, Blok, RT, RW, No., dan Nomor, serta kelurahan atau desa yang langsung mengikuti alamat tersebut.

Keterbatasan: alamat yang ditulis **tanpa kata penanda** (misalnya hanya nama kampung atau nama kompleks tanpa "Jl.", "Blok", atau "RT") tidak terdeteksi. Pemilik perlu menandainya secara manual.

## Basis data (PostgreSQL) dan migrasi

Produksi memakai PostgreSQL (SQLite hanya untuk dev/tes):

```bash
pip install -e .[postgres]
export DIGITADLP_DATABASE_URL=postgresql+psycopg://digitadlp:SANDI@127.0.0.1/digitadlp
alembic upgrade head          # jalankan dari folder backend/, juga setiap kali update
```

## Kunci enkripsi file

File sumber dan ketiga versi disimpan terenkripsi (Fernet). Buat kunci sekali:

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

Kata sandi diminta dua kali di terminal. Pengguna lain, unit kerja, dan aturan label dikelola Admin lewat `/api/admin/...`.

## Variabel lingkungan

| Variabel | Keterangan |
|---|---|
| `DIGITADLP_FERNET_KEY` | Wajib. Kunci Fernet (lihat di atas). |
| `DIGITADLP_DATABASE_URL` | Default `sqlite:///./digitadlp.db`. Produksi: PostgreSQL. |
| `DIGITADLP_STORAGE` | Folder penyimpanan terenkripsi. Default `./storage`. |
| `DIGITADLP_SESSION_HOURS` | Lama sesi login. Default 8. |
| `DIGITADLP_COOKIE_SECURE` | Default `1` (cookie hanya lewat HTTPS). Set `0` hanya untuk dev lewat http. |
| `DIGITADLP_RUN_WORKER` | Default `1`: worker pemrosesan berjalan di dalam proses aplikasi. |
| `DIGITADLP_FRONTEND_DIR` | Folder hasil build antarmuka web (default `frontend/dist` di repo bila ada). Disajikan di `/`; API di `/api`. |
| `DIGITADLP_JOB_STALE_MINUTES` | Job berjalan tanpa heartbeat selama ini diambil ulang. Default 30. |

## Menjalankan

```bash
python -m digitadlp
# sama dengan: uvicorn digitadlp.app.main:app --host 127.0.0.1 --port 8000 --workers 1
```

**Jalankan tepat satu proses aplikasi** (`--workers 1`, jangan `gunicorn -w N`). Alasannya:

- Worker pemrosesan dokumen berjalan sebagai thread di dalam proses aplikasi.
- Pembatas percobaan login juga disimpan di memori proses.

Letakkan reverse proxy HTTPS (mis. nginx) di depan `127.0.0.1:8000`.

## Antarmuka web

Antarmuka React dibangun di folder `frontend/` (`npm ci && npm run build`, lihat README di root repo). Salin `frontend/dist` ke server lalu arahkan `DIGITADLP_FRONTEND_DIR` ke folder itu. Backend menyajikannya di `/`, sedangkan API tetap di `/api`. Untuk pengembangan, `npm run dev` di `frontend/` meneruskan `/api` ke backend di `127.0.0.1:8000`.

## API (ringkas)

Semua endpoint butuh login (cookie sesi dari `POST /api/auth/login`), kecuali login itu sendiri.

- `POST /api/auth/login`, `POST /auth/logout`, `GET /auth/me`
- `POST /api/documents` (multipart `file`, PDF/DOCX, maks. 50 MB), `GET /documents`, `GET /documents/{id}`
- `PUT /api/documents/{id}/label`, `POST /documents/{id}/corrections`, `/approve`, `/reupload`, `/release`
- `GET /api/documents/{id}/versions/{publik|internal|rahasia}`
- `GET /api/documents/{id}/text` (teks sumber per halaman; hak akses sama dengan melihat temuan, diaudit)
- Admin: `GET/POST /api/admin/units`, `GET/POST /admin/users`, `PATCH /admin/users/{id}`, `GET/PUT /admin/label-rules`, `GET /admin/audit?document_id=&actor_id=&limit=100` (maks. 500, terbaru dulu)

## Tes

```bash
pytest -v
```

## Keterbatasan yang diketahui

- Gambar yang luasnya < 20% halaman pada halaman PDF bertext tidak di-OCR.
- Gambar EMF/WMF/SVG serta objek tertanam, makro, dan altChunk pada DOCX ditolak.
- NIK hanya dikenali jika ditulis 16 digit berurutan atau dikelompokkan 4-4-4-4.
- Halaman pindaian diputar otomatis (OSD tesseract; bila teks terlalu sedikit, dicoba 0/90/180/270 dan dipilih yang paling banyak kata yakin). Lapisan teks hasil OCR ulang dibuat dari gambar tegak; tampilan halaman tetap seperti aslinya.
- NIP tanpa kata "NIP" dikenali hanya jika 18 digit (berurutan atau 8-6-1-3 dengan satu spasi) dan strukturnya sah: tanggal lahir 1940-2010, TMT 1960-tahun depan, digit ke-15 1/2. NIP dengan pola lain tetap butuh kata "NIP".
- Alamat pada baris yang juga memuat Telp/Telepon/Fax/Faks/Email/Website/Web/Kode Pos dianggap alamat kantor (kop surat) dan tidak disamarkan. Akibatnya alamat pribadi yang ditulis sebaris dengan nomor telepon juga tidak terdeteksi sebagai alamat (nomor HP tetap terdeteksi).
- Nama warga dikenali dari label formulir di awal baris (Nama, Nama Lengkap, Nama Pemohon/Pemilik/Pelapor/Ayah/Ibu/Wali, Atas Nama) diikuti ":" atau ";", termasuk tata letak kolom OCR "Nama" / ":" / nilai. Jika OCR membaca semua label lebih dulu lalu semua nilai, nama tidak bisa dipasangkan dan perlu ditandai manual.
- Bila temuan harus dicari per kata (mis. alamat dua baris), kata lain hanya dicari di sekitar kata jangkar (±3 tinggi baris); bila tidak ketemu, proses gagal (fail-closed) alih-alih menyamarkan kata yang sama di tempat lain.
