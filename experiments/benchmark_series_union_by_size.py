"""Benchmark series component set merges with and without union-by-size.

Uses deterministic synthetic disjoint-set operations only; no database or network IO.
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


def find(parent: dict[int, int], item_id: int) -> int:
    while parent[item_id] != item_id:
        parent[item_id] = parent[parent[item_id]]
        item_id = parent[item_id]
    return item_id


def components(parent: dict[int, int], count: int) -> set[frozenset[int]]:
    result: dict[int, set[int]] = {}
    for item_id in range(count):
        result.setdefault(find(parent, item_id), set()).add(item_id)
    return {frozenset(members) for members in result.values()}


def reference_union(count: int) -> tuple[set[frozenset[int]], int]:
    parent = {item_id: item_id for item_id in range(count)}
    members = {item_id: {item_id} for item_id in range(count)}
    moved = 0
    # Deliberately adverse order for the legacy always-left-root rule.
    for left_id in range(count - 2, -1, -1):
        left_root = find(parent, left_id)
        right_root = find(parent, left_id + 1)
        if left_root == right_root:
            continue
        moved += len(members[right_root])
        parent[right_root] = left_root
        members[left_root].update(members.pop(right_root))
    return components(parent, count), moved


def balanced_union(count: int) -> tuple[set[frozenset[int]], int]:
    parent = {item_id: item_id for item_id in range(count)}
    members = {item_id: {item_id} for item_id in range(count)}
    moved = 0
    for left_id in range(count - 2, -1, -1):
        left_root = find(parent, left_id)
        right_root = find(parent, left_id + 1)
        if left_root == right_root:
            continue
        _root, copied = series._merge_component_roots(
            parent, members, left_root, right_root
        )
        moved += copied
    return components(parent, count), moved


def percentile(samples: list[float], fraction: float) -> float:
    ordered = sorted(samples)
    return ordered[min(len(ordered) - 1, max(0, round((len(ordered) - 1) * fraction)))]


def run_count(count: int, iterations: int) -> dict:
    reference_output, reference_moved = reference_union(count)
    balanced_output, balanced_moved = balanced_union(count)
    if balanced_output != reference_output:
        raise AssertionError(f"component partitions differ for {count} members")

    reference_samples, balanced_samples = [], []
    for iteration in range(iterations):
        modes = (("reference", reference_union), ("balanced", balanced_union))
        if iteration % 2:
            modes = tuple(reversed(modes))
        for label, function in modes:
            started = time.perf_counter()
            output, _moved = function(count)
            elapsed_ms = (time.perf_counter() - started) * 1000
            if output != reference_output:
                raise AssertionError(f"{label} output changed for {count} members")
            (reference_samples if label == "reference" else balanced_samples).append(elapsed_ms)

    reference_median = statistics.median(reference_samples)
    balanced_median = statistics.median(balanced_samples)
    return {
        "members": count,
        "component_partitions_match": balanced_output == reference_output,
        "members_reinserted_by_set_merges": {
            "reference_always_left_root": reference_moved,
            "balanced_union_by_size": balanced_moved,
        },
        "reference": {
            "median_ms": round(reference_median, 3),
            "p95_ms": round(percentile(reference_samples, .95), 3),
        },
        "balanced": {
            "median_ms": round(balanced_median, 3),
            "p95_ms": round(percentile(balanced_samples, .95), 3),
        },
        "median_speedup_ratio": round(reference_median / balanced_median, 3) if balanced_median > 0 else None,
        "scope": "synthetic union-find/set-merge cost only; not whole library grouping",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--member-counts", nargs="+", type=int, default=[500, 1000, 2000])
    parser.add_argument("--iterations", type=int, default=5)
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()
    if any(count < 2 or count > 10000 for count in args.member_counts):
        parser.error("member counts must be between 2 and 10000")
    if not 1 <= args.iterations <= 30:
        parser.error("iterations must be between 1 and 30")
    payload = {
        "benchmark": "series component unions by size",
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "workload": "deterministic adverse-order synthetic disjoint-set operations",
        "iterations_per_mode": args.iterations,
        "results": [run_count(count, args.iterations) for count in args.member_counts],
    }
    print(json.dumps(payload, indent=2))
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
