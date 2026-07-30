"""Dataset loading and validation.

Two fields govern how much a row's numbers can be trusted, and they are
deliberately separate:

    author        who wrote the utterance — `native` or `llm_drafted`
    review_status whether a native speaker has since checked it —
                  `native_reviewed` or `unreviewed`

They were one boolean once. Splitting them is what makes a six-language dataset
honest: the maintainer is a native Persian speaker and can legitimately sign off
on the Persian rows, but cannot personally vouch for the Chinese, Russian,
Arabic, Spanish or French ones. Collapsing "nobody has checked this" and "a
native speaker wrote it" into a single `reviewed: true` would let the report
claim a review that never happened.

Publishability is therefore decided per language, not for the dataset as a
whole — see `language_stats()`.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from . import languages

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
DEFAULT_DATASET = DATA_DIR / "utterances.jsonl"

VALID_INTENTS = {"bug", "feature", "refactor", "question", "ops"}
VALID_AUTHORS = {"native", "llm_drafted"}
VALID_REVIEW_STATUS = {"native_reviewed", "unreviewed"}


@dataclass
class Utterance:
    id: str
    lang: str
    text: str
    gloss: str
    identifiers: list[str]
    intent: str
    domain: str
    author: str
    review_status: str
    notes: str = ""

    @property
    def reviewed(self) -> bool:
        """Native-speaker reviewed. The only status that licenses publication."""
        return self.review_status == "native_reviewed"

    @property
    def language(self) -> languages.Language:
        return languages.get(self.lang)

    @classmethod
    def from_dict(cls, raw: dict, source: str) -> "Utterance":
        missing = [
            f
            for f in ("id", "lang", "text", "gloss", "identifiers", "intent", "domain")
            if f not in raw
        ]
        if missing:
            raise ValueError(f"{source}: entry missing field(s): {', '.join(missing)}")

        try:
            language = languages.get(raw["lang"])
        except KeyError as exc:
            raise ValueError(f"{source}: id={raw['id']}: {exc}") from exc

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

        # A dataset row must contain the language it claims to be in, or the
        # residue metric is measuring nothing. Caught here rather than silently
        # producing a flawless-looking score on an English-only "Persian" row.
        if not _contains_source_language(raw["text"], language):
            raise ValueError(
                f"{source}: id={raw['id']} is marked lang={language.code} but its text "
                f"contains no detectable {language.name}. Either the row is mislabelled "
                "or it was never code-switched."
            )

        author = raw.get("author", "native")
        if author not in VALID_AUTHORS:
            raise ValueError(
                f"{source}: id={raw['id']} has author={author!r}; "
                f"expected one of {sorted(VALID_AUTHORS)}"
            )

        review_status = _resolve_review_status(raw, source)

        return cls(
            id=str(raw["id"]),
            lang=language.code,
            text=raw["text"],
            gloss=raw["gloss"],
            identifiers=list(raw["identifiers"]),
            intent=raw["intent"],
            domain=raw["domain"],
            author=author,
            review_status=review_status,
            notes=raw.get("notes", ""),
        )


def _resolve_review_status(raw: dict, source: str) -> str:
    """Reads `review_status`, accepting the legacy `reviewed` boolean.

    Older dataset files carried `reviewed: true|false`. Those map cleanly onto
    the new vocabulary, so an old file still loads rather than failing.
    """
    if "review_status" in raw:
        status = raw["review_status"]
        if status not in VALID_REVIEW_STATUS:
            raise ValueError(
                f"{source}: id={raw['id']} has review_status={status!r}; "
                f"expected one of {sorted(VALID_REVIEW_STATUS)}"
            )
        return status

    if "reviewed" in raw:
        return "native_reviewed" if raw["reviewed"] else "unreviewed"

    return "unreviewed"


def _contains_source_language(text: str, lang: languages.Language) -> bool:
    from .metrics import score_script

    return score_script(text, lang).residual_chars > 0


def load(path: Path | None = None, langs: list[str] | None = None) -> list[Utterance]:
    path = path or DEFAULT_DATASET
    if not path.exists():
        raise SystemExit(f"Dataset not found: {path}")

    wanted = {languages.get(c).code for c in langs} if langs else None

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
            try:
                item = Utterance.from_dict(raw, f"{path}:{lineno}")
            except ValueError as exc:
                raise SystemExit(str(exc)) from exc
            if item.id in seen:
                raise SystemExit(f"{path}:{lineno}: duplicate id {item.id!r}")
            seen.add(item.id)
            if wanted is None or item.lang in wanted:
                items.append(item)

    if not items:
        raise SystemExit(
            f"Dataset is empty: {path}"
            + (f" (no rows matched langs={sorted(wanted)})" if wanted else "")
        )
    return items


@dataclass
class LanguageStats:
    code: str
    name: str
    total: int
    reviewed: int
    native_authored: int
    detection: str

    @property
    def publishable(self) -> bool:
        """Every row in this language has been checked by a native speaker."""
        return self.total > 0 and self.reviewed == self.total


def language_stats(items: list[Utterance]) -> list[LanguageStats]:
    """Per-language review coverage, in registry order."""
    by_lang: dict[str, list[Utterance]] = {}
    for item in items:
        by_lang.setdefault(item.lang, []).append(item)

    stats = []
    for code in sorted(by_lang):
        rows = by_lang[code]
        lang = languages.get(code)
        stats.append(
            LanguageStats(
                code=code,
                name=lang.name,
                total=len(rows),
                reviewed=sum(1 for r in rows if r.reviewed),
                native_authored=sum(1 for r in rows if r.author == "native"),
                detection=lang.detection,
            )
        )
    return stats


def summarise(items: list[Utterance]) -> str:
    reviewed = sum(1 for i in items if i.reviewed)
    intents = Counter(i.intent for i in items)
    langs = Counter(i.lang for i in items)
    breakdown = ", ".join(f"{k}={v}" for k, v in sorted(intents.items()))
    by_lang = ", ".join(f"{k}={v}" for k, v in sorted(langs.items()))
    idents = sum(len(i.identifiers) for i in items)
    return (
        f"{len(items)} utterances across {len(langs)} languages ({by_lang}); "
        f"{reviewed} native-speaker reviewed, {idents} expected identifiers; "
        f"{breakdown}"
    )
