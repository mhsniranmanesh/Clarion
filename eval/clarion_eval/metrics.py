"""Deterministic metrics.

These carry the headline claims. They are pure functions of (input, output) with
no model in the loop, so anyone can recompute them from the committed run files
and get byte-identical numbers.

The LLM-judged scores in `judge.py` are reported alongside, but deliberately as
secondary evidence.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass, field

from . import languages

# ── Identifier preservation ──────────────────────────────────────────────────

_WORD = "A-Za-z0-9_"


def _occurs(identifier: str, text: str, *, fold_case: bool = False) -> bool:
    """True if `identifier` appears in `text` as a standalone token.

    Boundary-aware so `useState` matches in `useState()`, `` `useState` `` and
    "the useState hook", but not inside `myUseStateThing`. Dotted and
    snake_cased identifiers work because the identifier is escaped literally.
    """
    flags = re.IGNORECASE if fold_case else 0
    pattern = re.compile(
        rf"(?<![{_WORD}]){re.escape(identifier)}(?![{_WORD}])", flags
    )
    return bool(pattern.search(text))


@dataclass
class IdentifierScore:
    total: int
    preserved: int
    preserved_case_insensitive: int
    missing: list[str]
    case_only_errors: list[str]

    @property
    def recall(self) -> float:
        return self.preserved / self.total if self.total else 1.0

    @property
    def recall_case_insensitive(self) -> float:
        return (
            self.preserved_case_insensitive / self.total if self.total else 1.0
        )


def score_identifiers(identifiers: list[str], output: str) -> IdentifierScore:
    """Exact-match recall of technical tokens that must survive translation.

    Case-sensitive recall is the reported metric, because `useState` and
    `usestate` are different symbols to a compiler. Case-insensitive recall is
    tracked too, so a model that kept the word but mangled the casing is
    distinguishable from one that dropped it entirely.
    """
    missing: list[str] = []
    case_only: list[str] = []
    preserved = 0
    preserved_ci = 0

    for ident in identifiers:
        exact = _occurs(ident, output)
        loose = _occurs(ident, output, fold_case=True)
        if exact:
            preserved += 1
        if loose:
            preserved_ci += 1
        if not exact:
            (case_only if loose else missing).append(ident)

    return IdentifierScore(
        total=len(identifiers),
        preserved=preserved,
        preserved_case_insensitive=preserved_ci,
        missing=missing,
        case_only_errors=case_only,
    )


# ── Residual source language ─────────────────────────────────────────────────


@dataclass
class ScriptScore:
    residual_chars: int
    residual_sample: str
    method: str = "script"
    markers: list[str] = field(default_factory=list)

    @property
    def fully_english(self) -> bool:
        return self.residual_chars == 0

    @property
    def exact(self) -> bool:
        """True when the verdict is a proof, not a heuristic.

        Script detection cannot produce a false positive: a Han or Cyrillic
        codepoint in the output is untranslated source, full stop. Function-word
        detection can in principle misfire, so it is labelled differently
        everywhere it is reported.
        """
        return self.method == "script"


def _score_by_script(output: str, lang: languages.Language) -> ScriptScore:
    residual = [
        ch
        for ch in output
        if any(lo <= ord(ch) <= hi for lo, hi in lang.ranges)
    ]
    return ScriptScore(
        residual_chars=len(residual),
        residual_sample="".join(residual[:60]),
        method="script",
    )


# Words are compared lowercased and apostrophe-normalised, so `C'est` and `c’est`
# both match the marker `c'est`.
_TOKEN = re.compile(r"[^\W\d_]+(?:['’][^\W\d_]+)?", re.UNICODE)


def _score_by_function_words(output: str, lang: languages.Language) -> ScriptScore:
    hits: list[str] = []

    for raw in _TOKEN.findall(output):
        token = raw.lower().replace("’", "'")
        if token in lang.words:
            hits.append(raw)

    hits += [ch for ch in output if ch in lang.chars]

    normalised = output.replace("’", "'")
    for pattern in lang.patterns:
        hits += re.findall(pattern, normalised, re.IGNORECASE)

    return ScriptScore(
        residual_chars=len(hits),
        residual_sample=" ".join(hits[:20]),
        method="function_words",
        markers=sorted({h.lower() for h in hits}),
    )


def score_script(output: str, lang: str | languages.Language = "fa") -> ScriptScore:
    """Detects source-language text surviving into an output that must be English.

    Dispatches on the language's declared detection method. For script languages
    a correct answer has exactly zero residue and the check is exact. For
    Latin-script languages it counts high-frequency source-language function
    words, which is a heuristic — `ScriptScore.exact` says which you got, and the
    report prints the two in separate columns.
    """
    language = lang if isinstance(lang, languages.Language) else languages.get(lang)
    if language.detection == "script":
        return _score_by_script(output, language)
    return _score_by_function_words(output, language)


# ── Format compliance ────────────────────────────────────────────────────────

# Deliberately conservative. A structured prompt legitimately often begins "I
# want..." or "I have a bug where...", so first-person openings are NOT flagged.
# Only unambiguous meta-commentary counts as a violation.
_PREAMBLE_PATTERNS = [
    (r"^\s*here(?:'s| is| are)\s+(?:the|your|a|an)\b", "leading_here_is"),
    (r"^\s*(?:sure|certainly|of course|okay|alright)\s*[,.!:]", "leading_filler"),
    (r"^\s*below is\b", "leading_below_is"),
    (r"^\s*structured\s+(?:english\s+)?prompt\s*:", "echoes_label"),
    (r"^\s*```", "wrapped_in_code_fence"),
]

_TRAILING_PATTERNS = [
    (r"\blet me know if\b", "trailing_offer"),
    (r"\bhope this helps\b", "trailing_offer"),
    (r"\bwould you like me to\b", "trailing_offer"),
]


@dataclass
class FormatScore:
    violations: list[str]

    @property
    def clean(self) -> bool:
        return not self.violations


def score_format(output: str) -> FormatScore:
    """Detects preamble and commentary the shared prompt explicitly forbids.

    Reported separately from quality so that a model losing points purely for a
    formatting tic is visible as such, rather than being silently marked down as
    a worse translator.
    """
    violations: list[str] = []
    for pattern, name in _PREAMBLE_PATTERNS:
        if re.search(pattern, output, re.IGNORECASE):
            violations.append(name)
    for pattern, name in _TRAILING_PATTERNS:
        if re.search(pattern, output, re.IGNORECASE):
            violations.append(name)
    return FormatScore(violations=sorted(set(violations)))


# ── Length ───────────────────────────────────────────────────────────────────


def _word_count(text: str) -> int:
    return len([t for t in re.split(r"\s+", text.strip()) if t])


def length_ratio(output: str, reference: str) -> float:
    """Output length over reference-gloss length. Catches truncation (<<1) and
    padding (>>1); neither is penalised directly, it is a diagnostic."""
    ref = _word_count(reference)
    return _word_count(output) / ref if ref else 0.0


# ── Aggregate ────────────────────────────────────────────────────────────────


@dataclass
class DeterministicScores:
    identifiers: IdentifierScore
    script: ScriptScore
    fmt: FormatScore
    length_ratio: float
    empty_output: bool
    lang: str

    def to_dict(self) -> dict:
        return {
            "lang": self.lang,
            "identifier_recall": round(self.identifiers.recall, 4),
            "identifier_recall_ci": round(
                self.identifiers.recall_case_insensitive, 4
            ),
            "identifiers_total": self.identifiers.total,
            "identifiers_preserved": self.identifiers.preserved,
            "identifiers_missing": self.identifiers.missing,
            "identifiers_case_only_errors": self.identifiers.case_only_errors,
            "residual_source_chars": self.script.residual_chars,
            "residual_source_sample": self.script.residual_sample,
            "residual_method": self.script.method,
            "residual_markers": self.script.markers,
            "residual_exact": self.script.exact,
            "fully_english": self.script.fully_english,
            "format_clean": self.fmt.clean,
            "format_violations": self.fmt.violations,
            "length_ratio": round(self.length_ratio, 3),
            "empty_output": self.empty_output,
        }


def score_all(
    output: str, identifiers: list[str], gloss: str, lang: str = "fa"
) -> DeterministicScores:
    normalised = unicodedata.normalize("NFC", output or "")
    return DeterministicScores(
        identifiers=score_identifiers(identifiers, normalised),
        script=score_script(normalised, lang),
        fmt=score_format(normalised),
        length_ratio=length_ratio(normalised, gloss),
        empty_output=not normalised.strip(),
        lang=languages.get(lang).code,
    )


__all__ = [
    "DeterministicScores",
    "FormatScore",
    "IdentifierScore",
    "ScriptScore",
    "asdict",
    "score_all",
    "score_format",
    "score_identifiers",
    "score_script",
]
