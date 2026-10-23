# NekoTrack performance and accessibility modernization

**Product requirement: preserve the NekoTrack that exists today.** Its current Qt Widgets pages, visual styling, navigation, saved data, settings, and existing backend behavior are the reference implementation. This work must not invent a new UI or replace real behavior with sample cards. Any change that visibly alters the current design requires a separate explicit decision.

## Architecture decision

Keep the working stack and add only language/runtime complexity that earns its place:

| Area | Decision | Reason |
| --- | --- | --- |
| Complete desktop UI | **Keep PySide6 + Qt Widgets and the existing theme/branding/navigation.** | It is the only approach that guarantees the current look and workflows remain the source of truth. A QML rewrite would require rebuilding every page and backend/UI integration, and does not automatically improve speed. |
| Existing backend | **Keep Python services, `api.py`, SQLite functions in `database.py`, bundling logic, background workers, diagnostics, update and rollback behavior.** | They already implement the app's actual behavior. Optimize in place rather than substituting a mock or rewriting providers. |
| Performance extension | **Rust via PyO3 + maturin only for a demonstrated CPU-bound hotspot.** | Rust must improve the actual workload enough to justify native-build, CI, Windows packaging, and support costs. No port is approved based on language reputation alone. |
| Persistence | **Keep SQLite and SQL.** | Measure queries and batch/index work before changing storage. Network waits and GUI painting are not fixed by replacing SQL. |
| Installer/release | **Keep PyInstaller + Inno Setup.** | Extend packaging only if a tested native module becomes worthwhile; verify install, update, rollback, and fresh-install paths before release. |

QML/JavaScript was reconsidered and is **not the chosen replacement UI** for this requirement. A separate sample-only QML shell was removed from this PR because it looked different from the real app and did not use the complete backend. We should not ship a parallel mock UI merely to add another language.

## Non-negotiable parity checklist

- Preserve the current Neko theme, purple accent, wordmark/logo, wallpaper/background transparency, spacing, typography, card style, icons, hover and selection states, navigation order, and existing page layouts.
- Preserve the current behavior across Home/recommendations, Library/bundles/progress, Search/providers/filters/pagination, Calendar/reminders, Favorites/profiles, Work Details/episodes/volumes/chapters/relations, Settings, setup, updates, and rollback.
- Keep one source of truth for each API and persistence operation. API integration stays in `api.py`; database access stays in the existing database layer.
- Preserve the user's database, preferences, image cache, saved bundles, custom appearance overrides, reading/watching progress, and update safety.
- Accessibility improvements should work within the existing design: keyboard operation, meaningful accessible names/roles, visible focus where needed, scaling, correct light-mode surfaces, screen-reader behavior, and non-color cues. Do not restyle the app just to make this branch look new.

## Performance work

### 1. Establish comparable measurements

The app already logs structured diagnostic operations. Use those timestamps to separate time spent in network calls, SQLite, bundling/data transformation, artwork, widget creation, and GUI-thread work. Keep cold and warm runs separate and report median/p95 from repeated trials on the same machine/build.

Priority workloads:

| Workload | Measure |
| --- | --- |
| Startup | launch to first usable window; first useful page content |
| Home | local library snapshot, first interactive recommendations, full feed |
| Search | local input/filter handling, AniList/MangaBaka request, artwork separately |
| Library | SQL retrieval, grouping/bundles, card creation, first interactive content |
| Work Details | initial open, large bundle sections, episode/chapter lists and artwork |
| Recommendation ranking | pure CPU scoring time, separate from network/API wait |
| Scrolling/memory | long-list scrolling responsiveness, number of live widgets/cards, peak working set |

Do not treat synthetic CPU benchmarks as whole-app performance data. Do not put invented numbers in the README or PR.

### 2. Optimize the whole app in place

Fix the measured causes rather than performing a broad rewrite. Likely areas to examine are repeated database/provider calls, duplicate work during grouping, unnecessary complete rerenders, image decode/cache churn, large widget construction on the GUI thread, and callbacks left attached during view replacement. Preserve output/ordering and UI behavior with regression tests.

Current changes in this PR:
- Reuse a precomputed recommendation source-credit index during one ranking pass instead of rebuilding the same weights for every candidate. A regression test checks that the index is created once and the tested ranking output stays consistent. This is an algorithmic optimization hypothesis until before/after benchmark measurements quantify the benefit.
- Fix recommendation scrollbar rebinding by disconnecting the previously tracked bar and avoiding redundant reconnects. A regression test checks old-bar callbacks and failed-disconnect warnings.
- Add a deterministic CPU-only benchmark for `recommendation_engine.rank_candidates`. It uses synthetic data only and does not access the live database or network.

Run from the repository root:
```powershell
python experiments/benchmark_recommendations.py --candidate-sizes 50 250 500 --sources 50 --iterations 7 --json-out "$env:TEMP\nekotrack-ranking-baseline.json"
```

Record Python version, machine, branch/commit, candidate/source counts, median, and p95. Run the same workload before and after the optimization. For real NekoTrack scenarios, use the same installed app/library and export diagnostics. Do not compare measurements taken from different machines or unrelated versions.

### 3. Rust gate

The first Rust candidate should be selected from measured CPU profiling, with recommendation contributor matching/ranking investigated first because it is isolated and can be benchmarked. That is a candidate—not an assumption that it is currently the bottleneck.

Only add a Rust extension when:
- profiling proves the path is materially CPU-bound rather than waiting on API/SQLite or GUI work;
- Rust yields a substantial improvement in that isolated function and a measurable end-to-end benefit;
- output, scoring, ordering, exclusion rules, and recommendation explanations match the Python reference under deterministic and randomized/adversarial tests;
- a Python fallback remains until the native module is built and tested on Windows with every supported Python build;
- the frozen PyInstaller app and installer/update/rollback paths pass.

If the gain is small or native-boundary conversion dominates, keep the optimized Python code. Do not port the whole backend to Rust.

## Merge and release gates

- One ongoing modernization PR; add related fixes here rather than creating more PRs.
- CI must pass on all supported Python/OS combinations and the adversarial stress workflow.
- Test the affected current UI pages against existing visual/behavioral regression tests; test a real local library rather than only sample data.
- Record before/after performance evidence for each claimed speed improvement.
- No loss of existing screens, backend functions, user data, progress, bundles, settings, or update/rollback safety.
- Do not merge or publish a release until the user-facing checks and combined test suite are clean.

## References

- [Qt for Python performance guidance](https://doc.qt.io/qtforpython-6/overviews/qtquick-performance.html): profile actual bottlenecks and avoid spending GUI-frame time on blocking work.
- [Qt Quick accessibility documentation](https://doc.qt.io/qt-6/accessible-qtquick.html): relevant if a future explicit decision reopens QML, but not a reason to replace the current UI by default.
- [PyO3 user guide](https://pyo3.rs/main/) and [maturin guide](https://www.maturin.rs/tutorial.html): official methods for a measured Rust extension if the benchmark warrants it.
