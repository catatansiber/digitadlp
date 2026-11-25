# DigitaDLP Rencana 3: Tampilan Web (React) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tampilan web untuk staf instansi, sesuai mockup yang sudah disetujui. Layarnya: login, beranda dokumen, upload, layar cek temuan, tiga versi, dan admin (pengguna, unit, daftar pegawai, aturan label, audit). Semua berjalan di atas API Rencana 2.

**Architecture:** Single-page app (Vite + React + TypeScript) di folder `frontend/`. Hasil build disajikan oleh FastAPI dari origin yang sama, supaya cookie `SameSite=Strict` tetap berfungsi dan tidak perlu CORS. Seluruh API dipindah ke prefix `/api`, dan path lain jatuh ke `index.html`. Data diambil lewat TanStack Query, dengan polling untuk status dokumen yang sedang diproses. Ada dua tambahan kecil di backend: endpoint teks dokumen untuk pratinjau, dan alasan pengembalian dokumen.

**Tech Stack:** Vite 5, React 18, TypeScript 5, React Router 6, TanStack Query 5, Vitest + Testing Library + MSW 2 (tes unit/komponen), Playwright (e2e terhadap backend asli dengan `DIGITADLP_NER=fake`). CSS biasa dengan token warna dari mockup, tanpa framework CSS.

**Spec:** `docs/superpowers/specs/2026-11-24-digitadlp-design.md`. Mockup: `docs/mockup/digitadlp-mockup.html`. API: `docs/superpowers/plans/2026-11-25-alur-kerja-akses.md`.

## Global Constraints

- Semua teks antarmuka dalam bahasa Indonesia.
- Tidak ada aset dari CDN atau layanan luar saat runtime: font, ikon, dan skrip dibundel (on-premise, mungkin tanpa internet).
- Warna dan tata letak mengikuti mockup: aksen teal `#0d5c63`, chip label Publik hijau, Internal oranye, Rahasia merah, serta tema terang dan gelap.
- Data pribadi tidak boleh disimpan di `localStorage`/`sessionStorage` dan tidak boleh di-log ke console.
- Tombol dan menu ditampilkan sesuai peran. Server tetap menjadi penentu akses, jadi UI harus menangani 401/403/404/409/413/415/422 dengan pesan `detail` dari server.
- Tidak ada `dangerouslySetInnerHTML`. Teks dokumen selalu dirender sebagai teks.
- Lebar ponsel (400px) tetap bisa dipakai, tanpa scroll horizontal di level halaman.

## Review Focus

1. Sesi berakhir di tengah kerja (API membalas 401) → pengguna diarahkan ke halaman login dengan pesan "Sesi berakhir. Silakan masuk lagi.", lalu kembali ke halaman semula setelah masuk. Tes di Task 2.
2. Teks dokumen berisi karakter HTML (`<script>`) → tampil sebagai teks biasa. Tes di Task 4.
3. Pemeriksa membuka dokumen unggahannya sendiri → tombol "Setujui" nonaktif dengan penjelasan. Kalau API tetap membalas 403, pesannya tampil. Tes di Task 4.
4. File lebih dari 50 MB atau berformat bukan PDF/DOCX → ditolak di browser sebelum upload, dengan pesan yang sama seperti pesan server. Tes di Task 3.
5. Temuan dengan `page=null` (bookmark, metadata) → tampil di grup "Di luar halaman", tidak hilang dan tidak menyebabkan crash. Tes di Task 4.

---

## Struktur file

```
backend/digitadlp/app/main.py             # Modify: prefix /api, sajikan frontend/dist + fallback SPA
backend/digitadlp/app/routes/documents.py # Modify: GET /documents/{id}/text, return_reason
backend/digitadlp/app/models.py + alembic/versions/0003_*.py
frontend/
  package.json, vite.config.ts, tsconfig.json, index.html, playwright.config.ts
  src/main.tsx, src/App.tsx, src/styles/tokens.css, src/styles/app.css
  src/api/client.ts        # fetch + ApiError
  src/api/types.ts         # tipe respons API
  src/api/hooks.ts         # hook TanStack Query
  src/auth/AuthProvider.tsx, src/auth/RequireRole.tsx
  src/components/          # Chip, StatusChip, Button, Dropzone, Table, Toast, EmptyState
  src/pages/Login.tsx, Dashboard.tsx, Upload.tsx, Review.tsx, Versions.tsx
  src/pages/admin/Users.tsx, Units.tsx, Employees.tsx, LabelRules.tsx, Audit.tsx
  src/lib/labels.ts        # teks Indonesia untuk Kind, Status, Label
  src/lib/highlight.ts     # pecah teks jadi segmen berdasarkan temuan
  src/test/                # setup Vitest + handler MSW
  e2e/flow.spec.ts
```

---

### Task 1: Penyesuaian backend untuk tampilan

**Files:**
- Modify: `backend/digitadlp/app/main.py`, `backend/digitadlp/app/routes/documents.py`, `backend/digitadlp/app/workflow.py`, `backend/digitadlp/app/models.py`
- Create: `backend/alembic/versions/0003_return_reason.py`
- Test: `backend/tests/app/test_frontend_support.py`. Tes lama yang masih memakai path tanpa `/api` juga diperbarui.

**Interfaces:**
- Produces:
  - Semua router di bawah `/api`: `/api/auth/*`, `/api/documents/*`, `/api/admin/*`.
  - `create_app(settings, engine)` menyajikan `settings.frontend_dir` (env `DIGITADLP_FRONTEND_DIR`, default `../frontend/dist` relatif ke paket) jika folder itu ada:
    - `/assets/*` disajikan sebagai file statis dengan `Cache-Control: public, max-age=31536000, immutable`.
    - Path non-`/api` lainnya membalas `index.html` dengan `Cache-Control: no-store`.
    - Path `/api/*` yang tidak dikenal tetap 404 JSON.
    - Header keamanan di semua respons: `Content-Security-Policy: default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; frame-ancestors 'none'`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`.
  - `GET /api/documents/{id}/text` → `{"pages": [str, ...]}`, teks sumber per halaman (PDF memakai `extract_pdf_text`, DOCX memakai `extract_docx_text` sebagai satu "halaman" per paragraf). Hak aksesnya sama dengan melihat temuan (`can_see_rahasia`); selain itu 404. Header `Cache-Control: no-store`, dan setiap akses diaudit dengan `action="unduh"` dan `detail="versi=teks"`.
  - Kolom `Document.return_reason` (nullable, maksimal 500 karakter). `return_to_owner` menyimpannya. Kolom ini dikosongkan saat `reupload`. Nilainya ikut di `GET /documents/{id}` hanya bila `detail=True` (pemeriksa atau unit pemilik). Audit tetap hanya mencatat `alasan_len`.
  - `GET /api/documents` dan `GET /api/documents/{id}` menyertakan `owner_name` dan `unit_name`.

- [ ] **Step 1: Tes gagal**: `test_api_prefix` (`/api/auth/me` 401, `/auth/me` tidak dikenal), `test_spa_fallback_serves_index` (folder dist palsu di `tmp_path`, `/dokumen/abc` → isi index.html), `test_unknown_api_404_json`, `test_security_headers`, `test_text_endpoint_access` (pemeriksa 200, unit lain 404), `test_text_endpoint_audited`, `test_return_reason_visible_to_owner_unit_only`, `test_reupload_clears_reason`.
- [ ] **Step 2–4:** FAIL → tulis → PASS (seluruh suite hijau).
- [ ] **Step 5:** `git commit -m "feat(app): /api prefix, SPA serving, document text and return reason"`

### Task 2: Kerangka frontend, klien API, login

**Files:**
- Create: `frontend/` (package.json, vite.config.ts dengan proxy `/api` ke `http://127.0.0.1:8000` saat dev, tsconfig strict), `src/main.tsx`, `src/App.tsx`, `src/styles/*`, `src/api/client.ts`, `src/api/types.ts`, `src/auth/*`, `src/pages/Login.tsx`, `src/components/{Button,Toast}.tsx`, `src/test/setup.ts`
- Test: `src/api/client.test.ts`, `src/auth/AuthProvider.test.tsx`, `src/pages/Login.test.tsx`

**Interfaces:**
- Produces:
  - `class ApiError extends Error { status: number; detail: string }`
  - `api<T>(path: string, init?: RequestInit): Promise<T>`:
    - Prefix `/api`, `credentials: "same-origin"`.
    - JSON in/out. Body `FormData` dikirim apa adanya.
    - Respons tidak ok → `ApiError` dengan `detail` dari body. Kalau body tidak bisa dibaca → "Terjadi kesalahan. Coba lagi."
  - `apiBlob(path): Promise<{blob: Blob, filename: string}>` untuk unduhan.
  - `AuthProvider`: memanggil `GET /api/auth/me` saat mulai. Menyediakan `useAuth(): {user: Me | null, loading, login(u,p), logout()}`, dengan tipe `type Me = {id, full_name, role: "pengunggah"|"pemeriksa"|"admin", unit: string}` (sesuaikan dengan respons asli `/auth/me`).
  - Handler global: setiap `ApiError` 401 dari query → `user=null`, lalu navigasi ke `/masuk?kembali=<path>` dengan pesan sesi berakhir.
  - `RequireRole({roles, children})`: kalau peran tidak cocok, tampilkan "Anda tidak punya akses ke halaman ini."
  - Rute: `/masuk`, `/` (Beranda), `/upload`, `/dokumen/:id` (Cek temuan), `/dokumen/:id/versi`, `/admin/pengguna`, `/admin/unit`, `/admin/pegawai`, `/admin/aturan-label`, `/admin/audit`.
  - Layout atas: nama aplikasi "DigitaDLP", "Unit · Nama", tab menurut peran, tombol "Keluar".
  - Token di `tokens.css` disalin dari `:root` mockup (terang dan gelap).
  - Font memakai system stack (tanpa Google Fonts, sesuai batasan on-premise).

- [ ] **Step 1: Tes gagal** (Vitest + MSW):
  - `client throws ApiError with server detail`
  - `client fallback message on non-JSON error`
  - `login success shows dashboard`
  - `login 401 shows "Nama pengguna atau kata sandi salah."`
  - `429 message shown`
  - `401 during session redirects to /masuk?kembali=…`
  - `pengunggah does not see Admin tab`
  - `no localStorage writes` (spy `Storage.prototype.setItem`)
- [ ] **Step 2:** `cd frontend && npm install && npx vitest run` → FAIL.
- [ ] **Step 3:** Tulis.
- [ ] **Step 4:** `npx vitest run && npx tsc --noEmit && npm run build` → PASS.
- [ ] **Step 5:** Tambahkan `frontend/node_modules`, `frontend/dist`, `frontend/test-results` ke `.gitignore`. `git commit -m "feat(web): scaffold, API client, auth and login"`

### Task 3: Beranda + upload

**Files:**
- Create: `src/pages/Dashboard.tsx`, `src/pages/Upload.tsx`, `src/components/{Chip,StatusChip,Dropzone,Table,EmptyState}.tsx`, `src/lib/labels.ts`, `src/api/hooks.ts`
- Test: `src/pages/Dashboard.test.tsx`, `src/pages/Upload.test.tsx`, `src/lib/labels.test.ts`

**Interfaces:**
- Produces:
  - `labels.ts`:
    - `LABEL_TEXT = {publik:"Publik", internal:"Internal", rahasia:"Rahasia"}`
    - `STATUS_TEXT = {diproses:"Diproses", menunggu_cek:"Menunggu cek", dikembalikan:"Dikembalikan", membuat_versi:"Membuat versi…", disetujui:"Disetujui", dirilis:"Dirilis", gagal:"Gagal diproses"}`
    - `KIND_TEXT` untuk 11 Kind: NIK, No. KK, NPWP, No. HP, Email, No. rekening, Nama warga, Nama pegawai, NIP, Alamat, Tanggal lahir.
  - Hook `useDocuments(filter)`: polling setiap 5 detik selama ada dokumen berstatus `diproses` atau `membuat_versi`, dan berhenti kalau tidak ada.
  - Beranda:
    - Kotak ringkasan (Menunggu cek, Disetujui, Dirilis, Gagal), dihitung dari daftar.
    - Tabel: judul, saran label (chip), status (chip), pemilik, unit, tanggal (format `id-ID`).
    - Klik baris membuka `/dokumen/:id`.
    - Filter status dan "Hanya milik saya".
    - Keadaan kosong: "Belum ada dokumen. Upload dokumen pertama." Tombol upload hanya untuk pengunggah dan pemeriksa.
  - Upload:
    - Dropzone dan input file. Sebelum dikirim, file dicek: ekstensi `.pdf`/`.docx`, ukuran maksimal 50 MB, file tidak kosong. Pesannya sama persis dengan server ("Ukuran file melebihi batas 50 MB.", dan seterusnya; salin pesan dari `workflow.py`).
    - Progres upload, lalu redirect ke `/dokumen/:id`.
    - Teks bantuan: "File diproses di server instansi. Tidak dikirim ke layanan luar."

- [ ] **Step 1: Tes gagal**:
  - `dashboard lists docs with chips`
  - `polls while diproses, stops when done` (fake timers)
  - `empty state`
  - `upload rejects .txt client-side without request`
  - `upload rejects 51MB client-side`
  - `upload success navigates to review`
  - `server 422 detail shown`
- [ ] **Step 2–4:** FAIL → tulis → PASS (`vitest`, `tsc`, `build`).
- [ ] **Step 5:** `git commit -m "feat(web): dashboard and upload"`

### Task 4: Layar cek temuan

**Files:**
- Create: `src/pages/Review.tsx`, `src/lib/highlight.ts`, `src/components/FindingList.tsx`, `src/components/DocText.tsx`
- Test: `src/lib/highlight.test.ts`, `src/pages/Review.test.tsx`

**Interfaces:**
- Consumes: `GET /api/documents/{id}`, `GET /api/documents/{id}/text`, `PUT …/label`, `POST …/corrections`, `POST …/approve`, `POST …/return`, `POST …/reupload`
- Produces:
  - `segments(text: string, marks: {text: string, kind: string}[]) -> {text: string, kind?: string}[]`. Fungsi ini mencari setiap `mark.text` (tanpa membedakan huruf besar/kecil, semua kemunculan). Kalau ada yang tumpang tindih, yang lebih panjang menang. Segmen yang dihasilkan menutup seluruh teks tanpa celah. Data posisi dari server tidak dipakai, karena koreksi manual memakai -1.
  - `DocText`: halaman sebagai blok `<p>`. Temuan dirender sebagai `<mark>` dengan warna menurut kekuatan: merah untuk NIK, KK, rekening, NPWP; oranye untuk lainnya; hijau untuk nama pegawai. Semua teks dirender sebagai child React, tidak sebagai HTML.
  - Panel kanan:
    - Kotak saran label beserta alasannya, misalnya "Ada 3 NIK → Rahasia" (hitungan per Kind kuat).
    - Pemilih label, hanya untuk pemeriksa.
    - Daftar temuan dikelompokkan per halaman, ditambah grup "Di luar halaman" untuk `page=null`.
    - Tiap temuan punya tombol "Abaikan".
    - Tombol "+ Tandai manual": membuka form (jenis, teks, halaman) yang terisi otomatis dari teks yang diseleksi di `DocText` (`window.getSelection`).
    - Tombol "Setujui & buat versi". Kalau `doc.owner_id === me.id`, tombol ini nonaktif dengan tooltip/teks "Pemeriksa tidak boleh menyetujui dokumen yang ia upload sendiri."
    - Tombol "Kembalikan ke pengunggah" membuka dialog alasan (maksimal 500 karakter).
  - Pengunggah yang bukan pemeriksa melihat status dan versi temuan tanpa tombol. Kalau status `dikembalikan`, alasan ditampilkan bersama tombol "Upload ulang".
  - Setiap aksi: tombol menampilkan status sibuk, data di-refetch setelah sukses, dan toast muncul ("Label diubah", "Temuan ditambahkan", "Disetujui. Versi sedang dibuat."). Error menampilkan `detail` server di toast.
  - Selama status `membuat_versi`, layar melakukan polling. Setelah status `disetujui`, muncul tautan "Lihat tiga versi".

- [ ] **Step 1: Tes gagal**:
  - `segments covers text exactly, case-insensitive, longest wins`
  - `segments with no marks returns whole text`
  - `script text rendered as text` (`<script>` terlihat sebagai teks, tidak ada elemen script)
  - `page=null findings in "Di luar halaman"`
  - `self-approval button disabled with reason`
  - `abaikan posts correction and refetches`
  - `manual add prefilled from selection`
  - `return requires reason ≤500`
  - `owner sees return reason and reupload`
  - `403 detail shown in toast`
- [ ] **Step 2–4:** FAIL → tulis → PASS.
- [ ] **Step 5:** `git commit -m "feat(web): review screen"`

### Task 5: Layar tiga versi + rilis

**Files:**
- Create: `src/pages/Versions.tsx`
- Test: `src/pages/Versions.test.tsx`

**Interfaces:**
- Produces:
  - Tiga kartu (Publik, Internal, Rahasia), masing-masing dengan chip, penjelasan singkat dari mockup, dan tombol "Unduh". Unduh memakai `apiBlob` lalu `URL.createObjectURL`, dan URL dicabut setelah klik. Nama file dari server.
  - Kalau 403 atau 404, kartu menampilkan pesan server dan tombolnya nonaktif. Tidak ada percobaan otomatis untuk mengecek akses, supaya audit tidak dibanjiri.
  - Tombol "Rilis versi Publik" untuk pemeriksa dan admin saat status `disetujui`, dengan konfirmasi dua langkah di halaman (bukan `window.confirm`).
  - Pratinjau teks versi tidak ditampilkan, karena unduhan tercatat di audit.

- [ ] **Step 1: Tes gagal**: `download calls versions endpoint and creates blob URL`, `403 shows server message on that card only`, `release needs confirm step`, `release hidden for pengunggah`.
- [ ] **Step 2–4:** FAIL → tulis → PASS.
- [ ] **Step 5:** `git commit -m "feat(web): versions and release"`

### Task 6: Layar admin

**Files:**
- Create: `src/pages/admin/{Users,Units,Employees,LabelRules,Audit}.tsx`
- Test: `src/pages/admin/*.test.tsx`

**Interfaces:**
- Consumes: semua `/api/admin/*`.
- Produces:
  - Pengguna:
    - Tabel dengan kolom username, nama, peran, unit, aktif.
    - Form tambah: password minimal 10 karakter, dicek di browser dengan pesan yang sama dengan server.
    - Ubah peran, unit, atau status aktif. Reset password lewat dialog.
    - Pada baris admin itu sendiri, ubah peran dan nonaktifkan dimatikan, dengan teks penjelasan. Server tetap membalas 409.
  - Unit: daftar dan tambah.
  - Daftar pegawai: upload xlsx (kolom `nama`, `nip`), tampilkan jumlah yang dimuat dari respons server, dan peringatan bahwa file disimpan terenkripsi.
  - Aturan label: tabel 11 Kind × pilihan label, tombol "Simpan" (PUT seluruh tabel), dan tombol "Kembalikan bawaan" (isi bawaan: NIK, KK, rekening, NPWP → Rahasia; lainnya → Internal; nama pegawai → Internal).
  - Audit: tabel waktu, pengguna, aksi (teks Indonesia), dokumen, dan detail. Filter dokumen dan pengguna, limit 100, 200, atau 500.

- [ ] **Step 1: Tes gagal**: `create user validates password length client-side`, `own row cannot demote or deactivate`, `deactivate calls PATCH active=false`, `label rules save sends full table`, `employees upload shows count`, `audit filters pass query params`.
- [ ] **Step 2–4:** FAIL → tulis → PASS.
- [ ] **Step 5:** `git commit -m "feat(web): admin screens"`

### Task 7: Integrasi build + e2e + README

**Files:**
- Create: `frontend/playwright.config.ts`, `frontend/e2e/flow.spec.ts`, `frontend/e2e/start-backend.sh`
- Modify: `backend/README.md` (bagian frontend), root `README.md` (baru, ringkas: apa ini, cara build dan jalankan)

**Interfaces:**
- `start-backend.sh` menyiapkan:
  - SQLite di folder sementara, lalu `alembic upgrade head`.
  - Admin dibuat lewat skrip Python kecil, karena `create-admin` membaca prompt.
  - `DIGITADLP_NER=fake`, `DIGITADLP_COOKIE_SECURE=false`, `DIGITADLP_FRONTEND_DIR=frontend/dist`, `DIGITADLP_FERNET_KEY` baru.
  - Lalu menjalankan `python -m digitadlp` di port 8765.
- Playwright `webServer` menjalankan skrip itu. Chromium memakai browser yang sudah terpasang di container, dan trace dimatikan.
- `flow.spec.ts`, satu skenario:
  1. Admin masuk, membuat unit "Bidang Pelayanan", pengguna `rina` (pengunggah), dan `dedi` (pemeriksa).
  2. Rina masuk dan meng-upload PDF yang dibuat di tes (berisi "NIK 6474015203880002").
  3. Status berubah menjadi "Menunggu cek", dengan saran label Rahasia.
  4. Dedi masuk, membuka dokumen, melihat NIK disorot, lalu menekan "Setujui".
  5. Status menjadi "Disetujui". Dedi mengunduh versi Publik, dan file yang diunduh tidak berisi string NIK (dibaca dengan `pdf-parse` atau cek byte sederhana setelah dekompresi lewat skrip Python).
  6. Dedi merilis dokumen.
  7. Admin membuka Audit dan melihat aksi `unduh`.
- Screenshot di setiap langkah utama disimpan ke `frontend/test-results/`, dan tidak di-commit.

- [ ] **Step 1:** Tulis e2e. Jalankan `cd frontend && npm run build && npx playwright test --trace off` → FAIL, lalu perbaiki integrasi yang belum pas. Perbaikan di backend tetap dengan tes pytest.
- [ ] **Step 2:** `npx vitest run`, `npx tsc --noEmit`, dan `cd ../backend && .venv/bin/pytest -q` → semua hijau.
- [ ] **Step 3:** README: `npm ci && npm run build` di mesin build. Folder `frontend/dist` disalin ke server. Variabel `DIGITADLP_FRONTEND_DIR`. Cara menjalankan dev (Vite proxy).
- [ ] **Step 4:** `git commit -m "test(web): end-to-end flow; docs: build and run"`
