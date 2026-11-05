import csv
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from library_export import export_library_csv


class LibraryCsvExportTests(unittest.TestCase):
    @staticmethod
    def _connection(include_optional=True):
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        optional = (
            ", format TEXT, episodes INTEGER, chapters INTEGER, volumes INTEGER, "
            "score REAL, start_year INTEGER"
            if include_optional else ""
        )
        connection.executescript(f"""
            CREATE TABLE works (
                id INTEGER PRIMARY KEY,
                title TEXT NOT NULL,
                type TEXT NOT NULL
                {optional}
            );
            CREATE TABLE user_library (
                work_id INTEGER PRIMARY KEY,
                status TEXT NOT NULL,
                progress_episodes INTEGER DEFAULT 0,
                progress_chapters INTEGER DEFAULT 0,
                progress_volumes INTEGER DEFAULT 0,
                rating INTEGER,
                notes TEXT,
                added_date TEXT,
                updated_date TEXT
            );
        """)
        return connection

    def test_exports_titles_status_progress_and_unicode(self):
        connection = self._connection()
        connection.execute("""
            INSERT INTO works
                (id, title, type, format, episodes, chapters, volumes, score, start_year)
            VALUES (42, '葬送のフリーレン', 'MANGA', 'MANGA', 28, 120, 12, 91.5, 2023)
        """)
        connection.execute("""
            INSERT INTO user_library
                (work_id, status, progress_episodes, progress_chapters,
                 progress_volumes, rating, notes, added_date, updated_date)
            VALUES (42, 'Current', 0, 32, 3, 9, 'Great series', '2026-10-01', '2026-11-01')
        """)
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "library.csv"
            with patch("library_export.get_connection", return_value=connection):
                exported = export_library_csv(destination)
            with destination.open("r", encoding="utf-8-sig", newline="") as handle:
                row = next(csv.DictReader(handle))

        self.assertEqual(exported, 1)
        self.assertEqual(row["work_id"], "42")
        self.assertEqual(row["title"], "葬送のフリーレン")
        self.assertEqual(row["list_status"], "Current")
        self.assertEqual(row["chapters_read"], "32")
        self.assertEqual(row["volumes_read"], "3")
        self.assertEqual(row["personal_rating"], "9")
        self.assertEqual(row["notes"], "Great series")
        self.assertEqual(row["chapters_total"], "120")
        self.assertEqual(row["volumes_total"], "12")

    def test_empty_library_still_writes_headers(self):
        connection = self._connection()
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "empty.csv"
            with patch("library_export.get_connection", return_value=connection):
                exported = export_library_csv(destination)
            with destination.open("r", encoding="utf-8-sig", newline="") as handle:
                reader = csv.DictReader(handle)
                rows = list(reader)

        self.assertEqual(exported, 0)
        self.assertIn("title", reader.fieldnames)
        self.assertEqual(rows, [])

    def test_older_schema_exports_missing_optional_columns_as_empty(self):
        connection = self._connection(include_optional=False)
        connection.execute("INSERT INTO works (id, title, type) VALUES (7, 'Older title', 'ANIME')")
        connection.execute("""
            INSERT INTO user_library (work_id, status, added_date, updated_date)
            VALUES (7, 'Planning', '2026-01-01', '2026-01-01')
        """)
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "older.csv"
            with patch("library_export.get_connection", return_value=connection):
                export_library_csv(destination)
            with destination.open("r", encoding="utf-8-sig", newline="") as handle:
                row = next(csv.DictReader(handle))

        self.assertEqual(row["title"], "Older title")
        self.assertEqual(row["format"], "")
        self.assertEqual(row["chapters_total"], "")
        self.assertEqual(row["catalog_score"], "")

    def test_formula_like_text_is_escaped(self):
        connection = self._connection()
        connection.execute(
            "INSERT INTO works (id, title, type) VALUES (1, '=HYPERLINK(\"bad\")', 'MANGA')"
        )
        connection.execute("""
            INSERT INTO user_library (work_id, status, notes, added_date, updated_date)
            VALUES (1, 'Planning', '=1+1', '2026-01-01', '2026-01-01')
        """)
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "formula.csv"
            with patch("library_export.get_connection", return_value=connection):
                export_library_csv(destination)
            with destination.open("r", encoding="utf-8-sig", newline="") as handle:
                row = next(csv.DictReader(handle))

        self.assertEqual(row["title"], "'=HYPERLINK(\"bad\")'")
        self.assertEqual(row["notes"], "'=1+1'")

    def test_invalid_destination_is_rejected(self):
        with self.assertRaises(ValueError):
            export_library_csv("")


if __name__ == "__main__":
    unittest.main()
