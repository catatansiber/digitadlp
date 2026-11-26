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


import pytest

from digitadlp.detect import pipeline
from digitadlp.models import Finding


def _fake(monkeypatch, text, spans):
    fs = [Finding(k, text.index(s), text.index(s) + len(s), s, "regex") for k, s in spans]
    monkeypatch.setattr(pipeline, "find_patterns", lambda t: list(fs))


def test_chain_overlaps_never_overlap(monkeypatch):
    text = "abcdefghij"
    _fake(monkeypatch, text, [(Kind.ADDRESS, "abcd"), (Kind.ADDRESS, "cdefg"), (Kind.ADDRESS, "fghij")])
    found = detect(text)
    assert [(f.start, f.end, f.text) for f in found] == [(0, 10, "abcdefghij")]


def test_partial_overlap_extends_winner_to_union(monkeypatch):
    text = "xx6474015203880002 Jalan"
    _fake(monkeypatch, text, [(Kind.NIK, "6474015203880002"), (Kind.ADDRESS, "xx6474015")])
    found = detect(text)
    assert [(f.kind, f.start, f.text) for f in found] == [(Kind.NIK, 0, "xx6474015203880002")]


def test_contained_loser_changes_nothing(monkeypatch):
    text = "Alamat Jalan Mawar Nomor 5"
    _fake(monkeypatch, text, [(Kind.ADDRESS, "Jalan Mawar Nomor 5"), (Kind.ADDRESS, "Mawar")])
    assert [(f.start, f.text) for f in detect(text)] == [(7, "Jalan Mawar Nomor 5")]


def test_equal_strength_longer_wins(monkeypatch):
    text = "Alamat Jalan Mawar Nomor 5 Bontang"
    _fake(monkeypatch, text, [(Kind.ADDRESS, "Jalan Mawar"), (Kind.ADDRESS, "Jalan Mawar Nomor 5")])
    assert [f.text for f in detect(text)] == ["Jalan Mawar Nomor 5"]


def test_stronger_beats_weaker_overlap(monkeypatch):
    text = "NIK 6474015203880002"
    _fake(monkeypatch, text, [(Kind.ADDRESS, "6474015203880002"), (Kind.NIK, "6474015203880002")])
    assert [f.kind for f in detect(text)] == [Kind.NIK]
