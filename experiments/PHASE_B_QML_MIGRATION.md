# Phase B: QML interface migration

## Current state

PR: [#102 — NekoTrack QML UI modernization (Phase B)](https://github.com/konokuroineko/Nekotrack/pull/102)

The branch contains a real QML application shell, not a sample/demo screen. `ui/qml/ApplicationShell.qml` owns the visible navigation and the Home, Library, Search, Calendar, Favorites, Settings, Work Details, and Entity Profile routes. `ui/qml/LibraryView.qml` remains the production Library grid, backed by the Python `QAbstractListModel` and existing grouping/database code.

The branch is still a **draft** and is not ready to merge until the latest CI and a populated-database smoke test have actually passed. A queued workflow is not a pass. Python remains responsible for the AniList/MangaBaka/TMDB integration, grouping, SQLite persistence, progress tracking, recommendations, dialogs that are still delegated to legacy page handlers, and release/update behavior. QML is the presentation layer.

## Exact appearance and sizing values to preserve

These values are sourced from the app's current preferences and the QML bridge. Do not silently replace the discrete settings choices with approximate sliders.

- Default poster width: `210 px`.
- QML poster width range: `80–270 px`; the Settings presets are `180, 210, 240, 270 px`.
- Cover ratio: `210:284`; poster height is `round(width * 284 / 210)`.
- Default interface text size: `13 px`; Settings choices are `12, 13, 14, 15 px`.
- Default poster gap: `24 px`; supported preference range: `0–120 px` in steps of `2 px`.
- Default corner radius: `12 px`; Settings choices are `6, 10, 12, 16, 20 px`.
- UI scale choices: `80, 90, 100, 110, 125, 150, 175, 200%`; restart is required when the active scale changes.
- Resize animation default: enabled; default duration `260 ms`; Settings choices are `0, 180, 260, 380, 520 ms`.
- Preserve the Neko/purple theme defaults, selected/hover colors, current cover cache behavior, and title wrapping/fitting.

## Current implementation slices

### Library and poster model

- The QML grid uses the existing canonical Python Library groups and supports All, Watching, Completed, and Planned filters.
- Poster cards use real cached/local cover paths when available, and the existing remote-cover cache bridge otherwise.
- Bundle labels, open-details, bundle appearance editing, and deletion confirmation are connected to Python handlers. The empty and loading states are distinct.
- Library data snapshot/grouping work is scheduled off the UI thread in the application bridge.

### Search and recommendations

- QML Search forwards query, type/format, status, season, year, score, sort, genre, tag, MangaBaka publisher/licensing and Fast Search parameters through the Python bridge.
- The existing combined AniList/MangaBaka catalog query, search grouping, pagination, recommendation engine, recommendation feedback, and add-to-library logic remain the backend.
- Recommendations are deferred until after the first visible frame; local Library snapshot loading is asynchronous.

### Work Details and profiles

- Work Details loads saved episode/character/staff/relation snapshots in background workers.
- Bundle episodes retain their owning work ID and are labeled by member/season. The visible list is bounded to `300` rows, and progress changes save to the correct member. “Mark all watched” processes each bundle member.
- Manga/novel tracking uses per-member chapter/volume progress; progress summaries label episodes separately from chapters and volumes.
- Character/staff/voice-actor profiles use the existing AniList profile API, show profile facts and linked works, and save favorites through the existing favorites table.
- Work Details exposes refresh, bundle edit, and safe delete actions. Some detailed bundle-manipulation and title/cover editing actions remain legacy-page functionality and must be reviewed for parity before the draft is declared complete.

### Settings and packaging

- Settings preserves discrete card size, text size, radius, animation speed, and UI-scale choices.
- The QML settings bridge handles themes/light mode, update channel and startup checks, rollback, background image selection/slideshow/overlay, bundle contents, recommendation voice language, TMDB fallback token, restore defaults, setup, and diagnostics export.
- The installer build script explicitly bundles the production QML files and PySide6's Qt QML import directory.

## Validation requirements before merge

1. Confirm Python checks and adversarial stress workflows complete successfully for the **latest PR head SHA**. Earlier/older queued runs are not evidence that the latest code passed.
2. The headless smoke test `tests/test_qml_view.py` must load both the production `LibraryView.qml` and `ApplicationShell.qml` with their respective Python bridges.
3. Verify with a populated real database: default and alternative poster sizes, dark/light themes, accent colors, filters and counts, cover caching, bundle appearance overrides, delete confirmation, Home startup timing, Search filters/Fast Search, empty states, episode ownership for multi-season bundles, manga/novel chapter/volume saving, profile loading/favorites, and the fallback behavior if QML fails.
4. Build and launch the Windows installer from a clean environment. Verify all QML modules are packaged, not just source files.
5. Keep this PR as a draft until the checks above pass. Do not merge it on the strength of static review alone.

## Files to review first

- `ui/qml/ApplicationShell.qml` — visible routes and controls.
- `ui/qml/LibraryView.qml` and `ui/qml/PosterCard.qml` — exact poster sizing and Library interaction.
- `ui/qml_app_bridge.py` — app-level actions and asynchronous snapshots.
- `ui/qml_bridge.py` — Library model, theme geometry, filters and cover cache integration.
- `ui/main_window.py` — QML/legacy fallback and existing Python action wiring.
- `tests/test_qml_bridge.py`, `tests/test_qml_view.py`, and `tests/test_installer_configuration.py` — bridge, QML smoke, and packaging checks.
