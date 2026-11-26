# Sensor Area — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pemilik dokumen PDF bisa menarik kotak di gambar halaman. Area itu dihapus total (teks dan piksel) di versi Publik dan Internal.

**Architecture:** Tabel `area_redactions` dan API di backend. `redact_pdf` menerima daftar area. Server merender halaman menjadi PNG. Tab "Halaman" di layar cek menampilkan lapisan kotak berbasis pointer events.

**Tech Stack:** FastAPI, SQLAlchemy/Alembic, PyMuPDF, React.

**Spec:** `docs/superpowers/specs/2026-11-26-sensor-area-design.md`

## Global Constraints

- Area berlaku di Publik dan Internal, tidak di Rahasia.
- Hanya PDF. DOCX mendapat 404 dari endpoint halaman dan area.
- Hanya pemilik yang bisa menambah atau menghapus area, saat status `menunggu_cek` atau `disetujui`. Di status `disetujui`, perubahan membatalkan persetujuan (`_invalidate` dan hapus versi).
- Gambar halaman dan daftar area hanya untuk unit pemilik (`can_see_rahasia`). Gambar dikirim dengan `Cache-Control: no-store`. Audit memakai aksi `lihat_halaman` (detail `hal=<n>`), `area_tambah`, dan `area_hapus` (detail `hal=<n>`), tanpa koordinat.
- Validasi: 0 ≤ x0 < x1 ≤ 1, 0 ≤ y0 < y1 ≤ 1, x1−x0 ≥ 0,005, y1−y0 ≥ 0,005, halaman ada, maksimal 200 area per dokumen. Pesan error berbahasa Indonesia.
- Unggah ulang menghapus semua area.
- CSS biasa saja, tanpa gaya inline, sesuai CSP.

## Review Focus

1. Halaman scan yang miring (orientasi dikoreksi OCR), atau PDF dengan `/Rotate` → kotak dari gambar tampilan harus mendarat di tempat yang sama di file hasil. Tes di Task 2.
2. Area menutupi bagian gambar → piksel di bawahnya benar-benar hilang (dicek dengan sampel warna gambar hasil), bukan hanya ditimpa anotasi. Tes di Task 2.
3. Pengguna unit lain meminta `/pages/0.png` → 404, dan penolakan diaudit. Tes di Task 1.
4. Kotak ditambah setelah disetujui → status kembali ke `menunggu_cek` dan versi lama tidak bisa diunduh. Tes di Task 1.
5. Kotak digambar terbalik (dari kanan bawah ke kiri atas) → tetap tersimpan benar. Tes di Task 3.

---

### Task 1: Backend — model, migrasi 0005, API halaman dan area

**Files:**
- Modify: `backend/digitadlp/app/models.py` (tambah `AreaRedaction`), `backend/digitadlp/app/audit.py` (tambah aksi), `backend/digitadlp/app/workflow.py`, `backend/digitadlp/app/routes/documents.py`
- Create: `backend/alembic/versions/0005_area_redactions.py`
- Test: `backend/tests/app/test_areas.py`

**Interfaces:**
- Produces di `workflow.py`:
  - `add_area(db, user, doc, page:int, box:tuple[float,float,float,float], page_count:int) -> AreaRedaction`
  - `delete_area(db, user, doc, area_id:str) -> None`
  - Keduanya memakai `_owner`. Status harus `menunggu_cek` atau `disetujui`; di status `disetujui` keduanya memanggil `_invalidate` dan menghapus versi (seperti `add_correction`).
  - `reupload` juga menghapus semua area.
- Routes: `GET /api/documents/{id}/pages`, `GET /api/documents/{id}/pages/{n}.png` (render 110 dpi dari sumber yang didekripsi lewat `FileStore.decrypted`), `GET|POST /api/documents/{id}/areas`, `DELETE /api/documents/{id}/areas/{area_id}`.
- `areas_for(db, doc) -> list[tuple[int, tuple[float, float, float, float]]]`, dipakai oleh Task 2.

- [ ] **Step 1: Tes gagal**:
  - `test_pages_count_and_png_owner_unit`: status 200, `image/png`, header `no-store`, ada audit `lihat_halaman`.
  - `test_pages_other_unit_404_audited`
  - `test_pages_docx_404`
  - `test_add_list_delete_area_owner`
  - `test_unit_mate_cannot_add_area_403`
  - `test_area_validation` (koordinat terbalik, di luar 0..1, terlalu kecil, halaman tidak ada, lebih dari 200 → 422)
  - `test_area_after_approval_invalidates`
  - `test_reupload_clears_areas`
  - `test_migration_0005_upgrade`
- [ ] **Step 2–4:** FAIL → tulis → `cd backend && .venv/bin/pytest -q` PASS.
- [ ] **Step 5:** `git commit -m "feat(app): area redactions API and page images"`

### Task 2: Mesin — terapkan area saat membuat versi

**Files:**
- Modify: `backend/digitadlp/redact/pdf.py` (`redact_pdf(..., areas=None)`), `backend/digitadlp/app/processing.py` (meneruskan `areas_for`)
- Test: `backend/tests/test_redact_pdf.py`, `backend/tests/app/test_jobs.py`

**Interfaces:**
- `redact_pdf(src, dst, findings_per_page, version, detect_fn=None, areas: list[tuple[int, tuple[float,float,float,float]]] | None = None)`
- Untuk `Version.PUBLIK` dan `Version.INTERNAL`, setiap area diubah ke koordinat halaman: `rect = Rect(x0*W, y0*H, x1*W, y1*H) * page.derotation_matrix`, dengan W dan H dari `page.rect` (ruang tampilan setelah rotasi). Lalu `add_redact_annot(rect, fill=(0,0,0))`. Semua area diterapkan bersama temuan lain lewat `apply_redactions(images=PDF_REDACT_IMAGE_PIXELS)`. Untuk `RAHASIA`, area diabaikan.
- Gambar PNG di Task 1 dirender dari `page.get_pixmap(dpi=110)`, yang memakai ruang tampilan. Jadi pecahan koordinat dari UI cocok dengan `page.rect`.

- [ ] **Step 1: Tes gagal**:
  - `test_area_removes_text_publik_internal_not_rahasia` (teks di dalam area hilang di Publik dan Internal, masih ada di Rahasia)
  - `test_area_wipes_image_pixels`: gambar merah di dalam area, lalu di hasil Publik piksel di tengah area berwarna hitam dan tidak ada piksel merah tersisa di area itu.
  - `test_area_on_rotated_page`: halaman dengan `set_rotation(90)` dan teks di sudut yang diketahui. Kotak dari koordinat tampilan harus menghapus teks itu.
  - `test_job_versi_applies_areas` (alur lewat `run_pending`)
- [ ] **Step 2–4:** FAIL → tulis → seluruh suite PASS.
- [ ] **Step 5:** `git commit -m "feat(redact): apply area redactions in public and internal versions"`

### Task 3: Tampilan — tab Halaman dengan gambar kotak

**Files:**
- Create: `frontend/src/components/PageAreas.tsx`, `frontend/src/lib/areas.ts`
- Modify: `frontend/src/pages/Review.tsx`, `frontend/src/api/hooks.ts` atau setara, `frontend/src/styles/app.css`
- Test: `frontend/src/lib/areas.test.ts`, `frontend/src/components/PageAreas.test.tsx`, `frontend/src/pages/Review.test.tsx`

**Interfaces:**
- `normalizeBox(ax, ay, bx, by, w, h) -> {x0,y0,x1,y1} | null`: mengurutkan titik, membatasi nilai ke 0..1, dan mengembalikan null bila sisi < 0,005.
- `PageAreas({docId, ext, pageCount, canEdit})`:
  - Navigasi halaman ◀ n / N ▶.
  - `<img>` dari `/api/documents/{id}/pages/{n}.png`.
  - Kotak yang sudah ada sebagai elemen absolut. Posisinya diatur lewat CSS custom property (`--x0` dan seterusnya) yang di-set dengan `element.style.setProperty`. Ini diizinkan CSP karena di-set lewat CSSOM, bukan atribut `style`.
  - Menggambar kotak dengan pointer events (`pointerdown`/`move`/`up`, `setPointerCapture`), lalu POST.
  - Daftar kotak di samping dengan tombol "Hapus". Saat dokumen `disetujui`, muncul peringatan "Mengubah area membatalkan persetujuan."
- Review: tab "Teks" dan "Halaman". Tab Halaman hanya muncul untuk PDF dan bila viewer boleh melihat temuan.

- [ ] **Step 1: Tes gagal**:
  - `normalizeBox handles reversed drag, clamps, rejects tiny`
  - `owner draws box → POST with normalized coords`
  - `unit mate sees boxes but cannot draw or delete`
  - `docx has no Halaman tab`
  - `delete calls DELETE and refetches`
- [ ] **Step 2–4:** `cd frontend && npx vitest run && npx tsc --noEmit && npm run build` → PASS.
- [ ] **Step 5:** `git commit -m "feat(web): page view with area redaction drawing"`

### Task 4: e2e dan dokumentasi

**Files:**
- Modify: `frontend/e2e/flow.spec.ts`, `README.md`, `backend/README.md`

- [ ] **Step 1:** Perluas e2e. Pemilik membuka tab Halaman dan menarik kotak di atas teks "Siti Rahmawati" (posisinya dihitung dari tata letak fixture), lalu Buat versi. Versi Publik tidak berisi teks itu, versi Rahasia masih berisi.
- [ ] **Step 2:** `cd frontend && npm run build && npx playwright test --trace off` → PASS. Lalu `cd backend && .venv/bin/pytest -q` → PASS.
- [ ] **Step 3:** README: bagian "Sensor area" (cara pakai, khusus PDF, berlaku untuk Publik dan Internal).
- [ ] **Step 4:** `git commit -m "test(web): e2e area redaction; docs"`
