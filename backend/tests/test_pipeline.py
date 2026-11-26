from digitadlp.detect.pipeline import detect
from digitadlp.models import Kind

TEXT = (
    "Nama: Siti Rahmawati, NIK 6474015203880002, mengajukan permohonan. "
    "Disetujui oleh Kepala Dinas, Drs. Bambang Sutrisno"
)


def test_detect_is_patterns_only():
    found = detect("Nama Siti Rahmawati NIK 6474015203880002")
    assert [f.kind for f in found] == [Kind.NIK]


def test_mockup_text_has_no_automatic_names():
    found = detect(TEXT)
    assert [(f.kind, f.text) for f in found] == [(Kind.NIK, "6474015203880002")]


def test_address_and_nik_both_found_without_overlap():
    text = "NIK 6474015203880002 alamat Jalan Mawar Nomor 5 Bontang"
    found = detect(text)
    assert [f.kind for f in found] == [Kind.NIK, Kind.ADDRESS]
    assert found[1].text == "Jalan Mawar Nomor 5 Bontang"
    for a, b in zip(found, found[1:]):
        assert a.end <= b.start


def test_stronger_pattern_wins_inside_address():
    # a phone inside an address span: union-span resolution keeps nothing leaking
    text = "Jalan Mawar 081234567890 Bontang"
    found = detect(text)
    covered = "".join(text[f.start:f.end] for f in found)
    assert "081234567890" in covered
    for a, b in zip(found, found[1:]):
        assert a.end <= b.start
