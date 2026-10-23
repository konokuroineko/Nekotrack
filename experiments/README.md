# NekoTrack performance modernization

This PR is Phase A: improve Python backend hot paths and evaluate a small, optional
Rust/PyO3 acceleration pilot. The current real Qt Widgets UI remains unchanged.
QML/JavaScript UI modernization is Phase B, to be considered after these measurements.

See MODERNIZATION_PLAN.md for the architecture, parity requirements, measurements
and merge gate.

## Python recommendation benchmark

From the repository root in PowerShell:

    python experiments/benchmark_recommendations.py --candidate-sizes 50 250 500 --sources 50 --iterations 7 --json-out "$env:TEMP\nekotrack-ranking.json"

This compares the former repeated source-credit indexing path with the optimized
Python implementation on identical deterministic synthetic records. It checks the
ranked outputs are identical and reports median, p95 and speedup. It does not access
the live database or network. It measures only the ranking CPU path, not full feed
latency, UI rendering, or startup.

## Native Rust benchmark

Build and install the optional extension following rust/nekotrack_core/README.md,
then run:

    python experiments/benchmark_native_similarity.py --pairs 5000 --iterations 9 --json-out "$env:TEMP\nekotrack-native-similarity.json"

This compares Python difflib with the Rust matching-block implementation over the
same deterministic title pairs and refuses to run when the native module was not
loaded. It checks exact outputs before timing and reports median, p95 and ratio.
The CI workflow builds and tests the extension on Windows and Linux with Python
3.11 and 3.14 and uploads both backend benchmark JSON files per environment.

## Interpreting the results

Synthetic benchmarks help isolate a code path but do not prove a whole-app speedup.
The Rust title matcher is used only after Python normalizes and checks titles; the
real impact depends on how much time title matching occupies relative to API waits
and other work. Startup, real provider lookup latency, library population, work-detail
loading, scrolling and peak memory remain to be measured separately.

The optional module is imported through native_acceleration.py. When it is missing
or fails to load, Python difflib remains the fallback. The normal requirements list
does not require Rust; builds that want native acceleration must build and install
the wheel in the same environment before packaging.

No QML screen or UI migration is part of Phase A. Preserve existing application
behavior and user data, and do not merge until CI, benchmark review and packaged-app
checks are complete.

## CI benchmark results (2026-10-23)

The Phase A CI matrix passed on Windows and Linux with Python 3.11 and 3.14.
The uploaded synthetic benchmark artifacts reported exact ranking / similarity
output parity.

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

The remaining Phase A gate is a local before/after run on the user's Windows PC and
a packaged executable check that proves the frozen app actually loads the Rust
module. Benchmark the actual app/library; do not extrapolate whole-app speed from
synthetic CI numbers. Keep the PR draft and defer QML Phase B until those results
are reviewed.
