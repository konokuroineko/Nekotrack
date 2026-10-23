"""Benchmark per-work versus batched bundle-detail and readiness SQLite reads.

Uses disposable synthetic data, makes no API calls, and never opens the user's DB.
Checks exact output parity before reporting latency and SQLite connection counts.
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
for path in (ROOT, ROOT / "tests"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
import database  # noqa: E402
from test_database_bundle_queries import (  # noqa: E402
    reference_bundle_characters, reference_bundle_detail_readiness,
    reference_bundle_relations, reference_bundle_staff,
)


def percentile(samples, fraction):
    ordered = sorted(samples)
    return ordered[min(len(ordered) - 1, max(0, round((len(ordered) - 1) * fraction)))]


def create_synthetic_db(path: Path, count: int):
    database.DATABASE_NAME = str(path)
    con = database.get_connection()
    try:
        con.executescript("""
            CREATE TABLE works (id INTEGER PRIMARY KEY, title TEXT NOT NULL, type TEXT NOT NULL, format TEXT, cover_url TEXT, cover_path TEXT, episodes INTEGER, characters_loaded INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE characters (id INTEGER PRIMARY KEY, name TEXT NOT NULL, image_url TEXT, image_path TEXT);
            CREATE TABLE people (id INTEGER PRIMARY KEY, name TEXT NOT NULL, image_url TEXT, image_path TEXT);
            CREATE TABLE work_characters (work_id INTEGER NOT NULL, character_id INTEGER NOT NULL, role TEXT, PRIMARY KEY (work_id, character_id));
            CREATE TABLE work_character_voice_actors (work_id INTEGER NOT NULL, character_id INTEGER NOT NULL, person_id INTEGER NOT NULL, language TEXT, PRIMARY KEY (work_id, character_id, person_id));
            CREATE TABLE work_staff (work_id INTEGER NOT NULL, person_id INTEGER NOT NULL, role TEXT NOT NULL, PRIMARY KEY (work_id, person_id, role));
            CREATE TABLE work_relations (source_id INTEGER NOT NULL, target_id INTEGER NOT NULL, relation_type TEXT NOT NULL, PRIMARY KEY (source_id, target_id, relation_type));
            CREATE TABLE episodes (id INTEGER PRIMARY KEY, work_id INTEGER NOT NULL, episode_number INTEGER NOT NULL, title TEXT, description TEXT, air_date TEXT, thumbnail_url TEXT, watched INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE user_library (work_id INTEGER PRIMARY KEY, status TEXT, progress_episodes INTEGER, progress_chapters INTEGER, progress_volumes INTEGER, rating INTEGER, notes TEXT, added_date TEXT, updated_date TEXT);
            CREATE TABLE bundle_overrides (bundle_anchor_id INTEGER PRIMARY KEY, custom_title TEXT, cover_work_id INTEGER, custom_cover_path TEXT);
        """)
        works = [(i, f"Synthetic Work {i}", "ANIME", "TV", None, None) for i in range(1, count + 1)]
        works += [(count + 100 + i, f"External Relation {i}", "ANIME", "TV", None, None) for i in range(20)]
        con.executemany("INSERT INTO works (id,title,type,format,cover_url,cover_path) VALUES (?,?,?,?,?,?)", works)
        con.executemany(
            "UPDATE works SET episodes = ?, characters_loaded = 1 WHERE id = ?",
            [(12 if work_id % 2 == 0 else 0, work_id) for work_id in range(1, count + 1)],
        )
        con.executemany("INSERT INTO characters (id,name) VALUES (?,?)", [(1000+i, f"Character {i}") for i in range(30)])
        people = [(2000+i, f"Voice Actor {i:02d}", None, None) for i in range(25)]
        people += [(3000+i, f"Staff Person {i:02d}", None, None) for i in range(45)]
        con.executemany("INSERT INTO people VALUES (?,?,?,?)", people)
        char_roles = ("MAIN", "SUPPORTING", "BACKGROUND")
        staff_roles = ("Animation", "Director", "Music", "Original Creator", "Producer", "Script", "Series Composition")
        rel_types = ("ADAPTATION", "PREQUEL", "SEQUEL", "SIDE_STORY")
        characters, voices, staff, relations = [], [], [], []
        for work in range(1, count + 1):
            for n in range(6):
                char_id = 1000 + ((work * 3 + n) % 30)
                characters.append((work, char_id, char_roles[(work+n) % 3]))
                voices.append((work, char_id, 2000 + ((work+n) % 25),
                               "Japanese" if (work+n) % 4 == 0 else "English"))
            for n in range(8):
                staff.append((work, 3000 + ((work*2+n) % 45), staff_roles[(work+n) % len(staff_roles)]))
            for n, relation_type in enumerate(rel_types):
                relations.append((work, count + 100 + ((work*3+n) % 20), relation_type))
        con.executemany("INSERT INTO work_characters VALUES (?,?,?)", characters)
        con.executemany("INSERT INTO work_character_voice_actors VALUES (?,?,?,?)", voices)
        con.executemany("INSERT INTO work_staff VALUES (?,?,?)", staff)
        con.executemany("INSERT INTO work_relations VALUES (?,?,?)", relations)
        con.executemany(
            "INSERT INTO episodes (id, work_id, episode_number) VALUES (?, ?, ?)",
            [(work_id * 1000 + 1, work_id, 1) for work_id in range(1, count + 1) if work_id % 2 == 0],
        )
        con.executemany(
            "INSERT INTO bundle_overrides VALUES (?, ?, ?, ?)",
            [(anchor, f"Custom Bundle {anchor}", anchor + 1, None)
             for anchor in range(1, count, 4) if anchor + 1 <= count],
        )
        con.commit()
    finally:
        con.close()
    return list(range(1, count + 1))


def _bundle_groups(ids):
    return [ids[start:start + 2] for start in range(0, len(ids), 2)
            if len(ids[start:start + 2]) > 1]


def reference_override_snapshots(ids):
    snapshots = []
    for members in _bundle_groups(ids):
        row = database.get_bundle_override(members)
        snapshots.append({
            "member_ids": list(members),
            "override": dict(row) if row is not None else None,
        })
    return snapshots


def batched_override_snapshots(ids):
    groups = _bundle_groups(ids)
    rows = database.get_bundle_overrides(ids)
    by_anchor = {int(row["bundle_anchor_id"]): dict(row) for row in rows}
    snapshots = []
    for members in groups:
        selected = next((by_anchor[work_id] for work_id in sorted(members)
                         if work_id in by_anchor), None)
        snapshots.append({"member_ids": list(members), "override": selected})
    return snapshots


def old_read(ids):
    return (
        reference_bundle_characters(ids),
        reference_bundle_staff(ids),
        reference_bundle_relations(ids),
        reference_bundle_detail_readiness(ids),
        reference_override_snapshots(ids),
    )


def batched_read(ids):
    return (
        database.get_bundle_characters(ids),
        database.get_bundle_staff(ids),
        database.get_bundle_relations(ids),
        database.get_bundle_detail_readiness(ids),
        batched_override_snapshots(ids),
    )


def run_one_size(count, iterations):
    with tempfile.TemporaryDirectory(prefix="nekotrack-bundle-bench-") as directory:
        prior_db = database.DATABASE_NAME
        try:
            ids = create_synthetic_db(Path(directory) / "benchmark.sqlite3", count)
            expected = old_read(ids)
            actual = batched_read(ids)
            if actual != expected:
                raise AssertionError("batched output differs from former per-work implementation")
            old_samples, new_samples = [], []
            for iteration in range(iterations):
                modes = (("old", old_read), ("new", batched_read))
                if iteration % 2:
                    modes = tuple(reversed(modes))
                for label, fn in modes:
                    started = time.perf_counter()
                    result = fn(ids)
                    elapsed = (time.perf_counter() - started) * 1000
                    if result != expected:
                        raise AssertionError(f"{label} output changed")
                    (old_samples if label == "old" else new_samples).append(elapsed)
            with patch.object(database, "get_connection", wraps=database.get_connection) as counter:
                old_read(ids)
                old_calls = counter.call_count
            with patch.object(database, "get_connection", wraps=database.get_connection) as counter:
                batched_read(ids)
                new_calls = counter.call_count
        finally:
            database.DATABASE_NAME = prior_db
    old_med, new_med = statistics.median(old_samples), statistics.median(new_samples)
    return {
        "works_in_bundle": count,
        "results_match_exactly": actual == expected,
        "connections_per_full_read": {"per_work_reference": old_calls, "batched": new_calls},
        "per_work_reference": {"median_ms": round(old_med, 3), "p95_ms": round(percentile(old_samples, .95), 3)},
        "batched": {"median_ms": round(new_med, 3), "p95_ms": round(percentile(new_samples, .95), 3)},
        "median_speedup_ratio": round(old_med/new_med, 3) if new_med > 0 else None,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-counts", nargs="+", type=int, default=[5, 20, 50])
    parser.add_argument("--iterations", type=int, default=5)
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()
    if any(n < 1 or n > 500 for n in args.work_counts):
        parser.error("work counts must be between 1 and 500")
    if not 1 <= args.iterations <= 30:
        parser.error("iterations must be between 1 and 30")
    payload = {
        "benchmark": "database bundled Work Details reads",
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "workload": "temporary synthetic SQLite database; no external APIs or user data",
        "iterations_per_mode": args.iterations,
        "results": [run_one_size(n, args.iterations) for n in args.work_counts],
    }
    print(json.dumps(payload, indent=2))
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
