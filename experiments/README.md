# NekoTrack performance and accessibility work

This directory holds benchmark tools and the plan for the single ongoing modernization
pull request. The production app remains the reference for visuals and behavior: existing
Qt Widgets pages, Neko theme, sidebar/wordmark, card styling, navigation, and backend
functions must stay intact. This is not a new mock interface.

See [MODERNIZATION_PLAN.md](MODERNIZATION_PLAN.md) for the re-evaluated architecture,
full-app parity requirements, performance priorities, accessibility checks, and Rust gate.

## Reproducible recommendation-ranking benchmark

From the repository root in PowerShell:

```powershell
python experiments/benchmark_recommendations.py --candidate-sizes 50 250 500 --sources 50 --iterations 7 --json-out "$env:TEMP\nekotrack-ranking-baseline.json"
```

This benchmark runs the current Python `recommendation_engine.rank_candidates` function
on deterministic synthetic candidates/source credits. It makes no network requests and
does not read the live database or personal library. It measures the CPU ranking path,
not startup, search latency, the UI, or total recommendation refresh duration.

Run the same command before and after a performance change on the same machine and
Python version. Keep the JSON output along with the commit, machine, settings, median,
and p95 measurements. The first benchmark after the optimization can establish a local
baseline, but comparison against an unoptimized baseline is needed to quantify its gain.
Do not invent or extrapolate performance numbers.

## Current optimization work

The ranking path now builds shared source-credit weights once per ranking pass, rather
than repeating that scan for each candidate. The new regression test checks that the
index is built once and that ranking results remain consistent during the tested call.
This reduces redundant work by design, but its measured impact has not been recorded yet.

The recommendations view also has a safer scrollbar-rebinding path: it disconnects the
previous tracked scrollbar, avoids unnecessary rebinding to the same bar, and includes
a test that verifies stale scrollbars no longer trigger pagination and that the failed-
disconnect warning is absent.

## Whole-app performance baseline

Use the same PC and same build for repeated runs. Keep cold and warm caches separate,
and record median and p95. Use app diagnostics to separate API waiting, database calls,
data transformations, artwork, UI construction, and first interactive content.

| Workload | Baseline |
| --- | --- |
| Startup to first usable window | Not measured |
| Home: first interactive recommendation content | Not measured |
| Search: local filtering / API wait / artwork | Not measured |
| Library: database, grouping, first interactive card | Not measured |
| Large work-detail bundle and episode/chapter content | Not measured |
| Recommendation CPU ranking | Run the synthetic benchmark above |
| Long-list scroll responsiveness and peak memory | Not measured |

## Language choice

Keep Python and PySide6 for the existing UI, business logic, services, API and database
boundaries. Rust via PyO3/maturin remains an option for a measured CPU-bound operation,
not a rewrite of network access, SQLite, or UI rendering. The benchmark is the first
screening step; keep Rust only if it produces a substantial isolated speedup **and** a
measurable end-to-end benefit after packaging and conversion costs.

No QML rewrite or native extension is currently enabled in the production application.
