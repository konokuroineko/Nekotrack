from PySide6.QtCore import QTimer


def _patch_search_skeletons():
    try:
        from ui.pages.search_page import SearchPage
    except Exception:
        return

    if getattr(SearchPage, "_skeleton_persistence_patch", False):
        return

    original_trim = SearchPage._trim_skeletons_to_pending

    def trim_only_when_exhausted(self):
        # Keep the full skeleton stream while there are more result pages.
        if self.has_next_page:
            return
        original_trim(self)

    SearchPage._trim_skeletons_to_pending = trim_only_when_exhausted
    SearchPage._skeleton_persistence_patch = True


QTimer.singleShot(0, _patch_search_skeletons)
