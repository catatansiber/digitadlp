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

## Variabel lingkungan

| Variabel | Keterangan |
|---|---|
| `DIGITADLP_NER_PATH` | Wajib. Folder model IndoBERT NER. |
| `DIGITADLP_EMPLOYEES_XLSX` | Opsional. Daftar pegawai (.xlsx); jika kosong, direktori pegawai kosong. |
| `DIGITADLP_STORAGE` | Folder penyimpanan dokumen. Default `./storage`. |
| `DIGITADLP_NER=fake` | Hanya untuk dev/test: memakai NER palsu tanpa model (nama tidak terdeteksi). Jangan dipakai di produksi. |

## Menjalankan

```bash
export DIGITADLP_NER_PATH=./models/indobert-ner
python -m digitadlp
# atau: uvicorn digitadlp.__main__:app --host 127.0.0.1 --port 8000
```

Server mendengarkan di `127.0.0.1:8000`.

## API

- `POST /documents` (multipart `file`, PDF atau DOCX, maks. 50 MB): upload dan deteksi. Mengembalikan `id`, `suggested_label`, dan `findings`.
- `POST /documents/{id}/versions`: membuat versi `publik`, `internal`, `rahasia`.
- `GET /documents/{id}/versions/{version}`: mengunduh versi tersebut.

Contoh:

```bash
ID=$(curl -s -F file=@surat.pdf http://127.0.0.1:8000/documents | python -c "import sys,json;print(json.load(sys.stdin)['id'])")
curl -s -X POST http://127.0.0.1:8000/documents/$ID/versions
curl -s -o publik.pdf http://127.0.0.1:8000/documents/$ID/versions/publik
```

## Tes

```bash
pytest -v
```

## Keterbatasan yang diketahui

- Gambar yang luasnya < 20% halaman pada halaman PDF bertext tidak di-OCR.
- Gambar EMF/WMF/SVG serta objek tertanam, makro, dan altChunk pada DOCX ditolak.
- NIK hanya dikenali jika ditulis 16 digit berurutan atau dikelompokkan 4-4-4-4.
- Belum ada autentikasi (direncanakan di Plan 2): jangan buka ke jaringan; biarkan di 127.0.0.1.
