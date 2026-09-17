from PySide6.QtCore import QObject, Signal


class NavigationController(QObject):
    page_changed = Signal(str)

    def __init__(self, stack):
        super().__init__()
        self.stack = stack
        self.pages = {}

    def add_page(self, name, page):
        self.pages[name] = page
        self.stack.addWidget(page)

    def show(self, name):
        if name not in self.pages:
            return

        self.stack.setCurrentWidget(
            self.pages[name]
        )

        self.page_changed.emit(name)