"""Benchmark indexed bundle-exclusion checks against the former pair scan.

Run from the repository root:
  python experiments/benchmark_series_exclusions.py --component-sizes 100 250 500 1000 --iterations 7

Inputs are deterministic synthetic component-member sets. No user database or APIs
are accessed. The excluded links deliberately do not cross the tested components so
the benchmark measures the worst-case absence check of the old cartesian scan.
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


def run_one_size(size: int, iterations: int) -> dict:
    left = set(range(size))
    right = set(range(size, 2 * size))
    # Non-empty exclusion data, but none connect the two components. This forces
    # the old check to inspect every pair while indexed lookup checks only adjacency.
    excluded = {(2 * size + 1, 2 * size + 2), (2 * size + 3, 2 * size + 5)}
    neighbors = series._build_exclusion_neighbors(excluded)

    def reference() -> bool:
        return any(
            tuple(sorted((left_id, right_id))) in excluded
            for left_id in left
            for right_id in right
        )

    def previous_indexed() -> bool:
        # Reproduce the former default-set allocation for every missing ID.
        if not neighbors:
            return False
        left_members, right_members = left, right
        if len(left_members) > len(right_members):
            left_members, right_members = right_members, left_members
        return any(
            not neighbors.get(member_id, set()).isdisjoint(right_members)
            for member_id in left_members
        )

    def indexed() -> bool:
        return series._components_have_excluded_pair(left, right, neighbors)

    expected = reference()
    if expected != previous_indexed() or expected != indexed():
        raise AssertionError("indexed exclusion result differs from reference")

    reference_samples = []
    previous_indexed_samples = []
    indexed_samples = []
    for iteration in range(iterations):
        modes = (
            ("reference", reference),
            ("previous_indexed", previous_indexed),
            ("indexed", indexed),
        )
        if iteration % 2:
            modes = tuple(reversed(modes))
        for name, operation in modes:
            started = time.perf_counter()
            actual = operation()
            elapsed_ms = (time.perf_counter() - started) * 1000
            if actual != expected:
                raise AssertionError(f"{name} exclusion result changed")
            if name == "reference":
                reference_samples.append(elapsed_ms)
            elif name == "previous_indexed":
                previous_indexed_samples.append(elapsed_ms)
            else:
                indexed_samples.append(elapsed_ms)

    reference_median = statistics.median(reference_samples)
    previous_indexed_median = statistics.median(previous_indexed_samples)
    indexed_median = statistics.median(indexed_samples)
    return {
        "component_members_each_side": size,
        "pair_checks_in_reference_worst_case": size * size,
        "excluded_pairs": len(excluded),
        "results_match": expected == indexed(),
        "reference_cross_product": {
            "median_ms": round(reference_median, 3),
            "p95_ms": round(percentile(reference_samples, 0.95), 3),
        },
        "previous_indexed_neighbor_lookup": {
            "median_ms": round(previous_indexed_median, 3),
            "p95_ms": round(percentile(previous_indexed_samples, 0.95), 3),
        },
        "allocation_free_indexed_neighbor_lookup": {
            "median_ms": round(indexed_median, 3),
            "p95_ms": round(percentile(indexed_samples, 0.95), 3),
        },
        "allocation_free_speedup_vs_previous_helper": round(
            previous_indexed_median / indexed_median, 3
        ) if indexed_median > 0 else None,
        "median_speedup_ratio": round(reference_median / indexed_median, 3)
        if indexed_median > 0 else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--component-sizes", nargs="+", type=int, default=[100, 250, 500, 1000])
    parser.add_argument("--iterations", type=int, default=7)
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()
    if any(size < 1 or size > 10000 for size in args.component_sizes):
        parser.error("component sizes must be between 1 and 10000")
    if not 1 <= args.iterations <= 50:
        parser.error("iterations must be between 1 and 50")

    payload = {
        "benchmark": "series._components_have_excluded_pair",
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "workload": "synthetic component member sets; no cross-component exclusions; no database/network",
        "iterations_per_mode": args.iterations,
        "results": [run_one_size(size, args.iterations) for size in args.component_sizes],
    }
    print(json.dumps(payload, indent=2))
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
