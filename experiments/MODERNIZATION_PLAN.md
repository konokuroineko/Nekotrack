# NekoTrack performance modernization — Phase A

## Scope

Phase A improves the existing Python backend and measures an optional Rust/PyO3
acceleration pilot. The current shipped Qt Widgets UI remains unchanged. The goal is
to demonstrate useful performance gains while preserving existing API behavior,
recommendation results, local data, saved progress, themes, bundles, settings and
release safety.

Phase B — the QML/JavaScript UI modernization — is explicitly deferred until we
have comparable Phase A measurements. This PR does not add a replacement UI,
sample-only screen, or alternate production frontend.

## Architecture for Phase A

| Area | Decision |
| --- | --- |
| Existing desktop UI | Keep the current PySide6/Qt Widgets screens and theme intact during Phase A. |
| Backend and domain behavior | Keep Python as the source of truth for APIs, SQLite operations, bundles, progress, recommendations, caching, settings and updates. Improve measured hot paths in place. |
| Native acceleration | Add an optional Rust extension using PyO3/maturin with an exact Python fallback. Enable only the operation with parity tests and benchmark its result. |
| Database | Keep SQLite and SQL. Add or change query/index behavior only with evidence and regression coverage. |
| Release packaging | Keep PyInstaller and Inno Setup. A build must explicitly build/install the native wheel before packaging to use Rust; the Python fallback must remain available. |

Rust is not a rewrite of the backend. QML is a later UI layer connected to Python
services, not part of the current implementation phase.

## Work already included

- Python recommendation ranking precomputes source-contributor weights once per
  ranking pass instead of rebuilding the same index for every candidate.
- A regression test checks that the optimized and reference paths return identical
  ranking outputs while the reference repeats index construction and the optimized
  path constructs the index once.
- A deterministic recommendation benchmark compares the reference and optimized
  Python paths using synthetic data, with no API calls or personal database access.
- Recommendation scrollbar rebinding disconnects the previous scrollbar and avoids
  redundant connections; a regression test covers stale scrollbar callbacks and
  disconnect warnings.
- An optional Rust/PyO3 module implements the matching-block algorithm used by
  difflib.SequenceMatcher with autojunk disabled. The API uses this helper only after
  the existing Python title normalization and exact/containment checks.
- native_acceleration.py uses the Rust module when available and falls back to the
  standard-library Python implementation when it is absent or cannot be loaded.
- Startup diagnostics record whether the Python or Rust path was loaded.
- Native parity tests compare results against Python over exhaustive short strings,
  deterministic random inputs and Unicode examples. The same test checks that API
  title-matching scores remain identical.
- CI builds the native wheel on Windows and Linux with Python 3.11 and 3.14, runs
  parity tests, and uploads benchmark JSON for native title matching and Python
  recommendation ranking.

## Measurement plan

Run comparisons on the same machine and Python version, alternate which path runs
first, keep warm-up runs separate, and record median and p95.

| Workload | Current evidence |
| --- | --- |
| Python recommendation ranking | A synthetic before/after benchmark exists; capture actual results from the benchmark output or CI artifact. |
| Native title similarity | Exact parity is required; capture Python/Rust median, p95 and ratio from CI artifacts. |
| Full application startup | Not yet measured. |
| API and TMDB lookup end-to-end latency | Not yet measured. |
| Library first-content time and widget count | Not yet measured. |
| Work-detail first-content time and image work | Not yet measured. |
| Scroll responsiveness and memory | Not yet measured. |

An isolated microbenchmark is useful but is not an end-to-end performance claim. In
particular, title matching occurs after provider requests and may represent only a
small fraction of wall-clock time. Keep the Rust pilot only if its benefit justifies
the extra native build and packaging complexity and real usage shows an improvement.

## Rust acceptance criteria

- Exact equivalence with Python title-similarity ratios; no change to provider match
  selection, ordering, or visible behavior.
- The extension is optional at import/runtime and absence never prevents startup.
- Supported Windows and Linux CI builds succeed; Python 3.11 and 3.14 parity tests pass.
- Record native-versus-Python benchmark output. Do not claim a speedup until numbers
  have actually been recorded.
- Before a public release uses Rust, build/install the native wheel in the PyInstaller
  environment, verify the frozen executable loads it, and test installation, upgrade,
  rollback and fallback behavior.
- If the native microbenchmark does not translate into an end-to-end benefit, revert
  or replace the Rust target rather than preserving it just to add a language.

## Phase B entry gate

Only after reviewing Phase A results should we begin QML/JavaScript UI work. That
future phase should connect to the existing Python services and reproduce the real
NekoTrack screens and behavior—not use mock cards or a separate demonstration app.
The interface change needs its own parity, accessibility, scrolling, memory and
packaging evaluation, and must preserve all existing workflows and local data.

## Merge and release gate

Keep one ongoing modernization PR. Do not merge or release until all relevant CI
checks pass, benchmark data is reviewed, real-app behavior has been tested, and the
native/fallback packaging path is understood. No performance figure may be invented
or inferred from language reputation.
