# DigitaDLP — Desain

Tanggal: 2026-11-24

## Maksud dan alasan

Staf instansi pemerintah sering merilis dokumen ke publik. Dokumen itu bisa memuat data pribadi warga (NIK, alamat, no HP). Kalau lolos, instansi melanggar UU PDP dan warga dirugikan.

DigitaDLP membantu staf: upload dokumen, sistem temukan data pribadi, sarankan label, lalu buat versi yang aman sesuai pembaca.

## Tujuan

- Deteksi data pribadi otomatis di dokumen yang di-upload.
- Sarankan label klasifikasi. Staf boleh mengubahnya.
- Hasilkan 3 versi dari satu dokumen sumber:
  - **Publik**: semua data pribadi disensor.
  - **Internal**: sebagian disensor (data identitas kuat seperti NIK, KK, rekening tetap disensor; nama dan jabatan pegawai boleh tampil).
  - **Rahasia**: utuh, hanya untuk pihak berwenang.
- Wajib cek manusia sebelum versi Publik dirilis.
- Catat jejak audit: siapa upload, siapa setujui, kapan.

## Bukan tujuan (tahap awal)

- Memantau email, USB, atau jaringan (DLP endpoint/jaringan).
- LLM atau AI cloud.
- Aplikasi mobile.

## Anti-tujuan (gagal walau "jalan")

- Sensor hanya kotak hitam visual, teks asli masih bisa disalin.
- Dokumen atau data pribadi dikirim keluar server instansi.
- Versi Publik bisa dirilis tanpa disetujui manusia.
- Versi Rahasia bisa diakses orang yang tidak berwenang.

## Batasan

- Semua proses di server instansi (on-premise). Tanpa panggilan ke layanan luar.
- Server biasa, tanpa GPU.
- Bahasa dokumen: Indonesia.

## Pendekatan yang dipertimbangkan

| Pendekatan | Untung | Rugi |
|---|---|---|
| **A. Pola (regex) + NER kecil (IndoBERT) + OCR** — dipilih | Cepat, murah, tanpa GPU | Kadang salah konteks; ditutup oleh cek manusia |
| B. LLM lokal (Ollama) | Paham konteks | Perlu GPU, lambat |
| C. Gabungan A + LLM untuk bagian ragu | Paling akurat | Paling rumit |

Dipilih **A** oleh pengguna. C bisa ditambah nanti jika ada GPU.

## Keputusan pengguna

- Label berarti **pembaca** → satu dokumen jadi 3 versi.
- Label **disarankan sistem**, staf bisa ubah.
- Data **tetap di server instansi**.
- Deteksi pakai **pola + NER**.

## Usulan saya (bisa dikoreksi)

- **Data yang dicari**: NIK (16 digit), No KK, NPWP, no HP, email, no rekening, nama orang, alamat, tanggal lahir.
- **Format file**: PDF (teks dan hasil scan via OCR) dan DOCX. Output versi dalam format yang sama dengan input.
- **Aturan saran label**: ada data identitas kuat (NIK, KK, rekening) → Rahasia; hanya nama/kontak pegawai → Internal; tidak ada data pribadi → Publik. Aturan ini bisa diatur admin.
- **Sensor sungguhan**: teks dihapus dari file (PyMuPDF redaction untuk PDF, ganti teks untuk DOCX), metadata dibersihkan.
- **Cara sensor**: ganti dengan blok hitam atau penanda seperti `[NIK]`. Penyamaran sebagian (contoh `3201********0001`) untuk versi Internal.
- **Peran**: Pengunggah, Pemeriksa (menyetujui rilis), Admin (atur aturan dan pengguna).
- **Teknologi** (dipilih pengguna, opsi 1): Python + FastAPI (backend), React (frontend), PostgreSQL (metadata + audit), penyimpanan file lokal terenkripsi.
- **Layar cek**: dokumen tampil dengan sorotan tiap temuan. Pemeriksa bisa tambah, hapus, atau ubah temuan sebelum setuju.

## Keputusan saya dari cek pembangun (bisa dikoreksi)

- **PDF scan**: gambar ikut disensor (piksel ditimpa), lalu PDF diratakan. Lapisan teks OCR dibuat ulang dari hasil yang sudah disensor, agar tetap bisa dicari.
- **Isi DOCX**: header, footer, tabel, komentar ikut diperiksa. Tracked changes dan komentar dibuang di versi Publik. Gambar di dalam DOCX di-OCR.
- **Alur cek**: versi Publik wajib disetujui. Pemeriksa tidak boleh menyetujui upload sendiri. Kalau sumber diubah setelah disetujui, persetujuan batal. "Rilis" = versi bisa diunduh/diekspor, dan tercatat di audit.
- **Beban**: proses lewat antrean kerja (background job), agar dokumen tebal tidak membuat web macet.

## Keputusan pengguna (lanjutan)

- **Akses versi Rahasia**: pegawai di unit kerja pemilik dokumen + Pemeriksa. Pengguna punya atribut unit kerja.
- **Nama pegawai vs warga**: dicocokkan ke daftar pegawai (impor dari SIMPEG/Excel oleh Admin). Nama yang cocok = pegawai (tampil di Internal); lainnya = warga (disensor). Pemeriksa bisa koreksi.
- **Login**: akun lokal di aplikasi (password di-hash, dikelola Admin).

## Diserahkan ke pembangun

- Pilihan model NER IndoBERT tertentu dan cara mengemasnya.
- Struktur folder, skema database rinci.
- Desain tampilan.
