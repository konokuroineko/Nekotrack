"""Paired benchmark: original logical-season algorithm vs title-metadata snapshot.

Runs both implementations in the same interpreter on identical synthetic groups,
clearing title-analysis caches before cold samples and keeping them warm for warm
samples. Exact logical-season counts must match. No SQLite, API, or user data is used.
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


def reference_logical_season_count(members):
    """The previous implementation, retained here as a benchmark control."""
    tv_members = [
        member for member in members
        if str(series._get(member, "format") or "").upper() in {"TV", "TV_SHORT"}
        and series._valid_relation_id(series._get(member, "id")) is not None
    ]
    if not tv_members:
        return 0

    by_id = {
        series._valid_relation_id(series._get(member, "id")): member
        for member in tv_members
    }
    ids = set(by_id)
    parent = {media_id: media_id for media_id in ids}

    def find(media_id):
        while parent[media_id] != media_id:
            parent[media_id] = parent[parent[media_id]]
            media_id = parent[media_id]
        return media_id

    def union(left, right):
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    by_marker = {}
    for media_id, member in by_id.items():
        marker = series._season_marker(series._title_text(member))
        if marker:
            by_marker.setdefault(marker, []).append(media_id)
    for members_for_marker in by_marker.values():
        for media_id in members_for_marker[1:]:
            union(members_for_marker[0], media_id)

    for member_id, member in by_id.items():
        title = series._title_text(member)
        if not series._is_continuation(title):
            continue
        current_marker = series._season_marker(title)
        for edge in series._search_relation_edges(member):
            if edge.get("relationType") not in {"PREQUEL", "SEQUEL"}:
                continue
            node = edge.get("node")
            if not isinstance(node, dict):
                continue
            target_id = series._valid_relation_id(node.get("id"))
            if target_id is None or target_id not in by_id:
                continue
            target_marker = series._season_marker(series._title_text(by_id[target_id]))
            if current_marker is not None and target_marker is not None:
                if current_marker == target_marker:
                    union(member_id, target_id)
            elif current_marker is None and target_marker is None:
                union(member_id, target_id)

    arc_ids = {
        media_id for media_id, member in by_id.items()
        if series._is_arc(series._title_text(member))
        and series._season_marker(series._title_text(member)) is None
        and not series._is_continuation(series._title_text(member))
    }
    for member_id in arc_ids:
        member_period = series._air_period(by_id[member_id])
        if member_period is None:
            continue
        for edge in series._search_relation_edges(by_id[member_id]):
            if edge.get("relationType") not in {"PREQUEL", "SEQUEL"}:
                continue
            node = edge.get("node")
            if not isinstance(node, dict):
                continue
            target_id = series._valid_relation_id(node.get("id"))
            if target_id is None or target_id not in arc_ids:
                continue
            target_period = series._air_period(by_id[target_id])
            if target_period is not None and member_period == target_period:
                union(member_id, target_id)

    return len({find(media_id) for media_id in ids})


def make_groups(group_count: int) -> list[list[dict]]:
    groups = []
    for group_index in range(group_count):
        if group_index % 3 == 0:
            titles = [
                f"Synthetic Series {group_index} Saga",
                f"Synthetic Series {group_index} Saga Season 2",
                f"Synthetic Series {group_index} Saga Season 3",
                f"Synthetic Series {group_index} Saga Season 4",
            ]
        elif group_index % 3 == 1:
            titles = [
                f"Synthetic Series {group_index} Saga Part 1",
                f"Synthetic Series {group_index} Saga Part 2",
                f"Synthetic Series {group_index} Saga Part 3",
                f"Synthetic Series {group_index} Saga Part 4",
            ]
        else:
            titles = [
                f"Synthetic Series {group_index} Arc One",
                f"Synthetic Series {group_index} Arc Two",
                f"Synthetic Series {group_index} Arc Three",
                f"Synthetic Series {group_index} Arc Four",
            ]

        ids = [group_index * 4 + offset + 1 for offset in range(4)]
        members = []
        for offset, (media_id, title) in enumerate(zip(ids, titles)):
            edges = []
            if offset + 1 < len(ids):
                edges.append({
                    "relationType": "SEQUEL",
                    "node": {"id": ids[offset + 1]},
                })
            if offset > 0:
                edges.append({
                    "relationType": "PREQUEL",
                    "node": {"id": ids[offset - 1]},
                })
            members.append({
                "id": media_id,
                "type": "ANIME",
                "format": "TV",
                "title": {"english": title, "romaji": title, "native": None},
                "startDate": {"year": 2020 + offset, "month": 1 + offset % 3, "day": 1},
                "relations": {"edges": edges},
            })
        groups.append(members)
    return groups


def clear_title_caches() -> None:
    series._cached_season_marker.cache_clear()
    series._cached_is_continuation.cache_clear()
    series._cached_is_arc.cache_clear()


def run_all(groups, function) -> list[int]:
    return [function(group) for group in groups]


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * fraction)))
    return ordered[index]


def time_mode(groups, function, iterations: int, cold: bool) -> list[float]:
    samples = []
    for _ in range(iterations):
        if cold:
            clear_title_caches()
        started = time.perf_counter()
        result = run_all(groups, function)
        elapsed_ms = (time.perf_counter() - started) * 1000
        if result != EXPECTED_COUNTS:
            raise AssertionError(f"{function.__name__} changed logical-season outputs")
        samples.append(elapsed_ms)
    return samples


EXPECTED_COUNTS: list[int] = []


def run_benchmark(group_count: int, iterations: int) -> dict:
    global EXPECTED_COUNTS
    groups = make_groups(group_count)
    clear_title_caches()
    EXPECTED_COUNTS = run_all(groups, reference_logical_season_count)
    clear_title_caches()
    optimized_counts = run_all(groups, series.logical_season_count)
    if optimized_counts != EXPECTED_COUNTS:
        raise AssertionError("Optimized logical-season results differ from reference")

    cold_reference, cold_optimized = [], []
    for iteration in range(iterations):
        modes = (
            (("reference", reference_logical_season_count), ("optimized", series.logical_season_count))
            if iteration % 2 == 0 else
            (("optimized", series.logical_season_count), ("reference", reference_logical_season_count))
        )
        for mode, function in modes:
            samples = time_mode(groups, function, 1, cold=True)
            (cold_reference if mode == "reference" else cold_optimized).extend(samples)

    clear_title_caches()
    run_all(groups, reference_logical_season_count)
    run_all(groups, series.logical_season_count)
    warm_reference, warm_optimized = [], []
    for iteration in range(iterations):
        modes = (
            (("reference", reference_logical_season_count), ("optimized", series.logical_season_count))
            if iteration % 2 == 0 else
            (("optimized", series.logical_season_count), ("reference", reference_logical_season_count))
        )
        for mode, function in modes:
            samples = time_mode(groups, function, 1, cold=False)
            (warm_reference if mode == "reference" else warm_optimized).extend(samples)

    def summary(reference_samples, optimized_samples):
        reference_median = statistics.median(reference_samples)
        optimized_median = statistics.median(optimized_samples)
        return {
            "previous_algorithm": {
                "median_ms": round(reference_median, 3),
                "p95_ms": round(percentile(reference_samples, 0.95), 3),
            },
            "metadata_snapshot_algorithm": {
                "median_ms": round(optimized_median, 3),
                "p95_ms": round(percentile(optimized_samples, 0.95), 3),
            },
            "speedup_ratio": round(reference_median / optimized_median, 3)
            if optimized_median > 0 else None,
        }

    return {
        "group_count": group_count,
        "member_count": group_count * 4,
        "results_match_exactly": True,
        "reference_sample_output_counts": sorted(set(EXPECTED_COUNTS)),
        "cold_title_caches": summary(cold_reference, cold_optimized),
        "warm_title_caches": summary(warm_reference, warm_optimized),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--group-count", type=int, default=1250)
    parser.add_argument("--iterations", type=int, default=7)
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()
    if not 1 <= args.group_count <= 5000:
        parser.error("group count must be between 1 and 5000")
    if not 1 <= args.iterations <= 20:
        parser.error("iterations must be between 1 and 20")

    payload = {
        "benchmark": "paired logical-season metadata snapshot comparison",
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "workload": "synthetic 4-work bundles with season, Part continuation and Arc titles",
        "iterations_per_mode": args.iterations,
        "results": run_benchmark(args.group_count, args.iterations),
    }
    print(json.dumps(payload, indent=2))
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
