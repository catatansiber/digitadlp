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
}


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
        from transformers import pipeline  # optional extra: lazy import

        self._pipe = pipeline(
            "token-classification",
            model=model_path,
            aggregation_strategy="simple",
            device=-1,
            model_kwargs={"local_files_only": True},
        )

    def find(self, text: str) -> list[Finding]:
        out: list[Finding] = []
        for offset, chunk in _chunks(text):
            out.extend(self._find_chunk(chunk, offset))
        return out

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
