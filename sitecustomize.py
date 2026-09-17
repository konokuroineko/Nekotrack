"""Small startup compatibility patch for search rate-limit recovery.

This keeps pagination skeletons visible while AniList is rate-limited and
retries the exact failed page after a cooldown. It is intentionally isolated
so the main search implementation remains unchanged.
"""

from PySide6.QtCore import QTimer


def _install_search_rate_limit_patch():
    try:
        from ui.pages.search_page import SearchPage
    except Exception:
        return

    if getattr(SearchPage, "_rate_limit_patch_installed", False):
        return

    original_start_search = SearchPage._start_search
    original_load_more_results = SearchPage.load_more_results
    original_search_clicked = SearchPage.search_clicked
    original_search_error = SearchPage.search_error

    def patched_start_search(self, page):
        self._rate_limit_active_page = page
        return original_start_search(self, page)

    def patched_load_more_results(self):
        if getattr(self, "_rate_limit_waiting", False):
            return
        return original_load_more_results(self)

    def patched_search_clicked(self):
        self._rate_limit_waiting = False
        self._rate_limit_retry_generation = getattr(
            self, "_rate_limit_retry_generation", 0
        ) + 1
        return original_search_clicked(self)

    def retry_after_rate_limit(self, generation, page):
        if generation != getattr(self, "_rate_limit_retry_generation", 0):
            return
        self._rate_limit_waiting = False
        if not self.has_searched or self.is_loading:
            return
        if page is None:
            return
        self._rate_limit_active_page = page
        self._start_search(page)

    def patched_search_error(self, message):
        lowered = message.lower()
        if "429" not in message and "too many requests" not in lowered:
            return original_search_error(self, message)

        # The failed page's skeletons intentionally remain in the grid.
        # Only stop the current worker; the exact same page is retried after
        # the cooldown and successful results replace those existing skeletons.
        self.is_loading = False
        self.search_button.setEnabled(True)
        self._stop_pending_render()
        self.pending_items = []
        self.pending_batch_active = False

        self._rate_limit_waiting = True
        self._rate_limit_retry_generation = getattr(
            self, "_rate_limit_retry_generation", 0
        ) + 1
        generation = self._rate_limit_retry_generation
        page = getattr(self, "_rate_limit_active_page", None)

        count = len(self.displayed_items)
        self.results_title.setText(
            f"{count} result{'s' if count != 1 else ''} · waiting for AniList…"
        )

        QTimer.singleShot(
            5000,
            lambda: retry_after_rate_limit(self, generation, page),
        )

    SearchPage._start_search = patched_start_search
    SearchPage.load_more_results = patched_load_more_results
    SearchPage.search_clicked = patched_search_clicked
    SearchPage.search_error = patched_search_error
    SearchPage._rate_limit_patch_installed = True


_install_search_rate_limit_patch()
