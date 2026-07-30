"""Tests for dataset schema and the review-provenance rules.

The point of separating `author` from `review_status` is that the report may
never claim a native-speaker review that did not happen. These tests hold that
line: publishability is per language, and it requires every row in that language
to carry `native_reviewed`.

    python -m pytest eval/tests -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from clarion_eval import dataset  # noqa: E402

ITEMS = dataset.load()


def _row(**overrides) -> dict:
    base = {
        "id": "t-001",
        "lang": "es",
        "text": "Este useEffect se está ejecutando varias veces en cada render.",
        "gloss": "This useEffect runs several times on every render.",
        "identifiers": ["useEffect"],
        "intent": "bug",
        "domain": "react",
        "author": "llm_drafted",
        "review_status": "unreviewed",
    }
    base.update(overrides)
    return base


class TestShippedDataset:
    def test_loads(self):
        assert len(ITEMS) == 210

    def test_six_languages_of_equal_size(self):
        stats = {s.code: s for s in dataset.language_stats(ITEMS)}
        assert set(stats) == {"fa", "ar", "zh", "ru", "es", "fr"}
        assert {s.total for s in stats.values()} == {35}

    def test_ids_are_language_prefixed_and_unique(self):
        ids = [i.id for i in ITEMS]
        assert len(set(ids)) == len(ids)
        for item in ITEMS:
            assert item.id.startswith(f"{item.lang}-"), item.id

    def test_persian_is_native_and_reviewed(self):
        persian = [i for i in ITEMS if i.lang == "fa"]
        assert all(i.author == "native" for i in persian)
        assert all(i.reviewed for i in persian)

    def test_drafted_rows_are_not_marked_reviewed(self):
        """The whole point. An LLM-drafted row must never claim native review
        without a human actually having done it."""
        for item in ITEMS:
            if item.author == "llm_drafted":
                assert not item.reviewed, f"{item.id} claims a review it did not get"

    def test_only_persian_is_publishable_today(self):
        stats = {s.code: s for s in dataset.language_stats(ITEMS)}
        assert stats["fa"].publishable
        assert not any(s.publishable for c, s in stats.items() if c != "fa")

    def test_every_identifier_was_actually_spoken(self):
        for item in ITEMS:
            for ident in item.identifiers:
                assert ident in item.text, f"{item.id}: {ident!r} not in text"


class TestFiltering:
    def test_langs_filter(self):
        subset = dataset.load(langs=["zh", "ru"])
        assert {i.lang for i in subset} == {"zh", "ru"}
        assert len(subset) == 70

    def test_alias_in_filter(self):
        assert {i.lang for i in dataset.load(langs=["zh-CN"])} == {"zh"}

    def test_unknown_lang_filter_raises(self):
        with pytest.raises(KeyError):
            dataset.load(langs=["xx"])


class TestValidation:
    def test_unknown_language_rejected(self):
        with pytest.raises(ValueError, match="Unknown language"):
            dataset.Utterance.from_dict(_row(lang="xx"), "test")

    def test_identifier_absent_from_text_rejected(self):
        with pytest.raises(ValueError, match="does not appear"):
            dataset.Utterance.from_dict(_row(identifiers=["useReducer"]), "test")

    def test_row_with_no_source_language_rejected(self):
        """An English-only row labelled `es` would score a flawless residue
        number while measuring nothing at all."""
        with pytest.raises(ValueError, match="no detectable Spanish"):
            dataset.Utterance.from_dict(
                _row(text="This useEffect runs on every render.", identifiers=[]),
                "test",
            )

    def test_bad_intent_rejected(self):
        with pytest.raises(ValueError, match="intent"):
            dataset.Utterance.from_dict(_row(intent="chore"), "test")

    def test_bad_author_rejected(self):
        with pytest.raises(ValueError, match="author"):
            dataset.Utterance.from_dict(_row(author="intern"), "test")

    def test_bad_review_status_rejected(self):
        with pytest.raises(ValueError, match="review_status"):
            dataset.Utterance.from_dict(_row(review_status="probably"), "test")

    def test_missing_lang_rejected(self):
        row = _row()
        del row["lang"]
        with pytest.raises(ValueError, match="missing field"):
            dataset.Utterance.from_dict(row, "test")


class TestLegacyMigration:
    """Older dataset files carried a single `reviewed` boolean. They still load."""

    def test_legacy_true_maps_to_native_reviewed(self):
        row = _row(reviewed=True)
        del row["review_status"]
        assert dataset.Utterance.from_dict(row, "test").review_status == "native_reviewed"

    def test_legacy_false_maps_to_unreviewed(self):
        row = _row(reviewed=False)
        del row["review_status"]
        assert dataset.Utterance.from_dict(row, "test").review_status == "unreviewed"

    def test_absent_review_information_defaults_to_unreviewed(self):
        row = _row()
        del row["review_status"]
        assert not dataset.Utterance.from_dict(row, "test").reviewed
