"""Safe CSV export of the user's saved NekoTrack library."""

from __future__ import annotations

import csv
import os
import tempfile
from pathlib import Path

from database import get_connection


_EXPORT_FIELDS = (
    ("work_id", "works", "id", True),
    ("title", "works", "title", True),
    ("media_type", "works", "type", True),
    ("format", "works", "format", False),
    ("episodes_total", "works", "episodes", False),
    ("chapters_total", "works", "chapters", False),
    ("volumes_total", "works", "volumes", False),
    ("catalog_score", "works", "score", False),
    ("start_year", "works", "start_year", False),
    ("list_status", "user_library", "status", True),
    ("episodes_watched", "user_library", "progress_episodes", False),
    ("chapters_read", "user_library", "progress_chapters", False),
    ("volumes_read", "user_library", "progress_volumes", False),
    ("personal_rating", "user_library", "rating", False),
    ("notes", "user_library", "notes", False),
    ("added_date", "user_library", "added_date", False),
    ("updated_date", "user_library", "updated_date", False),
)
_FIELD_NAMES = tuple(field[0] for field in _EXPORT_FIELDS)


def _table_columns(connection, table_name):
    rows = connection.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {row["name"] if hasattr(row, "keys") else row[1] for row in rows}


def _spreadsheet_safe(value):
    if not isinstance(value, str):
        return value
    if value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def export_library_csv(destination):
    """Write a portable list/progress report and return the number of saved works."""
    target = Path(destination).expanduser()
    if not str(destination or "").strip() or not target.name:
        raise ValueError("Choose a destination file for the library export.")
    if not target.parent.is_dir():
        raise FileNotFoundError(f"Export folder does not exist: {target.parent}")

    connection = get_connection()
    try:
        available = {
            "works": _table_columns(connection, "works"),
            "user_library": _table_columns(connection, "user_library"),
        }
        select_parts = []
        for alias, table_name, column_name, required in _EXPORT_FIELDS:
            if column_name in available[table_name]:
                select_parts.append(f"{table_name}.{column_name} AS {alias}")
            elif required:
                raise RuntimeError(
                    f"The NekoTrack database is missing required column "
                    f"{table_name}.{column_name}; initialize or repair the database first."
                )
            else:
                select_parts.append(f"NULL AS {alias}")

        query = (
            "SELECT " + ", ".join(select_parts)
            + " FROM works"
            + " INNER JOIN user_library ON user_library.work_id = works.id"
            + " ORDER BY user_library.added_date DESC, works.title COLLATE NOCASE, works.id"
        )
        rows = connection.execute(query).fetchall()
    finally:
        connection.close()

    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8-sig",
            newline="",
            prefix=f".{target.name}.",
            suffix=".tmp",
            dir=str(target.parent),
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            writer = csv.DictWriter(temporary_file, fieldnames=_FIELD_NAMES)
            writer.writeheader()
            for row in rows:
                writer.writerow({
                    field_name: _spreadsheet_safe(row[field_name])
                    for field_name in _FIELD_NAMES
                })
            temporary_file.flush()
            os.fsync(temporary_file.fileno())

        os.replace(temporary_path, target)
        temporary_path = None
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass

    return len(rows)
