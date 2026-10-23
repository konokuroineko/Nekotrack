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
- A code audit found a quadratic TV title-prefix comparison in series grouping.
  It now uses a prefix index that returns the same matching candidate indices in the
  same order, preserving exclusion-aware union behavior while avoiding comparisons
  between unrelated titles. A reference-equivalence test and synthetic benchmark cover it.
- TMDB and MangaBaka title normalizers now use bounded, 8,192-entry caches to avoid
  repeating regex and whitespace normalization for aliases reused across candidates.
- The separate MangaBaka fuzzy-match path also calls the Rust helper for short titles.
  For right-hand strings of 200+ characters it deliberately stays on difflib, because
  difflib's default autojunk behavior would otherwise change scores.

## Measurement plan

Run comparisons on the same machine and Python version, alternate which path runs
first, keep warm-up runs separate, and record median and p95.

| Workload | Current evidence |
| --- | --- |
| Python recommendation ranking | A synthetic before/after benchmark exists; capture actual results from the benchmark output or CI artifact. |
| Native title similarity | Exact parity is required; TMDB and short MangaBaka comparisons use Rust when available. Capture Python/Rust median, p95 and ratio from CI artifacts. |
| TV title-prefix grouping | Compare the indexed candidate discovery against the original all-pairs reference; capture median/p95 at 100–2,000 synthetic titles. |
| Repeated title normalization | Bounded cache hit behavior is tested; quantify end-to-end value only in provider-matching workloads. |
| Full application startup | Not yet measured. |
| API and TMDB lookup end-to-end latency | Not yet measured. |
| Library first-content time and widget count | Not yet measured. |
| Work-detail first-content time and image work | Not yet measured. |
| Scroll responsiveness and memory | Not yet measured. |

An isolated microbenchmark is useful but is not an end-to-end performance claim. In
particular, title matching occurs after provider requests and may represent only a
small fraction of wall-clock time. Keep the Rust pilot only if its benefit justifies
the extra native build and packaging complexity and real usage shows an improvement.

## Second-pass code audit

The next Python targets were selected by reading the actual current paths rather than
assuming CPU-bound code should be ported to Rust:

- `series._group_discovered` had a nested loop comparing every TV title key against
  every other key to find token-prefix relationships. With relation discovery allowed
  to reach 2,000 nodes, this could scan roughly four million pairs. A prefix index now
  visits only keys that actually share the qualifying 2+ token prefix. Candidate index
  lists are sorted back into their original order so the exclusion-aware union calls
  retain their previous order. Tests compare the indexed candidate lists with a direct
  reference implementation on deterministic generated inputs.
- `api._normalize_title` and `api._mangabaka_normalize_title` normalized the same
  aliases repeatedly while candidates were scored. Their pure string transformation
  steps now have bounded caches (8,192 entries each).
- `match_series_for_anilist` had a second Python `SequenceMatcher` path that wasn't
  using the native helper. Short title pairs now use the already-tested Rust function.
  To preserve Python's *default* `autojunk=True` semantics exactly, right-hand strings
  of 200 characters or more deliberately fall back to Python's standard-library matcher.
- New tests cover exact candidate-order parity, normalization-cache hits, MangaBaka
  integration, and default-autojunk compatibility. A separate synthetic benchmark
  compares the prefix index to its former all-pairs algorithm. No UI code changes are
  included.

The new prefix benchmark is synthetic and isolates title-prefix candidate generation.
Record its output before claiming a whole-app speedup. For real benefit, next measure
Home/Search grouping time on the same local library, along with title-enrichment time.

## Third-pass Python audit

- Both `series._group_discovered` and `series.get_library_series` protected user-defined
  exclusions by checking the cartesian product of two union-find components. That
  check was correct but could grow with component-size product on every attempted union.
  An undirected neighbor index now checks only excluded neighbors of the smaller
  component. The membership decision is equivalent to the former pair scan and keeps
  the explicit no-indirect-bypass behavior intact.
- Added randomized equivalence tests and a synthetic worst-case-absence benchmark
  that records median/p95 timings across 100–1,000 members per side. The benchmark
  contains no user library or SQLite data; results are pending CI.
- Do not convert more functions to Rust without profiling. These grouping/index and
  database-I/O paths are better addressed in Python/SQL first.

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

## CI benchmark results (2026-10-23)

The Phase A CI matrix passed on Windows and Linux with Python 3.11 and 3.14 on
the earlier ranking/native-similarity commit, and the uploaded synthetic benchmark
artifacts reported exact ranking/similarity output parity. The current second/third-pass audits add indexed series-prefix matching, bounded
normalization caches, a short-title MangaBaka Rust path, and indexed exclusion checks;
those expanded tests and new series benchmarks are pending CI on the latest branch head.

### Optimized Python recommendations

Median speedup ratio by number of synthetic candidates:

| Candidates | Observed speedup ratio across CI machines | Observed median time |
| ---: | ---: | --- |
| 50 | 24.9–25.8× | Reference 110.9–231.7 ms; optimized 4.3–9.3 ms |
| 250 | 42.5–45.4× | Reference 564.0–1,177.1 ms; optimized 13.3–26.8 ms |
| 500 | 45.4–50.6× | Reference 1,151.3–2,381.1 ms; optimized 25.4–49.6 ms |

The Python benchmark deliberately repeats source-credit index construction in its
reference mode. This very large isolated gain validates removing that repeated work;
it does not mean NekoTrack's full Home feed or app will be 25–50 times faster.

### Rust title-similarity pilot

Across the same four CI OS/Python combinations, native similarity matching was
about 3.83–4.46× faster than Python difflib on 5,000 deterministic synthetic pairs
(about 73.9–77.6% lower median time). Median timings were 18.8–36.9 ms for Rust
and 72.0–157.0 ms for Python, depending on runner/Python version. Outputs matched
exactly for all benchmark pairs, and the Rust parity tests passed.

This validates that the native helper speeds up the isolated string-matching
calculation. It does not establish an equivalent end-to-end TMDB enrichment gain:
real provider response time and how many title comparisons happen per user action
still need measurement on a user machine.

### Next validation

The remaining Phase A gate is a local before/after run on the user's Windows PC,
including ordinary search and library/work-detail workflows. Verify the source app
reports the Rust backend as loaded in diagnostics. A packaged executable check is a
release gate, not a prerequisite for launching the source app or reviewing the current
benchmarks. Do not extrapolate whole-app speed from synthetic CI numbers. Keep the PR
draft and defer QML Phase B until those results are reviewed.

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


## Fourth-pass database audit — bundle Work Details reads

Bundled Characters, Staff and Relations previously called the ordinary single-work
reader once for each bundle member. This repeated SQLite connections and query setup
while opening combined Work Details. The bundle helpers now issue set-based queries
in bounded ID chunks and keep aggregation in Python so role/voice selection and
relation de-duplication remain explicit. Staff rows are re-sorted per work using the
existing scoring key before roles merge; relations retain the original work-ID and
per-source relation/title ordering.

A parity test compares the new readers with copies of the former implementation
against a disposable SQLite fixture. Another test verifies that each non-empty
reader opens one connection for a normal-sized bundle. CI runs a synthetic SQLite
benchmark checking exact parity, timings, and connection counts. Its numbers isolate
the database path and do not establish whole-app speedup.


## CI compatibility fix after batched bundle reads

The older character-role aggregation tests mocked the old single-work API and did not
set up the database tables. They now mock the new per-work batch boundary instead,
while retaining role-precedence, order-independence, and sqlite3.Row coverage. The
production aggregation also normalizes returned row objects into dictionaries before
using mapping access. The first CI run identified these four obsolete mock assumptions;
the full regression and adversarial workflows must rerun on this fix.
