"""Correctness checks for optional Rust text-similarity acceleration."""
from __future__ import annotations

from difflib import SequenceMatcher
import itertools
import re
import random
import unittest

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
            name = re.sub(r"[\\W_]+", "", str(left or "").casefold(), flags=re.UNICODE)
            query = re.sub(r"[\\W_]+", "", str(right or "").casefold(), flags=re.UNICODE)
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
