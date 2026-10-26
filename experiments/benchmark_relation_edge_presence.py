"""Benchmark relation-edge presence checks against filtered-list allocation.

Uses deterministic synthetic relation edges only. No API, SQLite database, or user
library is accessed. Outputs must match the production filtered-list helper exactly.
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


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * fraction)))
    return ordered[index]


def fixtures(edge_count: int) -> dict[str, dict]:
    valid = [{"relationType": "SEQUEL", "node": {"id": index + 1}} for index in range(edge_count)]
    invalid = [None if index % 2 else "malformed" for index in range(edge_count)]
    late_valid = list(invalid)
    if late_valid:
        late_valid[-1] = {"relationType": "PREQUEL", "node": {"id": edge_count + 1}}
    return {
        "empty": {"relations": {"edges": []}},
        "valid_edges": {"relations": {"edges": valid}},
        "invalid_only": {"relations": {"edges": invalid}},
        "valid_after_invalid": {"relations": {"edges": late_valid}},
    }


def run_case(item: dict, calls: int, iterations: int) -> dict:
    expected = bool(series._search_relation_edges(item))
    actual = series._has_search_relation_edges(item)
    if actual != expected:
        raise AssertionError("presence helper differs from filtered edge-list truthiness")

    reference_samples = []
    optimized_samples = []
    for iteration in range(iterations):
        modes = ("reference", "optimized") if iteration % 2 == 0 else ("optimized", "reference")
        for mode in modes:
            operation = (
                (lambda: bool(series._search_relation_edges(item)))
                if mode == "reference"
                else (lambda: series._has_search_relation_edges(item))
            )
            started = time.perf_counter()
            observed = False
            for _ in range(calls):
                observed = operation()
            elapsed_ms = (time.perf_counter() - started) * 1000
            if observed != expected:
                raise AssertionError(f"{mode} result changed")
            (reference_samples if mode == "reference" else optimized_samples).append(elapsed_ms)

    reference_median = statistics.median(reference_samples)
    optimized_median = statistics.median(optimized_samples)
    return {
        "edge_count": len((item.get("relations") or {}).get("edges") or []),
        "has_valid_edge": expected,
        "calls_per_iteration": calls,
        "filtered_list_reference": {
            "median_ms": round(reference_median, 3),
            "p95_ms": round(percentile(reference_samples, 0.95), 3),
        },
        "fast_path_presence_check": {
            "median_ms": round(optimized_median, 3),
            "p95_ms": round(percentile(optimized_samples, 0.95), 3),
        },
        "median_speedup_ratio": round(reference_median / optimized_median, 3)
        if optimized_median > 0 else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--edge-counts", nargs="+", type=int, default=[0, 3, 10, 50])
    parser.add_argument("--calls", type=int, default=30000)
    parser.add_argument("--iterations", type=int, default=7)
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()
    if any(count < 0 or count > 1000 for count in args.edge_counts):
        parser.error("edge counts must be between 0 and 1000")
    if not 1 <= args.calls <= 200000 or not 1 <= args.iterations <= 20:
        parser.error("calls or iterations outside allowed bounds")

    result_rows = []
    for count in args.edge_counts:
        for fixture_name, item in fixtures(count).items():
            result = run_case(item, args.calls, args.iterations)
            result["fixture"] = fixture_name
            result_rows.append(result)
    payload = {
        "benchmark": "relation edge presence check",
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "workload": "synthetic edge lists; no network, database, or user data",
        "iterations_per_mode": args.iterations,
        "results": result_rows,
    }
    print(json.dumps(payload, indent=2))
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
