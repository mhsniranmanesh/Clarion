"""Dataset loading and validation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
DEFAULT_DATASET = DATA_DIR / "utterances.jsonl"

VALID_INTENTS = {"bug", "feature", "refactor", "question", "ops"}


@dataclass
class Utterance:
    id: str
    text: str
    gloss: str
    identifiers: list[str]
    intent: str
    domain: str
    reviewed: bool
    notes: str = ""

    @classmethod
    def from_dict(cls, raw: dict, source: str) -> "Utterance":
        missing = [
            f for f in ("id", "text", "gloss", "identifiers", "intent", "domain")
            if f not in raw
        ]
        if missing:
            raise ValueError(f"{source}: entry missing field(s): {', '.join(missing)}")

        if raw["intent"] not in VALID_INTENTS:
            raise ValueError(
                f"{source}: id={raw['id']} has intent={raw['intent']!r}; "
                f"expected one of {sorted(VALID_INTENTS)}"
            )

        if not isinstance(raw["identifiers"], list):
            raise ValueError(f"{source}: id={raw['id']} identifiers must be a list")

        for ident in raw["identifiers"]:
            if ident not in raw["text"]:
                raise ValueError(
                    f"{source}: id={raw['id']} lists identifier {ident!r} which does "
                    "not appear in the utterance text. Every expected identifier must "
                    "actually have been spoken, or recall is unmeasurable."
                )

        return cls(
            id=str(raw["id"]),
            text=raw["text"],
            gloss=raw["gloss"],
            identifiers=list(raw["identifiers"]),
            intent=raw["intent"],
            domain=raw["domain"],
            reviewed=bool(raw.get("reviewed", False)),
            notes=raw.get("notes", ""),
        )


def load(path: Path | None = None) -> list[Utterance]:
    path = path or DEFAULT_DATASET
    if not path.exists():
        raise SystemExit(f"Dataset not found: {path}")

    items: list[Utterance] = []
    seen: set[str] = set()
    with path.open(encoding="utf-8") as handle:
        for lineno, line in enumerate(handle, 1):
            line = line.strip()
            if not line or line.startswith("//"):
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError as exc:
                raise SystemExit(f"{path}:{lineno}: invalid JSON: {exc}") from exc
            item = Utterance.from_dict(raw, f"{path}:{lineno}")
            if item.id in seen:
                raise SystemExit(f"{path}:{lineno}: duplicate id {item.id!r}")
            seen.add(item.id)
            items.append(item)

    if not items:
        raise SystemExit(f"Dataset is empty: {path}")
    return items


def summarise(items: list[Utterance]) -> str:
    reviewed = sum(1 for i in items if i.reviewed)
    intents: dict[str, int] = {}
    for item in items:
        intents[item.intent] = intents.get(item.intent, 0) + 1
    breakdown = ", ".join(f"{k}={v}" for k, v in sorted(intents.items()))
    idents = sum(len(i.identifiers) for i in items)
    return (
        f"{len(items)} utterances ({reviewed} native-speaker reviewed), "
        f"{idents} expected identifiers; {breakdown}"
    )
