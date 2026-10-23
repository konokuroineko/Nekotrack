"""Benchmark indexed TV-title-prefix grouping against its former all-pairs scan.

Run from the repository root:
  python experiments/benchmark_series_prefix.py --candidate-sizes 100 500 1000 2000 --iterations 5

Only deterministic synthetic normalized title keys are used. No SQLite database,
network calls, or user library are accessed.
"""
from __future__ import annotations

import argparse
import json
import platform
import random
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import series  # noqa: E402


def build_title_keys(count: int, seed: int = 20261023) -> list[str]:
    rng = random.Random(seed)
    keys = []
    variants = (
        lambda family: f"franchise {family}",
        lambda family: f"franchise {family} season two",
        lambda family: f"franchise {family} season two part two",
        lambda family: f"franchise {family} ova",
    )
    for index in range(count):
        family = index // len(variants)
        variant = variants[index % len(variants)]
        key = variant(family)
        # Add short and unrelated labels like real provider results can contain.
        if index % 37 == 0:
            key = f"unrelated {index} {rng.choice(('special', 'arc', 'edition'))}"
        elif index % 53 == 0:
            key = "single"
        keys.append(key)
    return keys


def reference_all_pairs(keys: list[str]) -> tuple[list[tuple[str, ...]], list[list[int]]]:
    token_lists = [tuple(str(key or "").split()) for key in keys]
    results = []
    for tokens in token_lists:
        matches = []
        if len(tokens) >= 2:
            for other_index, other_tokens in enumerate(token_lists):
                if len(other_tokens) < 2:
                    continue
                shorter, longer = (
                    (tokens, other_tokens)
                    if len(tokens) <= len(other_tokens)
                    else (other_tokens, tokens)
                )
                if longer[:len(shorter)] == shorter:
                    matches.append(other_index)
        results.append(matches)
    return token_lists, results


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    position = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * fraction)))
    return ordered[position]


def run_one_size(count: int, iterations: int) -> dict:
    keys = build_title_keys(count)
    expected = reference_all_pairs(keys)
    actual = series._prefix_related_tv_candidate_indices(keys)
    if actual != expected:
        raise AssertionError(f"indexed candidates differ from reference for {count} titles")

    reference_samples = []
    indexed_samples = []
    for iteration in range(iterations):
        modes = ("reference", "indexed") if iteration % 2 == 0 else ("indexed", "reference")
        for mode in modes:
            started = time.perf_counter()
            result = (
                reference_all_pairs(keys)
                if mode == "reference"
                else series._prefix_related_tv_candidate_indices(keys)
            )
            elapsed_ms = (time.perf_counter() - started) * 1000
            if result != expected:
                raise AssertionError(f"{mode} output changed for {count} titles")
            (reference_samples if mode == "reference" else indexed_samples).append(elapsed_ms)

    reference_median = statistics.median(reference_samples)
    indexed_median = statistics.median(indexed_samples)
    candidate_pairs = sum(len(row) for row in actual[1])
    return {
        "input_titles": count,
        "possible_all_pairs": count * count,
        "prefix_candidate_entries": candidate_pairs,
        "outputs_match_exactly": actual == expected,
        "reference_all_pairs_scan": {
            "median_ms": round(reference_median, 3),
            "p95_ms": round(percentile(reference_samples, 0.95), 3),
        },
        "indexed_prefix_candidates": {
            "median_ms": round(indexed_median, 3),
            "p95_ms": round(percentile(indexed_samples, 0.95), 3),
        },
        "median_speedup_ratio": round(reference_median / indexed_median, 3)
        if indexed_median > 0 else None,
        "median_speedup_percent": round(
            (reference_median - indexed_median) / reference_median * 100, 2
        ) if reference_median > 0 else 0.0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-sizes", nargs="+", type=int, default=[100, 500, 1000, 2000])
    parser.add_argument("--iterations", type=int, default=5)
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()
    if any(size < 1 or size > 10000 for size in args.candidate_sizes):
        parser.error("candidate sizes must be between 1 and 10000")
    if not 1 <= args.iterations <= 50:
        parser.error("--iterations must be between 1 and 50")

    payload = {
        "benchmark": "series._prefix_related_tv_candidate_indices",
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "workload": "deterministic synthetic title keys; no network or user database",
        "iterations_per_mode": args.iterations,
        "results": [run_one_size(count, args.iterations) for count in args.candidate_sizes],
    }
    print(json.dumps(payload, indent=2))
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
