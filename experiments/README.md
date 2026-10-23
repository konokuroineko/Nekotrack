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

## Modernization plan and performance work

See [MODERNIZATION_PLAN.md](MODERNIZATION_PLAN.md) for the proposed full-app UI migration,
performance acceptance gates, and conditional Rust/PyO3 plan. The direction is broader
than this sample screen.

A deterministic CPU-only benchmark is available from the repository root:

```powershell
python experiments/benchmark_recommendations.py --candidate-sizes 50 250 500 --sources 50 --iterations 7 --json-out artifacts/recommendation-baseline.json
```

It reports the local recommendation-ranking function's timing on synthetic data only.
It does not read the user's database or call an API, and it must not be treated as an
end-to-end startup/search benchmark. Save each run with the machine/Python/build details;
compare the same settings before and after changes. Use the timings to choose whether
a Rust port has a realistic payoff instead of assuming that Rust will speed up I/O or UI
rendering.

The current performance improvement precomputes stable source-credit weights once per
ranking pass rather than rebuilding them for each eligible candidate. A regression test
checks that this index is built once and that ranking output remains the same across
the tested call. Its real-world benefit still needs measured before/after timings.

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
