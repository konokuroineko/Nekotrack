import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication, QLabel, QPushButton

import database
from ui.display_identity import copy_custom_cover, get_display_override, invalidate_display_override
from ui.pages.favorites_page import FavoritesPage
from ui.pages.work_detail_page import WorkDetailPage
from ui.widgets.work_card import WorkCard


class FavoritesIdentityOverrideTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self._old_cwd = os.getcwd()
        self._directory = tempfile.TemporaryDirectory()
        os.chdir(self._directory.name)
        self._db_path = Path(self._directory.name) / "favorites.db"
        self._db_patch = patch.object(database, "DATABASE_NAME", str(self._db_path))
        self._db_patch.start()
        database.initialize_database()
        connection = database.get_connection()
        connection.executemany(
            "INSERT INTO works (id, title, type, format, episodes, cover_url) VALUES (?, ?, ?, ?, ?, ?)",
            [
                (101, "Library Anime", "ANIME", "TV", 12, None),
                (102, "Favorite Only", "ANIME", "TV", 8, None),
                (103, "Identity Title", "ANIME", "TV", 6, None),
            ],
        )
        connection.commit()
        connection.close()
        invalidate_display_override()

    def tearDown(self):
        invalidate_display_override()
        self._db_patch.stop()
        os.chdir(self._old_cwd)
        self._directory.cleanup()

    def _image(self, path, color="#d65382"):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        image = QImage(48, 64, QImage.Format.Format_ARGB32)
        image.fill(QColor(color))
        self.assertTrue(image.save(str(path), "PNG"))
        return path

    def test_favorite_is_persistent_and_independent_of_library_membership(self):
        database.add_to_library(101, "Watching")
        self.assertTrue(
            database.set_work_favorite(
                102,
                True,
                {
                    "id": 102,
                    "type": "ANIME",
                    "format": "TV",
                    "title": {"english": "Favorite Only", "romaji": "Favorite Only"},
                    "cover_url": None,
                    "episodes": 8,
                },
            )
        )
        self.assertTrue(database.is_work_favorite(102))
        favorites = database.get_favorite_works()
        self.assertEqual([row["id"] for row in favorites], [102])
        self.assertEqual(favorites[0]["title"], "Favorite Only")
        self.assertIsNone(favorites[0]["status"])

        database.set_work_favorite(101, True, {"id": 101, "title": "Library Anime"})
        database.set_work_favorite(102, True)
        favorites = database.get_favorite_works()
        self.assertEqual({row["id"] for row in favorites}, {101, 102})
        self.assertTrue(database.is_work_favorite(101))

        self.assertFalse(database.set_work_favorite(102, False))
        self.assertFalse(database.is_work_favorite(102))
        self.assertEqual([row["id"] for row in database.get_favorite_works()], [101])

    def test_title_and_custom_cover_override_are_saved_and_cleared(self):
        external_cover = self._image(Path(self._directory.name) / "external.png")
        stored_cover = copy_custom_cover(str(external_cover))
        self.assertTrue((Path.cwd() / stored_cover).is_file())
        self.assertTrue(stored_cover.startswith("data/display_overrides/"))

        saved = database.save_work_display_override(
            103, "My preferred title", stored_cover
        )
        self.assertEqual(saved["custom_title"], "My preferred title")
        self.assertEqual(Path(saved["custom_cover_path"]), Path.cwd() / stored_cover)
        self.assertEqual(
            database.get_work_display_override(103)["custom_title"],
            "My preferred title",
        )
        self.assertEqual(
            get_display_override(103)["custom_title"],
            "My preferred title",
        )

        database.clear_work_display_override(103)
        invalidate_display_override(103)
        self.assertEqual(database.get_work_display_override(103), {})
        self.assertEqual(get_display_override(103), {})

    def test_identity_override_rejects_external_cover_paths_and_bad_titles(self):
        external_cover = self._image(Path(self._directory.name) / "outside.png")
        with self.assertRaisesRegex(ValueError, "display-overrides"):
            database.save_work_display_override(
                103, "Title", str(external_cover)
            )
        with self.assertRaisesRegex(ValueError, "200 printable"):
            database.save_work_display_override(103, "x" * 201, None)
        with self.assertRaises(ValueError):
            database.save_work_display_override(103, "Valid title", "../outside.png")


    def test_permanent_work_deletion_clears_favorite_and_global_override(self):
        source = self._image(Path(self._directory.name) / "delete-cover.png")
        stored_cover = copy_custom_cover(str(source))
        database.set_work_favorite(103, True, {"id": 103, "title": "Identity Title"})
        database.save_work_display_override(103, "Custom Identity Title", stored_cover)
        managed_cover = Path.cwd() / stored_cover
        self.assertTrue(managed_cover.is_file())
        self.assertTrue(database.is_work_favorite(103))

        self.assertTrue(database.delete_work_data(103))
        self.assertFalse(database.is_work_favorite(103))
        self.assertEqual(database.get_work_display_override(103), {})
        self.assertFalse(managed_cover.exists())

    def test_poster_cards_and_detail_titles_use_global_override_but_bundles_do_not(self):
        cover = self._image(Path(self._directory.name) / "global-cover.png")
        with patch(
            "ui.widgets.work_card.get_display_override",
            return_value={
                "custom_title": "Global Custom Name",
                "custom_cover_path": str(cover),
            },
        ):
            single = WorkCard(
                {
                    "id": 103,
                    "type": "ANIME",
                    "title": {"english": "Provider Name"},
                    "cover_url": None,
                    "cover_path": None,
                },
                mode="library",
            )
            self.assertEqual(single._title(), "Global Custom Name")
            self.assertFalse(single.cover._pixmap.isNull())
            single.deleteLater()

            bundle = WorkCard(
                {
                    "id": 103,
                    "type": "ANIME",
                    "title": {"english": "Bundle Name"},
                    "_series_count": 2,
                    "_series_members": [
                        {"id": 103, "title": {"english": "Provider Name"}},
                        {"id": 104, "title": {"english": "Second Member"}},
                    ],
                    "cover_url": None,
                    "cover_path": None,
                },
                mode="library",
            )
            self.assertEqual(bundle._title(), "Bundle Name")
            self.assertTrue(bundle.cover._pixmap.isNull())
            bundle.deleteLater()

        page = WorkDetailPage()
        page.work = {
            "id": 103,
            "title": {"english": "Provider Name"},
            "_series_members": [],
        }
        with patch(
            "ui.pages.work_detail_page.get_display_override",
            return_value={"custom_title": "Global Detail Name"},
        ):
            self.assertEqual(page._title(), "Global Detail Name")
        page.deleteLater()
        self.app.processEvents()

    def test_favorites_page_refreshes_and_removes_favorites(self):
        rows = [{
            "id": 102,
            "title": "Favorite Only",
            "type": "ANIME",
            "format": "TV",
            "status": None,
            "cover_url": None,
            "cover_path": None,
        }]
        with (
            patch("ui.pages.favorites_page.get_favorite_works", side_effect=[rows, []]),
            patch("ui.pages.favorites_page.set_work_favorite") as remove,
        ):
            page = FavoritesPage()
            self.app.processEvents()
            self.assertEqual(
                [label.text() for label in page.findChildren(QLabel, "favoritesStatus")],
                ["Not in Library"],
            )
            button = page.findChild(QPushButton, "favoritesRemove")
            self.assertIsNotNone(button)
            button.click()
            self.app.processEvents()
            remove.assert_called_once_with(102, False)
            self.assertTrue(
                any(
                    label.text() == "Nothing favorited yet"
                    for label in page.findChildren(QLabel)
                )
            )
            page.close()
            page.deleteLater()
            self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
