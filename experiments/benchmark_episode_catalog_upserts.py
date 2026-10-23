"""Benchmark episode catalog upserts before and after batching thumbnail reads.

Uses a disposable synthetic SQLite database and a local placeholder image only.
No network requests or user-library data are used.
"""
from __future__ import annotations

import argparse
import json
import math
import platform
import re
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


def reference_save_episodes(work_id, episode_data):
    """Former per-episode thumbnail SELECT + upsert implementation."""
    safe_work_id = database._validated_work_id(work_id)

    def valid_number(value):
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            number = value
        elif isinstance(value, float):
            if not math.isfinite(value) or not value.is_integer():
                return None
            number = int(value)
        elif isinstance(value, str):
            text = value.strip()
            if not text or len(text) > 7 or not re.fullmatch(r"[0-9]+", text):
                return None
            number = int(text)
        else:
            return None
        return number if 1 <= number <= database._MAX_TRACKED_EPISODE_NUMBER else None

    def optional_text(value):
        return value.strip() or None if isinstance(value, str) else None

    connection = database.get_connection()
    try:
        for episode in list(episode_data or []):
            if not isinstance(episode, dict):
                continue
            number = valid_number(episode.get("episodeNumber"))
            if number is None:
                continue
            incoming = optional_text(episode.get("thumbnail"))
            existing = connection.execute(
                "SELECT thumbnail_url FROM episodes WHERE work_id = ? AND episode_number = ?",
                (safe_work_id, number),
            ).fetchone()
            existing_thumbnail = (
                str(existing["thumbnail_url"]).strip()
                if existing and existing["thumbnail_url"] else None
            )
            if (
                existing_thumbnail
                and Path(existing_thumbnail).is_file()
                and (not incoming or not Path(incoming).is_file())
            ):
                thumbnail = existing_thumbnail
            else:
                thumbnail = incoming
            connection.execute("""
                INSERT INTO episodes (
                    work_id, episode_number, title, description, air_date, thumbnail_url
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(work_id, episode_number) DO UPDATE SET
                    title = COALESCE(excluded.title, episodes.title),
                    description = COALESCE(excluded.description, episodes.description),
                    air_date = COALESCE(excluded.air_date, episodes.air_date),
                    thumbnail_url = COALESCE(excluded.thumbnail_url, episodes.thumbnail_url)
            """, (
                safe_work_id, number,
                optional_text(episode.get("title")),
                optional_text(episode.get("description")),
                optional_text(episode.get("airdate")),
                thumbnail,
            ))
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def snapshot(work_id):
    connection = database.get_connection()
    try:
        rows = connection.execute(
            """
            SELECT episode_number, title, description, air_date, thumbnail_url, watched
            FROM episodes WHERE work_id = ? ORDER BY episode_number
            """,
            (work_id,),
        ).fetchall()
        return [tuple(row) for row in rows]
    finally:
        connection.close()


def percentile(samples: list[float], fraction: float) -> float:
    ordered = sorted(samples)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * fraction)))
    return ordered[index]


def run_count(count: int, iterations: int) -> dict:
    with tempfile.TemporaryDirectory(prefix="nekotrack-episode-upserts-") as temp:
        previous_db = database.DATABASE_NAME
        try:
            database.DATABASE_NAME = str(Path(temp) / "catalog.sqlite3")
            cached_image = Path(temp) / "cached-local-thumbnail.jpg"
            cached_image.write_bytes(b"test image path exists")
            con = database.get_connection()
            try:
                con.execute("""
                    CREATE TABLE episodes (
                        id INTEGER PRIMARY KEY,
                        work_id INTEGER NOT NULL,
                        episode_number INTEGER NOT NULL,
                        title TEXT, description TEXT, air_date TEXT,
                        thumbnail_url TEXT, watched INTEGER NOT NULL DEFAULT 0,
                        UNIQUE(work_id, episode_number)
                    )
                """)
                con.executemany(
                    """
                    INSERT INTO episodes
                        (id, work_id, episode_number, title, description, air_date, thumbnail_url, watched)
                    VALUES (?, 1, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            number, number, f"Old title {number}", f"Old description {number}",
                            None, str(cached_image) if number % 10 == 0 else f"https://old.invalid/{number}.jpg",
                            1 if number % 7 == 0 else 0,
                        )
                        for number in range(1, count + 1)
                    ],
                )
                con.commit()
            finally:
                con.close()

            incoming = [
                {
                    "episodeNumber": number,
                    "title": f"Updated episode {number}",
                    "description": "Provider synopsis",
                    "airdate": "2026-01-02",
                    "thumbnail": None if number % 5 == 0
                    else f"https://image.tmdb.org/t/p/w500/{number}.jpg",
                }
                for number in range(1, count + 1)
            ]
            reference_save_episodes(1, incoming)
            expected = snapshot(1)
            database.save_episodes(1, incoming)
            actual = snapshot(1)
            if actual != expected:
                raise AssertionError(f"batched catalog upsert differs from reference for {count} episodes")

            reference_samples, batched_samples = [], []

            def traced_write(writer):
                statements = []
                prior_get_connection = database.get_connection

                def connect():
                    connection = prior_get_connection()
                    connection.set_trace_callback(statements.append)
                    return connection

                with patch.object(database, "get_connection", side_effect=connect) as connection_factory:
                    started = time.perf_counter()
                    writer(1, incoming)
                    elapsed_ms = (time.perf_counter() - started) * 1000
                select_count = sum(
                    statement.lstrip().upper().startswith("SELECT THUMBNAIL_URL")
                    for statement in statements
                )
                return elapsed_ms, connection_factory.call_count, select_count

            for iteration in range(iterations):
                modes = (("reference", reference_save_episodes), ("batched", database.save_episodes))
                if iteration % 2:
                    modes = tuple(reversed(modes))
                for label, writer in modes:
                    elapsed, _connections, _selects = traced_write(writer)
                    if snapshot(1) != expected:
                        raise AssertionError(f"{label} changed catalog values for {count} episodes")
                    (reference_samples if label == "reference" else batched_samples).append(elapsed)

            _elapsed, reference_connections, reference_selects = traced_write(reference_save_episodes)
            _elapsed, batched_connections, batched_selects = traced_write(database.save_episodes)
        finally:
            database.DATABASE_NAME = previous_db

    reference_median = statistics.median(reference_samples)
    batched_median = statistics.median(batched_samples)
    return {
        "episodes": count,
        "results_match_exactly": actual == expected,
        "connections_per_save": {
            "reference": reference_connections,
            "batched": batched_connections,
        },
        "thumbnail_selects_per_save": {
            "reference_per_episode": reference_selects,
            "batched_chunked": batched_selects,
        },
        "reference": {
            "median_ms": round(reference_median, 3),
            "p95_ms": round(percentile(reference_samples, .95), 3),
        },
        "batched": {
            "median_ms": round(batched_median, 3),
            "p95_ms": round(percentile(batched_samples, .95), 3),
        },
        "median_speedup_ratio": round(reference_median / batched_median, 3)
        if batched_median > 0 else None,
        "scope": "SQLite catalog upserts only; excludes TMDB/network work",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--episode-counts", nargs="+", type=int, default=[12, 100, 500, 1500])
    parser.add_argument("--iterations", type=int, default=5)
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()
    if any(count < 1 or count > 10000 for count in args.episode_counts):
        parser.error("episode counts must be between 1 and 10000")
    if not 1 <= args.iterations <= 30:
        parser.error("iterations must be between 1 and 30")
    payload = {
        "benchmark": "episode catalog upsert thumbnail reads",
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "workload": "synthetic SQLite database; no network requests or user data",
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
