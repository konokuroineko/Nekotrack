import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from ui.widgets.switch_control import SwitchControl


class SwitchControlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_clicks_across_the_visible_track_toggle_the_switch(self):
        switch = SwitchControl()
        switch.resize(switch.sizeHint())
        switch.show()
        self.app.processEvents()
        changes = []
        switch.toggled.connect(changes.append)

        QTest.mouseClick(
            switch,
            Qt.MouseButton.LeftButton,
            pos=QPoint(30, switch.height() // 2),
        )
        self.assertTrue(switch.isChecked())
        self.assertEqual(changes, [True])

        QTest.mouseClick(
            switch,
            Qt.MouseButton.LeftButton,
            pos=QPoint(7, switch.height() // 2),
        )
        self.assertFalse(switch.isChecked())
        self.assertEqual(changes, [True, False])
        switch.close()
        switch.deleteLater()
        self.app.processEvents()

    def test_click_target_covers_the_entire_control_rectangle(self):
        switch = SwitchControl()
        switch.resize(switch.sizeHint())
        self.assertTrue(switch.hitButton(QPoint(37, switch.height() // 2)))
        self.assertFalse(switch.hitButton(QPoint(switch.width(), switch.height() // 2)))
        switch.deleteLater()
        self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
