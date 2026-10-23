# NekoTrack polyglot experiment

This directory contains an isolated Qt Quick/QML prototype. It is not imported by
`main.py`, is not included by the production PyInstaller build, and does not
read or write the NekoTrack database.

## Run the prototype

Use the same Python environment in which NekoTrack and PySide6 are installed.
From the repository root:

```powershell
python experiments/qml_preview.py
```

The current screen uses sample data only. Search filters the sample anime, manga,
and light novel entries. Selecting a card changes only an on-screen prototype
message.

## What this experiment is intended to establish

- Whether a Qt Quick/QML component can be developed and run alongside the
  existing PySide6/Qt Widgets app without changing the production entry point.
- Whether the visual direction improves responsive layout and repeated result
  cards without losing keyboard focus visibility or useful accessible names.
- Whether the QML layer can remain presentation-only, with Python retaining
  application services, provider integration, and persistence.
- What additional Qt Quick modules, resources, and build steps would be required
  before production packaging could support QML.

## Manual acceptance checklist

- [ ] The preview launches without QML warnings/errors.
- [ ] Search filters by title, media format, and description.
- [ ] Clear restores all sample results and returns focus to the search field.
- [ ] Keyboard users can reach the search field, Clear button, and result cards.
- [ ] The focused control is visibly identifiable.
- [ ] Result cards expose a meaningful accessible name and description to the
      Windows Narrator accessibility tree.
- [ ] The window remains usable when resized down to its minimum size.
- [ ] Larger Windows text/scaling settings do not obscure controls or text.
- [ ] The production application and installer are unaffected.

## Performance baseline

Record measurements from the same computer and build before and after meaningful
changes. Do not fill in numbers from estimates.

| Scenario | Baseline result | Measurement method |
| --- | --- | --- |
| Cold application startup | Not measured yet | Time from launch to usable main window; repeat several times |
| Search response | Not measured yet | Measure a common query with cached data and with cache cleared |
| Open a large bundle | Not measured yet | Time from selection to usable detail view |
| Initial Library load | Not measured yet | Time from entering Library to visible, interactive cards |
| Recommendation generation | Not measured yet | Measure ranking separately from waiting for network responses |

Keep cold and warm runs separate, note machine and build details, and compare
median results rather than relying on a single run.

## Current architecture direction

- **Python/PySide6:** primary application and service layer.
- **QML/JavaScript:** experimental declarative UI layer, introduced incrementally.
- **Rust:** only consider a native extension after profiling identifies a CPU-bound
  operation and a benchmark demonstrates useful improvement.
- **SQLite/SQL:** retain persistence and improve query/data-access boundaries.
- **PowerShell/Inno Setup:** retain Windows update and installer tooling.

No full UI migration or Rust dependency is implied by this prototype.
