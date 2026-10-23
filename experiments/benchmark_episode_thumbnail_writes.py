"""Compare per-image episode-path writes with batched SQLite persistence.

Uses a disposable synthetic database; no image downloads, provider API calls, or user DB access.
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


def percentile(samples: list[float], fraction: float) -> float:
    ordered = sorted(samples)
    return ordered[min(len(ordered) - 1, max(0, round((len(ordered) - 1) * fraction)))]


def create_database(path: Path, count: int) -> None:
    database.DATABASE_NAME = str(path)
    connection = database.get_connection()
    try:
        connection.execute("""
            CREATE TABLE episodes (
                id INTEGER PRIMARY KEY,
                work_id INTEGER NOT NULL,
                episode_number INTEGER NOT NULL,
                thumbnail_url TEXT,
                UNIQUE(work_id, episode_number)
            )
        """)
        connection.executemany(
            "INSERT INTO episodes (id, work_id, episode_number) VALUES (?, 1, ?)",
            [(number, number) for number in range(1, count + 1)],
        )
        connection.commit()
    finally:
        connection.close()


def legacy_write(work_id: int, entries: list[tuple[int, str]]) -> set[int]:
    saved = set()
    for number, path in entries:
        if database.save_episode_thumbnail_path(work_id, number, path):
            saved.add(number)
    return saved


def batched_write(work_id: int, entries: list[tuple[int, str]]) -> set[int]:
    return database.save_episode_thumbnail_paths(work_id, entries)


def read_snapshot(work_id: int) -> dict[int, str | None]:
    connection = database.get_connection()
    try:
        rows = connection.execute(
            "SELECT episode_number, thumbnail_url FROM episodes WHERE work_id = ? ORDER BY episode_number",
            (work_id,),
        ).fetchall()
        return {int(row["episode_number"]): row["thumbnail_url"] for row in rows}
    finally:
        connection.close()


def run_count(count: int, iterations: int) -> dict:
    with tempfile.TemporaryDirectory(prefix="nekotrack-thumbnail-writes-") as directory:
        previous_db = database.DATABASE_NAME
        try:
            create_database(Path(directory) / "thumbnails.sqlite3", count)
            entries = [(number, f"cache/episode-{number}.jpg") for number in range(1, count + 1)]
            expected = {number: path for number, path in entries}

            legacy_saved = legacy_write(1, entries)
            legacy_snapshot = read_snapshot(1)
            if legacy_saved != set(expected) or legacy_snapshot != expected:
                raise AssertionError("legacy thumbnail writes did not persist all expected paths")
            batched_saved = batched_write(1, entries)
            batched_snapshot = read_snapshot(1)
            if batched_saved != legacy_saved or batched_snapshot != legacy_snapshot:
                raise AssertionError("batched thumbnail write output differs from legacy writes")

            legacy_samples, batched_samples = [], []
            for iteration in range(iterations):
                modes = (("legacy", legacy_write), ("batched", batched_write))
                if iteration % 2:
                    modes = tuple(reversed(modes))
                for label, writer in modes:
                    start = time.perf_counter()
                    saved = writer(1, entries)
                    elapsed = (time.perf_counter() - start) * 1000
                    if saved != legacy_saved or read_snapshot(1) != expected:
                        raise AssertionError(f"{label} write changed stored thumbnail paths")
                    (legacy_samples if label == "legacy" else batched_samples).append(elapsed)

            with patch.object(database, "get_connection", wraps=database.get_connection) as counter:
                legacy_write(1, entries)
                legacy_connections = counter.call_count
            with patch.object(database, "get_connection", wraps=database.get_connection) as counter:
                batched_write(1, entries)
                batched_connections = counter.call_count
        finally:
            database.DATABASE_NAME = previous_db

    legacy_median = statistics.median(legacy_samples)
    batched_median = statistics.median(batched_samples)
    return {
        "episodes": count,
        "results_match_exactly": legacy_snapshot == batched_snapshot == expected,
        "connections_per_write_batch": {
            "legacy_per_episode": legacy_connections,
            "batched": batched_connections,
        },
        "legacy_per_episode": {
            "median_ms": round(legacy_median, 3),
            "p95_ms": round(percentile(legacy_samples, .95), 3),
        },
        "batched": {
            "median_ms": round(batched_median, 3),
            "p95_ms": round(percentile(batched_samples, .95), 3),
        },
        "median_speedup_ratio": round(legacy_median / batched_median, 3) if batched_median > 0 else None,
        "scope": "SQLite thumbnail-path persistence only; excludes image/network time",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--episode-counts", nargs="+", type=int, default=[12, 50, 100, 500])
    parser.add_argument("--iterations", type=int, default=7)
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()
    if any(count < 1 or count > 5000 for count in args.episode_counts):
        parser.error("episode counts must be between 1 and 5000")
    if not 1 <= args.iterations <= 40:
        parser.error("iterations must be between 1 and 40")
    payload = {
        "benchmark": "episode thumbnail path writes",
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "workload": "temporary synthetic SQLite database; no downloads, providers or user data",
        "iterations_per_mode": args.iterations,
        "results": [run_count(count, args.iterations) for count in args.episode_counts],
    }
    print(json.dumps(payload, indent=2))
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
