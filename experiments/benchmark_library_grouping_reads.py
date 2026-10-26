"""Compare Library grouping-state queries with the former three-reader path.

Uses disposable SQLite databases only; no user data or provider APIs are accessed.
It checks exact row parity, median/p95 latency, and SQLite connection counts.
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


def _create_database(path: Path, count: int):
    database.DATABASE_NAME = str(path)
    database.initialize_database()
    connection = database.get_connection()
    try:
        connection.executemany(
            "INSERT INTO works (id, title, type, format) VALUES (?, ?, 'ANIME', 'TV')",
            [(i, f"Synthetic work {i}") for i in range(1, count + 1)],
        )
        links = [(i, i + 1) for i in range(1, count, 10)]
        exclusions = [(i, i + 2) for i in range(1, count - 1, 13)]
        connection.executemany(
            "INSERT INTO manual_bundle_links (work_a, work_b) VALUES (?, ?)", links
        )
        connection.executemany(
            "INSERT INTO bundle_exclusions (work_a, work_b) VALUES (?, ?)", exclusions
        )
        memberships = []
        for start in range(1, count, 20):
            for work_id in range(start, min(start + 4, count + 1)):
                memberships.append((start, work_id))
        connection.executemany(
            "INSERT INTO automatic_bundle_memberships (bundle_id, work_id) VALUES (?, ?)",
            memberships,
        )
        connection.commit()
    finally:
        connection.close()
    return list(range(1, count + 1))


def _normalize(rows):
    return {
        "manual_links": [(int(row["work_a"]), int(row["work_b"])) for row in rows["manual_links"]],
        "exclusions": [(int(row["work_a"]), int(row["work_b"])) for row in rows["exclusions"]],
        "automatic_memberships": [
            (int(row["bundle_id"]), int(row["work_id"]))
            for row in rows["automatic_memberships"]
        ],
    }


def _reference(ids):
    return _normalize({
        "manual_links": database.get_manual_bundle_links(ids),
        "exclusions": database.get_bundle_exclusions(ids),
        "automatic_memberships": database.get_automatic_bundle_memberships(ids),
    })


def _batched(ids):
    return _normalize(database.get_library_bundle_grouping_state(ids))


def _percentile(values, fraction):
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * fraction)))
    return ordered[index]


def run_one_size(count, iterations):
    old_samples, new_samples = [], []
    reference_calls, batched_calls = [], []
    expected = actual = None
    for iteration in range(iterations):
        for mode in (("reference", "batched") if iteration % 2 == 0 else ("batched", "reference")):
            with tempfile.TemporaryDirectory(prefix="nekotrack-library-grouping-") as temporary:
                previous_name = database.DATABASE_NAME
                try:
                    ids = _create_database(Path(temporary) / "library.sqlite3", count)
                    started = time.perf_counter()
                    if mode == "reference":
                        result = _reference(ids)
                    else:
                        result = _batched(ids)
                    elapsed = (time.perf_counter() - started) * 1000
                    with patch.object(database, "get_connection", wraps=database.get_connection) as factory:
                        (_reference if mode == "reference" else _batched)(ids)
                        calls = factory.call_count
                    if mode == "reference":
                        expected = result
                        old_samples.append(elapsed)
                        reference_calls.append(calls)
                    else:
                        actual = result
                        new_samples.append(elapsed)
                        batched_calls.append(calls)
                    if expected is not None and actual is not None and expected != actual:
                        raise AssertionError("batched grouping-state rows differ from the former readers")
                finally:
                    database.DATABASE_NAME = previous_name

    old_median, new_median = statistics.median(old_samples), statistics.median(new_samples)
    return {
        "library_work_count": count,
        "results_match_exactly": expected == actual,
        "connections_per_read": {
            "former_three_readers": round(statistics.median(reference_calls), 1),
            "batched_reader": round(statistics.median(batched_calls), 1),
        },
        "former_three_readers": {
            "median_ms": round(old_median, 3),
            "p95_ms": round(_percentile(old_samples, .95), 3),
        },
        "batched_reader": {
            "median_ms": round(new_median, 3),
            "p95_ms": round(_percentile(new_samples, .95), 3),
        },
        "median_speedup_ratio": round(old_median / new_median, 3) if new_median > 0 else None,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-counts", nargs="+", type=int, default=[100, 1000, 5000])
    parser.add_argument("--iterations", type=int, default=7)
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()
    if any(count < 2 or count > 10000 for count in args.work_counts):
        parser.error("work counts must be between 2 and 10,000")
    if not 1 <= args.iterations <= 30:
        parser.error("iterations must be between 1 and 30")
    payload = {
        "benchmark": "Library grouping-state SQLite reads",
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "workload": "temporary synthetic SQLite library; no external API or user database",
        "iterations_per_mode": args.iterations,
        "results": [run_one_size(count, args.iterations) for count in args.work_counts],
    }
    print(json.dumps(payload, indent=2))
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
