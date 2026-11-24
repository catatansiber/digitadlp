# DigitaDLP Rencana 1: Mesin Deteksi & Sensor — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pustaka Python + API FastAPI yang menerima PDF/DOCX, menemukan data pribadi, menyarankan label, dan menghasilkan versi Publik / Internal / Rahasia dengan sensor sungguhan.

**Architecture:** Paket `digitadlp` dibagi tiga lapis: `detect` (teks → daftar `Finding`), `policy` (Finding + versi → aksi KEEP/MASK/REDACT, plus saran label), dan `redact` (file + aksi → file baru). API tipis di atasnya. NER diakses lewat protokol agar tes memakai detektor palsu; model IndoBERT hanya dimuat di produksi. Login, peran, alur persetujuan, audit, antrean, dan React masuk **Rencana 2**.

**Tech Stack:** Python 3.11, FastAPI, PyMuPDF (`pymupdf`), `python-docx`, `pytesseract` + Tesseract `ind`, `transformers` (IndoBERT NER), `openpyxl`, pytest.

**Spec:** `docs/superpowers/specs/2026-11-24-digitadlp-design.md`

## Global Constraints

- Tidak ada panggilan jaringan ke layanan luar saat memproses dokumen. Model NER dimuat dari folder lokal (`DIGITADLP_NER_PATH`).
- Berjalan di CPU, tanpa GPU.
- Sensor harus menghapus teks dari file; kotak hitam di atas teks yang masih ada = gagal.
- Versi Publik: metadata, komentar, dan tracked changes dibuang.
- Versi Internal: NIK, KK, rekening tetap tersamar (`3201********0001`); nama pegawai dan NIP tampil.
- Versi Rahasia: utuh.
- Saran label: ada NIK/KK/rekening → `rahasia`; hanya data pegawai → `internal`; tanpa data pribadi → `publik`.
- Format output = format input.

## Review Focus

1. NIK ditulis dengan spasi/titik/strip (`6474 0152 0388 0002`) → tetap terdeteksi dan disensor. Tes di Task 2.
2. Angka 16 digit yang bukan NIK (nomor faktur, tanggal tidak valid) → tidak ditandai NIK. Tes di Task 2.
3. Data pribadi terpecah di beberapa *run* DOCX (format tebal di tengah NIK) → tetap tersensor. Tes di Task 7.
4. Data pribadi di header/footer/tabel DOCX → tersensor. Tes di Task 7.
5. PDF terenkripsi atau rusak → API membalas 422 dengan pesan jelas, bukan 500. Tes di Task 8.

---

## Struktur file

```
backend/
  pyproject.toml
  digitadlp/
    models.py            # Finding, Kind, Strength, Label, Version, Action
    detect/patterns.py   # regex + validasi NIK
    detect/ner.py        # protokol NerDetector, IndoBertNer
    detect/employees.py  # EmployeeDirectory (impor Excel)
    detect/pipeline.py   # detect(): gabung semua detektor
    policy.py            # suggest_label(), action_for(), mask_value()
    redact/pdf.py        # PDF teks + PDF scan
    redact/docx.py       # DOCX
    api.py               # FastAPI
  tests/
    fixtures/            # dibuat oleh conftest.py, bukan file biner di repo
    conftest.py
    test_*.py
```

---

### Task 1: Kerangka proyek + model data

**Files:**
- Create: `backend/pyproject.toml`, `backend/digitadlp/__init__.py`, `backend/digitadlp/models.py`
- Test: `backend/tests/test_models.py`

**Interfaces:**
- Produces:
  - `class Kind(StrEnum)`: `NIK, KK, NPWP, PHONE, EMAIL, ACCOUNT, NAME_CITIZEN, NAME_EMPLOYEE, NIP, ADDRESS, BIRTHDATE`
  - `class Strength(StrEnum)`: `STRONG, MEDIUM, EMPLOYEE`
  - `class Label(StrEnum)` dan `class Version(StrEnum)`: `PUBLIK, INTERNAL, RAHASIA` (nilai huruf kecil)
  - `class Action(StrEnum)`: `KEEP, MASK, REDACT`
  - `@dataclass(frozen=True) class Finding: kind: Kind; start: int; end: int; text: str; source: str` dengan properti `strength -> Strength`. Nilainya `STRONG` untuk NIK/KK/ACCOUNT/NPWP, `EMPLOYEE` untuk NAME_EMPLOYEE/NIP, dan `MEDIUM` untuk sisanya.

- [ ] **Step 1: Tes gagal** — `test_strength_mapping`: `Finding(Kind.NIK,0,16,"6474015203880002","regex").strength == Strength.STRONG`; NAME_EMPLOYEE → EMPLOYEE; PHONE → MEDIUM.
- [ ] **Step 2:** `cd backend && pip install -e .[dev] && pytest tests/test_models.py -v` → FAIL (import error).
- [ ] **Step 3:** Tulis `pyproject.toml` (dependensi di atas, extra `dev` = pytest, httpx) dan `models.py`.
- [ ] **Step 4:** `pytest tests/test_models.py -v` → PASS.
- [ ] **Step 5:** `git add backend && git commit -m "feat: project skeleton and data models"`

### Task 2: Detektor pola (regex)

**Files:**
- Create: `backend/digitadlp/detect/__init__.py`, `backend/digitadlp/detect/patterns.py`
- Test: `backend/tests/test_patterns.py`

**Interfaces:**
- Consumes: `Finding`, `Kind` (Task 1)
- Produces: `find_patterns(text: str) -> list[Finding]` (urut `start`, `source="regex"`); `is_valid_nik(digits: str) -> bool`

Aturan validasi NIK: tepat 16 digit; digit ke-7–8 (tanggal) bernilai 01–31 atau 41–71; digit ke-9–10 (bulan) 01–12; digit ke-13–16 ≠ `0000`. Angka 16 digit diberi tanda NIK jika valid. Kalau tidak valid, tetapi dalam 30 karakter sebelumnya ada kata "KK" atau "Kartu Keluarga", angka itu diberi tanda KK. Pemisah spasi/titik/strip di antara kelompok digit diizinkan; `start/end` mencakup teks asli termasuk pemisah. HP: `(\+62|62|0)8\d{1,2}[-\s]?\d{3,4}[-\s]?\d{3,5}`. NIP: 18 digit (kata "NIP" di depan). Rekening: 10–16 digit dengan pemisah strip didahului kata "rekening"/"rek". NPWP: `\d{2}\.\d{3}\.\d{3}\.\d-\d{3}\.\d{3}` atau 16 digit setelah "NPWP". Email: regex standar.

- [ ] **Step 1: Tes gagal**
```python
def test_nik_plain():
    f = find_patterns("NIK 6474015203880002 ok")
    assert [(x.kind, x.text) for x in f] == [(Kind.NIK, "6474015203880002")]
def test_nik_separated():
    assert find_patterns("NIK: 6474 0152 0388 0002")[0].text == "6474 0152 0388 0002"
def test_invalid_16_digits_not_nik():
    assert find_patterns("Faktur 1234569999990000") == []   # bulan 99
def test_kk_by_context():
    assert find_patterns("No. KK 6474010000000001")[0].kind == Kind.KK
def test_phone_email_account_nip():
    kinds = {x.kind for x in find_patterns(
        "HP 0812-5544-0921, a@b.go.id, rekening BRI 0215-01-004567-50-3, NIP 197004121998031005")}
    assert kinds == {Kind.PHONE, Kind.EMAIL, Kind.ACCOUNT, Kind.NIP}
```
- [ ] **Step 2:** `pytest tests/test_patterns.py -v` → FAIL.
- [ ] **Step 3:** Tulis `patterns.py`. NIP dicek sebelum NIK, supaya 18 digit tidak terpotong jadi NIK.
- [ ] **Step 4:** → PASS.
- [ ] **Step 5:** `git commit -m "feat: regex detectors with NIK validation"`

### Task 3: NER + daftar pegawai

**Files:**
- Create: `backend/digitadlp/detect/ner.py`, `backend/digitadlp/detect/employees.py`
- Test: `backend/tests/test_employees.py`, `backend/tests/test_ner.py`

**Interfaces:**
- Produces:
  - `class NerDetector(Protocol): def find(self, text: str) -> list[Finding]`. Hasilnya `NAME_CITIZEN` / `ADDRESS` dengan `source="ner"`.
  - `class IndoBertNer`, dengan konstruktor `__init__(self, model_path: str)`. Model dimuat lewat `transformers.pipeline("token-classification", aggregation_strategy="simple", device=-1)` dengan `local_files_only=True`. Label `PER` → NAME_CITIZEN, label `LOC`/`ADDRESS` → ADDRESS.
  - `class FakeNer(NerDetector)`, dengan konstruktor `__init__(self, spans: dict[str, Kind])`. Kelas ini mencari string persis di teks. Dipakai untuk tes.
  - `class EmployeeDirectory`: `from_xlsx(path) -> EmployeeDirectory` (kolom `nama`, `nip`), `from_names(names: list[str])`, `is_employee(name: str) -> bool`. Pencocokan memakai normalisasi: huruf kecil, gelar dibuang (`drs.`, `ir.`, `s.kom`, `m.si`, `s.h.`, `dr.`), lalu spasi dirapikan.

- [ ] **Step 1: Tes gagal** — `test_directory_strips_titles`: `EmployeeDirectory.from_names(["Bambang Sutrisno"]).is_employee("Drs. Bambang Sutrisno, M.Si") is True`; `is_employee("Siti Rahmawati") is False`. `test_from_xlsx` memakai file xlsx yang dibuat dengan openpyxl di `tmp_path`. `test_indobert_marked_slow` diberi tanda `@pytest.mark.skipif(not os.getenv("DIGITADLP_NER_PATH"))`, dan memeriksa bahwa "Siti Rahmawati tinggal di Bontang" menghasilkan setidaknya satu NAME_CITIZEN.
- [ ] **Step 2:** → FAIL.
- [ ] **Step 3:** Tulis `ner.py` dan `employees.py`.
- [ ] **Step 4:** → PASS (tes IndoBERT di-skip di CI).
- [ ] **Step 5:** `git commit -m "feat: NER protocol and employee directory"`

### Task 4: Pipeline deteksi

**Files:**
- Create: `backend/digitadlp/detect/pipeline.py`
- Test: `backend/tests/test_pipeline.py`

**Interfaces:**
- Consumes: `find_patterns`, `NerDetector`, `EmployeeDirectory`
- Produces: `detect(text: str, ner: NerDetector, directory: EmployeeDirectory) -> list[Finding]`

Aturan: gabungkan regex + NER. NAME_CITIZEN yang cocok dengan direktori diubah jadi NAME_EMPLOYEE. Kalau dua temuan tumpang tindih, ambil yang `strength`-nya lebih kuat (STRONG > MEDIUM > EMPLOYEE). Kalau sama kuat, ambil yang lebih panjang. Hasil diurutkan menurut `start`.

- [ ] **Step 1: Tes gagal** — teks contoh dari mockup ("Nama: Siti Rahmawati, NIK 6474015203880002 … Kepala Dinas, Drs. Bambang Sutrisno"). Pakai `FakeNer({"Siti Rahmawati": NAME_CITIZEN, "Drs. Bambang Sutrisno": NAME_CITIZEN})` dan direktori berisi "Bambang Sutrisno". Assert jenis temuan = `[NAME_CITIZEN, NIK, NAME_EMPLOYEE]`. Tes tumpang tindih: NER menandai "6474015203880002" sebagai ADDRESS, regex sebagai NIK. Hanya NIK yang boleh tersisa.
- [ ] **Step 2:** → FAIL. **Step 3:** tulis. **Step 4:** → PASS.
- [ ] **Step 5:** `git commit -m "feat: detection pipeline"`

### Task 5: Kebijakan — label, aksi, penyamaran

**Files:**
- Create: `backend/digitadlp/policy.py`
- Test: `backend/tests/test_policy.py`

**Interfaces:**
- Produces:
  - `suggest_label(findings: list[Finding]) -> Label`
  - `action_for(f: Finding, v: Version) -> Action`. Untuk RAHASIA, semua temuan KEEP. Untuk PUBLIK, NAME_EMPLOYEE KEEP dan sisanya REDACT; NIP pegawai juga REDACT. Untuk INTERNAL, temuan EMPLOYEE KEEP dan sisanya MASK.
  - `mask_value(f: Finding) -> str`. Untuk NIK/KK/ACCOUNT/NPWP/NIP/PHONE: digit ke-5 sampai 4 digit terakhir diganti `*`, pemisah dipertahankan. Untuk nama: tiap kata, huruf pertama dan dua huruf terakhir tampil, sisanya `*` ("Siti Rahmawati" → "Siti R*****ti"; kata ≤4 huruf tetap utuh). Untuk ADDRESS: hanya kata sebelum "RT" atau angka pertama yang dipertahankan. Untuk EMAIL: `s***@domain`.
  - `placeholder(kind: Kind) -> str`, contohnya `"[NIK]"`, `"[NAMA]"`, `"[ALAMAT]"`, `"[HP]"`, `"[EMAIL]"`, `"[REKENING]"`, `"[NPWP]"`, `"[NIP]"`, `"[KK]"`, `"[TGL LAHIR]"`.

- [ ] **Step 1: Tes gagal**
```python
def test_label_rules():
    assert suggest_label([]) == Label.PUBLIK
    assert suggest_label([emp]) == Label.INTERNAL
    assert suggest_label([emp, phone]) == Label.INTERNAL
    assert suggest_label([nik]) == Label.RAHASIA
def test_mask_nik():
    assert mask_value(nik) == "6474********0002"
def test_mask_name():
    assert mask_value(F(Kind.NAME_CITIZEN, "Siti Rahmawati")) == "Siti R*****ti"
def test_actions():
    assert action_for(nik, Version.PUBLIK) == Action.REDACT
    assert action_for(nik, Version.INTERNAL) == Action.MASK
    assert action_for(emp, Version.INTERNAL) == Action.KEEP
    assert action_for(nik, Version.RAHASIA) == Action.KEEP
```
(Aturan label: MEDIUM tanpa STRONG → INTERNAL, sesuai dengan sifat data warga non-identitas yang tidak boleh publik.)
- [ ] **Step 2–4:** FAIL → tulis → PASS.
- [ ] **Step 5:** `git commit -m "feat: labeling and masking policy"`

### Task 6: Sensor PDF (teks + scan)

**Files:**
- Create: `backend/digitadlp/redact/__init__.py`, `backend/digitadlp/redact/pdf.py`
- Modify: `backend/tests/conftest.py` (fixture `make_pdf(text) -> Path`, `make_scanned_pdf(text) -> Path` yang merender teks ke gambar 200 dpi)
- Test: `backend/tests/test_redact_pdf.py`

**Interfaces:**
- Consumes: `detect`, `action_for`, `mask_value`, `placeholder`
- Produces:
  - `class DocumentError(Exception)`, dipakai untuk file terenkripsi atau rusak
  - `extract_pdf_text(path: Path) -> list[str]` (satu string per halaman; halaman tanpa teks di-OCR dengan `pytesseract`, `lang="ind"`)
  - `redact_pdf(src: Path, dst: Path, findings_per_page: list[list[Finding]], version: Version) -> None`

Cara kerja: untuk tiap temuan berstatus REDACT atau MASK, cari kotaknya dengan `page.search_for(f.text)`. Untuk halaman scan, kotak diambil dari `pytesseract.image_to_data`. Lalu panggil `page.add_redact_annot(rect, text=placeholder|mask_value, fill=(0,0,0) untuk REDACT)` dan `page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_PIXELS)`. Untuk PUBLIK, jalankan juga `doc.set_metadata({})`, `doc.del_xml_metadata()`, dan hapus semua anotasi. Simpan dengan `garbage=4, deflate=True`. Halaman scan versi PUBLIK/INTERNAL di-OCR ulang setelah sensor (`page.get_textpage_ocr`) supaya teksnya tetap bisa dicari.

- [ ] **Step 1: Tes gagal**
```python
def test_text_really_removed(make_pdf, tmp_path):
    src = make_pdf("Nama Siti Rahmawati NIK 6474015203880002")
    ...redact_pdf(src, out, findings, Version.PUBLIK)
    text = fitz.open(out)[0].get_text()
    assert "6474015203880002" not in text and "[NIK]" in text
def test_internal_masks(...): assert "6474********0002" in text
def test_rahasia_unchanged(...): assert "6474015203880002" in text
def test_metadata_stripped(...): assert fitz.open(out).metadata["author"] == ""
def test_scanned_pdf_redacted(make_scanned_pdf, ...):  # skip jika tesseract tidak ada
    assert "6474015203880002" not in "".join(extract_pdf_text(out))
def test_encrypted_raises(tmp_path): with pytest.raises(DocumentError): extract_pdf_text(encrypted)
```
- [ ] **Step 2:** → FAIL. **Step 3:** tulis. **Step 4:** → PASS.
- [ ] **Step 5:** `git commit -m "feat: true PDF redaction for text and scanned pages"`

### Task 7: Sensor DOCX

**Files:**
- Create: `backend/digitadlp/redact/docx.py`
- Modify: `backend/tests/conftest.py` (fixture `make_docx(...)` dengan body, tabel, header, footer, komentar, dan NIK yang terpecah ke 2 run)
- Test: `backend/tests/test_redact_docx.py`

**Interfaces:**
- Produces: `extract_docx_text(path: Path) -> list[str]` (satu string per paragraf, termasuk tabel/header/footer); `redact_docx(src: Path, dst: Path, detect_fn: Callable[[str], list[Finding]], version: Version) -> None`

Cara kerja: untuk tiap paragraf (body, sel tabel, header, footer), gabungkan teks semua run, jalankan `detect_fn`, lalu ganti teks dari belakang ke depan. Teks pengganti ditaruh di run tempat temuan dimulai. Bagian temuan di run berikutnya dihapus, tapi format run itu tetap dipertahankan. Untuk PUBLIK: hapus `word/comments.xml` dan relasinya, terima semua `w:ins` (buka bungkusnya), buang semua `w:del`, kosongkan `core_properties` (author, last_modified_by, comments).

- [ ] **Step 1: Tes gagal** — `test_split_run_nik_removed` (NIK "64740152" tebal + "03880002" biasa → tidak ada di XML hasil), `test_header_footer_table`, `test_comments_and_tracked_changes_removed` (cari `w:comment` dan `w:del` di `document.xml`/zip), `test_core_props_cleared`.
- [ ] **Step 2–4:** FAIL → tulis → PASS.
- [ ] **Step 5:** `git commit -m "feat: DOCX redaction incl. headers, tables, split runs"`

### Task 8: API FastAPI

**Files:**
- Create: `backend/digitadlp/api.py`
- Test: `backend/tests/test_api.py`

**Interfaces:**
- Consumes: semua yang di atas
- Produces:
  - `create_app(ner: NerDetector, directory: EmployeeDirectory, storage: Path) -> FastAPI`
  - `POST /documents` (multipart `file`) → `201 {"id": str, "suggested_label": "rahasia", "findings": [{"kind","text","start","end","page"}]}`. File sumber disimpan di `storage/<id>/source.<ext>`.
  - `POST /documents/{id}/versions` → membuat 3 file `storage/<id>/{publik,internal,rahasia}.<ext>` dan membalas `{"versions": ["publik","internal","rahasia"]}`
  - `GET /documents/{id}/versions/{version}` → mengirim file
  - Ekstensi selain `.pdf`/`.docx` → 415. File ditolak dengan `DocumentError` → 422 `{"detail": "Dokumen terenkripsi atau rusak. Buka kunci atau simpan ulang file, lalu upload lagi."}`. ID tidak dikenal → 404.

(Pembatasan akses per peran untuk versi Rahasia ada di Rencana 2. Di sini API belum diekspos ke jaringan.)

- [ ] **Step 1: Tes gagal** — pakai `TestClient` dan `FakeNer`. Tes: upload PDF contoh → label `rahasia`; buat versi → unduh publik, NIK tidak ada; upload `.txt` → 415; upload PDF terenkripsi → 422 dengan pesan di atas; `GET` id palsu → 404.
- [ ] **Step 2–4:** FAIL → tulis → PASS.
- [ ] **Step 5:** `git commit -m "feat: document API"`

### Task 9: Verifikasi ujung-ke-ujung + README

**Files:**
- Create: `backend/README.md` (cara pasang Tesseract `ind`, mengunduh model IndoBERT ke folder lokal satu kali, `DIGITADLP_NER_PATH`, `uvicorn digitadlp.api:app`)
- Create: `backend/digitadlp/__main__.py` (`app = create_app(IndoBertNer(env), EmployeeDirectory.from_xlsx(env), Path(env))`)

- [ ] **Step 1:** `cd backend && pytest -v` → semua PASS. Tes yang butuh model atau Tesseract boleh di-skip, tapi nama tesnya ditulis di catatan commit.
- [ ] **Step 2:** Jalankan server. Upload PDF contoh dengan `curl`, lalu unduh versi publik. Cek dengan `python -c "import fitz;print(fitz.open('publik.pdf')[0].get_text())"`, dan pastikan tidak ada NIK di hasilnya.
- [ ] **Step 3:** `git commit -m "docs: backend setup and run instructions"`
