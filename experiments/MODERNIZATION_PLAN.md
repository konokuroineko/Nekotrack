# NekoTrack modernization plan: UI, performance, and a deliberate polyglot core

**Status: proposed implementation plan; not a performance result.** This plan is intentionally part of the ongoing modernization PR. No production-screen replacement should be merged just because a prototype renders.

## Decision summary

Keep the project as a native desktop application and evolve it in place:

| Layer | Direction | Why / guardrail |
| --- | --- | --- |
| Desktop UI | **PySide6 + Qt Quick/QML + JavaScript** for the new shell and migrated screens | Best match for a fully redesigned, responsive, consistent desktop UI while retaining Qt and Python. QML is not automatically faster; profile frame time and startup. |
| Application/services | **Python** | Keep AniList/TMDB/MangaBaka integration, sync, business rules, diagnostics, and update logic here. The QML view must not issue network or SQL requests directly. |
| UI/data boundary | **Python QObject services and typed QAbstractListModel adapters** | QML receives already-prepared view data; long work runs in workers and returns through Qt signals. This preserves the current API/SQLite ownership boundaries. |
| Persistence | **SQLite + SQL** | Keep local-first data and existing migrations. Optimize query shape, indexes, batching, and cache invalidation from query timings before considering a database replacement. |
| Performance kernel | **Rust + PyO3 + maturin, conditional on profiling** | Prototype a real hot path only after the Python benchmark identifies it. Keep semantic parity tests and a Python fallback during evaluation. Rust will not make remote API waits, SQLite lock waits, or UI painting faster by itself. |
| Packaging | Existing PyInstaller + Inno Setup, extended only after integration proves what QML/Rust runtime assets are needed | No installer changes during UI experiments. A native Rust extension must be built and tested on Windows, then verified inside the frozen installer. |

## Why not make the current tiny preview the whole project?

The search preview only proves that QML can start next to the current code. It does not establish that QML beats the current widgets UI, that the architecture is maintainable, or that Rust will improve user-perceived speed. The next UI iteration should be a complete navigable shell, then live data should be added screen-by-screen behind a narrow Python service boundary.

## Re-evaluating the UI choices

| Choice | Advantages | Costs | Decision |
| --- | --- | --- | --- |
| Keep Qt Widgets and only restyle | Lowest rewrite and packaging risk; the app already has substantial widget functionality and tests | Harder to establish a unified, highly customized design system across the large screen set | Keep as fallback, not the preferred long-term design |
| Move the whole view layer to Qt Quick/QML | Declarative layouts, reusable visual components, polished animations, adaptive/responsive screens; still uses Qt | Requires accessible QML equivalents, Python-facing models, packaging review, and staged migration | **Preferred UI direction**, conditional on a useful full-shell prototype and measured/accessible live-data slice |
| Replace the desktop UI with a web stack or another toolkit | Different ecosystem and possibly attractive web-style components | Duplicates infrastructure and abandons much of the existing PySide6 investment; larger rewrite and regression surface | Not recommended for this project right now |

Do not embed every new QML page inside `QQuickWidget` by default. Qt documents that QQuickWidget introduces an offscreen render pass and disables Qt Quick's threaded render loop on all platforms; choose the integration model from a working architecture spike rather than convenience.

## Full UI scope

The new design should cover the **whole application**, not just search:

- **App shell:** stable side navigation, page title/context, global search, update/connection status, responsive window layout.
- **Home:** continue watching/reading, recommendation rows, upcoming releases, skeleton/loading/error/empty states.
- **Library:** status filters, sort and format filters, bundles, progress editing, fast long-list scrolling.
- **Search:** provider/type filters, debounced query input, result cards, loading and retry states.
- **Work details:** real title/cover/description, bundle members, season/episode and volume/chapter progress, cast/staff/relations.
- **Calendar and Favorites:** real release reminders and person/character/staff favorites; preserve existing behavior.
- **Settings:** theme/light mode, scaling, language, accessibility and update/rollback controls.

Use a coherent design system (spacing, typography, surface/elevation, radii, focus/hover/pressed states, icons) rather than styling each page independently. Do not sacrifice existing functions for visual polish.

## Performance plan: measure first, then optimize

Capture repeatable measurements on the same PC/build and report median plus p95; do not write estimates into the baseline. Keep cold-cache and warm-cache runs separate.

| Workload | Measure separately |
| --- | --- |
| Cold startup | process start to first usable window; time to first usable content |
| Home | time to first interactive recommendations and time to fully populated rows |
| Search | local query/filter time; debounce delay; provider request time; image arrival time |
| Library | query time, grouping/bundling time, card/model population, first interactive paint |
| Work details | bundle lookup, episode/chapter catalog lookup, view construction, artwork loading |
| Recommendations | pure Python rank time on deterministic candidate/source-credit sizes; network fetch time separately |
| Memory and scrolling | peak working set, card/model count, scroll/frame stutter on long lists |

Priority order for real performance work:

1. Instrument operations and split network wait, SQL/data processing, image decoding/cache, model transformation, and GUI-thread/render work.
2. Fix known high-impact causes (repeated DB calls, work done on the GUI thread, duplicate image decode/download, unbounded widget creation, unnecessary full-list rerenders) where measurements confirm them.
3. Prefer Qt Quick's virtualized ListView/model patterns for large feeds; keep QML delegates simple and lazy-load only expensive pages.
4. Benchmark the recommendation engine separately. This repository has a pure `rank_candidates` path, so it is a candidate for a Rust experiment, but candidate scoring includes string normalization, Python dictionaries, contributor maps, and explanation text. Port only after timings identify the hot loop and a candidate Rust boundary avoids excessive Python/Rust conversions.
5. Rerun the real workload after each change; report before/after numbers, not an assertion that a language is faster.

### Rust acceptance gate

A Rust implementation is worth keeping only if it:
- reproduces the Python reference results exactly where ordering/IDs/explanations are expected, with explicit float tolerances for numeric values;
- passes normal tests plus randomized/adversarial parity cases;
- demonstrates a substantial speedup in the isolated operation **and** a meaningful improvement in the full local workload;
- builds reproducibly for the exact supported Python versions and Windows architecture and is included in the packaged app;
- does not create an untested mandatory dependency or make install/update/rollback less reliable.

Initial target for investigation: recommendation ranking / contributor matching, not HTTP requests and not Qt painting. A Python fallback remains until release packaging and benchmarks prove the extension safe and useful. If the measured gain is small, keep the cleaner Python implementation and optimize caching/data structures instead.

## Accessibility and localization gates

For every migrated screen: keyboard-only navigation and visible focus; Windows Narrator names/roles/states; high-contrast/contrast checks; text scaling and minimum-window behavior; no information conveyed by color alone; reduced-motion-friendly transitions; RTL layout and locale-aware dates/numbers. Verify light mode actually changes all relevant surfaces. Measure accessibility on the real QML controls, not only on the sample card.

## Acceptance gates before any merge/release

- The full QML shell covers every main navigation destination and survives minimum-size/window-scaling checks.
- At least one vertical slice uses real Python services/model data (first read-only, then progress writes) and has loading/error/empty states.
- Existing regression suite stays green; new integration and parity tests cover migrated behavior.
- Baselines and before/after performance numbers are checked into the PR; no numbers are invented.
- User-tested keyboard and Narrator flows work; no important feature disappears.
- Windows PyInstaller installer/update/rollback paths work with the chosen QML assets and, if enabled, the Rust extension.
- Draft stays open while work and verification are incomplete.

## Official references

- [Qt Quick performance guidance](https://doc.qt.io/qtforpython-6/overviews/qtquick-performance.html) — recommends profiling actual bottlenecks and cautions against overcomplicated delegates and indiscriminate Loader use.
- [Qt Quick Profiler](https://doc.qt.io/qtcreator/creator-qml-performance-monitor.html) — identifies JavaScript work, invisible-item work, frame drops, and UI-thread stalls.
- [Qt Quick accessibility](https://doc.qt.io/qt-6/accessible-qtquick.html) — documents accessibility names/roles/states and built-in keyboard behavior.
- [QQuickWidget performance notes](https://doc.qt.io/qtforpython-6/PySide6/QtQuickWidgets/QQuickWidget.html) — describes its additional render pass and disabled threaded render loop.
- [PyO3 guide](https://pyo3.rs/main/) and [maturin guide](https://www.maturin.rs/tutorial) — supported approach for a Rust extension to Python and release-mode benchmarking/builds.
