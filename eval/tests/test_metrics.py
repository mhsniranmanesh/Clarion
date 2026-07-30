"""Tests for the deterministic metrics.

These matter more than usual: the headline claims rest on these functions, so a
silent bug here would mean publishing wrong numbers.

    python -m pytest eval/tests -q
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from clarion_eval import metrics  # noqa: E402


class TestIdentifierRecall:
    def test_plain_occurrence(self):
        score = metrics.score_identifiers(["useState"], "Migrate to useState here.")
        assert score.recall == 1.0

    def test_wrapped_in_punctuation_still_counts(self):
        for text in [
            "call `useState` please",
            "call useState() please",
            "call (useState), please",
            'the "useState" hook',
            "useState",
        ]:
            score = metrics.score_identifiers(["useState"], text)
            assert score.recall == 1.0, text

    def test_substring_of_larger_token_does_not_count(self):
        score = metrics.score_identifiers(["useState"], "we use myUseStateWrapper")
        assert score.recall == 0.0
        assert score.missing == ["useState"]

    def test_case_error_is_distinguished_from_loss(self):
        score = metrics.score_identifiers(["useState"], "call usestate")
        assert score.recall == 0.0
        assert score.recall_case_insensitive == 1.0
        assert score.case_only_errors == ["useState"]
        assert score.missing == []

    def test_dotted_and_snake_identifiers(self):
        score = metrics.score_identifiers(
            ["np.array", "get_user_by_id"],
            "Use np.array and then get_user_by_id.",
        )
        assert score.recall == 1.0

    def test_regex_metacharacters_are_literal(self):
        score = metrics.score_identifiers(["a+b"], "the a+b helper")
        assert score.recall == 1.0

    def test_empty_identifier_list_is_perfect(self):
        assert metrics.score_identifiers([], "anything").recall == 1.0


class TestScript:
    """Per-language behaviour lives in test_languages.py; these cover the
    default path and the shape of the result."""

    def test_clean_english_has_no_residue(self):
        score = metrics.score_script("Fix the login button so it submits once.")
        assert score.fully_english
        assert score.residual_chars == 0

    def test_persian_residue_detected(self):
        score = metrics.score_script("Fix the دکمه so it works")  # 4 Persian chars
        assert not score.fully_english
        assert score.residual_chars == 4
        assert score.residual_sample == "دکمه"

    def test_persian_digits_count_as_residue(self):
        assert metrics.score_script("retry ۳ times").residual_chars == 1

    def test_language_is_selectable(self):
        assert metrics.score_script("修复按钮", "zh").residual_chars == 4
        assert metrics.score_script("修复按钮", "fa").residual_chars == 0


class TestFormat:
    def test_clean_output(self):
        assert metrics.score_format("Add a retry to the upload handler.").clean

    def test_first_person_opening_is_not_a_violation(self):
        # A structured prompt legitimately starts this way; flagging it would
        # penalise correct behaviour.
        for text in [
            "I want to add pagination to the users list.",
            "I have a bug where the modal does not close.",
        ]:
            assert metrics.score_format(text).clean, text

    def test_preamble_flagged(self):
        score = metrics.score_format("Here is the structured prompt:\n\nAdd retries.")
        assert not score.clean
        assert "leading_here_is" in score.violations

    def test_code_fence_flagged(self):
        assert "wrapped_in_code_fence" in metrics.score_format("```\nAdd retries\n```").violations

    def test_trailing_offer_flagged(self):
        score = metrics.score_format("Add retries.\n\nLet me know if you want tests.")
        assert "trailing_offer" in score.violations


class TestAggregate:
    def test_empty_output_is_marked(self):
        result = metrics.score_all("", ["useState"], "gloss here")
        assert result.empty_output
        assert result.to_dict()["identifier_recall"] == 0.0

    def test_round_trip_dict_shape(self):
        result = metrics.score_all("Use useState.", ["useState"], "Use useState.")
        payload = result.to_dict()
        for field in (
            "lang",
            "identifier_recall",
            "residual_source_chars",
            "residual_method",
            "residual_exact",
            "fully_english",
            "format_clean",
            "length_ratio",
        ):
            assert field in payload

    def test_language_reaches_the_record(self):
        """The report splits by `lang`, so it has to survive into the run file."""
        payload = metrics.score_all("Use useState.", [], "gloss", "fr").to_dict()
        assert payload["lang"] == "fr"
        assert payload["residual_method"] == "function_words"
        assert payload["residual_exact"] is False

    def test_script_language_is_marked_exact(self):
        payload = metrics.score_all("Use useState.", [], "gloss", "ru").to_dict()
        assert payload["residual_method"] == "script"
        assert payload["residual_exact"] is True
