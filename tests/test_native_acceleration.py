"""Correctness checks for optional Rust text-similarity acceleration."""
from __future__ import annotations

from difflib import SequenceMatcher
import itertools
import random
import unittest
from unittest.mock import patch

import api
import native_acceleration


def _reference(left: str, right: str) -> float:
    return SequenceMatcher(None, left, right, autojunk=False).ratio()


class NativeAccelerationTests(unittest.TestCase):
    def test_python_fallback_matches_reference(self):
        # This check runs even in development environments without a Rust build.
        cases = [
            ("", ""),
            ("", "neko"),
            ("neko", "neko"),
            ("ab", "ba"),
            ("cats", "cast"),
            ("the same title", "the same title"),
            ("rezero", "re zero"),
            ("kimetsunoyaiba", "kimetsu no yaiba"),
            ("しんげきのきょじん", "進撃の巨人"),
            ("éclair", "eclair"),
            ("aaaaab", "baaaaa"),
            ("aaaaaaaaab", "aaaaaaaaac"),
        ]
        for left, right in cases:
            with self.subTest(left=left, right=right):
                self.assertEqual(
                    native_acceleration.sequence_match_ratio(left, right),
                    _reference(left, right),
                )

    def test_rust_matches_reference_for_exhaustive_short_sequences(self):
        if not native_acceleration.RUST_AVAILABLE:
            self.skipTest("Optional Rust extension is not built in this environment")

        alphabet = "abc"
        strings = [""]
        for length in range(1, 5):
            strings.extend(
                "".join(characters)
                for characters in itertools.product(alphabet, repeat=length)
            )

        for left in strings:
            for right in strings:
                with self.subTest(left=left, right=right):
                    self.assertEqual(
                        native_acceleration.sequence_match_ratio(left, right),
                        _reference(left, right),
                    )

    def test_rust_matches_reference_for_unicode_and_deterministic_random_inputs(self):
        if not native_acceleration.RUST_AVAILABLE:
            self.skipTest("Optional Rust extension is not built in this environment")

        rng = random.Random(20261023)
        alphabet = "abcxyz0123456789日本語かなカナéß-_ "
        cases = [
            ("東京リベンジャーズ", "東京リベンジャーズ"),
            ("しんげきのきょじん", "しんげきのきょじんしん"),
            ("aaaaaaaaaaab", "baaaaaaaaaaa"),
            ("abXYcd", "abZZcd"),
            ("the same prefix", "the same suffix"),
        ]
        for _ in range(1500):
            left = "".join(rng.choice(alphabet) for _ in range(rng.randrange(0, 81)))
            right = "".join(rng.choice(alphabet) for _ in range(rng.randrange(0, 81)))
            cases.append((left, right))

        for left, right in cases:
            with self.subTest(left=left, right=right):
                self.assertEqual(
                    native_acceleration.sequence_match_ratio(left, right),
                    _reference(left, right),
                )


    def test_api_title_similarity_preserves_tmdb_matching_scores(self):
        def reference_title_similarity(left, right):
            name = api._normalize_title(left)
            query = api._normalize_title(right)
            if not name or not query:
                return 0.0
            if name == query:
                return 1.0
            if name in query or query in name:
                containment = min(len(name), len(query)) / max(len(name), len(query))
                return 0.72 + 0.28 * containment
            return _reference(name, query)

        cases = [
            ("Re:Zero", "Re: Zero"),
            ("Shingeki no Kyojin", "進撃の巨人"),
            ("進撃の巨人", "進撃の巨人"),
            ("The Title 2", "The Title"),
            ("", "No title"),
            ("Monogatari Series", "Monogatari Series Second Season"),
            ("Éclair", "eclair"),
        ]
        for left, right in cases:
            with self.subTest(left=left, right=right):
                self.assertEqual(
                    api._title_similarity(left, right),
                    reference_title_similarity(left, right),
                )

    def test_default_autojunk_compatible_matcher_matches_python_reference(self):
        short_cases = [
            ("", ""),
            ("My Hero Academia", "My Hero Academi"),
            ("東京物語", "東京物語"),
            ("進撃の巨人", "進撃の巨人 season two"),
            ("aaaaaaaaab", "baaaaaaaa"),
        ]
        for left, right in short_cases:
            with self.subTest(left=left, right=right):
                self.assertEqual(
                    native_acceleration.sequence_match_ratio_default(left, right),
                    SequenceMatcher(None, left, right).ratio(),
                )

        # difflib's default autojunk changes behavior when the right-hand
        # sequence reaches 200 characters and has popular repeated elements.
        left = "x" * 210 + "y"
        right = "y" + "x" * 210
        expected = SequenceMatcher(None, left, right).ratio()
        without_autojunk = SequenceMatcher(None, left, right, autojunk=False).ratio()
        self.assertNotEqual(expected, without_autojunk)
        self.assertEqual(
            native_acceleration.sequence_match_ratio_default(left, right),
            expected,
        )

    def test_rust_default_compatible_matcher_matches_mangabaka_short_titles(self):
        if not native_acceleration.RUST_AVAILABLE:
            self.skipTest("Optional Rust extension is not built in this environment")
        rng = random.Random(20261024)
        alphabet = "abcdef0123456789日本語かなカナ -"
        cases = [
            ("My Hero Academia", "My Hero Academi"),
            ("Re Zero Kara Hajimeru Isekai Seikatsu", "Re Zero Kara Hajimeru Isekai Seikatsu"),
            ("進撃の巨人", "進撃の巨人 season two"),
        ]
        for _ in range(1000):
            left = "".join(rng.choice(alphabet) for _ in range(rng.randrange(0, 100)))
            right = "".join(rng.choice(alphabet) for _ in range(rng.randrange(0, 100)))
            cases.append((left, right))
        for left, right in cases:
            with self.subTest(left=left, right=right):
                self.assertEqual(
                    native_acceleration.sequence_match_ratio_default(left, right),
                    SequenceMatcher(None, left, right).ratio(),
                )

    def test_mangabaka_series_matching_uses_compatible_fuzzy_matcher(self):
        candidate = {"id": 99, "english_title": "My Hero Academi"}
        media = {
            "id": 1,
            "title": {"english": "My Hero Academia", "romaji": None, "native": None},
            "synonyms": [],
        }
        with patch(
            "api.sequence_match_ratio_default",
            wraps=native_acceleration.sequence_match_ratio_default,
        ) as matcher:
            result = api.match_series_for_anilist(media, [candidate])
        self.assertIs(result, candidate)
        matcher.assert_called()

    def test_repeated_title_normalization_uses_bounded_caches(self):
        api._normalize_title_text.cache_clear()
        api._normalize_title("NekoTrack: 東京物語")
        api._normalize_title("NekoTrack: 東京物語")
        self.assertGreaterEqual(api._normalize_title_text.cache_info().hits, 1)
        self.assertEqual(api._normalize_title_text.cache_info().maxsize, 8192)

        api._normalize_mangabaka_title_text.cache_clear()
        api._mangabaka_normalize_title("Re:Zero Kara Hajimeru")
        api._mangabaka_normalize_title("Re:Zero Kara Hajimeru")
        self.assertGreaterEqual(api._normalize_mangabaka_title_text.cache_info().hits, 1)
        self.assertEqual(api._normalize_mangabaka_title_text.cache_info().maxsize, 8192)

    def test_backend_indicator_matches_loaded_extension(self):
        self.assertEqual(
            native_acceleration.BACKEND_NAME,
            "rust" if native_acceleration.RUST_AVAILABLE else "python",
        )
        self.assertEqual(
            native_acceleration.RUST_AVAILABLE,
            native_acceleration._native_sequence_match_ratio is not None,
        )


if __name__ == "__main__":
    unittest.main()
