"""A small, consistently painted switch for preference rows.

Unlike a stylesheet image indicator, this widget draws its thumb with Qt's
raster painter, so it remains visible in Windows, Linux, dark, and white mode.
It subclasses QCheckBox to preserve native checked state, keyboard activation,
and accessibility semantics.
"""

from PySide6.QtCore import QEasingCurve, QRectF, QSize, Qt, QVariantAnimation
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QCheckBox

from ui.theme import COLORS


class SwitchControl(QCheckBox):
    TRACK_WIDTH = 42
    TRACK_HEIGHT = 24
    THUMB_DIAMETER = 16
    LABEL_LEFT = 52

    def __init__(self, text="", parent=None, palette=None):
        super().__init__(text, parent)
        self._color_palette = dict(palette) if isinstance(palette, dict) else None
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMouseTracking(True)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self._thumb_position = 1.0 if self.isChecked() else 0.0
        self._thumb_animation = QVariantAnimation(self)
        self._thumb_animation.setDuration(180)
        self._thumb_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._thumb_animation.setStartValue(self._thumb_position)
        self._thumb_animation.setEndValue(self._thumb_position)
        self._thumb_animation.valueChanged.connect(self._set_thumb_position)
        self.toggled.connect(self._animate_thumb)

    def _set_thumb_position(self, value):
        self._thumb_position = float(value)
        self.update()

    def _animate_thumb(self, checked):
        self._thumb_animation.stop()
        self._thumb_animation.setStartValue(self._thumb_position)
        self._thumb_animation.setEndValue(1.0 if checked else 0.0)
        self._thumb_animation.start()

    def set_color_palette(self, palette=None):
        """Set optional preview colors; normal controls follow the live theme."""
        self._color_palette = dict(palette) if isinstance(palette, dict) else None
        self.update()

    def _colors(self):
        return self._color_palette if self._color_palette is not None else COLORS

    def sizeHint(self):
        label_width = self.fontMetrics().horizontalAdvance(self.text()) if self.text() else 0
        width = 42 if not label_width else self.LABEL_LEFT + label_width + 6
        height = max(self.TRACK_HEIGHT + 4, self.fontMetrics().height() + 2)
        return QSize(width, height)

    def minimumSizeHint(self):
        return self.sizeHint()

    def enterEvent(self, event):
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.update()
        super().leaveEvent(event)

    def focusInEvent(self, event):
        super().focusInEvent(event)
        self.update()

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self.update()

    def hitButton(self, position):
        """Use the full switch rectangle as its clickable target."""
        return self.rect().contains(position)

    def paintEvent(self, event):
        del event
        colors = self._colors()
        enabled = self.isEnabled()
        checked = self.isChecked()
        hovered = self.underMouse() and enabled

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

        track = QRectF(
            1.0,
            (self.height() - self.TRACK_HEIGHT) / 2.0,
            float(self.TRACK_WIDTH),
            float(self.TRACK_HEIGHT),
        )
        if enabled and checked:
            track_fill = colors.get("accent", "#7350a5")
            track_border = colors.get("accent", "#7350a5")
        elif enabled:
            track_fill = colors.get(
                "surface_hover" if hovered else "surface_alt", "#191521"
            )
            track_border = colors.get("border", "#2b2438")
        else:
            track_fill = colors.get("background_alt", "#0f0c16")
            track_border = colors.get("border", "#2b2438")

        painter.setPen(QPen(QColor(track_border), 1.0))
        painter.setBrush(QColor(track_fill))
        painter.drawRoundedRect(track, self.TRACK_HEIGHT / 2.0, self.TRACK_HEIGHT / 2.0)

        thumb_left = track.left() + 3.0
        thumb_right = track.right() - 3.0 - self.THUMB_DIAMETER
        thumb_x = thumb_left + (thumb_right - thumb_left) * self._thumb_position
        thumb_y = track.top() + (self.TRACK_HEIGHT - self.THUMB_DIAMETER) / 2.0
        thumb = QRectF(
            thumb_x, thumb_y, float(self.THUMB_DIAMETER), float(self.THUMB_DIAMETER)
        )
        thumb_fill = "#ffffff" if enabled else colors.get("muted", "#82758f")
        thumb_border = colors.get("border", "#2b2438")
        painter.setPen(QPen(QColor(thumb_border), 1.0))
        painter.setBrush(QColor(thumb_fill))
        painter.drawEllipse(thumb)

        if self.hasFocus() and enabled:
            focus = track.adjusted(-1.0, -1.0, 1.0, 1.0)
            painter.setPen(QPen(QColor(colors.get("accent", "#7350a5")), 1.5))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(
                focus, (self.TRACK_HEIGHT + 2.0) / 2.0, (self.TRACK_HEIGHT + 2.0) / 2.0
            )

        if self.text():
            text_color = colors.get("primary", "#f5f0fb") if enabled else colors.get("muted", "#82758f")
            painter.setPen(QColor(text_color))
            painter.drawText(
                QRectF(
                    float(self.LABEL_LEFT),
                    0.0,
                    max(0.0, self.width() - self.LABEL_LEFT),
                    float(self.height()),
                ),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                self.text(),
            )
        painter.end()
