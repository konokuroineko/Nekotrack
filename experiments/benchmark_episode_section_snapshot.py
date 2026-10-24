"""Benchmark legacy Work Details reads against a one-connection episode snapshot.

Only a disposable synthetic SQLite database is used; this makes no API calls and
never opens the user's NekoTrack database. Run from the repository root:
  python experiments/benchmark_episode_section_snapshot.py --episode-counts 12 100 1000 5000 --iterations 7
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
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * fraction)))
    return ordered[index]


def create_database(path: Path, episode_count: int) -> int:
    database.DATABASE_NAME = str(path)
    connection = database.get_connection()
    try:
        connection.executescript("""
            CREATE TABLE works (
                id INTEGER PRIMARY KEY, title TEXT NOT NULL, type TEXT NOT NULL,
                description TEXT, episodes INTEGER, score REAL, start_year INTEGER,
                cover_url TEXT, format TEXT, cover_path TEXT, chapters INTEGER,
                volumes INTEGER, source TEXT, end_year INTEGER, duration INTEGER,
                mal_id INTEGER, start_month INTEGER, start_day INTEGER, tmdb_id INTEGER,
                tmdb_season_number INTEGER, characters_loaded INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE user_library (
                work_id INTEGER PRIMARY KEY, status TEXT NOT NULL DEFAULT 'Planning',
                progress_episodes INTEGER DEFAULT 0, progress_chapters INTEGER DEFAULT 0,
                progress_volumes INTEGER DEFAULT 0, rating INTEGER, notes TEXT,
                added_date TEXT DEFAULT CURRENT_TIMESTAMP, updated_date TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE episodes (
                id INTEGER PRIMARY KEY, work_id INTEGER NOT NULL, episode_number INTEGER NOT NULL,
                title TEXT, description TEXT, air_date TEXT, thumbnail_url TEXT,
                watched INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE work_provider_metadata (
                work_id INTEGER NOT NULL, provider TEXT NOT NULL, provider_id TEXT,
                payload_json TEXT NOT NULL, updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (work_id, provider)
            );
        """)
        connection.execute(
            "INSERT INTO works (id, title, type, description, episodes, format, tmdb_id, tmdb_season_number) "
            "VALUES (1, 'Synthetic Work', 'ANIME', 'Synthetic synopsis', ?, 'TV', 77, 2)",
            (episode_count,),
        )
        connection.execute(
            "INSERT INTO user_library (work_id, status, progress_episodes, progress_chapters, progress_volumes) "
            "VALUES (1, 'Watching', 3, 0, 0)"
        )
        connection.executemany(
            "INSERT INTO episodes (id, work_id, episode_number, title, description, air_date, watched) "
            "VALUES (?, 1, ?, ?, ?, '2020-01-01', ?)",
            [
                (index, index, f"Episode {index}", f"Synthetic episode {index}", int(index <= 3))
                for index in range(1, episode_count + 1)
            ],
        )
        connection.execute(
            "INSERT INTO work_provider_metadata (work_id, provider, payload_json) VALUES (?, ?, ?)",
            (1, "tmdb_episode_match_version", json.dumps({
                "version": 4, "fetched_at": 1750000000, "complete": True
            })),
        )
        connection.commit()
    finally:
        connection.close()
    return 1


def reference_read(work_id: int) -> dict:
    work = database.get_work(work_id)
    if work is None:
        return {"work": None, "episodes": [], "catalog_metadata": None}
    return {
        "work": dict(work),
        "episodes": [dict(row) for row in database.get_episodes(work_id)],
        "catalog_metadata": database.get_provider_metadata(work_id, "tmdb_episode_match_version"),
    }


def batched_read(work_id: int) -> dict:
    snapshot = database.get_episode_section_snapshot(work_id)
    return {
        "work": dict(snapshot["work"]) if snapshot["work"] is not None else None,
        "episodes": [dict(row) for row in snapshot["episodes"]],
        "catalog_metadata": snapshot["catalog_metadata"],
    }


def run_count(count: int, iterations: int) -> dict:
    with tempfile.TemporaryDirectory(prefix="nekotrack-episode-snapshot-") as directory:
        prior_database = database.DATABASE_NAME
        try:
            work_id = create_database(Path(directory) / "episode-snapshot.sqlite3", count)
            expected = reference_read(work_id)
            actual = batched_read(work_id)
            if actual != expected:
                raise AssertionError(f"snapshot outputs differ for {count} episodes")
            old_samples, new_samples = [], []
            for iteration in range(iterations):
                modes = (("reference", reference_read), ("batched", batched_read))
                if iteration % 2:
                    modes = tuple(reversed(modes))
                for label, function in modes:
                    started = time.perf_counter()
                    result = function(work_id)
                    elapsed_ms = (time.perf_counter() - started) * 1000
                    if result != expected:
                        raise AssertionError(f"{label} output changed for {count} episodes")
                    (old_samples if label == "reference" else new_samples).append(elapsed_ms)
            with patch.object(database, "get_connection", wraps=database.get_connection) as counter:
                reference_read(work_id)
                old_connections = counter.call_count
            with patch.object(database, "get_connection", wraps=database.get_connection) as counter:
                batched_read(work_id)
                new_connections = counter.call_count
        finally:
            database.DATABASE_NAME = prior_database

    old_median, new_median = statistics.median(old_samples), statistics.median(new_samples)
    return {
        "episode_count": count,
        "results_match_exactly": actual == expected,
        "connections_per_read": {"legacy_standalone_reads": old_connections, "batched_snapshot": new_connections},
        "legacy_standalone_reads": {
            "median_ms": round(old_median, 3),
            "p95_ms": round(percentile(old_samples, 0.95), 3),
        },
        "batched_snapshot": {
            "median_ms": round(new_median, 3),
            "p95_ms": round(percentile(new_samples, 0.95), 3),
        },
        "median_speedup_ratio": round(old_median / new_median, 3) if new_median > 0 else None,
        "scope": "local SQLite reads only; excludes image and provider API work",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--episode-counts", nargs="+", type=int, default=[12, 100, 1000, 5000])
    parser.add_argument("--iterations", type=int, default=7)
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()
    if any(count < 1 or count > 100000 for count in args.episode_counts):
        parser.error("episode counts must be between 1 and 100000")
    if not 1 <= args.iterations <= 50:
        parser.error("iterations must be between 1 and 50")
    payload = {
        "benchmark": "Work Details episode-section snapshot",
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "workload": "synthetic SQLite database; no external provider or user data",
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
