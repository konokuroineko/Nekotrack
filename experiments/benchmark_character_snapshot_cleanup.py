"""Compare old per-character cleanup with batched complete-cast cleanup.

The benchmark creates disposable SQLite databases, seeds deterministic character and
voice-actor snapshots, then times only the cleanup step. It makes no API calls and
never opens the user's database.
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

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import database  # noqa: E402


class CountingConnection:
    """Thin proxy that counts Python execute/executemany calls."""

    def __init__(self, connection):
        self.connection = connection
        self.execute_calls = 0
        self.executemany_calls = 0

    def execute(self, *args, **kwargs):
        self.execute_calls += 1
        return self.connection.execute(*args, **kwargs)

    def executemany(self, *args, **kwargs):
        self.executemany_calls += 1
        return self.connection.executemany(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self.connection, name)


def _legacy_cleanup(work_id):
    """Reference implementation of the former per-record cleanup block."""
    connection = database.get_connection()

    def remove_person_if_orphaned(person_id):
        references = connection.execute(
            """
            SELECT 1 FROM character_voice_actors WHERE person_id = ?
            UNION ALL
            SELECT 1 FROM work_staff WHERE person_id = ?
            LIMIT 1
            """,
            (person_id, person_id),
        ).fetchone()
        if references is None:
            connection.execute("DELETE FROM people WHERE id = ?", (person_id,))

    try:
        existing_character_rows = connection.execute(
            "SELECT character_id FROM work_characters WHERE work_id = ?",
            (work_id,),
        ).fetchall()
        for row in existing_character_rows:
            character_id = int(row["character_id"])
            connection.execute(
                "DELETE FROM work_characters WHERE work_id = ? AND character_id = ?",
                (work_id, character_id),
            )
            old_scoped_actors = connection.execute(
                """
                SELECT person_id FROM work_character_voice_actors
                WHERE work_id = ? AND character_id = ?
                """,
                (work_id, character_id),
            ).fetchall()
            connection.execute(
                "DELETE FROM work_character_voice_actors WHERE work_id = ? AND character_id = ?",
                (work_id, character_id),
            )
            for old_actor_row in old_scoped_actors:
                person_id = int(old_actor_row["person_id"])
                still_assigned = connection.execute(
                    """
                    SELECT 1 FROM work_character_voice_actors
                    WHERE character_id = ? AND person_id = ? LIMIT 1
                    """,
                    (character_id, person_id),
                ).fetchone()
                if still_assigned is None:
                    connection.execute(
                        """
                        DELETE FROM character_voice_actors
                        WHERE character_id = ? AND person_id = ?
                        """,
                        (character_id, person_id),
                    )
                    remove_person_if_orphaned(person_id)

            still_linked = connection.execute(
                "SELECT 1 FROM work_characters WHERE character_id = ? LIMIT 1",
                (character_id,),
            ).fetchone()
            if still_linked is None:
                old_actor_rows = connection.execute(
                    "SELECT person_id FROM character_voice_actors WHERE character_id = ?",
                    (character_id,),
                ).fetchall()
                connection.execute(
                    "DELETE FROM character_voice_actors WHERE character_id = ?",
                    (character_id,),
                )
                for old_actor_row in old_actor_rows:
                    remove_person_if_orphaned(int(old_actor_row["person_id"]))
                connection.execute(
                    "DELETE FROM characters WHERE id = ?",
                    (character_id,),
                )

        connection.execute(
            "UPDATE works SET characters_loaded = 1 WHERE id = ?",
            (work_id,),
        )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _snapshot_database():
    tables = (
        "works",
        "characters",
        "people",
        "work_characters",
        "character_voice_actors",
        "work_character_voice_actors",
        "work_staff",
    )
    connection = database.get_connection()
    try:
        result = {}
        for table in tables:
            rows = connection.execute(
                f"SELECT * FROM {table} ORDER BY 1, 2"
                if table not in {"works", "characters", "people"}
                else f"SELECT * FROM {table} ORDER BY 1"
            ).fetchall()
            result[table] = [dict(row) for row in rows]
        return result
    finally:
        connection.close()


def _run_once(path: Path, count: int, mode: str) -> dict:
    prior_database = database.DATABASE_NAME
    database.DATABASE_NAME = str(path)
    try:
        database.initialize_database()
        connection = database.get_connection()
        try:
            connection.execute(
                """
                INSERT INTO works (id, title, type, format, episodes, characters_loaded)
                VALUES (1, 'Synthetic cast cleanup', 'ANIME', 'TV', 0, 0)
                """
            )
            connection.commit()
        finally:
            connection.close()

        payload = []
        for offset in range(count):
            character_id = 10_000 + offset
            actor_id = 20_000 + offset
            payload.append({
                "node": {
                    "id": character_id,
                    "name": {"full": f"Character {offset}"},
                    "image": {"large": f"https://example.invalid/character-{offset}.jpg"},
                },
                "role": "MAIN",
                "voiceActors": [{
                    "id": actor_id,
                    "name": {"full": f"Voice Actor {offset}"},
                    "image": {"large": f"https://example.invalid/actor-{offset}.jpg"},
                    "language": "Japanese",
                }],
            })
        database.save_characters(1, payload)

        original_factory = database.get_connection
        counted_connections = []

        def counted_factory():
            wrapped = CountingConnection(original_factory())
            counted_connections.append(wrapped)
            return wrapped

        database.get_connection = counted_factory
        try:
            started = time.perf_counter()
            if mode == "reference":
                _legacy_cleanup(1)
            else:
                database.save_characters(1, [])
            elapsed_ms = (time.perf_counter() - started) * 1000
        finally:
            database.get_connection = original_factory

        if len(counted_connections) != 1:
            raise AssertionError(f"expected one cleanup connection, got {len(counted_connections)}")
        return {
            "elapsed_ms": elapsed_ms,
            "execute_calls": counted_connections[0].execute_calls,
            "executemany_calls": counted_connections[0].executemany_calls,
            "snapshot": _snapshot_database(),
        }
    finally:
        database.DATABASE_NAME = prior_database


def _percentile(values, fraction):
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * fraction)))
    return ordered[index]


def run_one_size(count, iterations):
    old_samples, new_samples = [], []
    old_execute_counts, new_execute_counts = [], []
    old_many_counts, new_many_counts = [], []
    reference_snapshot = optimized_snapshot = None

    for iteration in range(iterations):
        modes = ("reference", "batched") if iteration % 2 == 0 else ("batched", "reference")
        for mode in modes:
            with tempfile.TemporaryDirectory(prefix="nekotrack-cast-cleanup-") as directory:
                output = _run_once(Path(directory) / "cleanup.sqlite3", count, mode)
            if mode == "reference":
                reference_snapshot = output["snapshot"]
                old_samples.append(output["elapsed_ms"])
                old_execute_counts.append(output["execute_calls"])
                old_many_counts.append(output["executemany_calls"])
            else:
                optimized_snapshot = output["snapshot"]
                new_samples.append(output["elapsed_ms"])
                new_execute_counts.append(output["execute_calls"])
                new_many_counts.append(output["executemany_calls"])

            if reference_snapshot is not None and optimized_snapshot is not None:
                if reference_snapshot != optimized_snapshot:
                    raise AssertionError(f"cleanup state differs for {count} characters")

    old_median = statistics.median(old_samples)
    new_median = statistics.median(new_samples)
    return {
        "characters_removed": count,
        "results_match_exactly": reference_snapshot == optimized_snapshot,
        "per_record_reference": {
            "median_ms": round(old_median, 3),
            "p95_ms": round(_percentile(old_samples, 0.95), 3),
            "execute_calls_median": round(statistics.median(old_execute_counts), 1),
            "executemany_calls_median": round(statistics.median(old_many_counts), 1),
        },
        "batched_cleanup": {
            "median_ms": round(new_median, 3),
            "p95_ms": round(_percentile(new_samples, 0.95), 3),
            "execute_calls_median": round(statistics.median(new_execute_counts), 1),
            "executemany_calls_median": round(statistics.median(new_many_counts), 1),
        },
        "median_speedup_ratio": round(old_median / new_median, 3) if new_median > 0 else None,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--character-counts", nargs="+", type=int, default=[25, 100, 250, 500, 1000])
    parser.add_argument("--iterations", type=int, default=3)
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()
    if any(count < 1 or count > 1000 for count in args.character_counts):
        parser.error("character counts must be between 1 and 1,000")
    if not 1 <= args.iterations <= 15:
        parser.error("iterations must be between 1 and 15")

    payload = {
        "benchmark": "complete character snapshot cleanup",
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "workload": "disposable synthetic SQLite database; one voice actor per character",
        "iterations_per_mode": args.iterations,
        "results": [run_one_size(count, args.iterations) for count in args.character_counts],
    }
    print(json.dumps(payload, indent=2))
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
