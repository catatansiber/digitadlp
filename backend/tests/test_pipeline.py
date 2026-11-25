from digitadlp.detect.employees import EmployeeDirectory
from digitadlp.detect.ner import FakeNer
from digitadlp.detect.pipeline import detect
from digitadlp.models import Kind

TEXT = (
    "Nama: Siti Rahmawati, NIK 6474015203880002, mengajukan permohonan. "
    "Disetujui oleh Kepala Dinas, Drs. Bambang Sutrisno"
)
DIRECTORY = EmployeeDirectory.from_names(["Bambang Sutrisno"])


def _ner():
    return FakeNer(
        {
            "Siti Rahmawati": Kind.NAME_CITIZEN,
            "Drs. Bambang Sutrisno": Kind.NAME_CITIZEN,
        }
    )


def test_mockup_text_kinds_in_order():
    found = detect(TEXT, _ner(), DIRECTORY)
    assert [f.kind for f in found] == [
        Kind.NAME_CITIZEN,
        Kind.NIK,
        Kind.NAME_EMPLOYEE,
    ]
    assert [f.start for f in found] == sorted(f.start for f in found)
    assert [f.text for f in found] == [
        "Siti Rahmawati",
        "6474015203880002",
        "Drs. Bambang Sutrisno",
    ]


def test_stronger_regex_beats_ner_overlap():
    ner = FakeNer({"6474015203880002": Kind.ADDRESS})
    found = detect(TEXT, ner, DIRECTORY)
    assert [f.kind for f in found] == [Kind.NIK]


def test_non_employee_name_stays_citizen():
    found = detect(TEXT, _ner(), EmployeeDirectory.from_names([]))
    assert Kind.NAME_EMPLOYEE not in [f.kind for f in found]


def test_equal_strength_longer_wins():
    text = "Alamat Jalan Mawar Nomor 5 Bontang"
    ner = FakeNer({"Jalan Mawar": Kind.ADDRESS, "Jalan Mawar Nomor 5": Kind.ADDRESS})
    found = detect(text, ner, DIRECTORY)
    assert [f.text for f in found] == ["Jalan Mawar Nomor 5"]


def test_chain_overlaps_never_overlap():
    text = "abcdefghij"
    ner = FakeNer(
        {"abcd": Kind.ADDRESS, "cdefg": Kind.ADDRESS, "fghij": Kind.ADDRESS}
    )
    found = detect(text, ner, DIRECTORY)
    for a, b in zip(found, found[1:]):
        assert a.end <= b.start
    assert [(f.start, f.end, f.text) for f in found] == [(0, 10, "abcdefghij")]


def test_mockup_result_never_overlaps():
    found = detect(TEXT, _ner(), DIRECTORY)
    for a, b in zip(found, found[1:]):
        assert a.end <= b.start


def test_partial_overlap_extends_winner_to_union():
    text = "xx6474015203880002 Jalan"
    ner = FakeNer({"xx6474015": Kind.ADDRESS})
    found = detect(text, ner, DIRECTORY)
    assert len(found) == 1
    assert found[0].kind == Kind.NIK
    assert found[0].text == text[: found[0].end]
    assert found[0].start == 0


def test_contained_loser_changes_nothing():
    text = "Alamat Jalan Mawar Nomor 5"
    ner = FakeNer({"Jalan Mawar Nomor 5": Kind.ADDRESS, "Mawar": Kind.ADDRESS})
    found = detect(text, ner, DIRECTORY)
    assert [(f.start, f.text) for f in found] == [(7, "Jalan Mawar Nomor 5")]
