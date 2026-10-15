import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QGridLayout

from ui.pages.entity_profile_page import (
    ClickableCharacterArtwork,
    EntityProfilePage,
    MediaCreditCard,
    RoundedArtworkLabel,
)
from ui.widgets.person_card import PersonCard


class EntityProfileUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_entire_media_credit_card_opens_internal_work_detail(self):
        card = MediaCreditCard({
            "node": {
                "id": 123,
                "type": "ANIME",
                "title": {"english": "Example Series"},
                "format": "TV",
            },
            "characterRole": "MAIN",
        }, "character")
        selected = []
        card.work_selected.connect(selected.append)
        card.show()
        self.app.processEvents()

        self.assertFalse(card.findChildren(QPushButton))
        QTest.mouseClick(card, Qt.LeftButton)
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0]["id"], 123)
        self.assertEqual(selected[0]["type"], "ANIME")
        card.close()

    def test_media_credit_artwork_uses_rounded_clipping_widget(self):
        card = MediaCreditCard(
            {"node": {"id": 123, "title": {"romaji": "Series"}}}, "staff"
        )
        self.assertIsInstance(card.cover, RoundedArtworkLabel)
        self.assertEqual((card.cover.width(), card.cover.height()), (88, 116))

    def test_voice_actor_credits_show_clickable_characters_on_the_right(self):
        card = MediaCreditCard({
            "node": {
                "id": 123,
                "type": "ANIME",
                "title": {"romaji": "Example Series"},
            },
            "characterRole": "MAIN",
            "characters": [{
                "id": 456,
                "name": {"full": "Example Character"},
                "image": {"large": "https://example.invalid/character.jpg"},
            }],
        }, "voice_actor")
        selected_work = []
        selected_character = []
        card.work_selected.connect(selected_work.append)
        card.character_selected.connect(selected_character.append)
        card.show()
        self.app.processEvents()

        self.assertEqual(len(card.character_cards), 1)
        self.assertEqual(card.character_cards[0].character["character_name"], "Example Character")
        role_label = card.findChild(QLabel, "mediaCreditRole")
        name_label = card.findChild(QLabel, "creditCharacterName")
        self.assertIsNotNone(role_label)
        self.assertIsNotNone(name_label)
        self.assertEqual(role_label.text(), "Main")
        self.assertEqual(name_label.text(), "Example Character")
        self.assertTrue(role_label.alignment() & Qt.AlignHCenter)
        self.assertTrue(name_label.alignment() & Qt.AlignVCenter)
        self.assertEqual(card.toolTip(), "Example Series")
        title_label = card.findChild(QLabel, "mediaCreditTitle")
        self.assertIsNotNone(title_label)
        self.assertEqual(title_label.text(), "Example Series")
        self.assertTrue(title_label.alignment() & Qt.AlignRight)
        self.assertEqual(title_label.parentWidget(), name_label.parentWidget())
        self.assertEqual(title_label.font().pointSize(), name_label.font().pointSize())
        text_layout = card.layout().itemAt(1).layout()
        self.assertIsInstance(text_layout, QGridLayout)
        role_index = text_layout.indexOf(role_label)
        self.assertGreaterEqual(role_index, 0)
        self.assertEqual(text_layout.getItemPosition(role_index), (0, 0, 1, 2))
        names_widget_item = next(
            index for index in range(text_layout.count())
            if text_layout.itemAt(index).widget() is name_label.parentWidget()
        )
        self.assertEqual(text_layout.getItemPosition(names_widget_item), (0, 0, 1, 2))
        QTest.mouseClick(card.character_cards[0], Qt.LeftButton)
        self.assertEqual(len(selected_character), 1)
        self.assertEqual(selected_character[0]["id"], 456)
        self.assertEqual(selected_work, [])
        QTest.mouseClick(card, Qt.LeftButton)
        self.assertEqual(len(selected_work), 1)
        self.assertEqual(selected_work[0]["id"], 123)
        card.close()

    def test_character_credit_artwork_is_clickable_without_nested_name_frame(self):
        character = ClickableCharacterArtwork({
            "id": 456, "name": {"full": "Character"}
        })
        selected = []
        character.clicked.connect(selected.append)
        character.show()
        self.app.processEvents()
        self.assertEqual((character.width(), character.height()), (88, 116))
        self.assertEqual(character.character["character_name"], "Character")
        self.assertFalse(character.findChildren(QLabel))
        QTest.mouseClick(character, Qt.LeftButton)
        self.assertEqual(selected[0]["id"], 456)
        character.close()

    def test_voice_actor_cards_use_portrait_not_square_artwork(self):
        card = PersonCard(
            {"name": "Sample voice actor"},
            portrait_size=(90, 120),
        )
        self.assertEqual((card.image.width(), card.image.height()), (90, 120))

    def test_profile_portraits_are_rounded_and_fill_their_frames(self):
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
                self.assertIsInstance(target, RoundedArtworkLabel)
                target.setPixmap(portrait)
                page.show()
                self.app.processEvents()
                rendered = target.grab().toImage()
                self.assertEqual(rendered.size().width(), target.width())
                self.assertEqual(rendered.size().height(), target.height())
                self.assertFalse(rendered.pixelColor(0, 0).red() > 200)
                page.hide()
        page.close()

    def test_profile_has_no_external_anilist_button(self):
        page = EntityProfilePage()
        page.set_profile("character", {"id": 0, "character_name": "Sample character"})
        visible_text = [
            button.text() for button in page.findChildren(QPushButton)
        ]
        self.assertEqual(visible_text, ["← Back"])
        self.assertFalse(any("AniList" in text for text in visible_text))
        page.close()


if __name__ == "__main__":
    unittest.main()
