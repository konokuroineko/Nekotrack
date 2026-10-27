# Phase B: QML interface migration

## Current slice: real Library screen

The existing Library route now hosts a QML poster grid inside the current Qt Widgets application shell. The application continues to use the existing SQLite/API/Python grouping logic; QML is the presentation layer. Clicking a card returns the original Python group to the existing Work Details page. The view includes status filters, theme-aware layout, bundle labels, selected/custom cover behavior, cover caching, bundle appearance editing, and deletion confirmation via existing Python page methods.

If QML cannot load, the Library route falls back to the existing Qt Widgets screen and logs the error. The rest of the app—including Search, Home, Calendar, Settings, Work Details, and navigation—remains Qt Widgets for now. In the normal startup path, QML engine creation is deferred until the user first opens Library so Home startup does not pay the QML initialization cost.

## Architecture

- The Python bridge exposes a read-only list model based on the existing canonical Library groups.
- The QML file implements the actual Library presentation; it is not a mock/sample screen.
- The current Library page retains Python-side relation sync, bundle edits, deletion confirmation, and Work Details hand-off.
- Canonical bundle member ordering and single-title/bundle title and cover overrides are preserved.

## Validation and remaining parity gate

Model tests cover member order, bundle aggregates, cached cover source choice, invalid rows, filters, signed work IDs, and refresh failures. A headless smoke test loads the production QML file against the Python bridge to catch QML import or syntax errors. CI must be checked after each push; queued checks are not passes.

Before the migration can be considered complete, compare the QML Library against the original screen using a populated real database and verify poster/card sizing across window widths, dark/light themes and accent colors, filter counts, cover caching, bundle edits, deletion, empty state, and opening each media type. Do not merge this PR until these checks pass. Later screens are separate follow-up work on the same Phase B branch/PR.
