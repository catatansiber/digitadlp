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


def test_indobert_labels_and_prefix_strip():
    text = "Siti di Bontang oleh Acme"
    ents = [
        {"entity_group": "PER", "start": 0, "end": 4},
        {"entity_group": "B-LOC", "start": 8, "end": 15},
        {"entity_group": "I-GPE", "start": 8, "end": 15},
        {"entity_group": "ORG", "start": 21, "end": 25},
    ]
    ner, _ = _stub(lambda c: ents)
    out = ner.find(text)
    assert [(f.kind, f.text) for f in out] == [
        (Kind.NAME_CITIZEN, "Siti"),
        (Kind.ADDRESS, "Bontang"),
        (Kind.ADDRESS, "Bontang"),
    ]
    assert all(f.source == "ner" for f in out)


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
