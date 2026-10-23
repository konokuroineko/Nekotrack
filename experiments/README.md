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

## Indexed series-title prefix benchmark

From the repository root:

    python experiments/benchmark_series_prefix.py --candidate-sizes 100 500 1000 2000 --iterations 5 --json-out "$env:TEMP\nekotrack-series-prefix.json"

This compares the new prefix index in series grouping with a reference implementation
of the prior all-pairs token-prefix scan. The benchmark verifies identical candidate
indices in their original order before timing and reports median/p95 times and ratio.
It uses synthetic title keys and does not access SQLite, the network, or the user's
library. The CI native-build matrix also runs this benchmark and uploads its JSON with
the other backend benchmark reports. CI timing for this newly added benchmark is
pending; no speedup claim is made yet.

## Second-pass Python audit

- Series grouping had a nested all-pairs comparison of TV title keys. The new prefix
  index only visits keys with a matching 2+ token prefix and retains the prior order
  for exclusion-aware union calls. Regression tests compare the matching candidate
  lists against the reference all-pairs algorithm.
- TMDB and MangaBaka title normalization now use bounded 8,192-entry caches because
  catalog matching repeatedly reuses the same aliases across candidates.
- The MangaBaka fuzzy-title matcher now uses the optional Rust helper for short pairs.
  It falls back to Python's standard library when the right-hand string reaches 200
  characters so default autojunk behavior and match scores remain unchanged.
- New tests cover exact series-candidate parity, normalizer-cache hits, short-title
  matching parity and long-string autojunk compatibility.

## Indexed bundle-exclusion benchmark

Run from the repository root:

    python experiments/benchmark_series_exclusions.py --component-sizes 100 250 500 1000 --iterations 7 --json-out "$env:TEMP\nekotrack-series-exclusions.json"

This compares the prior component cross-product exclusion scan with an undirected
neighbor-index check when the tested components have no matching excluded pair. It
verifies identical decisions before timing and reports median/p95 and speedup ratio.
The fixture is intentionally a worst-case absence check for the old scan, uses only
synthetic member sets, and does not read the user's database. CI results are pending.

## Third-pass Python audit

Both search-result grouping and local-library grouping used the same correct but
potentially expensive nested loop to check whether any user-defined excluded pair
crossed two components. The new helper checks excluded neighbors from the smaller
component instead. Randomized tests compare the decision with the original nested
scan, and existing grouping tests continue to cover transitive exclusions.

This is a Python data-structure optimization, not a Rust candidate; optimizing it in
Python keeps the behavior easy to test and avoids native-call overhead for a small
set-membership operation.

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

The Phase A CI matrix passed on Windows and Linux with Python 3.11 and 3.14 for the
previous ranking/native-similarity implementation. The current second-pass audit adds
series-prefix benchmarking and expanded parity tests; its CI results are pending.
The previously uploaded synthetic benchmark artifacts reported exact ranking and
similarity output parity.

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


## Batched bundle Work Details database reads

Run from the repository root:

    python experiments/benchmark_bundle_details.py --work-counts 5 20 50 --iterations 5 --json-out "$env:TEMP\nekotrack-bundle-details.json"

The benchmark compares the former per-work Characters, Staff and Relations readers
with the batched readers. It checks exact output parity before recording median/p95
timings and SQLite connection counts. It uses a temporary synthetic database and
makes no external API calls or reads from the user's database.


## Batch-reader test boundary

Bundle character aggregation tests mock `_load_bundle_character_rows`, the boundary
that now supplies work-specific rows. They still verify role precedence, member-order
independence and `sqlite3.Row` compatibility; SQL parity and connection-count behavior
are covered separately by `tests/test_database_bundle_queries.py`.


## Batched Work Details readiness check

The Work Details preload readiness check is included in
`experiments/benchmark_bundle_details.py`. It compares the former per-work cache/work/
episode-existence checks with the batched helper, verifies exact output parity, and
includes the readiness read in its connection counts. The benchmark uses only
synthetic SQLite data.


## Batched bundle appearance overrides

Search and Library grouping now load presentation overrides for all multi-member
groups in one set-based read, instead of opening one database connection per bundle.
The single-bundle accessor retains its anchor-selection behavior. Tests verify title/
cover application, a 1,200-ID query spanning chunks, and correct override selection.
`experiments/benchmark_bundle_details.py` now compares per-bundle and bulk override
reads along with the other bundled Work Details database operations.


## Large-ID bundle write paths

Write paths that take an entire library bundle now chunk their `IN (...)` reads and
deletes while keeping one connection and one transaction. Bundle-member removal
performs chunked manual-link deletion and batches the expected pairwise exclusions.
`tests/test_database_bundle_queries.py` stress-tests these operations using 1,200
synthetic work rows.


## Reverse-edge indexes for Library grouping

Schema initialization adds non-destructive `IF NOT EXISTS` indexes on the reverse
endpoints of work relations, manual links, bundle exclusions and automatic bundle
memberships. The corresponding test verifies their presence and checks
`EXPLAIN QUERY PLAN` actually selects each index on the targeted lookup.


## Large episode catalogs

Episode pruning keeps its simple `NOT IN` query for up to 400 valid episode numbers.
Larger verified catalogs use a temporary keep table and `NOT EXISTS` deletes rather
than building an unbounded SQL parameter list. The database regression fixture checks
a 1,200-episode replacement including stale reminders and progress normalization.


## Work Details staff-pagination state

The "load more staff credits" decision now batch-reads per-work saved staff counts and
persisted AniList link/page metadata rather than opening multiple connections per
bundle member. The existing per-work fallback remains available on read failure.
Parity and synthetic benchmark coverage compare the old and batched output.


The staff-pagination batching keeps linked AniList ID lookups limited to negative
local IDs, as the former UI path did, and has an integration test for load-more
decisions and resume-page handling.


## Relation-discovery failure isolation

Failed AniList relation batches no longer recursively explode into individual requests.
AniList and negative local MangaBaka IDs are fetched independently, so a shared AniList
failure does not block local provider results. The existing bounded discovery loop
controls retries; tests verify request counts and mixed-provider isolation.


## Search relation readiness queue

The FIFO queue in `has_pending_relation_enrichment` now uses `deque.popleft()` rather
than `list.pop(0)`, keeping traversal linear in queue operations. The new synthetic
benchmark compares the old and new queue paths at large frontier sizes; it explicitly
measures queue overhead only and makes no whole-app performance claim.


## Work Details episode snapshot

The episode-section worker now loads the selected work, saved episode rows and TMDB
catalog-version metadata using one SQLite connection. It reuses the selected work's
already-loaded TMDB ID/season fields rather than querying the same table again.
Alternate titles remain a conditional read when catalog refresh is necessary.
The new benchmark compares exact legacy outputs and connection counts on synthetic
episode catalogs up to 5,000 rows.


## Watched-checkbox progress updates

Episode checkbox changes now use the watched/total counters returned by the database
write transaction rather than opening another connection and loading all episode rows
just to recalculate those same counters. A worker test asserts the duplicate read stays
removed.


## Batched episode-thumbnail path writes

The background image-cache worker now persists cached local paths in batches of up to
12 instead of opening a SQLite connection and committing once per image. It flushes
already-downloaded images when cancellation stops the queue. Regression tests cover
normal batches, partial cancellation, invalid/missing episode rows and completion
signals. Run `experiments/benchmark_episode_thumbnail_writes.py` to compare legacy
per-image writes with batched SQLite-only persistence on synthetic data.


## Small-to-large series component merges

Search and Library grouping now keep the larger union-find component as the root,
avoiding repeated copies of large member sets on adverse merge orderings. Library
snapshot IDs follow the selected root. A deterministic stress test checks identical
component partitions, and `experiments/benchmark_series_union_by_size.py` measures
the isolated union/set-merge cost.


## Batched episode catalog upserts

Episode metadata refreshes now batch the existing-thumbnail reads in 400-ID chunks
and persist normalized updates with one `executemany` call. Existing local cached
images are still preserved; duplicate input entries retain their prior sequential
semantics. `experiments/benchmark_episode_catalog_upserts.py` compares saved state,
thumbnail SELECT counts, median/p95 latency and connection counts on synthetic data.


## Batched staff snapshot cleanup

Replacing a staff snapshot now checks old person candidates with a bounded set-based
delete, retaining anyone still referenced by any work's staff credits or the global
voice-actor association table. A regression test verifies orphan deletion and shared
staff/cast retention.


## Batched work-import persistence

`save_anime` now uses `executemany` for alternate titles, studio records/work links,
related-work metadata and outgoing relations. Input-order conflict behavior and the
existing validation gates are retained. A focused test covers duplicate records and
the `COALESCE` preservation rules for fields omitted by a later relation edge.


## Batched chapter/volume metadata upserts

Reading-item metadata imports now use one prepared batch for chapter or volume rows
instead of calling `execute` for each item. The upsert only changes titles, so saved
read-state remains intact. Test coverage exercises parsing, fallback numbering and
duplicate item numbers.
