"""Small page-stack wrapper with predictable back navigation."""

from PySide6.QtCore import QObject, Signal


class NavigationController(QObject):
    page_changed = Signal(str)

    def __init__(self, stack):
        super().__init__()
        self.stack = stack
        self.pages = {}
        self._history = []

    def add_page(self, name, page):
        self.pages[name] = page
        self.stack.addWidget(page)

    def current_name(self):
        current = self.stack.currentWidget()
        return next(
            (name for name, page in self.pages.items() if page is current),
            None,
        )

    def show(self, name, *, record_history=True):
        if name not in self.pages:
            return

        current_name = self.current_name()
        if record_history and current_name and current_name != name:
            self._history.append(current_name)
            if len(self._history) > 100:
                del self._history[:-100]

        self.stack.setCurrentWidget(self.pages[name])
        self.page_changed.emit(name)

    def back(self, fallback=None, skip=()):
        """Return to the most recent valid page, with an optional safe fallback."""
        current_name = self.current_name()
        skipped = set(skip)
        while self._history:
            previous = self._history.pop()
            if previous == current_name or previous in skipped or previous not in self.pages:
                continue
            self.show(previous, record_history=False)
            return previous

        if fallback in self.pages and fallback != current_name and fallback not in skipped:
            self.show(fallback, record_history=False)
            return fallback
        return current_name
