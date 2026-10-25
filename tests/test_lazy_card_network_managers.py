import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication

from ui.widgets.character_card import CharacterCard
from ui.widgets.person_card import PersonCard
from ui.widgets.relation_card import RelationCard


class LazyCardNetworkManagerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_cached_artwork_does_not_allocate_network_managers(self):
        with tempfile.TemporaryDirectory() as directory:
            image_path = Path(directory) / "cached.png"
            pixmap = QPixmap(8, 8)
            pixmap.fill(Qt.GlobalColor.white)
            self.assertTrue(pixmap.save(str(image_path), "PNG"))

            cards = [
                CharacterCard({
                    "id": 1,
                    "character_name": "Test character",
                    "character_image_path": str(image_path),
                    "person_id": 2,
                    "person_name": "Test voice actor",
                    "person_image_path": str(image_path),
                }),
                PersonCard({
                    "person_id": 3,
                    "name": "Test staff member",
                    "role": "Director",
                    "image_path": str(image_path),
                }),
                RelationCard({
                    "title": "Related work",
                    "cover_path": str(image_path),
                    "source_title": "Test source",
                    "relation_types": "SEQUEL",
                }),
            ]
            try:
                for card in cards:
                    self.assertIsNone(card._network_manager)
            finally:
                for card in cards:
                    card.close()
                    card.deleteLater()
                self.app.processEvents()
