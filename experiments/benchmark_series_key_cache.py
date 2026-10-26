"""Benchmark bounded caching of repeated series-title normalization.

Uses deterministic synthetic titles only. No SQLite database, network, or user data
is accessed. Compare regex work with the production bounded cache on repeated inputs.
"""
from __future__ import annotations

import argparse
import json
import platform
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import series  # noqa: E402


def reference_series_key(title):
    """Original uncached implementation, retained here as a correctness baseline."""
    value = str(title or "").lower().strip()
    import re

    value = re.sub(
        r"\s*[:\-–—]?\s*(?:the\s+)?final\s+season(?:\s+part\s+\d+)?(?:\s+\([^)]*\))?\s*$",
        "",
        value,
    )
    value = re.sub(
        r"\s*[:\-–—]?\s*(?:\d+(?:st|nd|rd|th)|season\s*\d+|series\s*\d+|season\s*[ivx]+|series\s*[ivx]+)(?:\s+part\s+\d+)?\s*$",
        "",
        value,
    )
    value = re.sub(r"(?:^|\s)(?:ii|iii|iv|v|vi)\s*[:\-–—]\s*", " ", value)
    value = re.sub(
        r"\s+(?:i|ii|iii|iv|v|vi|1st|2nd|3rd|4th|5th)\s*(?:season)?\s*$",
        "",
        value,
    )
    value = re.sub(r"\s*[:\-–—]?\s*(?:part|cour)\s*\d+\s*$", "", value)
    value = re.sub(r"\s+\d+$", "", value)
    value = re.sub(r"\s+", " ", value).strip()
    return re.sub(r"[^a-z0-9]+", " ", value).strip()


def build_titles(unique_count: int) -> list[str]:
    return [
        f"Synthetic Franchise {index} Season {index % 5 + 1} Part {index % 3 + 1}"
        for index in range(unique_count)
    ]


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    position = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * fraction)))
    return ordered[position]


def run_one_size(unique_count: int, calls: int, iterations: int) -> dict:
    titles = build_titles(unique_count)
    inputs = [titles[index % unique_count] for index in range(calls)]
    expected = [reference_series_key(title) for title in inputs]
    series._cached_series_key.cache_clear()
    actual = [series._series_key(title) for title in inputs]
    if actual != expected:
        raise AssertionError(f"cached title keys differ from reference for {unique_count} titles")

    reference_samples = []
    cached_samples = []
    for iteration in range(iterations):
        modes = ("reference", "cached") if iteration % 2 == 0 else ("cached", "reference")
        for mode in modes:
            if mode == "cached":
                series._cached_series_key.cache_clear()
            started = time.perf_counter()
            result = (
                [reference_series_key(title) for title in inputs]
                if mode == "reference"
                else [series._series_key(title) for title in inputs]
            )
            elapsed = (time.perf_counter() - started) * 1000
            if result != expected:
                raise AssertionError(f"{mode} output changed for {unique_count} titles")
            (reference_samples if mode == "reference" else cached_samples).append(elapsed)

    reference_median = statistics.median(reference_samples)
    cached_median = statistics.median(cached_samples)
    series._cached_series_key.cache_clear()
    [series._series_key(title) for title in inputs]
    cache_info = series._cached_series_key.cache_info()
    return {
        "unique_title_count": unique_count,
        "normalization_calls": calls,
        "cache_maxsize": cache_info.maxsize,
        "cache_entries_after_run": cache_info.currsize,
        "results_match_exactly": actual == expected,
        "uncached_reference": {
            "median_ms": round(reference_median, 3),
            "p95_ms": round(percentile(reference_samples, 0.95), 3),
        },
        "bounded_cached_normalizer": {
            "median_ms": round(cached_median, 3),
            "p95_ms": round(percentile(cached_samples, 0.95), 3),
        },
        "median_speedup_ratio": round(reference_median / cached_median, 3)
        if cached_median > 0 else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--unique-title-counts", nargs="+", type=int,
        default=[100, 1000, 5000, 10000],
    )
    parser.add_argument("--calls", type=int, default=30000)
    parser.add_argument("--iterations", type=int, default=5)
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()
    if any(count < 1 or count > 100000 for count in args.unique_title_counts):
        parser.error("unique title counts must be between 1 and 100000")
    if args.calls < 1 or args.calls > 200000:
        parser.error("calls must be between 1 and 200000")
    if not 1 <= args.iterations <= 20:
        parser.error("iterations must be between 1 and 20")

    payload = {
        "benchmark": "series._series_key bounded cache",
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "workload": "deterministic synthetic title keys repeated in a fixed cycle",
        "iterations_per_mode": args.iterations,
        "results": [
            run_one_size(count, args.calls, args.iterations)
            for count in args.unique_title_counts
        ],
    }
    print(json.dumps(payload, indent=2))
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
