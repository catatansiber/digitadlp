import pytest

from digitadlp.app.corrections import apply_corrections, corrected_detect_fn
from digitadlp.app.models import Correction, CorrectionOp
from digitadlp.models import Finding, Kind


def F(kind, text, start=0):
    return Finding(kind, start, start + len(text), text, "regex")


def C(op, text, page=None, kind="NAME_CITIZEN"):
    return Correction(op=op, text=text, page=page, kind=kind)


def test_ignore_removes_finding():
    pages = [[F(Kind.PHONE, "0812 3456"), F(Kind.EMAIL, "a@b.id")], [F(Kind.PHONE, "0812  3456")]]
    out = apply_corrections(pages, [C(CorrectionOp.ABAIKAN, "0812 3456", kind="PHONE")])
    assert out == [[pages[0][1]], []]


def test_ignore_page_scoped_and_casefold():
    pages = [[F(Kind.NAME_CITIZEN, "Rina")], [F(Kind.NAME_CITIZEN, "Rina")]]
    out = apply_corrections(pages, [C(CorrectionOp.ABAIKAN, "RINA", page=1)])
    assert len(out[0]) == 1 and out[1] == []


def test_ignore_not_substring():
    pages = [[F(Kind.NAME_CITIZEN, "Bu Rina Sari")]]
    assert apply_corrections(pages, [C(CorrectionOp.ABAIKAN, "Rina")]) == pages


def test_add_manual_pdf():
    out = apply_corrections([[], []], [C(CorrectionOp.TAMBAH, "Bu Rina", page=1)])
    assert out[0] == []
    assert out[1] == [Finding(Kind.NAME_CITIZEN, -1, -1, "Bu Rina", "manual")]


def test_add_out_of_range():
    with pytest.raises(ValueError):
        apply_corrections([[]], [C(CorrectionOp.TAMBAH, "x", page=3)])


def test_add_wins_over_ignore():
    out = apply_corrections(
        [[F(Kind.NAME_CITIZEN, "Rina")]],
        [C(CorrectionOp.ABAIKAN, "Rina", page=0), C(CorrectionOp.TAMBAH, "Rina", page=0)],
    )
    assert [f.source for f in out[0]] == ["manual"]


def test_does_not_mutate_input():
    pages = [[F(Kind.PHONE, "081")]]
    apply_corrections(pages, [C(CorrectionOp.ABAIKAN, "081")])
    assert len(pages[0]) == 1


def test_corrected_detect_fn_adds_offsets():
    fn = corrected_detect_fn(lambda t: [], [C(CorrectionOp.TAMBAH, "Bu Rina")])
    out = fn("Bu Rina tinggal di sini")
    assert out == [Finding(Kind.NAME_CITIZEN, 0, 7, "Bu Rina", "manual")]


def test_corrected_detect_fn_all_occurrences_case_insensitive():
    fn = corrected_detect_fn(lambda t: [], [C(CorrectionOp.TAMBAH, "bu rina")])
    out = fn("Bu Rina dan BU RINA")
    assert [(f.start, f.end, f.text) for f in out] == [(0, 7, "Bu Rina"), (12, 19, "BU RINA")]


def test_corrected_detect_fn_ignore():
    base = lambda t: [F(Kind.PHONE, "0812")]
    fn = corrected_detect_fn(base, [C(CorrectionOp.ABAIKAN, "0812")])
    assert fn("x 0812") == []
