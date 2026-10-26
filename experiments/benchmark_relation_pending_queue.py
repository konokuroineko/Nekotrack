"""Microbenchmark FIFO traversal overhead in Search relation readiness.

Runs only deterministic synthetic in-memory dictionaries. No SQLite database,
network calls, or user library are accessed. Run from repository root:
  python experiments/benchmark_relation_pending_queue.py --sizes 1000 5000 10000 20000 --iterations 7
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


def build_frontier(count: int) -> list[dict]:
    """Create already-loaded seed entries with no outgoing relation edges."""
    return [
        {
            "id": index + 1,
            "type": "ANIME",
            "format": "TV",
            "title": {"english": f"Synthetic Series {index + 1}", "romaji": f"Synthetic Series {index + 1}"},
            "relations": {"edges": []},
            "_relations_loaded": True,
        }
        for index in range(count)
    ]


def reference_list_queue(frontier: list[dict]) -> bool:
    """The former FIFO traversal using list.pop(0)."""
    seen = set()
    queue = list(frontier)
    while queue:
        item = queue.pop(0)
        item_id = int(item["id"])
        if item_id in seen:
            continue
        seen.add(item_id)
        if series._get(item, "_relations_loaded"):
            edges = series._search_relation_edges(item)
        else:
            cached = series._relation_cache.get(item_id)
            if cached:
                edges = (cached.get("relations") or {}).get("edges", [])
            elif series._get(item, "_related_only"):
                return True
            else:
                edges = series._search_relation_edges(item)
        for edge in edges:
            if not series._relation_edge_allowed(item, edge):
                continue
            node = edge.get("node") or {}
            target_id = node.get("id")
            if (
                target_id
                and int(target_id) not in seen
                and int(target_id) not in series._relation_cache
            ):
                queue.append(series._related_placeholder(node))
    return False


def percentile(samples: list[float], fraction: float) -> float:
    ordered = sorted(samples)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * fraction)))
    return ordered[index]


def run_size(count: int, iterations: int) -> dict:
    frontier = build_frontier(count)
    with __import__("unittest.mock", fromlist=["patch"]).patch.dict(
        series._relation_cache, {}, clear=True
    ):
        expected = reference_list_queue(frontier)
        actual = series.has_pending_relation_enrichment(frontier)
        if actual != expected:
            raise AssertionError(f"FIFO result differs for {count} seed items")

        reference_samples, deque_samples = [], []
        for iteration in range(iterations):
            modes = ("reference", "deque") if iteration % 2 == 0 else ("deque", "reference")
            for mode in modes:
                started = time.perf_counter()
                result = reference_list_queue(frontier) if mode == "reference" else series.has_pending_relation_enrichment(frontier)
                elapsed = (time.perf_counter() - started) * 1000
                if result != expected:
                    raise AssertionError(f"{mode} output changed for {count} seed items")
                (reference_samples if mode == "reference" else deque_samples).append(elapsed)

    old_median = statistics.median(reference_samples)
    new_median = statistics.median(deque_samples)
    return {
        "input_seed_items": count,
        "results_match_exactly": actual == expected,
        "reference_list_pop0": {
            "median_ms": round(old_median, 3),
            "p95_ms": round(percentile(reference_samples, 0.95), 3),
        },
        "optimized_deque_popleft": {
            "median_ms": round(new_median, 3),
            "p95_ms": round(percentile(deque_samples, 0.95), 3),
        },
        "median_speedup_ratio": round(old_median / new_median, 3) if new_median > 0 else None,
        "scope": "FIFO queue overhead only; excludes API and database latency",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sizes", nargs="+", type=int, default=[1000, 5000, 10000, 20000])
    parser.add_argument("--iterations", type=int, default=7)
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()
    if any(size < 1 or size > 100000 for size in args.sizes):
        parser.error("sizes must be between 1 and 100000")
    if not 1 <= args.iterations <= 50:
        parser.error("--iterations must be between 1 and 50")

    payload = {
        "benchmark": "Search relation readiness FIFO queue",
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "workload": "synthetic in-memory loaded seed items; no user or provider data",
        "iterations_per_mode": args.iterations,
        "results": [run_size(size, args.iterations) for size in args.sizes],
    }
    print(json.dumps(payload, indent=2))
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
