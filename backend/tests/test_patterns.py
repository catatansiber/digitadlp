from digitadlp.detect.patterns import find_patterns, is_valid_nik
from digitadlp.models import Kind


def test_nik_plain():
    f = find_patterns("NIK 6474015203880002 ok")
    assert [(x.kind, x.text) for x in f] == [(Kind.NIK, "6474015203880002")]


def test_nik_separated():
    assert find_patterns("NIK: 6474 0152 0388 0002")[0].text == "6474 0152 0388 0002"


def test_nik_dot_and_dash_separated():
    for raw in ("6474.0152.0388.0002", "6474-0152-0388-0002"):
        text = f"NIK {raw} ok"
        f = find_patterns(text)
        assert [(x.kind, x.text) for x in f] == [(Kind.NIK, raw)]
        assert text[f[0].start:f[0].end] == raw


def test_invalid_16_digits_not_nik():
    assert find_patterns("Faktur 1234569999990000") == []  # bulan 99


def test_kk_by_context():
    assert find_patterns("No. KK 6474010000000001")[0].kind == Kind.KK
    assert find_patterns("Kartu Keluarga: 6474010000000001")[0].kind == Kind.KK


def test_phone_email_account_nip():
    kinds = {x.kind for x in find_patterns(
        "HP 0812-5544-0921, a@b.go.id, rekening BRI 0215-01-004567-50-3, NIP 197004121998031005")}
    assert kinds == {Kind.PHONE, Kind.EMAIL, Kind.ACCOUNT, Kind.NIP}


def test_nip_not_cut_into_nik_and_offsets():
    text = "NIP 197004121998031005"
    f = find_patterns(text)
    assert [(x.kind, x.text) for x in f] == [(Kind.NIP, "197004121998031005")]
    assert text[f[0].start:f[0].end] == f[0].text


def test_npwp_formats():
    f = find_patterns("NPWP 12.345.678.9-012.345")
    assert [(x.kind, x.text) for x in f] == [(Kind.NPWP, "12.345.678.9-012.345")]
    f = find_patterns("NPWP: 1234567890123456")
    assert [(x.kind, x.text) for x in f] == [(Kind.NPWP, "1234567890123456")]


def test_no_duplicate_spans_for_valid_nik():
    f = find_patterns("NIK 6474015203880002 telp 6474015203880002")
    spans = [(x.start, x.end) for x in f]
    assert len(spans) == len(set(spans)) == 2
    assert all(x.kind == Kind.NIK for x in f)


def test_sorted_and_source():
    f = find_patterns("a@b.id HP 081255440921 NIK 6474015203880002")
    assert [x.start for x in f] == sorted(x.start for x in f)
    assert {x.source for x in f} == {"regex"}


def test_is_valid_nik():
    assert is_valid_nik("6474015203880002")
    assert is_valid_nik("6474014103880002")  # perempuan, tanggal 41
    assert not is_valid_nik("647401520388000")  # 15 digit
    assert not is_valid_nik("6474010000000001")  # tanggal 00
    assert not is_valid_nik("6474013203880002")  # tanggal 32
    assert not is_valid_nik("6474015213880002")  # bulan 13
    assert not is_valid_nik("6474015203880000")  # urut 0000
    assert not is_valid_nik("64740152038800a2")


def test_nik_after_space_separated_group():
    text = "Tgl 15 2024 6474 0152 0388 0002"
    f = find_patterns(text)
    assert [(x.kind, x.text) for x in f] == [(Kind.NIK, "6474 0152 0388 0002")]
    assert text[f[0].start:f[0].end] == "6474 0152 0388 0002"


def test_email_with_phone_like_local_part():
    f = find_patterns("kirim ke 081255440921@gmail.com")
    assert [(x.kind, x.text) for x in f] == [(Kind.EMAIL, "081255440921@gmail.com")]


def test_nip_without_separator():
    f = find_patterns("NIP197004121998031005")
    assert [(x.kind, x.text) for x in f] == [(Kind.NIP, "197004121998031005")]


import pytest


@pytest.mark.parametrize("text,addr", [
    ("alamat Jl. Pupuk Raya RT 12 No. 8, Kelurahan Gunung Elai.",
     ["Jl. Pupuk Raya RT 12 No. 8", "Kelurahan Gunung Elai"]),
    ("tinggal di Jalan Mulawarman Nomor 21 Bontang.", ["Jalan Mulawarman Nomor 21 Bontang"]),
    ("warga Perumahan Bukit Sekatup Damai Blok C2, mengajukan",
     ["Perumahan Bukit Sekatup Damai Blok C2"]),
    ("di Gang Kenari II RT 05 Kelurahan Api-Api.", ["Gang Kenari II RT 05", "Kelurahan Api-Api"]),
    ("terletak di Jl. KS Tubun, Kelurahan Bontang Baru.", ["Jl. KS Tubun", "Kelurahan Bontang Baru"]),
])
def test_address_patterns(text, addr):
    found = [f for f in find_patterns(text) if f.kind == Kind.ADDRESS]
    assert all(f.source == "regex" for f in found)
    for a in addr:
        assert any(a in f.text for f in found), (a, [f.text for f in found])


@pytest.mark.parametrize("text", [
    "Rapat di Kota Bontang.", "di Gedung Auditorium Taman 3 Dimensi",
    "Kantor di Kelurahan Api-Api.", "Jalan-jalan sore",
])
def test_not_address(text):
    assert not [f for f in find_patterns(text) if f.kind == Kind.ADDRESS]


@pytest.mark.parametrize("text", ["lampu jalan rusak dan jalan sehat", "masuk gang sempit", "blok kiri"])
def test_lowercase_full_cue_not_address(text):
    assert not [f for f in find_patterns(text) if f.kind == Kind.ADDRESS]


@pytest.mark.parametrize("text,addr", [
    ("Jalan Mulawarman Nomor 21", "Jalan Mulawarman Nomor 21"),
    ("alamat Jl. Pupuk No. A5, Bontang", "Jl. Pupuk No. A5"),
    ("alamat Jl. Pupuk Nomor. B7 Bontang", "Jl. Pupuk Nomor. B7 Bontang"),
])
def test_address_kept_whole(text, addr):
    assert [f.text for f in find_patterns(text) if f.kind == Kind.ADDRESS] == [addr]
