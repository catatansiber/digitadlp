# DigitaDLP — Sensor area (kotak di gambar halaman)

Tanggal: 2026-11-26

## Maksud

Sebagian data tidak bisa ditangkap lewat teks atau OCR, misalnya tanda tangan, stempel, foto KTP, tulisan tangan, atau scan buram. Pengguna perlu bisa menandai area di halaman secara langsung, dengan menarik kotak di gambar halaman.

## Keputusan pengguna

- Kotak ditutup hitam di versi **Publik dan Internal**. Versi Rahasia tetap utuh.
- Fitur ini khusus PDF. Dokumen DOCX tetap disensor lewat tandai teks manual.
- Pendekatan: server merender halaman menjadi PNG, lalu browser menampilkan lapisan kotak di atasnya (tanpa pdf.js).
- Hanya pemilik dokumen yang bisa menambah atau menghapus kotak, saat status *Menunggu cek*.
- Kalau dokumen sudah *Disetujui*, menambah atau menghapus kotak membatalkan persetujuan, sama seperti koreksi temuan.
- Unggah ulang menghapus semua kotak.
- Gambar halaman hanya untuk unit pemilik. Setiap akses diaudit sebagai "lihat halaman", dan gambar dikirim dengan `no-store`.

## Bukan tujuan

- Menggambar bentuk selain persegi panjang.
- Sensor area pada DOCX.
- Mengedit ukuran kotak setelah dibuat. Kotak cukup dihapus lalu digambar ulang.

## Desain

- Tabel `area_redactions`: `id`, `document_id`, `page` (0-based), `x0 y0 x1 y1` (pecahan 0–1 dari lebar dan tinggi halaman setelah rotasi tampilan), `author_id`, `created_at`. Dibuat lewat migrasi 0005.
- API, di bawah `/api/documents/{id}`:
  - `GET /pages` → `{"count": n, "sizes": [[w, h], …]}`. Hanya untuk PDF; DOCX mendapat 404.
  - `GET /pages/{n}.png`: PNG 110 dpi dengan `Cache-Control: no-store`. Akses diaudit `lihat_halaman`, dan hak aksesnya sama dengan teks dokumen.
  - `GET /areas`, `POST /areas` dengan body `{page, x0, y0, x1, y1}`, dan `DELETE /areas/{area_id}`. Hanya pemilik yang bisa menambah atau menghapus. Validasi: 0 ≤ x0 < x1 ≤ 1, 0 ≤ y0 < y1 ≤ 1, ukuran minimal 0,005 per sisi, nomor halaman harus ada, dan maksimal 200 kotak per dokumen.
- Mesin: `redact_pdf(..., areas=[(page, (x0, y0, x1, y1)), …])`. Untuk Publik dan Internal, setiap kotak diubah ke koordinat halaman lalu diterapkan sebagai `add_redact_annot` berwarna hitam tanpa teks. Kotak ikut `apply_redactions` dengan `images=PDF_REDACT_IMAGE_PIXELS`, sehingga teks dan piksel gambar di bawahnya benar-benar terhapus. Untuk Rahasia, kotak diabaikan.
- Tampilan: layar cek mendapat tab **Teks | Halaman**. Tab Halaman berisi navigasi halaman, gambar halaman, kotak yang sudah ada (hitam semi-transparan), dan cara membuat kotak dengan menarik mouse atau jari (pointer events). Daftar kotak di samping punya tombol hapus. Untuk bukan pemilik, tab ini hanya bisa dilihat.

## Diserahkan ke pembangun

- Detail tampilan tab Halaman, selama mengikuti gaya dan aturan CSS yang sudah ada.
