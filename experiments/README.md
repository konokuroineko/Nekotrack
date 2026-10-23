# NekoTrack modernization experiment

This directory is the **ongoing modernization work** for NekoTrack, kept together
in the same draft pull request. It is not a disposable demo and it does not modify
the production app or packaged release yet.

## Run the full UI shell

Use the same Python environment in which NekoTrack and PySide6 are installed.
From the repository root:

```powershell
python experiments/qml_preview.py
```

The window now prototypes the main application destinations: Home, Library, Search,
Calendar, Favorites, Settings, and a work-detail view. The layout uses sample titles
and illustrative events only. It does not read, alter, or persist your real library;
the controls demonstrate page/navigation behavior and design direction, not production
functionality yet.

## What is changing beyond the UI spike

- [MODERNIZATION_PLAN.md](MODERNIZATION_PLAN.md) records the re-evaluated full-app
  architecture, UI migration scope, performance acceptance gates, accessibility
  requirements, and conditional Rust plan.
- [benchmark_recommendations.py](benchmark_recommendations.py) measures the real
  Python recommendation-ranking function on deterministic synthetic workloads.
- The recommendation engine now precomputes source contributor weights once for
  each ranking pass rather than repeating the same scan for every candidate.
- A regression test checks that the shared index is built once and scoring output
  remains unchanged for the tested workload.

## Benchmark the CPU-bound recommendation path

From the repository root in PowerShell:

```powershell
python experiments/benchmark_recommendations.py --candidate-sizes 50 250 500 --sources 50 --iterations 7 --json-out "$env:TEMP\nekotrack-ranking-baseline.json"
```

The benchmark uses synthetic inputs only. It does not call the network or read the
database. It measures recommendation ranking, **not** cold startup, actual API
latency, or end-to-end UI responsiveness. Keep the machine/Python/build details with
the output. Run the same settings before and after a change and compare median and
p95 timings; do not substitute estimated numbers.

## Performance baseline checklist

Collect real app timings separately from the synthetic benchmark. Repeat each scenario
on the same computer/build and report median and p95; measure cold and warm cache runs
separately.

| Scenario | Baseline |
| --- | --- |
| Cold start to first usable main window | Not measured |
| Home: first interactive content and fully loaded feed | Not measured |
| Search: local filtering, provider request, and artwork separately | Not measured |
| Library: query/grouping, first interactive card, full population | Not measured |
| Large bundle detail: initial view and episode/chapter content | Not measured |
| Recommendation CPU ranking (synthetic, no network/DB) | Use benchmark script |
| Long-list scrolling / frame stutter | Not measured |
| Peak working set (cold start and larger library) | Not measured |

## Manual acceptance checklist

- [ ] Preview opens with no QML warnings/errors.
- [ ] Side navigation switches between Home, Library, Search, Calendar, Favorites, and Settings.
- [ ] Global search filters sample titles; library status filters and search format filters work.
- [ ] Clear filters returns the sample results.
- [ ] Selecting a card opens the detail concept and Back returns to the prior page.
- [ ] Keyboard users can reach navigation, search, filters, cards, and actions with visible focus.
- [ ] Windows Narrator exposes useful names and descriptions for controls and result cards.
- [ ] Layout survives the minimum window size and larger Windows text scaling.
- [ ] Light/dark, contrast, RTL, and reduced-motion behavior have been tested before production adoption.
- [ ] Existing Widgets screens, local data, installer, updater and rollback are unchanged.

## Architecture direction

- **Python / PySide6:** APIs, business rules, sync, diagnostics, persistence access, and a narrow QObject/model adapter layer for QML.
- **Qt Quick / QML / JavaScript:** the long-term full UI direction, migrated by screen behind the Python service boundary. It is not automatically faster than Widgets; use profiler results and the live-data vertical slice to validate it.
- **Rust / PyO3 / maturin:** a measured performance kernel, not a rewrite of network calls, SQLite, or UI painting. Recommendation ranking and contributor matching are initial candidates to benchmark. Keep Rust only if the measured end-to-end gain justifies build, CI, and frozen-installer complexity.
- **SQLite / SQL:** retain the local database and improve query batching/indexes based on timing evidence.
- **PyInstaller / Inno Setup:** retain the release path until the new UI/optional native extension is packaged and tested end-to-end.

The production UI migration and Rust dependency are not complete. The draft PR stays open
until the useful screens are connected to real data, regression and accessibility checks
pass, and before/after performance numbers support the changes.
