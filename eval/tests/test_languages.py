"""Tests for multilingual residue detection.

The Spanish and French detectors are the reason this file exists. Script
detection cannot be wrong — a Han codepoint in an English sentence is
untranslated source, and that is the end of it. Function-word detection *can* be
wrong in both directions, and both directions corrupt a published number:

  false positive  a correct English output flagged as untranslated, marking a
                  model down for work it did correctly
  false negative  a Spanish sentence passed through untouched and scored as
                  "fully English", which is the failure the metric exists to catch

So the word lists are not asserted to be good, they are *measured* against the
dataset the harness actually runs on: every English gloss must come back clean,
and every Spanish and French utterance must trip its own detector with margin.
Adding a marker word that collides with English breaks these tests.

    python -m pytest eval/tests -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from clarion_eval import dataset, languages, metrics  # noqa: E402

ITEMS = dataset.load()
LATIN = [c for c in languages.codes() if languages.get(c).detection == "function_words"]

# Real English structuring output, of the shape the models actually produce.
# Includes the constructions most likely to trip a Romance-language word list:
# Latin borrowings, proper nouns, locale codes and code identifiers.
ENGLISH_SAMPLES = [
    "This useEffect is running multiple times. I want it to run once on mount.",
    "The compiler reports cannot borrow as mutable and I do not understand why.",
    "Add a rate limit on the login endpoint, five attempts per minute per IP.",
    "Set the locale to es-ES and fr-FR, then re-run the suite.",
    "This is de facto the standard approach; the son of the root node is null.",
    "Par for the course — the la carte menu parser chokes on a lone quote.",
    "Use np.array and get_user_by_id, then compare on par with the baseline.",
    "The deploy failed with exit code 137; the container ran out of memory.",
    "I want stricter types. Turn on strict in tsconfig and fix the errors.",
    "Write a script that converts every .png in the assets folder to webp.",
    "O'clock formatting breaks in the CI timezone. Don't we normalise it?",
    "It's the user's session that's stale, and we've seen this before.",
]


class TestRegistry:
    def test_every_language_declares_a_working_detector(self):
        for code in languages.codes():
            lang = languages.get(code)
            if lang.detection == "script":
                assert lang.ranges, f"{code} uses script detection but declares no ranges"
            else:
                assert lang.words, f"{code} uses word detection but declares no words"

    def test_aliases_resolve(self):
        assert languages.get("zh-CN").code == "zh"
        assert languages.get("fra").code == "fr"
        assert languages.get("es-ES").code == "es"

    def test_unknown_code_raises(self):
        with pytest.raises(KeyError):
            languages.get("xx")

    def test_exact_detection_is_the_non_latin_set(self):
        assert set(languages.exact_detection()) == {"fa", "ar", "zh", "ru"}


class TestScriptDetection:
    def test_clean_english_has_no_residue(self):
        for code in languages.exact_detection():
            score = metrics.score_script("Fix the login button so it submits once.", code)
            assert score.fully_english, code
            assert score.exact

    def test_persian_residue(self):
        score = metrics.score_script("Fix the دکمه so it works", "fa")
        assert not score.fully_english
        assert score.residual_chars == 4
        assert score.residual_sample == "دکمه"

    def test_persian_digits_count(self):
        assert metrics.score_script("retry ۳ times", "fa").residual_chars == 1

    def test_chinese_residue(self):
        score = metrics.score_script("Fix the 按钮 please", "zh")
        assert not score.fully_english
        assert score.residual_chars == 2

    def test_chinese_punctuation_counts(self):
        # A trailing 。 is the most common residue in a mostly-translated output.
        assert metrics.score_script("Fix the button。", "zh").residual_chars == 1

    def test_russian_residue(self):
        score = metrics.score_script("Fix the кнопка please", "ru")
        assert not score.fully_english
        assert score.residual_chars == 6

    def test_scripts_do_not_cross_detect(self):
        """A Cyrillic output must not register on the Han detector, or a
        per-language residue number would be measuring the wrong alphabet."""
        assert metrics.score_script("кнопка", "zh").residual_chars == 0
        assert metrics.score_script("按钮", "ru").residual_chars == 0
        assert metrics.score_script("دکمه", "ru").residual_chars == 0


class TestFunctionWordDetection:
    def test_flagged_as_heuristic(self):
        for code in LATIN:
            assert not metrics.score_script("anything", code).exact

    def test_untranslated_spanish_is_caught(self):
        score = metrics.score_script(
            "Este useEffect se está ejecutando varias veces en cada render.", "es"
        )
        assert not score.fully_english
        assert "este" in score.markers

    def test_untranslated_french_is_caught(self):
        score = metrics.score_script(
            "Cette fonction est appelée plusieurs fois dans le rendu.", "fr"
        )
        assert not score.fully_english
        assert "cette" in score.markers

    def test_french_elision_alone_is_enough(self):
        """The signal that word lists miss: an otherwise technical sentence
        whose only French is an elided article."""
        score = metrics.score_script("Mets un rate limit sur l'endpoint", "fr")
        assert not score.fully_english

    def test_english_contractions_are_not_elision(self):
        for text in ["Don't retry.", "It's stale.", "We've seen this.", "O'clock parsing."]:
            assert metrics.score_script(text, "fr").fully_english, text

    def test_inverted_punctuation_is_spanish(self):
        assert not metrics.score_script("¿Por qué falla?", "es").fully_english

    @pytest.mark.parametrize("text", ENGLISH_SAMPLES)
    @pytest.mark.parametrize("code", LATIN)
    def test_no_false_positive_on_english(self, code, text):
        score = metrics.score_script(text, code)
        assert score.fully_english, (
            f"{code} detector fired on English: {score.markers} in {text!r}"
        )


class TestAgainstTheRealDataset:
    """The empirical guard. These run over the shipped dataset, so a marker word
    that collides with English fails the suite the moment it is added."""

    @pytest.mark.parametrize("code", LATIN)
    def test_no_english_gloss_trips_a_detector(self, code):
        offenders = [
            (item.id, metrics.score_script(item.gloss, code).markers)
            for item in ITEMS
            if metrics.score_script(item.gloss, code).residual_chars
        ]
        assert not offenders, f"{code} detector fired on English glosses: {offenders[:5]}"

    def test_every_utterance_trips_its_own_detector(self):
        """Guards against a mislabelled or accidentally English-only row."""
        for item in ITEMS:
            score = metrics.score_script(item.text, item.lang)
            assert score.residual_chars > 0, f"{item.id} contains no detectable {item.lang}"

    def test_latin_rows_have_margin(self):
        """One stray marker would be a coin flip. Three or more means the
        detector is reading a sentence, not a coincidence."""
        thin = [
            (item.id, metrics.score_script(item.text, item.lang).residual_chars)
            for item in ITEMS
            if item.lang in LATIN
            and metrics.score_script(item.text, item.lang).residual_chars < 3
        ]
        assert not thin, f"rows with weak language signal: {thin}"
