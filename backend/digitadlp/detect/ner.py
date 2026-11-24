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
        for ent in self._pipe(text):
            label = str(ent.get("entity_group", "")).upper()
            if label.startswith(("B-", "I-")):
                label = label[2:]
            kind = _LABELS.get(label)
            if kind is None:
                continue
            start, end = int(ent["start"]), int(ent["end"])
            out.append(Finding(kind, start, end, text[start:end], "ner"))
        return out
