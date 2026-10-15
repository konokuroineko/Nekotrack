import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QGridLayout, QBoxLayout, QTextBrowser

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
        self.assertTrue(name_label.alignment() & Qt.AlignRight)
        self.assertEqual(card.toolTip(), "")
        title_label = card.findChild(QLabel, "mediaCreditTitle")
        self.assertIsNotNone(title_label)
        self.assertEqual(title_label.text(), "Example Series")
        self.assertEqual(title_label.toolTip(), "")
        self.assertTrue(title_label.alignment() & Qt.AlignLeft)
        self.assertEqual(title_label.parentWidget(), name_label.parentWidget())
        self.assertEqual(title_label.font().pointSize(), name_label.font().pointSize())
        names_layout = name_label.parentWidget().layout()
        self.assertEqual(names_layout.direction(), QBoxLayout.LeftToRight)
        self.assertEqual(name_label.parentWidget().layoutDirection(), Qt.LeftToRight)
        self.assertIs(names_layout.itemAt(0).widget(), title_label)
        self.assertIs(names_layout.itemAt(1).widget(), name_label)
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

    def test_voice_credit_names_keep_physical_left_right_order_under_rtl(self):
        previous_direction = self.app.layoutDirection()
        self.app.setLayoutDirection(Qt.RightToLeft)
        card = None
        try:
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
                }],
            }, "voice_actor")
            selected_work = []
            selected_character = []
            card.work_selected.connect(selected_work.append)
            card.character_selected.connect(selected_character.append)
            card.show()
            self.app.processEvents()

            self.assertEqual(card.layoutDirection(), Qt.LeftToRight)
            outer_layout = card.layout()
            self.assertEqual(outer_layout.direction(), QBoxLayout.LeftToRight)
            self.assertIsNotNone(card.character_artwork)
            self.assertLess(
                card.cover.geometry().center().x(),
                card.character_artwork.geometry().center().x(),
                "Work poster must render physically left of the character portrait",
            )

            name_label = card.findChild(QLabel, "creditCharacterName")
            title_label = card.findChild(QLabel, "mediaCreditTitle")
            self.assertIsNotNone(name_label)
            self.assertIsNotNone(title_label)
            self.assertEqual(name_label.layoutDirection(), Qt.LeftToRight)
            self.assertEqual(title_label.layoutDirection(), Qt.LeftToRight)
            self.assertLess(
                title_label.geometry().center().x(),
                name_label.geometry().center().x(),
                "Anime title must render physically left of the character name",
            )
            self.assertEqual(card.toolTip(), "")
            self.assertEqual(title_label.toolTip(), "")

            # The character portrait must keep its own navigation target while a
            # click in the poster's left-hand area still opens the work.
            QTest.mouseClick(card.character_artwork, Qt.LeftButton)
            self.assertEqual(len(selected_character), 1)
            self.assertEqual(selected_character[0]["id"], 456)
            self.assertEqual(selected_work, [])
            QTest.mouseClick(card, Qt.LeftButton, pos=card.cover.geometry().center())
            self.assertEqual(len(selected_work), 1)
            self.assertEqual(selected_work[0]["id"], 123)
        finally:
            if card is not None:
                card.close()
            self.app.setLayoutDirection(previous_direction)

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

    def test_profile_facts_and_biography_use_one_vertical_column(self):
        page = EntityProfilePage()
        try:
            with patch.object(EntityProfilePage, "_start_profile_load"):
                page.set_profile(
                    "voice_actor",
                    {"person_id": 456, "name": "Example Voice Actor"},
                )
            page._remote_data = {
                "id": 456,
                "name": {"full": "Example Voice Actor"},
                "primaryOccupations": ["Voice Actor", "Singer"],
                "languageV2": "Japanese",
                "gender": "Female",
                "description": "Biography text.",
                "descriptionHtml": (
                    "<p><strong>Biography text</strong> should follow the facts.</p>"
                ),
                "image": {},
                "staffMedia": {"edges": []},
                "characterMedia": {"edges": []},
            }
            page._render_profile()
            page.show()
            self.app.processEvents()

            header_item = page.content_layout.itemAt(0)
            header = header_item.widget() if header_item is not None else None
            self.assertIsNotNone(header)
            bio = header.findChild(QTextBrowser, "profileDescription")
            self.assertIsNotNone(bio)
            fact_labels = header.findChildren(QLabel, "profileFacts")
            self.assertTrue(fact_labels)
            last_fact = max(fact_labels, key=lambda label: label.geometry().bottom())

            self.assertLess(
                last_fact.geometry().bottom(),
                bio.geometry().top(),
                "All structured facts must appear above the biography, not beside it",
            )
            self.assertLessEqual(
                abs(last_fact.geometry().x() - bio.geometry().x()),
                4,
                "Facts and biography should share the same left edge",
            )
            self.assertIn("Biography text", bio.toPlainText())
        finally:
            page.close()
            page.deleteLater()

    def test_voice_actor_bio_links_are_fixed_without_changing_html_formatting(self):
        raw_description = "\n".join((
            r"[YouTube]\([https://www.youtube.com/](https://www.youtube.com/)"
            r"[@Ueda](https://anilist.co/user/Ueda)-Kana)",
            r"[Youtube]\([https://youtube.com/](https://youtube.com/)"
            r"[@officialyoutubechannel3974](https://anilist.co/user/officialyoutubechannel3974)"
            r"?si=9AjlJ6Ujj2Vw1CiU)",
            r"[Youtube]\([https://www.youtube.com/](https://www.youtube.com/)"
            r"[@OfficialChannel](https://anilist.co/user/OfficialChannel)-eu5sl)",
        ))
        # Model AniList's HTML response, including HTML structure around the
        # malformed Markdown links. Only those link fragments should be changed.
        html_description = "\n".join((
            "<p><strong>Biography formatting</strong> must stay intact.</p>",
            r'<p>[YouTube]\(<a href="https://www.youtube.com/">https://www.youtube.com/</a>'
            r'<a href="https://anilist.co/user/Ueda">@Ueda</a>-Kana)</p>',
            r'<p>[Youtube]\(<a href="https://youtube.com/">https://youtube.com/</a>'
            r'<a href="https://anilist.co/user/officialyoutubechannel3974">'
            r'@officialyoutubechannel3974</a>?si=9AjlJ6Ujj2Vw1CiU)</p>',
            r'<p>[Youtube]\(<a href="https://www.youtube.com/">https://www.youtube.com/</a>'
            r'<a href="https://anilist.co/user/OfficialChannel">@OfficialChannel</a>-eu5sl)</p>',
            "<ul><li>Keep this original list item.</li></ul>",
        ))
        expected_urls = (
            "https://www.youtube.com/@Ueda-Kana",
            "https://youtube.com/@officialyoutubechannel3974?si=9AjlJ6Ujj2Vw1CiU",
            "https://www.youtube.com/@OfficialChannel-eu5sl",
        )

        page = EntityProfilePage()
        try:
            with patch.object(EntityProfilePage, "_start_profile_load"):
                page.set_profile(
                    "voice_actor",
                    {"person_id": 456, "name": "Example Voice Actor"},
                )
            page._remote_data = {
                "id": 456,
                "name": {"full": "Example Voice Actor"},
                "description": raw_description,
                "descriptionHtml": html_description,
                "image": {},
                "staffMedia": {"edges": []},
                "characterMedia": {"edges": []},
            }
            page._render_profile()
            self.app.processEvents()

            bio = page.findChild(QTextBrowser, "profileDescription")
            self.assertIsNotNone(bio)
            self.assertTrue(bio.openExternalLinks())
            rendered = bio.toHtml()
            for url in expected_urls:
                with self.subTest(url=url):
                    self.assertIn(f'href="{url}"', rendered)
            self.assertNotIn("https://anilist.co/user/", rendered)
            self.assertNotIn(r"\([https://", rendered)
            self.assertNotIn("[YouTube]", rendered)
            self.assertNotIn("[Youtube]", rendered)

            # HTML-only formatting and structure outside links must survive.
            self.assertIn("Biography formatting", bio.toPlainText())
            self.assertIn("Keep this original list item.", bio.toPlainText())
            formatted = bio.document().find("Biography formatting")
            self.assertFalse(formatted.isNull())
            self.assertGreaterEqual(formatted.charFormat().fontWeight(), 600)
        finally:
            page.close()
            page.deleteLater()

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
