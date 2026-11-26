# Satu Peran Pengguna & Tanpa NER — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ganti peran Pengunggah dan Pemeriksa dengan satu peran Pengguna yang bertanggung jawab atas dokumennya sendiri. Hapus model IndoBERT. Nama disensor manual, dan alamat dideteksi dengan pola.

**Architecture:** Deteksi menjadi murni pola (`detect(text)`). Konsep `Engine`, NER, dan daftar pegawai dihapus dari aplikasi. Alur dokumen memakai aturan "hanya pemilik", ditambah Admin sebagai cadangan untuk rilis. Migrasi Alembic 0004 hanya memindahkan data peran dan status. Frontend dan Docker menyesuaikan.

**Tech Stack:** Tetap (FastAPI, SQLAlchemy/Alembic, React/Vite, Docker). Dependensi `transformers` dan `torch` dihapus.

**Spec:** `docs/superpowers/specs/2026-11-26-satu-peran-tanpa-ner-design.md`

## Global Constraints

- Peran hanya `pengguna` dan `admin`.
- Hanya pemilik dokumen yang boleh: ubah label, tambah/abaikan temuan, Buat versi, unggah ulang. Rilis: pemilik atau Admin.
- Admin tidak bisa mengunggah. Admin tidak otomatis bisa melihat temuan atau versi Rahasia unit lain.
- Temuan dan teks dokumen hanya untuk unit pemilik. Versi Rahasia hanya untuk unit pemilik.
- Status `dikembalikan` dan aksi "kembalikan" dihapus. Dokumen lama `dikembalikan` → `menunggu_cek`.
- Tidak ada deteksi nama otomatis. Kind `NAME_EMPLOYEE` dan `Strength.EMPLOYEE` tetap ada untuk data lama, tetapi tidak bisa dipilih di UI.
- Pilihan tandai manual untuk nama berlabel "Nama orang" (Kind `NAME_CITIZEN`).
- Temuan dan koreksi tersimpan tidak diubah oleh migrasi.
- Migrasi 0004 hanya data, tanpa downgrade.
- Tidak ada `torch`/`transformers` di dependensi maupun image Docker. Variabel `DIGITADLP_NER_PATH` dan `DIGITADLP_NER` dihapus.
- Semua teks UI dan error dalam bahasa Indonesia.

## Review Focus

1. Akun lama berperan `pemeriksa`/`pengunggah` masuk setelah upgrade → berhasil sebagai Pengguna, dan dokumennya masih ada. Tes di Task 3.
2. Rekan satu unit membuka dokumen orang lain → bisa melihat, tetapi tombol aksi tidak ada dan API membalas 403. Tes di Task 3 dan Task 4.
3. Teks "Rapat di Kota Bontang" atau "Gedung Auditorium" → tidak ditandai sebagai alamat. Tes di Task 1.
4. Dokumen lama yang disetujui dengan temuan `NAME_EMPLOYEE`/`source="ner"` → tetap bisa diunduh, dan halaman cek tidak crash. Tes di Task 3 dan Task 4.
5. Pemilik nonaktif dengan dokumen `disetujui` → Admin masih bisa merilis. Tes di Task 3.

---

### Task 1: Deteksi alamat dengan pola, hapus NER dari mesin

**Files:**
- Modify: `backend/digitadlp/detect/patterns.py`, `backend/digitadlp/detect/pipeline.py`, `backend/pyproject.toml` (hapus extra `ner`)
- Delete: `backend/digitadlp/detect/ner.py`, `backend/digitadlp/detect/employees.py`, `backend/scripts/eval_ner.py`, `backend/tests/test_ner.py`, `backend/tests/test_employees.py`
- Test: `backend/tests/test_patterns.py`, `backend/tests/test_pipeline.py`. Tes Rencana 1 yang memakai `FakeNer`/`EmployeeDirectory` disesuaikan ke `detect(text)`, termasuk `test_redact_pdf.py` dan `test_redact_docx.py`. Penyesuaian ini tidak boleh melemahkan assertion: nama di fixture lama ditandai lewat temuan manual (`Finding(Kind.NAME_CITIZEN, …, source="manual")`) bila tesnya butuh nama tersensor.

**Interfaces:**
- Produces:
  - `find_patterns(text)` juga menghasilkan `Kind.ADDRESS` dengan `source="regex"`.
  - `detect(text: str) -> list[Finding]` di `pipeline.py`. Isinya pola saja, dengan resolusi tumpang tindih yang sama (union span, pemenang menurut kekuatan).

Aturan alamat:
- Dimulai dari kata penanda `Jl.|Jln.?|Jalan|Gg.|Gang|Perumahan|Perum|Komplek|Kompleks|Blok` (tanpa membedakan huruf besar/kecil, batas kata).
- Kata penanda diikuti token-token sampai bertemu koma yang diikuti kata selain RT/RW/No/Nomor/Blok, titik akhir kalimat (titik + spasi + huruf kapital, atau akhir teks), atau akhir baris.
- Token RT/RW/No./Nomor/angka/Blok ikut masuk span.
- "Kelurahan|Kel.|Desa X…" yang mengikuti dengan jarak ≤ 3 karakter (", " atau spasi) ikut digabung ke span yang sama atau menjadi temuan ADDRESS terpisah.
- Kelurahan atau desa yang berdiri sendiri tidak ditandai.

- [ ] **Step 1: Tes gagal**, di `test_patterns.py`:
```python
@pytest.mark.parametrize("text,addr", [
  ("alamat Jl. Pupuk Raya RT 12 No. 8, Kelurahan Gunung Elai.", ["Jl. Pupuk Raya RT 12 No. 8", "Kelurahan Gunung Elai"]),
  ("tinggal di Jalan Mulawarman Nomor 21 Bontang.", ["Jalan Mulawarman Nomor 21 Bontang"]),
  ("warga Perumahan Bukit Sekatup Damai Blok C2, mengajukan", ["Perumahan Bukit Sekatup Damai Blok C2"]),
  ("di Gang Kenari II RT 05 Kelurahan Api-Api.", ["Gang Kenari II RT 05", "Kelurahan Api-Api"]),
  ("terletak di Jl. KS Tubun, Kelurahan Bontang Baru.", ["Jl. KS Tubun", "Kelurahan Bontang Baru"]),
])
def test_address_patterns(text, addr): ...  # setiap item addr tercakup oleh satu temuan ADDRESS (substring dari f.text)

@pytest.mark.parametrize("text", ["Rapat di Kota Bontang.", "di Gedung Auditorium Taman 3 Dimensi", "Kantor di Kelurahan Api-Api.", "Jalan-jalan sore"])
def test_not_address(text): assert not [f for f in find_patterns(text) if f.kind == Kind.ADDRESS]
```
  Ditambah `test_pipeline.py::test_detect_is_patterns_only` (`detect("Nama Siti Rahmawati NIK 6474015203880002")` → hanya `[NIK]`).
- [ ] **Step 2:** `cd backend && .venv/bin/pytest -q tests/test_patterns.py tests/test_pipeline.py` → FAIL.
- [ ] **Step 3:** Tulis pola dan `detect(text)`, hapus file NER/pegawai, lalu perbaiki import dan tes Rencana 1 yang tersisa di lapisan mesin (`detect/`, `redact/`, `policy.py`). Kode `app/` dibereskan di Task 2. Kalau `app/` masih memakai `detect(text, ner, directory)`, biarkan sementara rusak hanya bila tes `tests/app` dikecualikan dari langkah ini.
- [ ] **Step 4:** `.venv/bin/pytest -q tests --ignore=tests/app` → PASS.
- [ ] **Step 5:** `git commit -m "feat(detect): pattern-based addresses; drop NER and employee directory"`

### Task 2: Aplikasi tanpa Engine dan tanpa daftar pegawai

**Files:**
- Modify: `backend/digitadlp/app/processing.py`, `app/jobs.py`, `app/main.py`, `app/routes/admin.py`, `app/storage.py` (blob `employees.xlsx` tetap boleh ada, tetapi tidak dibaca), `app/audit.py` (aksi `impor_pegawai` tetap ada di daftar untuk audit lama)
- Test: `backend/tests/app/*` yang memakai Engine/FakeNer/pegawai

**Interfaces:**
- Consumes: `detect(text)` (Task 1).
- Produces:
  - `create_app(settings) -> FastAPI` (parameter `engine` dihapus).
  - `run_job(db, store, job, touch=None)` dan `run_pending(db_factory, store) -> int`. Parameter `engine` dihapus di semua fungsi proses.
  - Route `POST /api/admin/employees` dihapus → 404.

- [ ] **Step 1: Tes gagal**: `test_admin.py::test_employees_route_removed` (POST → 404), `test_app.py::test_create_app_without_engine` (`create_app(settings)` jalan tanpa env NER), `test_jobs.py::test_names_not_auto_detected` (PDF dengan "Siti Rahmawati" → tidak ada temuan nama setelah deteksi).
- [ ] **Step 2–4:** FAIL → tulis → `.venv/bin/pytest -q` PASS (seluruh suite).
- [ ] **Step 5:** `git commit -m "refactor(app): remove NER engine and employee import"`

### Task 3: Satu peran Pengguna, alur milik sendiri, migrasi 0004

**Files:**
- Modify: `app/models.py` (`Role`: `PENGGUNA="pengguna"`, `ADMIN`; `Status` tanpa `DIKEMBALIKAN`), `app/workflow.py`, `app/access.py`, `app/routes/documents.py`, `app/routes/admin.py` (validasi peran), `app/__main__.py`, `docker/bootstrap.py`
- Create: `backend/alembic/versions/0004_single_role.py`
- Test: `tests/app/test_workflow.py`, `test_access.py`, `test_admin.py`, `test_models.py`

**Interfaces:**
- Produces di `workflow.py`:
  - `_owner(user, doc)` → 403 `"Hanya pemilik dokumen yang bisa melakukan tindakan ini."`
  - `upload`: role `pengguna`.
  - `set_label`, `add_correction`, `approve`: `_owner`.
  - `reupload`: `_owner`, dari status `menunggu_cek|gagal`.
  - `release`: pemilik atau Admin.
  - `return_to_owner` dihapus, termasuk route `POST /documents/{id}/return` (→ 404 atau 405) dan pesan `MSG_SELF`.
  - `return_reason` dibiarkan di kolom dan respons (nilai lama), tetapi tidak diisi lagi.
- `access.py`: semua `Role.PEMERIKSA` dihapus.
  - `can_view` = pemilik, atau unit yang sama.
  - `can_see_rahasia` = unit yang sama.
  - `can_download` publik saat `disetujui` = unit yang sama. Sisanya tetap.
- Migrasi 0004:
  - `UPDATE users SET role='pengguna' WHERE role IN ('pengunggah','pemeriksa')`
  - `UPDATE documents SET status='menunggu_cek' WHERE status='dikembalikan'`
  - `downgrade()` melempar `NotImplementedError("migrasi data satu arah")`.

- [ ] **Step 1: Tes gagal**:
  - `test_owner_can_approve_own_document`
  - `test_unit_mate_cannot_approve_or_correct` (403 dengan pesan di atas)
  - `test_unit_mate_can_view_and_download_internal`
  - `test_admin_can_release_when_owner_inactive`
  - `test_return_route_gone`
  - `test_migration_0004_maps_roles_and_status`: jalankan `alembic upgrade 0003`, sisipkan user `pemeriksa` dan dokumen `dikembalikan`, lalu `upgrade head`. Hasilnya `pengguna` dan `menunggu_cek`, dan user masih bisa login lewat API.
  - `test_legacy_name_employee_findings_still_download`: dokumen `disetujui` dengan `findings_json` berisi `NAME_EMPLOYEE` dan `source:"ner"` → unduh versi 200.
- [ ] **Step 2–4:** FAIL → tulis → seluruh suite PASS. Tes lama Pemeriksa diubah ke aturan pemilik, bukan dihapus diam-diam.
- [ ] **Step 5:** `git commit -m "feat(app): single Pengguna role, owner-only workflow, migration 0004"`

### Task 4: Frontend

**Files:**
- Modify: `frontend/src/api/types.ts` (Role `"pengguna"|"admin"`), `src/lib/labels.ts` (`NAME_CITIZEN` → "Nama orang"; hapus `dikembalikan` dari filter), `src/pages/Review.tsx`, `src/pages/Versions.tsx`, `src/pages/Dashboard.tsx`, `src/App.tsx`, `src/components/Layout*`, `src/pages/admin/Users.tsx` (pilihan peran), `src/pages/admin/LabelRules.tsx`
- Delete: `src/pages/admin/Employees.tsx` dan tesnya, beserta route `/admin/pegawai` dan tab-nya.
- Test: tes yang ada disesuaikan, ditambah tes baru di bawah.

**Interfaces:**
- Review:
  - Aksi muncul hanya bila `doc.owner_id === me.id`. Saat `menunggu_cek`: ubah label, abaikan, tandai manual, dan tombol **"Buat versi"**. Saat `disetujui`: abaikan dan tandai manual dengan peringatan yang sudah ada.
  - Pilihan jenis pada "Tandai manual" tidak memuat `NAME_EMPLOYEE`. "Nama orang" ada di urutan pertama.
  - Teks bantuan: "Nama tidak dideteksi otomatis. Tandai nama orang yang perlu disensor; semua kemunculan yang sama ikut tersensor."
  - Dialog "Kembalikan" dan tampilan alasan pengembalian dihapus. Kalau dokumen lama punya `return_reason`, cukup jangan ditampilkan.
- Versions: "Rilis versi Publik" muncul untuk pemilik atau admin saat `disetujui`.
- Dashboard dan nav: Unggah untuk `pengguna`. Teks kosong untuk admin diganti "Dokumen diunggah oleh akun Pengguna; buat akunnya di menu Admin → Pengguna."
- Users: pilihan peran "Pengguna" dan "Admin" saja.
- Label NAME_EMPLOYEE untuk temuan lama tetap ditampilkan ("Nama pegawai") supaya tidak crash.

- [ ] **Step 1: Tes gagal**:
  - `review: owner sees Buat versi; unit mate sees no actions`
  - `review: manual kinds exclude NAME_EMPLOYEE and start with Nama orang`
  - `review: legacy NAME_EMPLOYEE finding renders`
  - `versions: owner can release`
  - `users: role options are Pengguna and Admin`
  - `admin nav has no Pegawai`
- [ ] **Step 2–4:** `cd frontend && npx vitest run && npx tsc --noEmit && npm run build` → PASS.
- [ ] **Step 5:** `git commit -m "feat(web): single Pengguna role, owner actions, manual names"`

### Task 5: Docker, README, e2e

**Files:**
- Modify: `Dockerfile` (hapus stage `model`, instalasi `torch` index CPU, `HF_*`/`TRANSFORMERS_*` env, `DIGITADLP_NER_PATH`; install `.[postgres]`), `README.md`, `backend/README.md` (hapus bagian IndoBERT dan Pegawai, tambah keterbatasan alamat tanpa kata penanda), `.env.example` bila menyebut NER, `frontend/e2e/flow.spec.ts` dan `frontend/e2e/start-backend.sh` (satu pengguna mengunggah, menandai "Siti Rahmawati" manual, Buat versi, cek Publik tanpa NIK dan tanpa nama, Rilis)

- [ ] **Step 1:** Perbarui e2e. `cd frontend && npm run build && npx playwright test --trace off` → PASS.
- [ ] **Step 2:** Build image dengan argumen proxy container seperti uji sebelumnya. Ukuran image harus < 1.2 GB (`docker images digitadlp`). Jalankan `docker compose up -d --no-build`, tunggu status healthy, lalu jalankan skrip smoke: buat pengguna, unggah PDF berisi NIK dan "Siti Rahmawati", tandai manual nama, Buat versi. Versi Publik tidak boleh berisi NIK maupun nama.
- [ ] **Step 3:** `cd backend && .venv/bin/pytest -q` dan `cd frontend && npx vitest run` → hijau.
- [ ] **Step 4:** `git commit -m "chore(docker): drop NER model; docs and e2e for single role"`
