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
