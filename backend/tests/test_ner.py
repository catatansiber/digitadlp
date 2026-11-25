import os

import pytest

from digitadlp.detect.ner import FakeNer
from digitadlp.models import Kind


def test_fake_ner_finds_all_occurrences():
    text = "Siti Rahmawati tinggal di Bontang. Siti Rahmawati lahir di Bontang."
    ner = FakeNer({"Siti Rahmawati": Kind.NAME_CITIZEN, "Bontang": Kind.ADDRESS})
    out = ner.find(text)
    assert len(out) == 4
    for f in out:
        assert text[f.start : f.end] == f.text
        assert f.source == "ner"
    assert sorted(f.start for f in out if f.kind == Kind.NAME_CITIZEN) == [0, 35]


def test_fake_ner_no_match():
    assert FakeNer({"x": Kind.ADDRESS}).find("abc") == []


@pytest.mark.skipif(not os.getenv("DIGITADLP_NER_PATH"), reason="no NER model")
def test_indobert_marked_slow():
    from digitadlp.detect.ner import IndoBertNer

    ner = IndoBertNer(os.environ["DIGITADLP_NER_PATH"])
    out = ner.find("Siti Rahmawati tinggal di Bontang")
    assert any(f.kind == Kind.NAME_CITIZEN for f in out)


def _stub(entities_by_chunk):
    from digitadlp.detect.ner import IndoBertNer

    ner = object.__new__(IndoBertNer)
    calls = []

    def pipe(chunk):
        calls.append(chunk)
        return entities_by_chunk(chunk)

    ner._pipe = pipe
    return ner, calls


def _ents(text, spans):
    """spans: list of (label, substring) -> pipeline-shaped entities."""
    out = []
    for label, sub in spans:
        i = text.index(sub)
        out.append({"entity_group": label, "start": i, "end": i + len(sub)})
    return out


def _run(text, spans):
    ner, _ = _stub(lambda c: _ents(text, spans))
    return [(f.kind, f.text) for f in ner.find(text)]


def test_indobert_labels_and_prefix_strip():
    text = "Siti di Jl. Pupuk Raya oleh Acme"
    out = _run(text, [("PER", "Siti"), ("B-LOC", "Jl. Pupuk Raya"),
                      ("I-FAC", "Jl. Pupuk Raya"), ("ORG", "Acme")])
    assert out == [
        (Kind.NAME_CITIZEN, "Siti"),
        (Kind.ADDRESS, "Jl. Pupuk Raya"),
        (Kind.ADDRESS, "Jl. Pupuk Raya"),
    ]


def test_city_and_public_building_not_address():
    text = "Rapat di Gedung Auditorium Taman 3 Dimensi, Kota Bontang dan Samarinda."
    assert _run(text, [("FAC", "Gedung Auditorium Taman 3 Dimensi"), ("GPE", "Kota"),
                       ("GPE", "Bontang"), ("GPE", "Samarinda")]) == []


def test_street_address_cues_kept():
    for addr in ["Jalan Mulawarman Nomor 21", "Gang Kenari II RT 05", "Perumahan Bukit Damai Blok C2",
                 "Gg. Melati", "Komplek PKT No. 3", "Jln KS Tubun"]:
        text = f"tinggal di {addr} sejak lama"
        assert _run(text, [("LOC", addr)]) == [(Kind.ADDRESS, addr)], addr


def test_kelurahan_kept_only_near_street_address():
    text = "alamat Jl. Pupuk Raya RT 12 No. 8, Kelurahan Gunung Elai. Kantor di Kelurahan Api-Api."
    out = _run(text, [("LOC", "Jl. Pupuk Raya RT 12 No. 8"), ("LOC", "Kelurahan Gunung Elai"),
                      ("LOC", "Kelurahan Api-Api")])
    assert out == [(Kind.ADDRESS, "Jl. Pupuk Raya RT 12 No. 8"),
                   (Kind.ADDRESS, "Kelurahan Gunung Elai")]


def test_honorific_alone_not_a_name():
    text = "Ibu Rina Marlina dan Bapak hadir, Yth. Sdr. Teguh"
    out = _run(text, [("PER", "Ibu"), ("PER", "Rina Marlina"), ("PER", "Bapak"),
                      ("PER", "Yth. Sdr."), ("PER", "Teguh")])
    assert out == [(Kind.NAME_CITIZEN, "Rina Marlina"), (Kind.NAME_CITIZEN, "Teguh")]


def test_indobert_chunks_and_shifts_offsets():
    para = "Siti Rahmawati tinggal di Bontang. " * 30  # ~1050 chars
    text = (para.strip() + "\n\n") * 3

    def ents(chunk):
        i = chunk.find("Siti")
        return [{"entity_group": "PER", "start": i, "end": i + 4}]

    ner, calls = _stub(ents)
    out = ner.find(text)
    assert len(calls) >= 2
    assert all(len(c) <= 1500 for c in calls)
    assert "".join(calls) == text
    assert len(out) == len(calls)
    for f in out:
        assert text[f.start : f.end] == "Siti" == f.text


def test_indobert_hard_cut_without_boundary():
    text = "a" * 4000
    ner, calls = _stub(lambda c: [])
    ner.find(text)
    assert "".join(calls) == text and max(map(len, calls)) <= 1500


def test_form_label_acronyms_not_names():
    text = "NIK 6474 dan No. KK serta NPWP, RT, HP milik Siti"
    out = _run(text, [("PER", "NIK"), ("PER", "KK"), ("PER", "NPWP"), ("PER", "RT"),
                      ("PER", "HP"), ("PER", "Siti")])
    assert out == [(Kind.NAME_CITIZEN, "Siti")]
