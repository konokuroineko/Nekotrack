"""Benchmark the complete Library grouping function with a synthetic SQLite library.

This exercises get_library_series() end-to-end through its database reads and Python
grouping logic, but not Qt painting or the actual user's database. It validates bundle
counts, exact member coverage and connection-factory counts, and reports cold/warm
normalized-title-cache timings.
"""
from __future__ import annotations

import argparse
import json
import platform
import statistics
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import database  # noqa: E402
import series  # noqa: E402


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    position = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * fraction)))
    return ordered[position]


def _seed_library(path: Path, count: int) -> None:
    database.DATABASE_NAME = str(path)
    database.initialize_database()
    connection = database.get_connection()
    try:
        works = []
        library = []
        memberships = []
        relations = []
        for work_id in range(1, count + 1):
            family_start = ((work_id - 1) // 4) * 4 + 1
            season_index = (work_id - 1) % 4
            title = f"Synthetic Series {(work_id - 1) // 4} Saga"
            if season_index:
                title += f" Season {season_index + 1}"
            year = 2000 + season_index
            works.append((work_id, title, "ANIME", "TV", 12, year))
            status = "Watching" if season_index == 0 else "Planning"
            library.append((work_id, status, season_index * 2))
            memberships.append((family_start, work_id))
            if season_index < 3:
                relations.append((work_id, work_id + 1, "SEQUEL"))

        connection.executemany(
            """
            INSERT INTO works (id, title, type, format, episodes, start_year)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            works,
        )
        connection.executemany(
            """
            INSERT INTO user_library (work_id, status, progress_episodes)
            VALUES (?, ?, ?)
            """,
            library,
        )
        connection.executemany(
            "INSERT INTO automatic_bundle_memberships (bundle_id, work_id) VALUES (?, ?)",
            memberships,
        )
        connection.executemany(
            "INSERT INTO work_relations (source_id, target_id, relation_type) VALUES (?, ?, ?)",
            relations,
        )
        connection.commit()
    finally:
        connection.close()


def _validate(groups: list[dict], work_count: int) -> dict:
    expected_groups = work_count // 4
    expected_member_sets = {
        frozenset(range(start, start + 4))
        for start in range(1, work_count + 1, 4)
    }
    actual_member_sets = {
        frozenset(int(member["id"]) for member in (group.get("_series_members") or []))
        for group in groups
    }
    flattened_ids = [
        int(member["id"])
        for group in groups
        for member in (group.get("_series_members") or [])
    ]
    group_count = len(groups)
    member_count = len(flattened_ids)
    member_ids_match = (
        len(flattened_ids) == work_count
        and set(flattened_ids) == set(range(1, work_count + 1))
    )
    groups_match_exactly = actual_member_sets == expected_member_sets
    valid = (
        group_count == expected_groups
        and member_count == work_count
        and member_ids_match
        and groups_match_exactly
        and all(int(group.get("_series_count", 0)) == 4 for group in groups)
    )
    if not valid:
        raise AssertionError(
            f"Unexpected grouping: groups={group_count}/{expected_groups}, "
            f"members={member_count}/{work_count}, unique_ids={len(set(flattened_ids))}, "
            f"exact_member_sets={groups_match_exactly}"
        )
    return {
        "results_match_expected_shape": True,
        "exact_group_membership_matches": True,
        "group_count": group_count,
        "member_count": member_count,
        "members_per_group": 4,
    }


def _measure_current(count: int, iterations: int) -> dict:
    previous_database_name = database.DATABASE_NAME
    try:
        with tempfile.TemporaryDirectory(prefix="nekotrack-full-library-grouping-") as tmp:
            _seed_library(Path(tmp) / "library.sqlite3", count)
            with patch.object(series, "get", return_value=False):
                # Prime module/import and SQLite statement paths, then measure both
                # retained and cleared title-normalization caches separately.
                series._cached_series_key.cache_clear()
                warmup_groups = series.get_library_series()
                _validate(warmup_groups, count)

                warm_samples = []
                for _ in range(iterations):
                    started = time.perf_counter()
                    groups = series.get_library_series()
                    warm_samples.append((time.perf_counter() - started) * 1000)
                    _validate(groups, count)

                cold_samples = []
                for _ in range(iterations):
                    series._cached_series_key.cache_clear()
                    started = time.perf_counter()
                    groups = series.get_library_series()
                    cold_samples.append((time.perf_counter() - started) * 1000)
                    _validate(groups, count)

            calls = []
            original_database_factory = database.get_connection
            original_series_factory = series.get_connection

            def counted_database_connection(*args, **kwargs):
                calls.append("database")
                return original_database_factory(*args, **kwargs)

            def counted_series_connection(*args, **kwargs):
                calls.append("series")
                return original_series_factory(*args, **kwargs)

            with (
                patch.object(database, "get_connection", side_effect=counted_database_connection),
                patch.object(series, "get_connection", side_effect=counted_series_connection),
                patch.object(series, "get", return_value=False),
            ):
                checked_groups = series.get_library_series()
            shape = _validate(checked_groups, count)
            if calls.count("database") != 1 or calls.count("series") != 1 or len(calls) != 2:
                raise AssertionError(f"Unexpected connection factory calls: {calls}")

            return {
                "library_work_count": count,
                **shape,
                "connection_factory_calls_per_refresh": {
                    "database_library_fetch": calls.count("database"),
                    "series_grouping_snapshot": calls.count("series"),
                    "total": len(calls),
                },
                "cold_title_cache": {
                    "median_ms": round(statistics.median(cold_samples), 3),
                    "p95_ms": round(percentile(cold_samples, 0.95), 3),
                },
                "warm_title_cache": {
                    "median_ms": round(statistics.median(warm_samples), 3),
                    "p95_ms": round(percentile(warm_samples, 0.95), 3),
                },
            }
    finally:
        database.DATABASE_NAME = previous_database_name


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-counts", nargs="+", type=int, default=[100, 1000, 5000])
    parser.add_argument("--iterations", type=int, default=7)
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()
    if any(count < 4 or count > 10000 or count % 4 for count in args.work_counts):
        parser.error("work counts must be multiples of four between 4 and 10,000")
    if not 1 <= args.iterations <= 20:
        parser.error("iterations must be between 1 and 20")

    payload = {
        "benchmark": "complete get_library_series synthetic SQLite grouping",
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "workload": (
            "synthetic local SQLite Library; four TV works per franchise; no APIs, "
            "Qt painting or user database"
        ),
        "iterations_per_mode": args.iterations,
        "results": [_measure_current(count, args.iterations) for count in args.work_counts],
    }
    print(json.dumps(payload, indent=2))
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
