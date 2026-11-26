# DigitaDLP — Satu peran pengguna & deteksi nama manual

Tanggal: 2026-11-26
Mengubah: `2026-11-24-digitadlp-design.md` (alur persetujuan, peran, deteksi nama).

## Maksud dan alasan

Pengguna akan bertanggung jawab sendiri atas dokumen yang mereka unggah, tanpa pemeriksa terpisah. Deteksi nama warga otomatis (model IndoBERT) dinilai terlalu sering salah, jadi nama disensor manual oleh pengguna. Melepas model sekaligus membuat aplikasi jauh lebih ringan dipasang.

## Tujuan

- Hanya dua peran: **Pengguna** dan **Admin**.
- Pemilik dokumen sendiri yang mengecek temuan, lalu menekan **Buat versi** dan **Rilis**.
- Tidak ada deteksi nama otomatis. Nama (warga maupun pegawai) disensor lewat **Tandai manual**.
- Alamat dideteksi dengan pola (tanpa model).
- Model IndoBERT, torch, dan transformers dilepas dari aplikasi dan image Docker.

## Bukan tujuan

- Mengubah cara sensor, enkripsi, audit, atau tiga versi.
- Fitur persetujuan berlapis atau pemeriksa opsional.

## Anti-tujuan

- Akun lama tidak bisa masuk atau kehilangan dokumennya setelah update.
- Dokumen yang sudah disetujui atau dirilis jadi tidak bisa diunduh.
- Rekan satu unit bisa mengubah atau menyetujui dokumen orang lain.

## Keputusan pengguna

- Peran Pengunggah dan Pemeriksa dihapus. Pengguna bertanggung jawab atas dokumennya sendiri.
- Tetap ada langkah cek sendiri. Pengguna menekan **Buat versi** setelah mengecek temuan (opsi A).
- Deteksi nama warga otomatis dihapus. Nama disensor manual.
- Model IndoBERT dilepas sepenuhnya. Alamat dideteksi dengan pola (opsi A).

## Pendekatan

| Pendekatan | Untung | Rugi |
|---|---|---|
| **Sederhanakan alur yang ada** (dipilih) | Perubahan kecil dan teruji, data lama tetap jalan | Masih ada sisa kode lama yang harus dibersihkan |
| Tulis ulang alur | Kode lebih bersih | Risiko regresi besar, tidak sepadan |

Untuk alamat: **pola tanpa model** (dipilih, image < 1 GB) vs mempertahankan model khusus alamat (image ±3 GB untuk satu jenis data).

## Desain

### Peran dan migrasi

- `Role` menjadi `pengguna` dan `admin`.
- Migrasi Alembic 0004 mengubah semua `pengunggah` dan `pemeriksa` menjadi `pengguna`. Sesi yang ada tetap berlaku.
- Admin tetap tidak bisa mengunggah, dan tidak otomatis bisa membuka versi Rahasia unit lain.

### Alur dokumen

1. Pengguna mengunggah. Deteksi berjalan, lalu status menjadi `menunggu_cek`.
2. Hanya **pemilik** yang bisa mengubah label, menambah atau mengabaikan temuan, menekan **Buat versi** (status `membuat_versi` → `disetujui`), dan menekan **Rilis** (`disetujui` → `dirilis`).
3. Koreksi setelah disetujui tetap membatalkan persetujuan (status kembali ke `menunggu_cek`, versi dihapus).
4. Status `dikembalikan` dan aksi "Kembalikan ke pengunggah" dihapus. Dokumen lama yang berstatus `dikembalikan` dimigrasi menjadi `menunggu_cek`.
5. Upload ulang tetap ada, hanya oleh pemilik, dari status `menunggu_cek` atau `gagal`.
6. Audit `setujui` tetap tercatat dengan pelakunya, sebagai bukti tanggung jawab.

### Akses

- Rekan satu unit bisa melihat dokumen. Temuan dan teks hanya terlihat oleh unit pemilik.
- Rekan satu unit bisa mengunduh versi sesuai aturan sekarang, tapi tidak bisa mengubah apa pun.
- Versi Rahasia hanya untuk unit pemilik. Aturan "atau Pemeriksa" dihapus.
- Versi Internal tetap untuk semua pengguna aktif setelah disetujui.

### Deteksi

- Hapus NER dari pipeline. `detect(text, ner, directory)` disederhanakan menjadi deteksi pola saja.
- Alamat berasal dari pola baru di `detect/patterns.py`:
  - Kata penanda alamat rumah (Jl./Jln/Jalan/Gg./Gang/Perumahan/Perum/Komplek/Blok), diikuti nama jalan, sampai akhir frasa alamat (RT/RW/No. ikut masuk).
  - "Kelurahan/Desa X" yang langsung mengikuti alamat itu.
  - Batas frasa: koma ganda, titik akhir kalimat, atau akhir baris.
- Daftar pegawai dan menu **Admin → Pegawai** dihapus. NIP tetap terdeteksi lewat pola.
- **Tandai manual** menjadi cara utama untuk nama. Sekali ditandai, semua kemunculan teks yang sama di dokumen ikut disensor. Perilaku ini sudah ada, dan sekarang ditonjolkan di UI.
- Jenis "Nama warga" di pilihan tandai manual diganti teks "Nama orang".

### Docker

- Stage unduh model dihapus, begitu juga instalasi torch dan transformers. Variabel `DIGITADLP_NER_PATH` dan `DIGITADLP_NER` dihapus.
- README dan `.env.example` disesuaikan.

## Keputusan saya dari cek pembangun (bisa dikoreksi)

- **Nama manual**: pilihan "Nama orang" berperilaku seperti `NAME_CITIZEN` hari ini, yaitu disensor di Publik dan disamarkan di Internal. Nama pejabat yang boleh tampil cukup tidak ditandai. Nilai `NAME_EMPLOYEE` dan `Strength.EMPLOYEE` tetap ada di kode supaya data lama terbaca, tapi tidak bisa dipilih lagi.
- **Dokumen lama**: temuan dan koreksi yang tersimpan tidak diubah, dan deteksi tidak dijalankan ulang. Dokumen `disetujui`/`dirilis` tetap utuh. Dokumen yang nanti dikoreksi atau diunggah ulang memakai deteksi baru.
- **Rilis**: pemilik bisa merilis. Admin tetap bisa merilis sebagai cadangan, misalnya kalau pemilik sudah nonaktif. Pengguna nonaktif tidak bisa masuk, jadi tidak bisa bertindak.
- **Akurasi alamat**: pola harus lolos semua contoh beralamat dari evaluasi IndoBERT (5 dari 5), dan tidak boleh menandai nama kota atau gedung. Alamat tanpa kata penanda dicatat sebagai keterbatasan di README.
- **Migrasi 0004** hanya mengubah data (kolom peran berupa string). Tidak ada downgrade, karena dua peran digabung jadi satu. Blob `employees.xlsx` lama dibiarkan dan tidak dipakai lagi.

## Diserahkan ke pembangun

- Bentuk regex alamat yang persis. Tes harus mencakup contoh dari evaluasi IndoBERT sebelumnya (`backend/scripts/eval_ner.py`), lalu skrip itu dihapus atau diganti skrip evaluasi pola.
- Pembersihan kode, tes, dan teks UI yang menyebut pemeriksa, pengunggah, atau pegawai.
