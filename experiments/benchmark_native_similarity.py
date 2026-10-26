"""Compare Python difflib with the optional Rust similarity implementation.

Run after building/installing the optional extension:
  python experiments/benchmark_native_similarity.py --pairs 5000 --iterations 9

The benchmark uses deterministic synthetic title pairs; it does not call APIs or
read NekoTrack's database. It refuses to report a Rust speedup if the extension
is not actually loaded, and it verifies every result against difflib first.
"""
from __future__ import annotations

import argparse
from difflib import SequenceMatcher
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

import native_acceleration  # noqa: E402


def build_pairs(count: int, seed: int = 20261023) -> list[tuple[str, str]]:
    rng = random.Random(seed)
    syllables = (
        "neko", "track", "anime", "manga", "novel", "rezero", "monogatari",
        "shingeki", "kimetsu", "boku", "hero", "school", "fantasy", "mystery",
        "東京", "進撃", "の", "巨人", "日常", "物語",
    )
    pairs = []
    for index in range(count):
        left_parts = [rng.choice(syllables) for _ in range(rng.randint(2, 8))]
        right_parts = list(left_parts)
        if index % 5 == 0 and right_parts:
            right_parts.pop(rng.randrange(len(right_parts)))
        elif index % 5 == 1 and right_parts:
            right_parts[rng.randrange(len(right_parts))] = rng.choice(syllables)
        elif index % 5 == 2:
            right_parts.append(rng.choice(syllables))
        else:
            right_parts = [rng.choice(syllables) for _ in range(rng.randint(2, 8))]
        pairs.append(("".join(left_parts), "".join(right_parts)))
    return pairs


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * fraction)))
    return ordered[index]


def run_benchmark(pairs: list[tuple[str, str]], iterations: int) -> dict:
    def python_score() -> list[float]:
        return [
            SequenceMatcher(None, left, right, autojunk=False).ratio()
            for left, right in pairs
        ]

    def rust_score() -> list[float]:
        return [
            native_acceleration.sequence_match_ratio(left, right)
            for left, right in pairs
        ]

    # Warm both code paths and fail before timing if any result differs.
    expected = python_score()
    actual = rust_score()
    if actual != expected:
        mismatch = next(
            i for i, (left, right) in enumerate(zip(expected, actual)) if left != right
        )
        raise AssertionError(
            f"Rust/Python similarity mismatch for pair {mismatch}: "
            f"{pairs[mismatch]!r}; expected={expected[mismatch]!r}, got={actual[mismatch]!r}"
        )

    python_samples = []
    rust_samples = []
    for iteration in range(iterations):
        modes = (("python", python_score), ("rust", rust_score))
        if iteration % 2:
            modes = tuple(reversed(modes))
        for name, operation in modes:
            started = time.perf_counter()
            output = operation()
            elapsed_ms = (time.perf_counter() - started) * 1000
            if output != expected:
                raise AssertionError(f"{name} output changed between runs")
            (python_samples if name == "python" else rust_samples).append(elapsed_ms)

    python_median = statistics.median(python_samples)
    rust_median = statistics.median(rust_samples)
    return {
        "benchmark": "difflib.SequenceMatcher vs Rust sequence_match_ratio",
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "native_backend": native_acceleration.BACKEND_NAME,
        "native_module_loaded": native_acceleration.RUST_AVAILABLE,
        "synthetic_title_pairs": len(pairs),
        "iterations_per_backend": iterations,
        "results_match_exactly": actual == expected,
        "python_difflib": {
            "median_ms": round(python_median, 3),
            "p95_ms": round(percentile(python_samples, 0.95), 3),
            "samples_ms": [round(value, 3) for value in python_samples],
        },
        "rust_extension": {
            "median_ms": round(rust_median, 3),
            "p95_ms": round(percentile(rust_samples, 0.95), 3),
            "samples_ms": [round(value, 3) for value in rust_samples],
        },
        "median_speedup_percent": round(
            (python_median - rust_median) / python_median * 100, 2
        ) if python_median > 0 else 0.0,
        "median_speedup_ratio": round(python_median / rust_median, 3) if rust_median > 0 else None,
        "warning": (
            None if native_acceleration.RUST_AVAILABLE else
            "No speedup conclusion: Rust extension was not loaded."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pairs", type=int, default=5000)
    parser.add_argument("--iterations", type=int, default=9)
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()
    if not 1 <= args.pairs <= 100_000:
        parser.error("--pairs must be between 1 and 100000")
    if not 1 <= args.iterations <= 100:
        parser.error("--iterations must be between 1 and 100")
    if not native_acceleration.RUST_AVAILABLE:
        parser.error(
            "Rust extension is not loaded. Build/install rust/nekotrack_core first; "
            "otherwise the benchmark would compare Python with its own fallback."
        )

    payload = run_benchmark(build_pairs(args.pairs), args.iterations)
    print(json.dumps(payload, indent=2))
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
