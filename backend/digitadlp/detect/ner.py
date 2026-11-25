import re
from typing import Protocol

from digitadlp.models import Finding, Kind


class NerDetector(Protocol):
    def find(self, text: str) -> list[Finding]: ...


class FakeNer:
    """Test double: finds exact occurrences of the configured strings."""

    def __init__(self, spans: dict[str, Kind]):
        self._spans = spans

    def find(self, text: str) -> list[Finding]:
        out: list[Finding] = []
        for needle, kind in self._spans.items():
            if not needle:
                continue
            pos = text.find(needle)
            while pos != -1:
                end = pos + len(needle)
                out.append(Finding(kind, pos, end, text[pos:end], "ner"))
                pos = text.find(needle, end)
        out.sort(key=lambda f: f.start)
        return out


_LABELS = {
    "PER": Kind.NAME_CITIZEN,
    "LOC": Kind.ADDRESS,
    "ADDRESS": Kind.ADDRESS,
    "GPE": Kind.ADDRESS,
    "FAC": Kind.ADDRESS,
}

# A place is only a personal address when it names a home-level location;
# city names and public buildings stay readable in published documents.
_STREET_CUE = re.compile(
    r"(?<![A-Za-z])(jl|jln|jalan|gg|gang|perumahan|perum|komplek|kompleks|blok|rt|rw|no|nomor)(?![A-Za-z])",
    re.IGNORECASE,
)
_AREA_CUE = re.compile(r"^\s*(kelurahan|kel|desa)(?![A-Za-z])", re.IGNORECASE)
_AREA_NEAR = 3  # max gap (e.g. ", ") between a street address and its kelurahan/desa
_HONORIFICS = frozenset(
    {"ibu", "bapak", "bpk", "bu", "pak", "sdr", "sdri", "saudara", "saudari",
     "yth", "tuan", "nyonya", "ny", "nona", "almarhum", "alm", "almarhumah", "almh"}
)


def _is_honorific_only(text: str) -> bool:
    words = [w for w in re.split(r"[\s.,]+", text.casefold()) if w]
    return bool(words) and all(w in _HONORIFICS for w in words)


def _refine(findings: list[Finding]) -> list[Finding]:
    """Drop NER hits that are not personal data: bare honorifics, and places
    without a home-address cue (a kelurahan/desa counts only right after one)."""
    findings = sorted(findings, key=lambda f: f.start)
    streets = [f for f in findings if f.kind == Kind.ADDRESS and _STREET_CUE.search(f.text)]
    out: list[Finding] = []
    for f in findings:
        if f.kind == Kind.NAME_CITIZEN:
            if not _is_honorific_only(f.text):
                out.append(f)
        elif f.kind == Kind.ADDRESS:
            if _STREET_CUE.search(f.text):
                out.append(f)
            elif _AREA_CUE.match(f.text) and any(
                0 <= f.start - s.end <= _AREA_NEAR for s in streets
            ):
                out.append(f)
        else:
            out.append(f)
    return out


MAX_CHUNK = 1500
_BOUNDARIES = ("\n\n", "\n", ". ", "? ", "! ", " ")


def _chunks(text: str, limit: int = MAX_CHUNK):
    pos = 0
    while pos < len(text):
        end = min(pos + limit, len(text))
        if end < len(text):
            window = text[pos:end]
            for b in _BOUNDARIES:
                i = window.rfind(b)
                if i > 0:
                    end = pos + i + len(b)
                    break
        yield pos, text[pos:end]
        pos = end


class IndoBertNer:
    def __init__(self, model_path: str):
        # optional extra: lazy import
        from transformers import AutoModelForTokenClassification, AutoTokenizer, pipeline

        # Load explicitly from the local folder so nothing is fetched from the network.
        tokenizer = AutoTokenizer.from_pretrained(model_path, local_files_only=True)
        model = AutoModelForTokenClassification.from_pretrained(model_path, local_files_only=True)
        self._pipe = pipeline(
            "token-classification",
            model=model,
            tokenizer=tokenizer,
            aggregation_strategy="simple",
            device=-1,
        )

    def find(self, text: str) -> list[Finding]:
        out: list[Finding] = []
        for offset, chunk in _chunks(text):
            out.extend(self._find_chunk(chunk, offset))
        return _refine(out)

    def _find_chunk(self, text: str, offset: int) -> list[Finding]:
        out: list[Finding] = []
        for ent in self._pipe(text):
            label = str(ent.get("entity_group", "")).upper()
            if label.startswith(("B-", "I-")):
                label = label[2:]
            kind = _LABELS.get(label)
            if kind is None:
                continue
            start, end = int(ent["start"]), int(ent["end"])
            out.append(Finding(kind, start + offset, end + offset, text[start:end], "ner"))
        return out
