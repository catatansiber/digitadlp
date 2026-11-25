"""Pemakaian: python scripts/eval_ner.py <folder-model>

Evaluasi IndoBertNer pada kalimat contoh gaya dokumen pemerintah (data fiktif)."""
import sys, time
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))
from digitadlp.detect.ner import IndoBertNer
from digitadlp.models import Kind

M = sys.argv[1]  # folder model lokal, mis. $DIGITADLP_NER_PATH
# (teks, nama orang yang wajib ketemu, potongan alamat yang wajib ketemu)
CASES = [
    ("Nama: Siti Rahmawati, alamat Jl. Pupuk Raya RT 12 No. 8, Kelurahan Gunung Elai.", ["Siti Rahmawati"], ["Pupuk Raya"]),
    ("Pemohon atas nama Ahmad Fauzi bertempat tinggal di Jalan Mulawarman Nomor 21 Bontang.", ["Ahmad Fauzi"], ["Mulawarman"]),
    ("Ditetapkan oleh Kepala Dinas, Drs. Bambang Sutrisno, M.Si.", ["Bambang Sutrisno"], []),
    ("Saudari Dewi Lestari telah menerima bantuan sosial tahap II.", ["Dewi Lestari"], []),
    ("Bersama ini kami sampaikan bahwa Bapak Hendra Gunawan tidak hadir dalam rapat.", ["Hendra Gunawan"], []),
    ("Ibu Rina Marlina, warga Perumahan Bukit Sekatup Damai Blok C2, mengajukan keberatan.", ["Rina Marlina"], ["Bukit Sekatup Damai"]),
    ("Daftar penerima: 1. Yusuf Maulana 2. Nur Aisyah 3. Agus Salim", ["Yusuf Maulana", "Nur Aisyah", "Agus Salim"], []),
    ("Surat ini dibuat untuk Muhammad Rizky yang beralamat di Gang Kenari II RT 05 Kelurahan Api-Api.", ["Muhammad Rizky"], ["Kenari"]),
    ("Pelapor bernama Wahyuni, umur 34 tahun, pekerjaan ibu rumah tangga.", ["Wahyuni"], []),
    ("Rapat dipimpin oleh Sekretaris Daerah dan dihadiri camat se-Kota Bontang.", [], []),
    ("Kegiatan dilaksanakan di Gedung Auditorium Taman 3 Dimensi pada hari Senin.", [], []),
    ("Anak atas nama Putri Ayu Ningsih lahir di Samarinda tanggal 3 Maret 2015.", ["Putri Ayu Ningsih"], []),
    ("Tanah milik almarhum H. Abdul Rahman terletak di Jl. KS Tubun, Kelurahan Bontang Baru.", ["Abdul Rahman"], ["KS Tubun"]),
    ("Kepada Yth. Sdr. Teguh Prasetyo di tempat.", ["Teguh Prasetyo"], []),
    ("Anggaran pengadaan komputer sebesar Rp 150.000.000 disetujui.", [], []),
]

t0 = time.time()
ner = IndoBertNer(M)
print(f"muat model: {time.time()-t0:.1f}s")

tp = fn = 0; atp = afn = 0; fp_names = []
t0 = time.time()
for text, names, addrs in CASES:
    found = ner.find(text)
    per = [f.text for f in found if f.kind == Kind.NAME_CITIZEN]
    adr = [f.text for f in found if f.kind == Kind.ADDRESS]
    for n in names:
        if any(n in p or p in n and len(p) >= 4 for p in per): tp += 1
        else: fn += 1; print("  LOLOS nama:", n, "| ditemukan:", per)
    for a in addrs:
        if any(a.lower() in x.lower() for x in adr): atp += 1
        else: afn += 1; print("  LOLOS alamat:", a, "| ditemukan:", adr)
    for p in per:
        if not any(p in n or n in p for n in names): fp_names.append(p)
dt = time.time() - t0
print(f"nama: {tp}/{tp+fn} ketemu ({100*tp/(tp+fn):.0f}%)")
print(f"alamat: {atp}/{atp+afn} ketemu ({100*atp/max(1,atp+afn):.0f}%)")
print("salah tandai sebagai nama:", fp_names)
print(f"waktu {len(CASES)} kalimat: {dt:.2f}s ({1000*dt/len(CASES):.0f} ms/kalimat, CPU)")
