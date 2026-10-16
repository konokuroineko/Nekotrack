import html as html_lib
import re
from math import ceil

from PySide6.QtCore import Qt, Signal, QUrl, QObject, QRunnable, QThreadPool, QRectF, QPoint, QRect, QSize
from PySide6.QtGui import QPixmap, QPainter, QPainterPath, QPen, QColor
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import (
    QFrame,
    QMessageBox,
    QBoxLayout,
    QGridLayout,
    QLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
    QSizePolicy,
    QTextBrowser,
)

from api import get_entity_profile, _normalize_anilist_profile_description
from database import is_entity_favorite, set_entity_favorite
from diagnostics import log_exception
from ui.theme import COLORS, card_stylesheet, muted_label_stylesheet, surface_rgba
from ui.widgets.character_card import CharacterArtwork
from ui.widgets.person_card import PersonCard
from ui.widgets.work_card import WorkCard


_PROFILE_METADATA_LABEL_PATTERN = re.compile(
    r"(?P<label>[A-Za-z][A-Za-z0-9 /&()'’-]{0,27}?)[ \t]*:[ \t]*"
)
_PROFILE_METADATA_INLINE_FIELD_PATTERN = re.compile(
    r"(?:[ \t]*(?:\||[•·]|;)[ \t]*)(?P<label>[A-Za-z][A-Za-z0-9 /&()'’-]{0,27}?)[ \t]*:[ \t]*"
)
_PROFILE_METADATA_ALIASES = {
    "blood type": ("blood_type", "Blood type"),
    "date of birth": ("birthday", "Birthday"),
    "dob": ("birthday", "Birthday"),
    "birthday": ("birthday", "Birthday"),
    "height": ("height", "Height"),
    "weight": ("weight", "Weight"),
    "age": ("age", "Age"),
    "gender": ("gender", "Gender"),
    "hometown": ("hometown", "Hometown"),
    "home town": ("hometown", "Hometown"),
    "language": ("language", "Language"),
    "occupation": ("occupation", "Occupation"),
    "occupations": ("occupation", "Occupation"),
    "years active": ("years_active", "Years active"),
    "active": ("years_active", "Years active"),
    "favourite": ("favourites", "Favourites"),
    "favourites": ("favourites", "Favourites"),
    "favorite": ("favourites", "Favourites"),
    "favorites": ("favourites", "Favourites"),
}
_PROFILE_METADATA_TYPED_VALUE_PATTERNS = {
    "height": re.compile(
        r"(?:\d{2,3}(?:\.\d+)?\s*(?:cm|centimeters?|mm|m|meters?|metres?)"
        r"|\d{1,2}\s*(?:ft|feet|foot)(?:\s*\d{1,2}\s*(?:in|inches))?"
        r"|\d{1,2}\s*(?:in|inches))",
        re.IGNORECASE,
    ),
    "weight": re.compile(
        r"\d{1,3}(?:\.\d+)?\s*(?:kg|kilograms?|lb|lbs|pounds?)",
        re.IGNORECASE,
    ),
    "birthday": re.compile(
        r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?"
        r"|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?"
        r"|Dec(?:ember)?)\.?\s+\d{1,2}(?:st|nd|rd|th)?(?:,\s*\d{4})?"
        r"|\d{1,2}(?:st|nd|rd|th)?\s+(?:January|February|March|April|May|June"
        r"|July|August|September|October|November|December)(?:\s+\d{4})?"
        r"|\d{4}[-/.]\d{1,2}(?:[-/.]\d{1,2})?|\d{4}|[A-Za-z]{3,9}\s+\d{1,2}",
        re.IGNORECASE,
    ),
    "age": re.compile(
        r"(?:\d{1,3}(?:\s*[-–]\s*\d{1,3})?(?:\s*(?:years? old|y/o))?"
        r"|unknown|unspecified|\?)",
        re.IGNORECASE,
    ),
    "gender": re.compile(
        r"(?:male\s*/\s*female|female\s*/\s*male|non[- ]?binary|genderfluid"
        r"|androgynous|genderless|agender|unknown|other|male|female)",
        re.IGNORECASE,
    ),
    "blood_type": re.compile(r"(?:AB|A|B|O)[+-]?", re.IGNORECASE),
}


def _description_visible_text_and_map(description, html_mode):
    """Return visible description text with offsets back into its original source."""
    source = str(description or "")
    if not html_mode:
        return source, [(index, index + 1) for index in range(len(source))]

    visible = []
    source_map = []
    tokens = re.compile(
        r"(?is)<[^>]*>|&(?:#(?:x[0-9a-f]+|\d+)|[a-z][a-z0-9]+);|."
    )
    block_tags = {"p", "div", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6"}
    for match in tokens.finditer(source):
        token = match.group(0)
        if token.startswith("<"):
            tag_match = re.match(r"<\s*(/?)\s*([a-z0-9]+)", token, re.IGNORECASE)
            if tag_match is None:
                continue
            closing, tag_name = tag_match.groups()
            should_break = tag_name.casefold() == "br" or (
                bool(closing) and tag_name.casefold() in block_tags
            )
            if should_break and (not visible or visible[-1] != "\n"):
                visible.append("\n")
                source_map.append((match.start(), match.end()))
        elif token.startswith("&"):
            decoded = html_lib.unescape(token)
            for character in decoded:
                visible.append(character)
                source_map.append((match.start(), match.end()))
        else:
            visible.append(token)
            source_map.append((match.start(), match.end()))

    return "".join(visible), source_map


def _profile_metadata_label(label):
    """Return a normalized key and readable label for a simple X: Y field."""
    cleaned = " ".join(str(label or "").split()).strip(" .:-")
    normalized = cleaned.casefold()
    if not cleaned:
        return "", ""
    alias = _PROFILE_METADATA_ALIASES.get(normalized)
    if alias:
        return alias
    key = re.sub(r"[^a-z0-9]+", "_", normalized).strip("_")
    return key, cleaned[0].upper() + cleaned[1:]


def _extract_leading_profile_metadata(description, html_mode=False):
    """Extract consecutive leading X: Y fields, leaving the remaining biography intact.

    Metadata labels are generic so fields such as Hobbies, Likes, or other
    AniList-specific details work without adding a hardcoded label for each one.
    Known labels with strongly recognizable value formats (for example Height)
    can end before prose that starts on the same line. Otherwise, a field must
    be separated by a line break or explicit field separator. Parsing stops at
    the first ordinary prose segment.
    """
    source = str(description or "")
    if not source.strip():
        return [], source

    visible, source_map = _description_visible_text_and_map(source, html_mode)
    cursor = 0
    facts = []
    first_fact_start = None
    last_fact_end = None

    while cursor < len(visible):
        while cursor < len(visible) and (
            visible[cursor].isspace() or visible[cursor] in "|•·;"
        ):
            cursor += 1
        if cursor >= len(visible):
            break

        label_match = _PROFILE_METADATA_LABEL_PATTERN.match(visible, cursor)
        if label_match is None:
            break

        label_key, display_label = _profile_metadata_label(label_match.group("label"))
        if not label_key:
            break
        value_start = label_match.end()

        value_end = None
        typed_pattern = _PROFILE_METADATA_TYPED_VALUE_PATTERNS.get(label_key)
        if typed_pattern is not None:
            value_match = typed_pattern.match(visible, value_start)
            if value_match is not None:
                candidate_end = value_match.end()
                if (
                    candidate_end == len(visible)
                    or visible[candidate_end].isspace()
                    or visible[candidate_end] in ",.;|•·);"
                ):
                    value_end = candidate_end
                    # Include a sentence-ending period so removing a field from
                    # "Height: 165 cm. This person..." does not leave ". This...".
                    if (
                        value_end < len(visible)
                        and visible[value_end] == "."
                        and (
                            value_end + 1 == len(visible)
                            or visible[value_end + 1].isspace()
                        )
                    ):
                        value_end += 1

        if value_end is None:
            line_end = visible.find("\n", value_start)
            if line_end < 0:
                line_end = len(visible)
            segment_end = line_end

            inline_field = _PROFILE_METADATA_INLINE_FIELD_PATTERN.search(
                visible, value_start, line_end
            )
            if inline_field is not None:
                segment_end = inline_field.start()

            # A generic value with one clear sentence followed by normal prose
            # should not absorb the prose. Dotted/abbreviated titles remain rare
            # here, but this conservative boundary is useful for common biographies.
            sentence_boundary = re.search(
                r"(?<=[.!?])[ \t]+(?=(?:I|He|She|They|This|That|The|A|An|My|His|Her|Their|Born|Known|Voiced|Worked|Was|Is)\b)",
                visible[value_start:segment_end],
            )
            if sentence_boundary is not None:
                segment_end = min(
                    segment_end, value_start + sentence_boundary.start()
                )

            value_end = segment_end
            while value_end > value_start and visible[value_end - 1].isspace():
                value_end -= 1

            value = visible[value_start:value_end].strip()
            if not value or len(value) > 180:
                break
            # Don't turn a complete prose sentence into a fact just because it
            # begins with a colon-bearing phrase like "Introduction: ...".
            if re.search(r"\.\s+[A-Z]", value):
                break
        else:
            value = visible[value_start:value_end].strip()

        if not value:
            break
        if first_fact_start is None:
            first_fact_start = cursor
        facts.append((label_key, display_label, value))
        last_fact_end = value_end
        cursor = value_end

        # A next field must begin after a line break or an explicit visual
        # separator; ordinary comma-separated values (e.g. hobby lists) stay intact.
        lookahead = cursor
        while lookahead < len(visible) and visible[lookahead].isspace():
            lookahead += 1
        while lookahead < len(visible) and visible[lookahead] in "|•·;":
            lookahead += 1
            while lookahead < len(visible) and visible[lookahead].isspace():
                lookahead += 1
        if _PROFILE_METADATA_LABEL_PATTERN.match(visible, lookahead) is None:
            break
        cursor = lookahead

    if not facts or first_fact_start is None or last_fact_end is None:
        return [], source

    start_offset = source_map[first_fact_start][0]
    end_offset = source_map[last_fact_end - 1][1]
    cleaned = source[:start_offset] + source[end_offset:]

    if html_mode:
        # The removed prefix may leave empty paragraphs or a leading line break.
        for _ in range(8):
            cleaned, count = re.subn(
                r"(?is)^\s*<(p|div)\b[^>]*>\s*</\1\s*>\s*",
                "",
                cleaned,
                count=1,
            )
            if not count:
                break
        cleaned = re.sub(
            r"(?is)^(\s*<(?:p|div)\b[^>]*>)\s*(?:<br\b[^>]*>\s*)+",
            r"\1",
            cleaned,
            count=1,
        )
        cleaned = re.sub(r"(?is)^\s*(?:<br\b[^>]*>\s*)+", "", cleaned)

    return facts, cleaned.strip()



def _crop_pixmap_to_size(pixmap, size):
    """Fill a portrait frame and crop overflow instead of letterboxing artwork."""
    if pixmap is None or pixmap.isNull() or size.width() <= 0 or size.height() <= 0:
        return QPixmap()
    scaled = pixmap.scaled(
        size,
        Qt.KeepAspectRatioByExpanding,
        Qt.SmoothTransformation,
    )
    x = max(0, (scaled.width() - size.width()) // 2)
    y = max(0, (scaled.height() - size.height()) // 2)
    return scaled.copy(x, y, size.width(), size.height())


class _ProfileLoadSignals(QObject):
    finished = Signal(int, str, int, object, str)


class _ProfileLoadWorker(QRunnable):
    def __init__(self, token, fetch_kind, entity_id):
        super().__init__()
        self.token = int(token)
        self.fetch_kind = str(fetch_kind)
        self.entity_id = int(entity_id)
        self.signals = _ProfileLoadSignals()

    def run(self):
        try:
            profile = get_entity_profile(self.fetch_kind, self.entity_id)
            self.signals.finished.emit(
                self.token, self.fetch_kind, self.entity_id, profile, ""
            )
        except Exception as error:
            self.signals.finished.emit(
                self.token, self.fetch_kind, self.entity_id, None,
                f"{type(error).__name__}: {error}",
            )


class RoundedArtworkLabel(QLabel):
    """Rounded, center-cropped artwork with the border directly on the image edge."""

    def __init__(self, width, height, radius=10, parent=None):
        super().__init__(parent)
        self._radius = max(1, int(radius))
        self.setFixedSize(width, height)
        self.setAlignment(Qt.AlignCenter)
        self.setScaledContents(False)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setStyleSheet("background:transparent;border:none;padding:0;")

    def paintEvent(self, event):
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        artwork_rect = self.rect().adjusted(2, 2, -2, -2)
        artwork_path = QPainterPath()
        artwork_path.addRoundedRect(
            QRectF(artwork_rect), self._radius, self._radius
        )
        painter.fillPath(artwork_path, QColor(COLORS["background_alt"]))

        pixmap = self.pixmap()
        if pixmap is not None and not pixmap.isNull():
            cropped = _crop_pixmap_to_size(pixmap, artwork_rect.size())
            if not cropped.isNull():
                painter.save()
                painter.setClipPath(artwork_path)
                painter.drawPixmap(QRectF(artwork_rect), cropped, QRectF(cropped.rect()))
                painter.restore()

        # Overlay the outline on the exact crop boundary. There is no inset inner
        # image rectangle, so the background cannot appear as a second line.
        painter.setPen(QPen(QColor(COLORS["frame"]), 2.0))
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(artwork_path)
        painter.end()


class ClickableCharacterArtwork(CharacterArtwork):
    """A Characters-tab portrait that opens its character profile when clicked."""

    clicked = Signal(object)

    def __init__(self, character, parent=None):
        character = character if isinstance(character, dict) else {}
        raw_name = character.get("name")
        if isinstance(raw_name, dict):
            name = raw_name.get("full") or raw_name.get("native") or "Unknown character"
        else:
            name = raw_name or "Unknown character"
        image = character.get("image")
        image_url = image.get("large") if isinstance(image, dict) else None
        try:
            character_id = int(character.get("id") or 0)
        except (TypeError, ValueError, OverflowError):
            character_id = 0

        self.character = {
            "id": character_id,
            "character_name": str(name),
            "character_image_url": image_url,
        }
        super().__init__(88, 116, 14, parent)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(str(name))
        self._network = QNetworkAccessManager(self)
        self._reply = (
            self._network.get(QNetworkRequest(QUrl(str(image_url))))
            if image_url else None
        )
        if self._reply is not None:
            self._reply.finished.connect(self._image_finished)

    def _image_finished(self):
        reply = self._reply
        self._reply = None
        if reply is not None and reply.error() == QNetworkReply.NetworkError.NoError:
            pixmap = QPixmap()
            if pixmap.loadFromData(reply.readAll()):
                self.set_pixmap(pixmap)
        if reply is not None:
            reply.deleteLater()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self.character["id"] > 0:
            event.accept()
            self.clicked.emit(dict(self.character))
            return
        super().mousePressEvent(event)


class MediaCreditCard(QFrame):
    """Characters-tab-style work card: work artwork left, credited character right."""

    work_selected = Signal(object)
    character_selected = Signal(object)

    def __init__(self, edge, credit_kind, parent=None):
        super().__init__(parent)
        edge = edge if isinstance(edge, dict) else {}
        node = edge.get("node") if isinstance(edge.get("node"), dict) else {}
        self.credit_kind = str(credit_kind or "")
        try:
            self.media_id = int(node.get("id") or 0)
        except (TypeError, ValueError, OverflowError):
            self.media_id = 0
        self.media_record = dict(node)
        if self.media_id > 0:
            self.media_record["id"] = self.media_id

        title_data = node.get("title") if isinstance(node.get("title"), dict) else {}
        title = (
            title_data.get("english") or title_data.get("romaji")
            or title_data.get("native") or "Untitled work"
        )
        characters = edge.get("characters")
        characters = characters if isinstance(characters, list) else []
        character_data = next(
            (item for item in characters if isinstance(item, dict) and item.get("id")),
            None,
        )
        self.character_artwork = None
        self.character_cards = []

        self.setObjectName("mediaCreditCard")
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet(card_stylesheet())
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMinimumWidth(430)
        self.setFixedHeight(140)

        voice_actor_layout = (
            self.credit_kind == "voice_actor" and character_data is not None
        )
        if voice_actor_layout:
            # Keep this work-poster/text/character composition physically left-to-right
            # even when the surrounding application uses a right-to-left layout.
            self.setLayoutDirection(Qt.LeftToRight)

        row = QHBoxLayout(self)
        if voice_actor_layout:
            row.setDirection(QBoxLayout.LeftToRight)
        row.setContentsMargins(12, 12, 12, 12)
        row.setSpacing(8)

        self.cover = RoundedArtworkLabel(88, 116, 14)
        self.cover.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        row.addWidget(self.cover, 0, Qt.AlignTop)

        cover_data = node.get("coverImage")
        cover_url = cover_data.get("large") if isinstance(cover_data, dict) else None
        self._network = QNetworkAccessManager(self)
        self._reply = (
            self._network.get(QNetworkRequest(QUrl(str(cover_url))))
            if cover_url else None
        )
        if self._reply is not None:
            self._reply.finished.connect(self._image_finished)

        if self.credit_kind in {"character", "voice_actor"}:
            credit = edge.get("characterRole")
        else:
            credit = edge.get("staffRole") or edge.get("role")

        if voice_actor_layout:
            # Keep each name beside its matching artwork and click target: anime title left,
            # character name right.
            text_layout = QGridLayout()
            text_layout.setContentsMargins(0, 0, 0, 0)
            text_layout.setHorizontalSpacing(18)
            text_layout.setVerticalSpacing(0)

            if credit:
                role_text = str(credit).replace("_", " ").title()
                role = QLabel(role_text)
                role.setObjectName("mediaCreditRole")
                role.setWordWrap(True)
                role.setFrameShape(QFrame.NoFrame)
                role.setLineWidth(0)
                role.setAttribute(Qt.WA_TransparentForMouseEvents, True)
                role.setStyleSheet(
                    f"background: transparent; border: none; color: {COLORS['primary']}; "
                    "font-size: 13px; font-weight: 700;"
                )
                role.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
                text_layout.addWidget(
                    role, 0, 0, 1, 2, Qt.AlignHCenter | Qt.AlignTop
                )

            raw_name = character_data.get("name")
            if isinstance(raw_name, dict):
                character_name = raw_name.get("full") or raw_name.get("native") or "Unknown character"
            else:
                character_name = raw_name or "Unknown character"
            name_label = QLabel(str(character_name))
            name_label.setObjectName("creditCharacterName")
            name_label.setWordWrap(True)
            name_label.setFrameShape(QFrame.NoFrame)
            name_label.setLineWidth(0)
            name_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            name_label.setStyleSheet(
                f"background: transparent; border: none; color: {COLORS['primary']}; "
                "font-weight: 600;"
            )
            # Keep both the widget direction and alignment absolute: Qt otherwise
            # mirrors left/right alignment when the application uses an RTL locale.
            name_label.setLayoutDirection(Qt.LeftToRight)
            name_label.setAlignment(
                Qt.AlignRight | Qt.AlignVCenter | Qt.AlignAbsolute
            )

            title_label = QLabel(str(title))
            title_label.setObjectName("mediaCreditTitle")
            title_label.setWordWrap(True)
            title_label.setFrameShape(QFrame.NoFrame)
            title_label.setLineWidth(0)
            title_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            title_label.setStyleSheet(
                f"background: transparent; border: none; color: {COLORS['primary']}; "
                "font-weight: 600;"
            )
            title_label.setLayoutDirection(Qt.LeftToRight)
            title_label.setAlignment(
                Qt.AlignLeft | Qt.AlignVCenter | Qt.AlignAbsolute
            )

            names_row = QHBoxLayout()
            names_row.setDirection(QBoxLayout.LeftToRight)
            names_row.setSpacing(18)
            names_row.addWidget(title_label, 1)
            names_row.addWidget(name_label, 1)
            names_widget = QWidget()
            names_widget.setLayoutDirection(Qt.LeftToRight)
            names_widget.setLayout(names_row)
            text_layout.addWidget(names_widget, 0, 0, 1, 2)
            text_layout.setColumnStretch(0, 1)
            text_layout.setColumnStretch(1, 1)
            text_layout.setRowStretch(0, 1)
            row.addLayout(text_layout, 1)
        else:
            text_column = QVBoxLayout()
            text_column.setContentsMargins(0, 0, 0, 0)
            text_column.setSpacing(5)
            title_label = QLabel(str(title))
            title_label.setObjectName("mediaCreditTitle")
            title_label.setWordWrap(True)
            title_label.setMaximumHeight(44)
            title_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            title_label.setStyleSheet(
                f"background:transparent;border:none;color:{COLORS['primary']};"
                "font-weight:750;font-size:13px;"
            )
            text_column.addWidget(title_label)

            if credit:
                role_text = str(credit).replace("_", " ").strip().title()
                role = QLabel(role_text)
                role.setObjectName("mediaCreditRole")
                role.setWordWrap(True)
                role.setAttribute(Qt.WA_TransparentForMouseEvents, True)
                role.setStyleSheet(
                    f"color:{COLORS['primary']};font-size:13px;font-weight:700;"
                    "background:transparent;border:none;"
                )
                text_column.addWidget(role)
            text_column.addStretch(1)
            row.addLayout(text_column, 1)

        if self.credit_kind == "voice_actor" and character_data is not None:
            self.character_artwork = ClickableCharacterArtwork(character_data)
            self.character_artwork.clicked.connect(self.character_selected.emit)
            self.character_cards = [self.character_artwork]
            row.addWidget(self.character_artwork, 0, Qt.AlignTop)

    def _image_finished(self):
        reply = self._reply
        self._reply = None
        if reply is not None and reply.error() == QNetworkReply.NetworkError.NoError:
            pixmap = QPixmap()
            if pixmap.loadFromData(reply.readAll()):
                self.cover.setPixmap(pixmap)
        if reply is not None:
            reply.deleteLater()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self.media_id > 0:
            event.accept()
            self.work_selected.emit(dict(self.media_record))
            return
        super().mousePressEvent(event)


class ProfileFlowLayout(QLayout):
    """Wrap fixed-width profile credit cards into tidy poster rows."""

    def __init__(self, parent=None, h_spacing=10, v_spacing=14):
        super().__init__(parent)
        self._items = []
        self._h_spacing = int(h_spacing)
        self._v_spacing = int(v_spacing)
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index):
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientations()

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._do_layout(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        return size + QSize(
            margins.left() + margins.right(),
            margins.top() + margins.bottom(),
        )

    def _do_layout(self, rect, test_only):
        margins = self.contentsMargins()
        effective = rect.adjusted(
            margins.left(), margins.top(), -margins.right(), -margins.bottom()
        )
        x = effective.x()
        y = effective.y()
        row_height = 0
        used_any = False

        for item in self._items:
            size = item.sizeHint()
            if size.width() <= 0:
                continue
            if used_any and x + size.width() > effective.right() + 1:
                x = effective.x()
                y += row_height + self._v_spacing
                row_height = 0
                used_any = False
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), size))
            x += size.width() + self._h_spacing
            row_height = max(row_height, size.height())
            used_any = True

        if not used_any:
            return margins.top() + margins.bottom()
        return y + row_height - rect.y() + margins.bottom()


class ProfileWorkCreditCard(WorkCard):
    """Poster card with staff credits between the title and work metadata."""

    def __init__(self, edge, parent=None):
        edge = edge if isinstance(edge, dict) else {}
        node = edge.get("node") if isinstance(edge.get("node"), dict) else {}
        work = dict(node)
        super().__init__(
            work,
            mode="search",
            show_add_button=False,
            parent=parent,
        )

        raw_role = edge.get("staffRole") or edge.get("role") or ""
        role_parts = str(raw_role).replace("\n", " · ").split("·")
        full_role = " · ".join(
            part.strip() for part in role_parts if part.strip()
        )
        if not full_role:
            return

        role = QLabel(full_role)
        role.setObjectName("profileCreditRole")
        role.setWordWrap(True)
        role.setFixedHeight(30)
        role.setToolTip(full_role)
        role.setStyleSheet(
            f"background:transparent;border:none;color:{COLORS['muted']};"
            "font-size:10px;font-weight:650;"
        )

        root = self.layout()
        content_item = root.itemAt(1) if root.count() > 1 else None
        content_layout = content_item.layout() if content_item is not None else None
        if content_layout is None:
            return

        title_index = next(
            (
                index for index in range(content_layout.count())
                if (widget := content_layout.itemAt(index).widget()) is not None
                and widget.objectName() == "title"
            ),
            -1,
        )
        meta_index = next(
            (
                index for index in range(content_layout.count())
                if (widget := content_layout.itemAt(index).widget()) is not None
                and widget.objectName() == "meta"
            ),
            -1,
        )
        insert_index = meta_index if meta_index >= 0 else max(0, title_index + 1)
        content_layout.insertWidget(insert_index, role)

        # WorkCard sets a fixed height before this extra line is inserted.
        added_height = role.height()
        self.setFixedHeight(
            self.height() + added_height + max(0, content_layout.spacing())
        )

class ProfileDescriptionBrowser(QTextBrowser):
    """Rich biography view that grows with its content instead of scrolling internally."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._updating_content_height = False
        self.document().contentsChanged.connect(self.update_content_height)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update_content_height()

    def update_content_height(self):
        if self._updating_content_height or self.width() <= 0:
            return
        viewport_width = max(1, self.viewport().width())
        self._updating_content_height = True
        try:
            document = self.document()
            document.setTextWidth(viewport_width)
            content_height = ceil(document.documentLayout().documentSize().height()) + 8
            if abs(self.minimumHeight() - content_height) > 1:
                self.setMinimumHeight(content_height)
        finally:
            self._updating_content_height = False


class EntityProfilePage(QWidget):
    """NekoTrack character and voice-actor profiles with internal work navigation."""

    back_requested = Signal()
    voice_actor_selected = Signal(object)
    character_selected = Signal(object)
    work_selected = Signal(object)

    def __init__(self):
        super().__init__()
        self._network_manager = QNetworkAccessManager(self)
        self._image_reply = None
        self._image_label = None
        self._request_token = 0
        self._workers = {}
        self._profile_cache = {}
        self.current_type = "character"
        self.current_record = {}
        self.source_work = None
        self.voice_actors = []
        self._remote_data = None
        self._remote_error = ""

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(12)

        header = QHBoxLayout()
        self.back_button = QPushButton("← Back")
        self.back_button.setCursor(Qt.PointingHandCursor)
        self.back_button.clicked.connect(self.back_requested.emit)
        header.addWidget(self.back_button)
        header.addStretch(1)
        self.page_status = QLabel("")
        self.page_status.setStyleSheet(muted_label_stylesheet())
        header.addWidget(self.page_status)
        root.addLayout(header)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.NoFrame)
        self.content = QWidget()
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(14)
        self.scroll_area.setWidget(self.content)
        root.addWidget(self.scroll_area, 1)

        self.refresh_theme()
        self.set_profile("character", {})

    def refresh_theme(self):
        self.setStyleSheet(
            f"""
            QPushButton {{
                color:{COLORS['primary']};
                background:{surface_rgba('surface')};
                border:1px solid {COLORS['border']};
                border-radius:10px;
                padding:9px 14px;
                font-weight:750;
            }}
            QPushButton:hover {{
                background:{surface_rgba('surface_hover')};
                border-color:{COLORS['accent']};
            }}
            QPushButton:disabled {{
                color:{COLORS['muted']};
                background:{surface_rgba('background_alt')};
            }}
            QFrame#profileHeader {{
                background:{surface_rgba('surface')};
                border:1px solid {COLORS['frame']};
                border-radius:18px;
            }}
            QFrame#profileSection {{
                background:{surface_rgba('surface')};
                border:1px solid {COLORS['frame']};
                border-radius:16px;
            }}
            QLabel#profileName {{
                color:{COLORS['primary']};
                font-size:30px;
                font-weight:900;
            }}
            QPushButton#profileFavoriteButton {{
                min-width:42px; max-width:42px; min-height:42px; max-height:42px;
                padding:0; border-radius:12px; font-size:21px; font-weight:850;
                color:{COLORS['secondary']}; background:{surface_rgba('surface_alt')};
                border:1px solid {COLORS['border']};
            }}
            QPushButton#profileFavoriteButton:hover,
            QPushButton#profileFavoriteButton:checked {{
                color:{COLORS['accent']}; background:{surface_rgba('accent_soft')};
                border-color:{COLORS['accent']};
            }}
            QLabel#profileKind {{
                color:{COLORS['accent']};
                font-size:11px;
                font-weight:900;
                letter-spacing:1px;
            }}
            QLabel#profileFacts {{
                color:{COLORS['secondary']};
                font-size:13px;
            }}
            QLabel#profileSectionTitle {{
                color:{COLORS['primary']};
                font-size:17px;
                font-weight:850;
            }}
            QLabel#profileImage {{
                background:{surface_rgba('background_alt')};
                border:1px solid {COLORS['frame']};
                border-radius:14px;
            }}
            QLabel#profileInlineTitle {{
                color:{COLORS['accent']};
                font-size:10px;
                font-weight:900;
                letter-spacing:1px;
                background:transparent;
                border:none;
            }}
            QLabel#profileDescription {{
                color:{COLORS['secondary']};
                font-size:12px;
                background:transparent;
                border:none;
            }}
            """
        )
        for widget in self.findChildren(QWidget):
            updater = getattr(widget, "refresh_theme", None)
            if callable(updater):
                updater()

    @staticmethod
    def _normalize_profile_description(description, html_mode=False):
        """Normalize malformed provider links through the shared AniList helper."""
        return _normalize_anilist_profile_description(
            description, html_mode=html_mode
        )

    @staticmethod
    def _value(item, key, fallback=None):
        if hasattr(item, "get"):
            try:
                value = item.get(key, fallback)
            except TypeError:
                value = item.get(key)
            return fallback if value is None else value
        try:
            value = item[key]
        except (KeyError, IndexError, TypeError):
            return fallback
        return fallback if value is None else value

    @staticmethod
    def _work_title(work):
        title = EntityProfilePage._value(work, "custom_title")
        if title:
            return str(title)
        title = EntityProfilePage._value(work, "title")
        if isinstance(title, dict):
            return str(
                title.get("english") or title.get("romaji")
                or title.get("native") or "Current work"
            )
        return str(title or EntityProfilePage._value(work, "english_title", "Current work"))

    @staticmethod
    def _name_from(value, fallback=""):
        if isinstance(value, dict):
            return str(value.get("full") or value.get("english") or value.get("romaji") or fallback)
        return str(value or fallback)

    @staticmethod
    def _image_url(value):
        if isinstance(value, dict):
            return value.get("large")
        return value

    @staticmethod
    def _format_date(value):
        if not isinstance(value, dict):
            return ""
        parts = [value.get(key) for key in ("year", "month", "day")]
        if not parts[0]:
            return ""
        try:
            year = int(parts[0])
            if parts[1] and parts[2]:
                return f"{year:04d}-{int(parts[1]):02d}-{int(parts[2]):02d}"
            if parts[1]:
                return f"{year:04d}-{int(parts[1]):02d}"
            return str(year)
        except (TypeError, ValueError, OverflowError):
            return str(parts[0])

    def profile_state(self):
        return {
            "entity_type": self.current_type,
            "record": dict(self.current_record),
            "source_work": self.source_work,
            "voice_actors": [dict(actor) for actor in self.voice_actors],
        }

    def _clear_content(self):
        while self.content_layout.count():
            item = self.content_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                self.content_layout.removeWidget(widget)
                widget.deleteLater()

    def set_profile(self, entity_type, record, source_work=None, voice_actors=None):
        raw_kind = str(entity_type or "").strip().lower()
        if raw_kind in {"voice_actor", "voice actor"}:
            normalized_kind = "voice_actor"
        elif raw_kind in {"staff", "person", "people"}:
            normalized_kind = "staff"
        else:
            normalized_kind = "character"

        self._request_token += 1
        token = self._request_token
        if self._image_reply is not None:
            try:
                self._image_reply.abort()
            except RuntimeError:
                pass
            self._image_reply = None

        self.current_type = normalized_kind
        try:
            self.current_record = dict(record or {})
        except (TypeError, ValueError):
            self.current_record = {}
        self.source_work = source_work
        saved_voices = voice_actors
        if saved_voices is None:
            saved_voices = self.current_record.get("voice_actors", [])
        self.voice_actors = [
            dict(actor) for actor in (saved_voices or [])
            if isinstance(actor, dict) or hasattr(actor, "keys")
        ]
        self._remote_data = None
        self._remote_error = ""
        self.page_status.setText("")
        self._render_profile()
        self._start_profile_load(token)

    def _start_profile_load(self, token):
        record = self.current_record
        raw_id = (
            self._value(record, "id")
            if self.current_type == "character"
            else self._value(record, "person_id", self._value(record, "id"))
        )
        try:
            entity_id = int(raw_id)
        except (TypeError, ValueError, OverflowError):
            return
        if entity_id <= 0:
            return
        fetch_kind = "Character" if self.current_type == "character" else "Staff"
        cached_profile = self._profile_cache.get((fetch_kind, entity_id))
        if isinstance(cached_profile, dict):
            self._remote_data = cached_profile
            self._remote_error = ""
            self.page_status.setText("Profile cached")
            self._render_profile()
            return
        self.page_status.setText("Loading profile details…")
        worker = _ProfileLoadWorker(token, fetch_kind, entity_id)
        self._workers[token] = worker
        worker.signals.finished.connect(self._profile_loaded)
        QThreadPool.globalInstance().start(worker)

    def _profile_loaded(self, token, fetch_kind, entity_id, profile, error):
        self._workers.pop(token, None)
        if token != self._request_token:
            return
        expected_kind = "Character" if self.current_type == "character" else "Staff"
        if fetch_kind != expected_kind:
            return
        current_id = (
            self._value(self.current_record, "id")
            if self.current_type == "character"
            else self._value(
                self.current_record, "person_id",
                self._value(self.current_record, "id"),
            )
        )
        try:
            current_id = int(current_id)
        except (TypeError, ValueError, OverflowError):
            return
        if current_id != entity_id:
            return

        if isinstance(profile, dict):
            self._remote_data = profile
            self._profile_cache[(fetch_kind, entity_id)] = profile
            self._remote_error = ""
            self.page_status.setText("Profile loaded")
        else:
            self._remote_error = str(error or "Profile details could not be loaded.")
            self.page_status.setText("Showing saved information")
        self._render_profile()

    def _profile_entity_id(self):
        record = self.current_record or {}
        raw_id = (
            self._value(record, "id")
            if self.current_type == "character"
            else self._value(record, "person_id", self._value(record, "id"))
        )
        try:
            numeric_id = int(raw_id)
        except (TypeError, ValueError, OverflowError):
            remote_id = self._remote_data.get("id") if isinstance(self._remote_data, dict) else None
            try:
                numeric_id = int(remote_id)
            except (TypeError, ValueError, OverflowError):
                return None
        return numeric_id if numeric_id > 0 else None

    def _toggle_entity_favorite(self, entity_type, entity_id, name, favorite, button):
        try:
            # Voice-actor favorites are identities, not a single language credit.
            # The selected audio language filters each candidate credit in the
            # ranking model instead of locking this person to one performance.
            saved = set_entity_favorite(
                entity_type, entity_id, bool(favorite), name=name, language=None
            )
            if not saved:
                raise RuntimeError("The favorite state was rejected by the local database.")
        except Exception as error:
            log_exception(
                "profile.entity_favorite_toggle_failed",
                error,
                entity_type=entity_type,
                entity_id=entity_id,
            )
            button.setChecked(not bool(favorite))
            QMessageBox.warning(
                self,
                "Favorite could not be saved",
                "NekoTrack could not update this profile's favorite state.",
            )
            return
        button.setText("♥" if favorite else "♡")
        button.setAccessibleName(
            "Remove from favorites" if favorite else "Add to favorites"
        )
        button.setToolTip(
            "Remove from favorites" if favorite
            else "Favorite this profile to improve recommendations"
        )

    def _render_profile(self):
        # Profile data and remote artwork can finish in either order. Cancel the
        # previous portrait request before replacing its target widget.
        if self._image_reply is not None:
            try:
                self._image_reply.abort()
            except RuntimeError:
                pass
            self._image_reply = None
        self._clear_content()
        record = self.current_record
        remote = self._remote_data if isinstance(self._remote_data, dict) else {}
        is_character = self.current_type == "character"
        is_voice_actor = self.current_type == "voice_actor"
        local_name_key = "character_name" if is_character else "name"
        name = (
            self._name_from(remote.get("name"))
            or self._name_from(self._value(record, local_name_key), "Unknown profile")
        )
        kind_label = (
            "CHARACTER PROFILE" if is_character
            else "VOICE ACTOR PROFILE" if is_voice_actor
            else "STAFF PROFILE"
        )
        image_path = (
            self._value(record, "character_image_path") if is_character
            else self._value(record, "image_path")
        )
        image_url = self._image_url(remote.get("image")) or (
            self._value(record, "character_image_url") if is_character
            else self._value(record, "image_url")
        )
        header = QFrame()
        header.setObjectName("profileHeader")
        row = QHBoxLayout(header)
        row.setContentsMargins(18, 18, 18, 18)
        row.setSpacing(20)

        artwork = RoundedArtworkLabel(180, 240, 14)
        artwork.setObjectName("profileImage")
        self._image_label = artwork
        pixmap = QPixmap(str(image_path)) if image_path else QPixmap()
        if not pixmap.isNull():
            self._set_artwork(pixmap)
        elif image_url:
            self._load_artwork(image_url)
        row.addWidget(artwork, 0, Qt.AlignTop)

        profile_text = QVBoxLayout()
        profile_text.setContentsMargins(0, 0, 0, 0)
        profile_text.setSpacing(8)
        kind = QLabel(kind_label)
        kind.setObjectName("profileKind")
        profile_text.addWidget(kind)

        title = QLabel(name)
        title.setObjectName("profileName")
        title.setWordWrap(True)
        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(10)
        title_row.addWidget(title, 1)
        entity_id = self._profile_entity_id()
        if entity_id is not None:
            try:
                favorite_enabled = is_entity_favorite(self.current_type, entity_id)
            except Exception as error:
                # Profiles should remain readable if a test/legacy connection has
                # not yet run the additive database migration. Normal app startup
                # initializes the new favorites table before this page is opened.
                log_exception(
                    "profile.entity_favorite_read_failed",
                    error,
                    entity_type=self.current_type,
                    entity_id=entity_id,
                )
                favorite_enabled = False
            favorite_button = QPushButton("♥" if favorite_enabled else "♡")
            favorite_button.setObjectName("profileFavoriteButton")
            favorite_button.setCheckable(True)
            favorite_button.setChecked(favorite_enabled)
            favorite_button.setAccessibleName(
                "Remove from favorites" if favorite_enabled else "Add to favorites"
            )
            favorite_button.setToolTip(
                "Remove from favorites" if favorite_enabled
                else "Favorite this profile to improve recommendations"
            )
            favorite_button.clicked.connect(
                lambda checked, kind=self.current_type, item_id=entity_id,
                       entity_name=name, button=favorite_button:
                    self._toggle_entity_favorite(
                        kind, item_id, entity_name, checked, button
                    )
            )
            title_row.addWidget(favorite_button, 0, Qt.AlignTop)
        profile_text.addLayout(title_row)

        # AniList biographies sometimes start with short X: Y facts (including
        # hobbies or other nonstandard labels). Move a consecutive leading block
        # into profile facts, and stop at the first ordinary prose segment.
        html_description = remote.get("descriptionHtml")
        has_original_html = isinstance(html_description, str) and bool(
            html_description.strip()
        )
        raw_description = str(
            html_description
            or remote.get("description")
            or self._value(record, "description", "")
            or ""
        ).strip()
        description_has_html = has_original_html or (
            "<" in raw_description and any(
                token in raw_description.casefold()
                for token in ("<p", "<br", "<a ", "<b>", "<i>", "<div", "<ul", "<ol")
            )
        )
        metadata_facts, raw_description = _extract_leading_profile_metadata(
            raw_description,
            html_mode=description_has_html,
        )

        facts_column = QVBoxLayout()
        facts_column.setContentsMargins(0, 0, 0, 0)
        facts_column.setSpacing(4)

        if is_character:
            role = str(
                self._value(record, "character_role", "") or ""
            ).replace("_", " ").title()
            if role:
                facts_column.addWidget(self._fact("Role in this bundle", role))
        else:
            local_roles = str(self._value(record, "role", "") or "")
            occupations = remote.get("primaryOccupations")
            if isinstance(occupations, list) and occupations:
                facts_column.addWidget(
                    self._fact(
                        "Occupation",
                        " · ".join(str(item) for item in occupations if item),
                    )
                )
            elif local_roles:
                facts_column.addWidget(
                    self._fact(
                        "Credits in this bundle",
                        local_roles.replace("\n", " · "),
                    )
                )
            language = remote.get("languageV2")
            if language:
                facts_column.addWidget(self._fact("Language", language))

        gender = str(remote.get("gender") or "").strip()
        age = str(remote.get("age") or "").strip()
        birth = self._format_date(remote.get("dateOfBirth"))
        blood_type = str(remote.get("bloodType") or "").strip()
        hometown = str(remote.get("homeTown") or "").strip()
        years_active = remote.get("yearsActive")
        facts = []
        for label, value in (
            ("Gender", gender), ("Age", age), ("Born", birth),
            ("Blood type", blood_type), ("Hometown", hometown),
        ):
            if value and value != "None":
                facts.append(f"{label}: {value}")
        if isinstance(years_active, list) and years_active:
            active_text = "–".join(
                str(item) for item in years_active if item is not None
            )
            if active_text:
                facts.append(f"Active: {active_text}")
        favourites = remote.get("favourites")
        if isinstance(favourites, int) and favourites > 0:
            facts.append(f"{favourites:,} favourites")
        for fact in facts:
            facts_column.addWidget(self._fact("", fact))

        # AniList already supplies some of these details in dedicated fields.
        # Strip duplicate bio copies, but only add a fact when no API field
        # currently displays the same category.
        existing_metadata_keys = set()
        if gender and gender != "None":
            existing_metadata_keys.add("gender")
        if age and age != "None":
            existing_metadata_keys.add("age")
        if birth:
            existing_metadata_keys.add("birthday")
        if blood_type and blood_type != "None":
            existing_metadata_keys.add("blood_type")
        if not is_character:
            if hometown and hometown != "None":
                existing_metadata_keys.add("hometown")
            if remote.get("languageV2"):
                existing_metadata_keys.add("language")
            occupations = remote.get("primaryOccupations")
            if isinstance(occupations, list) and any(occupations):
                existing_metadata_keys.add("occupation")
            if isinstance(years_active, list) and years_active:
                existing_metadata_keys.add("years_active")
            if isinstance(favourites, int) and favourites > 0:
                existing_metadata_keys.add("favourites")
        for metadata_key, display_label, value in metadata_facts:
            if metadata_key not in existing_metadata_keys:
                facts_column.addWidget(self._fact(display_label, value))
                existing_metadata_keys.add(metadata_key)

        details_row = QHBoxLayout()
        details_row.setContentsMargins(0, 0, 0, 0)
        details_row.setSpacing(16)

        if facts_column.count():
            facts_host = QWidget()
            facts_host.setObjectName("profileFactsColumn")
            facts_host.setLayout(facts_column)
            facts_host.setMinimumWidth(170)
            facts_host.setMaximumWidth(245)
            facts_host.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
            details_row.addWidget(facts_host, 0, Qt.AlignTop)

        # Render the remaining biography beside the facts in the same profile
        # header. It grows to its content height, leaving only the page itself
        # scrollable instead of nesting a second scroll area inside the header.
        description = self._normalize_profile_description(
            raw_description,
            html_mode=description_has_html,
        )
        if description:
            description_browser = ProfileDescriptionBrowser()
            description_browser.setObjectName("profileDescription")
            description_browser.setReadOnly(True)
            description_browser.setOpenExternalLinks(True)
            description_browser.setFrameShape(QFrame.NoFrame)
            description_browser.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            description_browser.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            description_browser.document().setDocumentMargin(0)
            description_browser.setSizePolicy(
                QSizePolicy.Expanding, QSizePolicy.Preferred
            )
            if description_has_html:
                description_browser.setHtml(description)
            else:
                # AniList descriptions use Markdown, including links and escaped
                # separators; preserve that formatting instead of showing syntax.
                description_browser.setMarkdown(description)
            description_browser.setStyleSheet(
                f"QTextBrowser#profileDescription {{ color:{COLORS['secondary']};"
                "background:transparent;border:none;font-size:12px; }"
                f"QTextBrowser#profileDescription a {{ color:{COLORS['accent']}; }}"
            )
            description_browser.update_content_height()
            details_row.addWidget(description_browser, 1)
        elif self._remote_error:
            note = QLabel(
                "Biography unavailable. Showing the saved profile details."
            )
            note.setWordWrap(True)
            note.setStyleSheet(muted_label_stylesheet())
            details_row.addWidget(note, 1)

        if details_row.count():
            profile_text.addLayout(details_row, 1)

        profile_text.addStretch(1)
        row.addLayout(profile_text, 1)

        self.content_layout.addWidget(header)

        if is_character:
            self._render_voice_actors()
            connection = remote.get("media")
            self._render_media_credits("Appears in", connection, "character")
        elif is_voice_actor:
            self._render_voice_acting_roles(remote.get("characterMedia"), remote)
            self._render_media_credits(
                "Staff credits", remote.get("staffMedia"), "staff"
            )
        else:
            self._render_media_credits(
                "Staff credits", remote.get("staffMedia"), "staff"
            )

        if self._remote_error:
            error_row = QHBoxLayout()
            error_note = QLabel("Profile detail lookup failed; showing cached data.")
            error_note.setWordWrap(True)
            error_note.setStyleSheet(muted_label_stylesheet())
            error_row.addWidget(error_note, 1)
            retry = QPushButton("Retry")
            retry.setCursor(Qt.PointingHandCursor)
            retry.clicked.connect(
                lambda checked=False, token=self._request_token:
                    self._start_profile_load(token)
            )
            error_row.addWidget(retry)
            self.content_layout.addLayout(error_row)

        self.content_layout.addStretch(1)
        self.scroll_area.verticalScrollBar().setValue(0)

    def _render_voice_actors(self):
        section, body = self._section("Voice actors")
        if not self.voice_actors:
            empty = QLabel(
                "No voice actors are saved for this character yet. Credits are specific "
                "to each adaptation and will appear here as NekoTrack refreshes its cast data."
            )
            empty.setWordWrap(True)
            empty.setStyleSheet(muted_label_stylesheet())
            body.addWidget(empty)
        else:
            grid_host = QWidget()
            grid = QGridLayout(grid_host)
            grid.setContentsMargins(0, 0, 0, 0)
            grid.setHorizontalSpacing(12)
            grid.setVerticalSpacing(12)
            ordered = sorted(
                self.voice_actors,
                key=lambda actor: (
                    0 if str(actor.get("language") or "").strip().lower()
                    in {"japanese", "ja", "jpn"} else 1,
                    str(actor.get("language") or ""),
                    str(actor.get("name") or ""),
                ),
            )
            for index, actor in enumerate(ordered):
                person = dict(actor)
                credits = [
                    credit for credit in (person.get("credits") or [])
                    if isinstance(credit, dict)
                ]
                languages = person.get("languages")
                language_labels = []
                if isinstance(languages, (list, tuple)):
                    for language in languages:
                        label = str(language or "").strip()
                        if label and label not in language_labels:
                            language_labels.append(label)
                if not language_labels:
                    for credit in credits:
                        label = str(credit.get("language") or "").strip()
                        if label and label not in language_labels:
                            language_labels.append(label)
                if not language_labels and person.get("language"):
                    language_labels = [str(person["language"]).strip()]

                credit_tooltip = []
                for credit in credits:
                    work_title = str(credit.get("work_title") or "").strip()
                    language = str(credit.get("language") or "").strip()
                    line = " · ".join(value for value in (language, work_title) if value)
                    if line and line not in credit_tooltip:
                        credit_tooltip.append(line)

                person["role"] = " · ".join(language_labels) or "Voice actor"
                card = PersonCard(person, portrait_size=(90, 120))
                if credit_tooltip:
                    card.setToolTip("\n".join(credit_tooltip))
                card.clicked.connect(self.voice_actor_selected.emit)
                grid.addWidget(card, index // 5, index % 5)
            body.addWidget(grid_host)
        self.content_layout.addWidget(section)

    def _render_voice_acting_roles(self, connection, remote):
        """Show full-size work-left/character-right cards, sorted by voice role."""
        del remote
        section, body = self._section("Voice acting roles")
        edges = connection.get("edges") if isinstance(connection, dict) else None
        roles_by_pair = {}
        role_priority = {"MAIN": 0, "SUPPORTING": 1, "BACKGROUND": 2}

        if isinstance(edges, list):
            for edge in edges:
                if not isinstance(edge, dict):
                    continue
                node = edge.get("node")
                node = node if isinstance(node, dict) else {}
                try:
                    work_id = int(node.get("id") or 0)
                except (TypeError, ValueError, OverflowError):
                    work_id = 0
                characters = edge.get("characters")
                if not isinstance(characters, list):
                    continue
                raw_role = str(edge.get("characterRole") or "").strip().upper()
                for character in characters:
                    if not isinstance(character, dict):
                        continue
                    try:
                        character_id = int(character.get("id") or 0)
                    except (TypeError, ValueError, OverflowError):
                        continue
                    if character_id <= 0:
                        continue
                    key = (work_id, character_id)
                    previous = roles_by_pair.get(key)
                    new_priority = role_priority.get(raw_role, 3)
                    old_priority = role_priority.get(
                        str(previous.get("characterRole") or "").upper(), 3
                    ) if previous else 999
                    if previous is not None and new_priority >= old_priority:
                        continue
                    role_edge = dict(edge)
                    role_edge["characterRole"] = raw_role
                    role_edge["characters"] = [dict(character)]
                    roles_by_pair[key] = role_edge

        if not roles_by_pair:
            empty = QLabel("No voice-acting character roles were found.")
            empty.setWordWrap(True)
            empty.setStyleSheet(muted_label_stylesheet())
            body.addWidget(empty)
        else:
            def role_sort_key(edge):
                node = edge.get("node") if isinstance(edge.get("node"), dict) else {}
                characters = edge.get("characters") or []
                character = characters[0] if characters and isinstance(characters[0], dict) else {}
                return (
                    role_priority.get(str(edge.get("characterRole") or "").upper(), 3),
                    str(self._work_title(node)).casefold(),
                    self._name_from(character.get("name"), "Unknown character").casefold(),
                    int(node.get("id") or 0),
                    int(character.get("id") or 0),
                )

            host = QWidget()
            grid = QGridLayout(host)
            grid.setContentsMargins(0, 0, 0, 0)
            grid.setHorizontalSpacing(12)
            grid.setVerticalSpacing(12)
            for index, edge in enumerate(
                sorted(roles_by_pair.values(), key=role_sort_key)
            ):
                card = MediaCreditCard(edge, "voice_actor")
                card.work_selected.connect(self.work_selected.emit)
                card.character_selected.connect(self.character_selected.emit)
                grid.addWidget(card, index // 2, index % 2)
            grid.setColumnStretch(0, 1)
            grid.setColumnStretch(1, 1)
            body.addWidget(host)
        self.content_layout.addWidget(section)

    def _render_media_credits(self, heading, connection, credit_kind):
        section, body = self._section(heading)
        edges = connection.get("edges") if isinstance(connection, dict) else None
        if not isinstance(edges, list) or not edges:
            message = (
                "No appearance data is available in the saved profile."
                if heading == "Appears in"
                else "No additional credits were found."
            )
            empty = QLabel(message)
            empty.setWordWrap(True)
            empty.setStyleSheet(muted_label_stylesheet())
            body.addWidget(empty)
        elif credit_kind == "staff":
            # One card per work. AniList may send separate edges when the staff
            # member has several credits on the same title.
            grouped = {}
            for edge in edges:
                if not isinstance(edge, dict):
                    continue
                node = edge.get("node")
                if not isinstance(node, dict):
                    continue
                work_id = node.get("id")
                node_title = node.get("title") if isinstance(node.get("title"), dict) else {}
                start_date = node.get("startDate") if isinstance(node.get("startDate"), dict) else {}
                key = ("id", str(work_id)) if work_id else (
                    "fallback",
                    str(node_title.get("romaji") or node_title.get("english") or ""),
                    str(node.get("type") or ""),
                    str(start_date.get("year") or ""),
                )
                entry = grouped.get(key)
                if entry is None:
                    entry = dict(edge)
                    entry["node"] = dict(node)
                    entry["_merged_roles"] = []
                    grouped[key] = entry
                raw_role = edge.get("staffRole") or edge.get("role") or ""
                for role_text in str(raw_role).replace("\n", " · ").split("·"):
                    role_text = " ".join(role_text.split()).strip()
                    if role_text and role_text not in entry["_merged_roles"]:
                        entry["_merged_roles"].append(role_text)

            host = QWidget()
            flow = ProfileFlowLayout(host, h_spacing=10, v_spacing=14)
            for edge in list(grouped.values())[:12]:
                edge["staffRole"] = " · ".join(edge.pop("_merged_roles", []))
                card = ProfileWorkCreditCard(edge)
                card.clicked.connect(self.work_selected.emit)
                flow.addWidget(card)
            body.addWidget(host)
        else:
            host = QWidget()
            flow = ProfileFlowLayout(host, h_spacing=10, v_spacing=14)
            valid_edges = [edge for edge in edges if isinstance(edge, dict)]
            for edge in valid_edges[:12]:
                node = edge.get("node")
                if not isinstance(node, dict) or not node.get("id"):
                    continue
                card = WorkCard(dict(node), mode="library", show_add_button=False)
                card.clicked.connect(self.work_selected.emit)
                flow.addWidget(card)
            body.addWidget(host)
        self.content_layout.addWidget(section)

    def _section(self, title):
        frame = QFrame()
        frame.setObjectName("profileSection")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(18, 16, 18, 18)
        layout.setSpacing(12)
        heading = QLabel(title)
        heading.setObjectName("profileSectionTitle")
        layout.addWidget(heading)
        return frame, layout

    @staticmethod
    def _fact(label, value):
        text = f"{label}: {value}" if label else str(value)
        fact = QLabel(text)
        fact.setObjectName("profileFacts")
        fact.setWordWrap(True)
        return fact

    def _load_artwork(self, url):
        if not url or self._image_label is None:
            return
        reply = self._network_manager.get(
            QNetworkRequest(QUrl(str(url)))
        )
        self._image_reply = reply
        target = self._image_label
        reply.finished.connect(
            lambda current=reply, image_target=target:
                self._image_finished(current, image_target)
        )

    def _image_finished(self, reply, target):
        if self._image_reply is reply:
            self._image_reply = None
        if (
            target is self._image_label
            and reply is not None
            and reply.error() == QNetworkReply.NetworkError.NoError
        ):
            pixmap = QPixmap()
            if pixmap.loadFromData(reply.readAll()):
                self._set_artwork(pixmap)
        if reply is not None:
            reply.deleteLater()

    def _set_artwork(self, pixmap):
        if self._image_label is None or pixmap.isNull():
            return
        self._image_label.setPixmap(
            _crop_pixmap_to_size(pixmap, self._image_label.size())
        )

    def request_shutdown(self):
        self._request_token += 1
        if self._image_reply is not None:
            try:
                self._image_reply.abort()
            except RuntimeError:
                pass
            self._image_reply = None
