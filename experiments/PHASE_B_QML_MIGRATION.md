# Phase B — QML interface migration

## Purpose

Move NekoTrack's existing interface from Qt Widgets toward QML/JavaScript in staged,
reviewable slices. This is a migration of the real application, not a second demo
application. The Python services and SQLite database remain authoritative.

## Guardrails

- Keep the existing shipped Qt Widgets interface as the production UI until an
  equivalent QML screen is wired into the application and passes its parity checks.
- Do not create mock library entries or sample-only replacement screens.
- Reuse the real Library grouping service so automatic bundles, manual links,
  exclusions, earliest-member presentation, and saved cover/title overrides remain
  governed by Python.
- QML is a view layer. API requests, SQLite reads/writes, progress rules, settings
  migration, update handling, and worker/thread lifetime remain in Python.
- Keep the QML boundary narrow and typed. Send user actions back to the existing
  application shell through signals; do not place backend rules in JavaScript.
- Test keyboard navigation, accessible names, focus behavior, scrolling, image
  loading, theme changes, large-library behavior, and first-content time for each
  real screen before switching that screen on by default.

## Initial foundation in this PR

ui/qml_bridge.py adds a read-only LibraryListModel backed by
series.get_library_series() plus a QmlApplicationBridge that exposes the model,
allows a view to request navigation to an existing work ID, and reports refresh
errors without crashing the host. The adapter only maps existing group data into
stable QML roles; it does not implement another bundle algorithm or query SQLite
directly.

The current application entry point and Qt Widgets pages are unchanged. The bridge
is intentionally not installed into main.py yet because it does not represent a
complete replacement for any existing screen on its own.

## Migration sequence

1. Add and test the Python/QML application boundary against real persisted data.
2. Migrate the existing Library screen as the first complete screen: retain search
   or filtering controls, status/progress, bundle editing, context actions, item
   selection, and navigation into Work Details. Wire selection to the current
   MainWindow so existing Work Details workers remain responsible for detail data.
3. Compare the QML Library's visible groups and actions against the current
   Qt Widgets implementation, including bundled and manually excluded items.
4. Migrate Search and Home next, keeping recommendation generation, provider calls,
   and search grouping in Python.
5. Migrate Calendar, Favorites, Recommendations, Settings, Work Details and entity
   profiles in separate slices. Keep the legacy implementation available until each
   slice has parity coverage.
6. Exercise a full source-mode run and then frozen Windows packaging, including
   local database, artwork cache, themes, update and shutdown behavior.

## Validation status

This PR introduces the migration boundary and unit tests only; it does not claim a
screen has been migrated or that the current interface has changed. Phase A was
merged as requested, but its latest CI checks did not finish on the merged head.
The known validation gap remains tracked separately from this QML foundation.
