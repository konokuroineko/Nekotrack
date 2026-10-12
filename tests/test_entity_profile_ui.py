import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import QApplication, QPushButton

from ui.pages.entity_profile_page import EntityProfilePage, MediaCreditCard
from ui.widgets.person_card import PersonCard


class EntityProfileUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_media_credit_opens_internal_work_detail(self):
        edge = {
            "node": {
                "id": 123,
                "type": "ANIME",
                "title": {"english": "Example Series"},
                "format": "TV",
            },
            "characterRole": "MAIN",
        }
        card = MediaCreditCard(edge, "character")
        selected = []
        card.work_selected.connect(selected.append)

        button = next(
            button for button in card.findChildren(QPushButton)
            if button.text() == "Open in NekoTrack →"
        )
        self.assertTrue(button.isEnabled())
        button.click()

        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0]["id"], 123)
        self.assertEqual(selected[0]["type"], "ANIME")

    def test_credit_card_has_no_external_anilist_link(self):
        card = MediaCreditCard(
            {"node": {"id": 123, "title": {"romaji": "Series"}}},
            "staff",
        )
        button_texts = [
            button.text() for button in card.findChildren(QPushButton)
        ]
        self.assertIn("Open in NekoTrack →", button_texts)
        self.assertFalse(any("AniList" in text for text in button_texts))

    def test_voice_actor_cards_use_portrait_not_square_artwork(self):
        card = PersonCard(
            {"name": "Sample voice actor"},
            portrait_size=(90, 120),
        )
        self.assertEqual((card.image.width(), card.image.height()), (90, 120))

    def test_character_and_voice_actor_portraits_fill_their_frames(self):
        page = EntityProfilePage()
        portrait = QPixmap(420, 180)
        portrait.fill(QColor("#cc2244"))

        for entity_type, record in (
            ("character", {"id": 0, "character_name": "Sample character"}),
            ("voice_actor", {"person_id": 0, "name": "Sample voice actor"}),
        ):
            with self.subTest(entity_type=entity_type):
                page.set_profile(entity_type, record)
                target = page._image_label
                page._set_artwork(portrait)
                displayed = target.pixmap()
                self.assertFalse(displayed.isNull())
                self.assertEqual(displayed.size(), target.size())

    def test_profile_has_no_external_anilist_button(self):
        page = EntityProfilePage()
        page.set_profile("character", {"id": 0, "character_name": "Sample character"})
        visible_text = [
            button.text() for button in page.findChildren(QPushButton)
        ]
        self.assertEqual(visible_text, ["← Back"])
        self.assertFalse(any("AniList" in text for text in visible_text))


if __name__ == "__main__":
    unittest.main()
