"""Paired benchmark for compiled vs module-level title normalization regexes.

Uses deterministic synthetic title strings only. No database, network, or user data.
Both algorithms return normalized title-family keys and must match exactly.
"""
from __future__ import annotations

import argparse
import json
import platform
import re
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PATTERN_SPECS = (
    (
        r"\s*[:\-–—]?\s*(?:the\s+)?final\s+season(?:\s+part\s+\d+)?(?:\s+\([^)]*\))?\s*$",
        "",
    ),
    (
        r"\s*[:\-–—]?\s*(?:\d+(?:st|nd|rd|th)|season\s*\d+|series\s*\d+|season\s*[ivx]+|series\s*[ivx]+)(?:\s+part\s+\d+)?\s*$",
        "",
    ),
    (r"(?:^|\s)(?:ii|iii|iv|v|vi)\s*[:\-–—]\s*", " "),
    (
        r"\s+(?:i|ii|iii|iv|v|vi|1st|2nd|3rd|4th|5th)\s*(?:season)?\s*$",
        "",
    ),
    (r"\s*[:\-–—]?\s*(?:part|cour)\s*\d+\s*$", ""),
    (r"\s+\d+$", ""),
    (r"\s+", " "),
)
COMPILED_PATTERN_SPECS = tuple((re.compile(pattern), replacement) for pattern, replacement in PATTERN_SPECS)
FINAL_KEY_PATTERN = re.compile(r"[^a-z0-9]+")


def normalize_with_re_sub(title: object) -> str:
    value = str(title or "").lower().strip()
    for pattern, replacement in PATTERN_SPECS:
        value = re.sub(pattern, replacement, value)
    value = value.strip()
    return re.sub(r"[^a-z0-9]+", " ", value).strip()


def normalize_with_compiled_patterns(title: object) -> str:
    value = str(title or "").lower().strip()
    for pattern, replacement in COMPILED_PATTERN_SPECS:
        value = pattern.sub(replacement, value)
    value = value.strip()
    return FINAL_KEY_PATTERN.sub(" ", value).strip()


def build_titles(count: int) -> list[str]:
    endings = (
        "Season 2 Part 3",
        "Second Season",
        "Final Season",
        "IV: The Return",
        "Cour 2",
        "Part 3",
        "Movie",
        "Season 5",
    )
    return [
        f"Synthetic Franchise {index} Saga {endings[index % len(endings)]}"
        for index in range(count)
    ]


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    position = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * fraction)))
    return ordered[position]


def paired_measure(titles: list[str], iterations: int) -> tuple[list[float], list[float]]:
    expected = [normalize_with_re_sub(title) for title in titles]
    reference_samples = []
    compiled_samples = []
    for iteration in range(iterations):
        modes = (
            (("reference", normalize_with_re_sub), ("compiled", normalize_with_compiled_patterns))
            if iteration % 2 == 0 else
            (("compiled", normalize_with_compiled_patterns), ("reference", normalize_with_re_sub))
        )
        for mode, function in modes:
            started = time.perf_counter()
            result = [function(title) for title in titles]
            elapsed = (time.perf_counter() - started) * 1000
            if result != expected:
                raise AssertionError(f"{function.__name__} changed normalized output")
            (reference_samples if mode == "reference" else compiled_samples).append(elapsed)
    return reference_samples, compiled_samples


def benchmark_size(count: int, iterations: int) -> dict:
    titles = build_titles(count)
    reference = [normalize_with_re_sub(title) for title in titles]
    compiled = [normalize_with_compiled_patterns(title) for title in titles]
    if compiled != reference:
        raise AssertionError(f"compiled pattern outputs differ for {count} titles")

    reference_samples, compiled_samples = paired_measure(titles, iterations)
    reference_median = statistics.median(reference_samples)
    compiled_median = statistics.median(compiled_samples)
    return {
        "unique_titles": count,
        "results_match_exactly": True,
        "module_re_sub": {
            "median_ms": round(reference_median, 3),
            "p95_ms": round(percentile(reference_samples, 0.95), 3),
        },
        "compiled_pattern_sub": {
            "median_ms": round(compiled_median, 3),
            "p95_ms": round(percentile(compiled_samples, 0.95), 3),
        },
        "speedup_ratio": round(reference_median / compiled_median, 3)
        if compiled_median > 0 else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--title-counts", nargs="+", type=int, default=[1000, 5000, 10000])
    parser.add_argument("--iterations", type=int, default=7)
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()
    if any(count < 1 or count > 50000 for count in args.title_counts):
        parser.error("title counts must be between 1 and 50000")
    if not 1 <= args.iterations <= 20:
        parser.error("iterations must be between 1 and 20")

    payload = {
        "benchmark": "paired title normalization re.sub vs compiled patterns",
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "workload": "unique deterministic franchise titles with season/part/cour suffixes",
        "iterations_per_mode": args.iterations,
        "results": [benchmark_size(count, args.iterations) for count in args.title_counts],
    }
    print(json.dumps(payload, indent=2))
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
