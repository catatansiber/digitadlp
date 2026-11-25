# DigitaDLP Rencana 2: Akun, Alur Persetujuan, Akses & Audit — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Menjadikan mesin Rencana 1 aplikasi multi-pengguna yang aman. Isinya: akun lokal dengan peran dan unit kerja, alur upload → cek → setuju → rilis, hak akses per versi, jejak audit, antrean kerja di latar belakang, dan file terenkripsi.

**Architecture:** Paket baru `digitadlp/app/` di atas mesin yang sudah ada (`detect`, `policy`, `redact`). Mesin tidak diubah kecuali dua titik kecil: aturan label bisa dikonfigurasi, dan temuan bisa dikoreksi pemeriksa. Data disimpan lewat SQLAlchemy 2 (PostgreSQL di produksi, SQLite untuk tes). Antrean kerja memakai tabel `jobs` dan thread worker, tanpa Redis, supaya pemasangan on-premise sederhana. File disimpan terenkripsi dengan Fernet. API lama di `digitadlp/api.py` diganti oleh `digitadlp/app/main.py`.

**Tech Stack:** FastAPI, SQLAlchemy 2.x, Alembic, `argon2-cffi`, `cryptography` (Fernet), psycopg 3 (produksi), pytest + httpx.

**Spec:** `docs/superpowers/specs/2026-11-24-digitadlp-design.md` (rencana sebelumnya: `docs/superpowers/plans/2026-11-24-engine-deteksi-sensor.md`)

## Global Constraints

- Semua proses tetap on-premise; tidak ada panggilan ke layanan luar.
- Peran: `pengunggah`, `pemeriksa`, `admin`. Setiap pengguna punya satu unit kerja.
- Login akun lokal; password di-hash (argon2id); dikelola Admin.
- Versi Publik wajib disetujui Pemeriksa sebelum rilis. Pemeriksa tidak boleh menyetujui upload sendiri.
- Kalau sumber atau temuan diubah setelah disetujui, persetujuan batal.
- Akses versi Rahasia: pegawai di unit kerja pemilik dokumen + Pemeriksa. Tiap akses dicatat.
- Audit mencatat siapa, aksi, dokumen, waktu. Isi audit tidak boleh memuat data pribadi dari dokumen.
- File sumber dan versi disimpan terenkripsi di disk.
- Pesan error dalam bahasa Indonesia, tanpa data pribadi.

## Review Focus

1. Pengguna unit lain mencoba unduh versi Rahasia atau Internal sebelum disetujui → 403, dan percobaan tercatat di audit. Tes di Task 7.
2. Pemeriksa menyetujui dokumen yang ia upload sendiri → 403. Tes di Task 6.
3. Temuan diubah setelah disetujui → status kembali ke `menunggu_cek`, dan versi lama tidak bisa diunduh. Tes di Task 6.
4. Worker mati di tengah job → job yang `berjalan` lebih dari 30 menit diambil ulang, dan tidak ada versi setengah jadi. Tes di Task 5.
5. File di disk dibuka langsung tanpa aplikasi → tidak ada teks NIK yang terbaca. Tes di Task 3.

---

## Struktur file

```
backend/digitadlp/
  policy.py               # Modify: suggest_label(findings, rules=None)
  app/
    __init__.py
    config.py             # Settings dari env
    db.py                 # engine, SessionLocal, Base, get_db
    models.py             # Unit, User, AuthSession, Document, Correction, Job, AuditEvent, LabelRule
    security.py           # hash/verify password, token sesi, current_user, require_role
    storage.py            # FileStore terenkripsi
    audit.py              # record()
    corrections.py        # terapkan koreksi pemeriksa ke temuan
    jobs.py               # enqueue, claim, worker loop
    processing.py         # job "deteksi" dan "versi" memanggil mesin
    workflow.py           # transisi status + aturan
    access.py             # can_download(user, doc, version)
    routes/auth.py, routes/documents.py, routes/admin.py
    main.py               # create_app(settings, ner, directory)
  alembic/ + alembic.ini
backend/tests/app/        # tes Rencana 2
```

Hapus `backend/digitadlp/api.py` dan `backend/tests/test_api.py` di Task 8. Kasus tesnya dipindah ke tes baru.

---

### Task 1: Basis data + model

**Files:**
- Create: `app/__init__.py`, `app/config.py`, `app/db.py`, `app/models.py`, `alembic.ini`, `alembic/env.py`, `alembic/versions/0001_initial.py`
- Modify: `backend/pyproject.toml` (sqlalchemy>=2, alembic, argon2-cffi, cryptography; extra `postgres` = psycopg[binary])
- Test: `tests/app/conftest.py` (fixture `db` = SQLite in-memory + `Base.metadata.create_all`), `tests/app/test_models.py`

**Interfaces:**
- Produces:
  - `Settings` (pydantic-settings atau dataclass dari env): `database_url` (default `sqlite:///./digitadlp.db`), `storage_dir`, `fernet_key` (wajib), `session_hours=8`, `job_stale_minutes=30`
  - Model (UUID hex string 32 sebagai PK, `created_at` UTC):
    - `Unit(id, name unique)`
    - `User(id, username unique, password_hash, full_name, role: Role, unit_id FK, active: bool)`; `class Role(StrEnum): PENGUNGGAH="pengunggah", PEMERIKSA="pemeriksa", ADMIN="admin"`
    - `AuthSession(token_hash PK, user_id, expires_at)`
    - `Document(id, title, ext, owner_id, unit_id, status: Status, suggested_label, label, reviewer_id nullable, approved_at nullable, released_at nullable, findings_json, revision: int)`. Status berupa `class Status(StrEnum)`: `DIPROSES="diproses"`, `MENUNGGU_CEK="menunggu_cek"`, `DIKEMBALIKAN="dikembalikan"`, `MEMBUAT_VERSI="membuat_versi"`, `DISETUJUI="disetujui"`, `DIRILIS="dirilis"`, `GAGAL="gagal"`.
    - `Correction(id, document_id, kind, page: int|None, text, op: "tambah"|"abaikan", author_id)`
    - `Job(id, kind: "deteksi"|"versi", document_id, revision, state: "antri"|"berjalan"|"selesai"|"gagal", claimed_at, error_code)`
    - `AuditEvent(id, at, actor_id nullable, action, document_id nullable, detail: str)`
    - `LabelRule(kind PK, label)`

- [ ] **Step 1: Tes gagal**: `test_create_user_with_unit` (simpan dan baca ulang, `role == Role.PEMERIKSA`), `test_username_unique` (IntegrityError), dan `test_alembic_upgrade_head` (jalankan `alembic upgrade head` ke SQLite file di `tmp_path`, lalu periksa semua tabel ada).
- [ ] **Step 2:** `cd backend && .venv/bin/pytest tests/app/test_models.py -v` → FAIL.
- [ ] **Step 3:** Tulis config, db, models, migrasi 0001.
- [ ] **Step 4:** → PASS.
- [ ] **Step 5:** `git commit -m "feat(app): database models and initial migration"`

### Task 2: Login, sesi, peran

**Files:**
- Create: `app/security.py`, `app/routes/auth.py`, `app/main.py` (kerangka `create_app` dengan router auth saja)
- Test: `tests/app/test_auth.py`

**Interfaces:**
- Produces:
  - `hash_password(pw) -> str`, `verify_password(pw, h) -> bool` (argon2id)
  - `create_session(db, user) -> str` → token acak 32 byte (`secrets.token_urlsafe`). Yang disimpan di DB hanya `sha256(token)`.
  - Dependency `current_user(request, db) -> User`: membaca cookie `digitadlp_session` (HttpOnly, SameSite=Strict, Secure jika `settings.cookie_secure`). Sesi kedaluwarsa, sesi tidak ada, atau user `active=False` → 401 `"Sesi berakhir. Silakan masuk lagi."`
  - `require_role(*roles)` → 403 `"Anda tidak punya akses untuk tindakan ini."`
  - `POST /auth/login {username, password}` → 200 `{id, full_name, role, unit}`, set cookie. Kalau salah → 401 `"Nama pengguna atau kata sandi salah."` (pesan sama untuk user tidak ada). Lima kali gagal berturut-turut untuk username yang sama dalam 15 menit → 429 `"Terlalu banyak percobaan. Coba lagi dalam 15 menit."`
  - `POST /auth/logout` → hapus sesi. `GET /auth/me`.
  - CLI `python -m digitadlp.app create-admin --username U --unit "Nama Unit"`: membaca password dari prompt (getpass), membuat unit jika belum ada.

- [ ] **Step 1: Tes gagal**: `test_login_ok_sets_httponly_cookie`, `test_wrong_password_same_message_as_unknown_user`, `test_expired_session_401` (geser `expires_at` ke masa lalu), `test_inactive_user_401`, `test_lockout_after_5_failures`, `test_require_role_403`, `test_token_not_stored_plain` (kolom `token_hash` ≠ token di cookie), `test_create_admin_cli` (monkeypatch getpass).
- [ ] **Step 2–4:** FAIL → tulis → PASS.
- [ ] **Step 5:** `git commit -m "feat(app): local accounts, sessions and roles"`

### Task 3: Penyimpanan file terenkripsi

**Files:**
- Create: `app/storage.py`
- Test: `tests/app/test_storage.py`

**Interfaces:**
- Produces: `class FileStore`, dengan konstruktor `__init__(root: Path, fernet_key: str)` dan method berikut:
  - `put(doc_id: str, name: str, data: bytes) -> None`. Atomik: tulis ke file sementara lalu `os.replace`.
  - `get(doc_id, name) -> bytes`
  - `exists(doc_id, name) -> bool`
  - `delete_versions(doc_id) -> None`: menghapus `publik.*`, `internal.*`, `rahasia.*`
  - `decrypted(doc_id, name) -> ContextManager[Path]`: file sementara terdekripsi di `root/.tmp/`, mode 0600, dihapus saat keluar meski ada error. Dipakai karena mesin redaksi butuh path file.
  - `name` hanya boleh `source.pdf|source.docx|{publik,internal,rahasia}.{pdf,docx}`. Selain itu → `ValueError`. `doc_id` harus 32 hex.

- [ ] **Step 1: Tes gagal**: `test_roundtrip`, `test_on_disk_is_not_plaintext` (byte NIK `b"6474015203880002"` tidak ada di file di disk), `test_bad_name_rejected` (`"../x"`, `"source.txt"`), `test_decrypted_tempfile_removed_on_error`, `test_wrong_key_raises`.
- [ ] **Step 2–4:** FAIL → tulis → PASS.
- [ ] **Step 5:** `git commit -m "feat(app): encrypted file store"`

### Task 4: Audit + aturan label + koreksi pemeriksa

**Files:**
- Create: `app/audit.py`, `app/corrections.py`
- Modify: `digitadlp/policy.py` (`suggest_label(findings, rules: Mapping[Kind, Label] | None = None)`)
- Test: `tests/app/test_audit.py`, `tests/app/test_corrections.py`, `tests/test_policy.py` (tambah kasus)

**Interfaces:**
- Produces:
  - `record(db, actor: User | None, action: str, document: Document | None = None, detail: str = "") -> AuditEvent`. Nilai `action` yang sah: `masuk, gagal_masuk, keluar, upload, deteksi_selesai, ubah_label, koreksi, setujui, kembalikan, rilis, unduh, akses_ditolak, user_dibuat, user_diubah, impor_pegawai, aturan_label`. `detail` maksimal 200 karakter. Sebelum disimpan, `detail` dilewatkan ke `find_patterns`; kalau ada temuan → `ValueError` (audit tidak boleh memuat data pribadi).
  - `suggest_label(findings, rules)`: kalau `rules` diberikan, label = label tertinggi (`RAHASIA > INTERNAL > PUBLIK`) dari `rules[f.kind]` untuk semua temuan. Kind yang tidak ada di `rules` memakai aturan bawaan. Tanpa `rules`, perilakunya sama persis dengan sekarang.
  - `apply_corrections(findings_per_page: list[list[Finding]], corrections: list[Correction]) -> list[list[Finding]]`:
    - `abaikan` menghapus temuan dengan `text` sama (dibandingkan setelah spasi dirapikan) di halaman itu, atau di semua halaman jika `page is None`.
    - `tambah` menambah `Finding(kind, start=-1, end=-1, text, source="manual")`. Offset -1 aman karena redaksi PDF mencari teks, bukan offset.
  - `corrected_detect_fn(detect_fn, corrections) -> Callable[[str], list[Finding]]`, untuk DOCX:
    - `abaikan` membuang temuan dengan teks sama.
    - `tambah` menambahkan setiap kemunculan teks itu di string masukan sebagai `Finding` dengan offset nyata.

- [ ] **Step 1: Tes gagal**: `test_record_rejects_pii_in_detail` ("NIK 6474015203880002" → ValueError), `test_record_ok`, `test_rules_override_label` (rules `{PHONE: RAHASIA}` → `[phone]` jadi RAHASIA), `test_default_unchanged`, `test_ignore_removes_finding`, `test_add_manual_pdf`, `test_corrected_detect_fn_adds_offsets` ("Bu Rina tinggal di sini", tambah "Bu Rina" → start 0, end 7).
- [ ] **Step 2–4:** FAIL → tulis → PASS (seluruh suite Rencana 1 tetap hijau).
- [ ] **Step 5:** `git commit -m "feat(app): audit log, configurable label rules, reviewer corrections"`

### Task 5: Antrean kerja + pemrosesan

**Files:**
- Create: `app/jobs.py`, `app/processing.py`
- Test: `tests/app/test_jobs.py`

**Interfaces:**
- Consumes: `FileStore.decrypted`, `extract_pdf_text`, `extract_pdf_extras`, `detect_docx`, `redact_pdf`, `redact_docx`, `apply_corrections`, `corrected_detect_fn`, `suggest_label`, `record`
- Produces:
  - `enqueue(db, kind, document) -> Job`, berisi `revision = document.revision`
  - `claim(db, stale_minutes) -> Job | None`. Mengambil satu job `antri`, atau job `berjalan` yang `claimed_at` lebih tua dari `stale_minutes`. Di PostgreSQL memakai `SELECT … FOR UPDATE SKIP LOCKED`. Di SQLite memakai UPDATE bersyarat dan memeriksa rowcount.
  - `run_job(db, store, engine: Engine, job) -> None`, dengan `@dataclass Engine(ner: NerDetector, directory: EmployeeDirectory)`:
    - `deteksi`: hitung temuan per halaman, simpan ke `findings_json` (list per halaman berisi `{kind, text, page, start, end, source}`), set `suggested_label` dan `label`, status `MENUNGGU_CEK`, catat audit `deteksi_selesai`.
    - `versi`: hapus versi lama, buat ketiga versi ke direktori sementara, enkripsi dan simpan semuanya, lalu status `DISETUJUI`.
    - Job yang `revision`-nya ≠ `document.revision` saat dijalankan ditandai `selesai` tanpa efek (job basi).
    - `DocumentError` → job `gagal`, `error_code="dokumen_rusak"`, dokumen `GAGAL`. Exception lain → job `gagal`, `error_code="galat_internal"`, dan traceback di-log tanpa isi dokumen.
  - `Worker(session_factory, store, engine, settings).start()/stop()`: thread daemon, polling setiap 1 detik.

- [ ] **Step 1: Tes gagal**:
  - `test_deteksi_sets_findings_and_label` (PDF contoh dari fixture Rencana 1, FakeNer) → status `menunggu_cek`, label `rahasia`.
  - `test_versi_creates_three_encrypted_files`.
  - `test_stale_running_job_reclaimed` (`claimed_at` 31 menit lalu → `claim` mengembalikannya).
  - `test_fresh_running_job_not_reclaimed`.
  - `test_outdated_revision_job_noop`.
  - `test_document_error_marks_gagal`, dan tidak ada file versi tersisa.
  - `test_findings_json_not_in_audit`.
- [ ] **Step 2–4:** FAIL → tulis → PASS.
- [ ] **Step 5:** `git commit -m "feat(app): DB-backed job queue and processing"`

### Task 6: Alur dokumen (workflow)

**Files:**
- Create: `app/workflow.py`, `app/routes/documents.py` (bagian alur)
- Test: `tests/app/test_workflow.py`

**Interfaces:**
- Produces fungsi di `workflow.py`. Semuanya memanggil `record` dan melempar `WorkflowError(http_status, pesan)`.
  - `upload(db, store, user, filename, data) -> Document`. Ekstensi harus `.pdf`/`.docx` (415). Ukuran maksimal 50 MB (413). Lalu simpan source, status `DIPROSES`, dan enqueue `deteksi`. Hanya untuk role pengunggah atau pemeriksa. Admin tidak mengunggah.
  - `set_label(db, user, doc, label)`: hanya pemeriksa, status `MENUNGGU_CEK`.
  - `add_correction(db, user, doc, op, kind, text, page)`: hanya pemeriksa, status `MENUNGGU_CEK` atau `DISETUJUI`. Langkahnya: `revision += 1`, hapus versi, `approved_at = None`, status kembali ke `MENUNGGU_CEK`, terapkan koreksi ke `findings_json`, hitung ulang `suggested_label` dengan aturan aktif. Label pilihan pemeriksa tidak ditimpa.
  - `approve(db, user, doc)`: hanya pemeriksa, status `MENUNGGU_CEK`. `doc.owner_id == user.id` → 403 `"Pemeriksa tidak boleh menyetujui dokumen yang ia upload sendiri."` Selain itu set `reviewer_id`, `approved_at`, status `MEMBUAT_VERSI`, lalu enqueue `versi`.
  - `return_to_owner(db, user, doc, reason)`: status `DIKEMBALIKAN`. `reason` diperiksa seperti audit `detail`.
  - `reupload(db, store, user, doc, filename, data)`: hanya pemilik, status `DIKEMBALIKAN` atau `GAGAL`. Langkahnya: `revision += 1`, ganti source, hapus koreksi dan versi, status `DIPROSES`, enqueue `deteksi`.
  - `release(db, user, doc)`: pemeriksa atau admin, status `DISETUJUI` → `DIRILIS`.
  - Transisi lain → 409 `"Dokumen sedang berstatus <status>; tindakan ini tidak bisa dilakukan."`
- Routes: `POST /documents` (multipart), `GET /documents` (lihat Task 7 untuk filter), `GET /documents/{id}` (termasuk `findings` dan `corrections`, hanya untuk yang boleh melihat versi Rahasia), `PUT /documents/{id}/label`, `POST /documents/{id}/corrections`, `POST /documents/{id}/approve`, `POST /documents/{id}/return`, `POST /documents/{id}/reupload`, `POST /documents/{id}/release`.

- [ ] **Step 1: Tes gagal** (fixture `client_as(role, unit)`, worker dijalankan sinkron lewat `run_pending(db)` di tes):
  - `test_full_flow`: upload → deteksi → approve oleh pemeriksa lain → versi → release → status `dirilis`.
  - `test_self_approval_403`.
  - `test_correction_after_approval_resets`: versi terhapus, status `menunggu_cek`, `revision` naik.
  - `test_ignore_correction_keeps_text_in_publik`.
  - `test_manual_add_redacted_in_publik`: "Bu Rina" tidak ada di teks versi Publik.
  - `test_return_and_reupload`.
  - `test_wrong_state_409`.
  - `test_admin_cannot_upload`.
  - `test_reason_with_pii_rejected`.
- [ ] **Step 2–4:** FAIL → tulis → PASS.
- [ ] **Step 5:** `git commit -m "feat(app): document approval workflow"`

### Task 7: Hak akses unduh + daftar dokumen

**Files:**
- Create: `app/access.py`
- Modify: `app/routes/documents.py` (`GET /documents`, `GET /documents/{id}/versions/{version}`)
- Test: `tests/app/test_access.py`

**Interfaces:**
- Produces: `can_download(user, doc, version) -> bool`:
  - `publik`: semua user aktif jika status `DIRILIS`; pemilik, pemeriksa, dan unit pemilik jika status `DISETUJUI`.
  - `internal`: semua user aktif jika status `DISETUJUI`/`DIRILIS`.
  - `rahasia`: (`user.unit_id == doc.unit_id` atau role `pemeriksa`), dan status `DISETUJUI`/`DIRILIS`.
  - `admin` tidak otomatis boleh membuka versi Rahasia. Admin hanya boleh membukanya kalau ia satu unit dengan dokumen.
- Unduh: versi tidak ada → 404. Ditolak → 403 `"Anda tidak punya akses ke versi ini."` dan audit `akses_ditolak`. Sukses → audit `unduh` dengan `detail=version`. Respons `Content-Disposition: attachment; filename="<id>-<version>.<ext>"` (judul asli tidak dipakai), `Cache-Control: no-store`.
- `GET /documents?status=&mine=`: pengunggah melihat dokumen unitnya. Pemeriksa dan admin melihat semua. Respons tanpa `findings`.

- [ ] **Step 1: Tes gagal**: buat matriks parametrize (role × unit sama/beda × versi × status) yang mengharapkan 200/403 sesuai aturan di atas. Ditambah `test_denied_is_audited`, `test_download_audited`, `test_admin_other_unit_rahasia_403`, `test_no_store_header`.
- [ ] **Step 2–4:** FAIL → tulis → PASS.
- [ ] **Step 5:** `git commit -m "feat(app): per-version download access control"`

### Task 8: Admin + perakitan aplikasi + hapus API lama

**Files:**
- Create: `app/routes/admin.py`
- Modify: `app/main.py` (rakit semua router; worker dijalankan saat startup jika `settings.run_worker`), `digitadlp/__main__.py` (jalankan `digitadlp.app.main:app`), `backend/README.md`
- Delete: `digitadlp/api.py`, `tests/test_api.py`
- Test: `tests/app/test_admin.py`, `tests/app/test_e2e.py`

**Interfaces:**
- Produces (semua hanya untuk role `admin`, dan semua diaudit):
  - `GET/POST /admin/units`
  - `GET/POST /admin/users`: password awal minimal 10 karakter.
  - `PATCH /admin/users/{id}`: ubah role, unit, active, atau reset password. Menonaktifkan user menghapus semua sesinya.
  - `POST /admin/employees` (multipart xlsx): simpan file terenkripsi sebagai daftar pegawai aktif, lalu muat ulang `EmployeeDirectory` milik `Engine` tanpa restart.
  - `GET/PUT /admin/label-rules`: `{kind: label}` untuk setiap `Kind`, berlaku untuk deteksi berikutnya.
  - `GET /admin/audit?document_id=&actor_id=&limit=100`
- `create_app(settings, engine: Engine | None = None) -> FastAPI`. Tanpa `engine`, aplikasi membuat `IndoBertNer(DIGITADLP_NER_PATH)`. Jika `DIGITADLP_NER=fake`, aplikasi memakai `FakeNer({})` (khusus dev/test, seperti Rencana 1).

- [ ] **Step 1: Tes gagal**: `test_admin_crud_user`, `test_deactivate_kills_sessions`, `test_non_admin_403`, `test_employee_import_reloads_directory` (nama baru langsung dikenali sebagai pegawai di deteksi berikutnya), `test_label_rules_applied`. `test_e2e.py` memindahkan kasus `tests/test_api.py` (415, 413, 422 PDF terenkripsi, 404 id palsu, path traversal) ke API baru dengan login.
- [ ] **Step 2–4:** FAIL → tulis → PASS. Seluruh suite hijau.
- [ ] **Step 5:** README: tambahkan bagian PostgreSQL + `alembic upgrade head`, pembuatan `DIGITADLP_FERNET_KEY` (`python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())"`), `create-admin`, dan peringatan untuk mencadangkan kunci (kunci hilang = file tidak bisa dibuka).
- [ ] **Step 6:** Uji manual. Jalankan server dengan `DIGITADLP_NER=fake`, lalu lewat `curl` dengan cookie: login admin → buat unit dan dua user → upload sebagai pengunggah → setujui sebagai pemeriksa → unduh versi Publik → cek NIK tidak ada. Catat outputnya di laporan.
- [ ] **Step 7:** `git commit -m "feat(app): admin endpoints, app assembly; remove legacy API"`
