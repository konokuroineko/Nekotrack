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
- TMDB and MangaBaka title normalizers now use bounded, 16,384-entry caches to avoid
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
  steps now have bounded caches (16,384 entries each).
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


## Fifth-pass database audit — Work Details preload readiness

The explicit Work Details preload path used to open separate SQLite connections for
each member's character-cache flag/role completeness, work row, and saved-episode
existence. A new `get_bundle_detail_readiness` helper now reads the same facts with
three set-based queries over bounded ID chunks and one connection. It deliberately
does not load episode content; the existing episode section worker still owns that.

Parity tests compare the batched map with the former per-work readers, including
missing work rows, zero-episode works, absent episode snapshots, and character rows
with legacy NULL roles. The synthetic bundle-details benchmark also compares this
readiness path and reports the combined connection reduction. This remains an
isolated database benchmark rather than an app-wide speedup claim.


## Sixth-pass optimization — batched bundle-appearance overrides

Search grouping and Library grouping applied presentation overrides one bundle at a
time. For result sets with several multi-member bundles, that meant one database
connection/query per group. They now collect all member IDs, fetch matching override
rows once in bounded chunks, and apply titles/covers from an index. The single-bundle
getter uses the same shared bulk reader, including ordered-anchor semantics.

Added a grouping test that checks the custom title and cover still win with one bulk
fetch, and a database test covering more than one query chunk and anchor precedence.
The synthetic bundle-details benchmark now includes old per-bundle override reads
versus one bulk override lookup, checks output equality, and includes connection
counts in its end-to-end database operation bundle. Whole-app improvement remains
unclaimed until real-library instrumentation is reviewed.


## Eighth-pass large-ID write safety

The large-library read audit also exposed write paths with unbounded `IN (...)`
lists. Character-snapshot invalidation, automatic-bundle membership replacement,
bundle-member removal, and bundle-appearance override save/clear operations now use
bounded chunks on the same SQLite connection and transaction. Removing a bundle
member additionally replaces per-member SELECT/delete/insert calls with chunked
manual-link deletes and one batched exclusion insert. This preserves pairwise
exclusions and the user's other manual links.

The synthetic database tests create 1,200 disposable work rows and exercise these
paths end to end. Assertions verify member snapshots, override identity/cover choices,
manual-link removal and all 1,199 expected exclusions. No production database is
accessed by those tests.


## Ninth-pass schema indexes for Library grouping

The library grouping path repeatedly filters saved relations by either endpoint, and
filters manual links, exclusions and automatic memberships by the non-primary-key
endpoint. The existing composite primary keys only indexed one side of those
queries. Startup schema initialization now creates four `IF NOT EXISTS` reverse-edge
indexes so existing databases gain the query acceleration without data migration or
rebuilding tables. A test checks both the indexes' presence and SQLite's chosen
query plans for the four hot predicates.


## Tenth-pass episode-catalog pruning for very large seasons

`prune_episode_catalog` previously built two `NOT IN` statements with one bind
parameter for each distinct episode number. Ordinary seasons now keep that fast path
when there are at most 400 valid numbers. Larger catalogs use a connection-local
temporary keep table and `NOT EXISTS` deletes, avoiding SQLite's host-parameter limit
without truncating the trusted replacement catalog. Stale watched-state rows are still
removed only after a non-empty, valid catalog is supplied, and retained episode rows
keep their watched state.

The database fixture includes a 1,200-episode replacement catalog with both kept and
stale episode/reminder rows and validates the resulting progress cap.


## Eleventh-pass Work Details staff-pagination state

Before deciding whether to show the staff-credit "load more" action, Work Details used
to count saved staff rows and separately read AniList pagination metadata for each
bundle member. A new `get_bundle_staff_page_state` helper retrieves per-work staff
counts, linked AniList IDs and page info in one connection with bounded queries.
Work Details retains the old per-work fallback if this combined read fails, as well
as the existing negative-ID link resolution and legacy no-page-info rule.

Parity tests and the synthetic bundle-details benchmark now include this path, using
work/credit fixtures only and no external APIs.


## Work Details staff-state parity follow-up

The batched reader fetches linked AniList IDs only for negative local IDs, matching
how the former UI path used that metadata. Positive AniList work IDs skip that extra
payload, while all members still share the same page-info/staff-count queries. An
integration test now confirms one batch call, preserves the "has next page" and
legacy saved-count rules, and verifies next-page counters only move forward.


## Twelfth-pass relation-discovery failure isolation

Search relation discovery previously recursively bisected any failed provider batch until it retried individual IDs. A shared AniList timeout/429/TLS failure could therefore fan one failed batch into many more requests. The cache helper now requests positive AniList IDs and negative local MangaBaka IDs independently, caches any valid returned rows, and logs a compact structured event for a failed group. It leaves transient retrying to the existing bounded discovery loop instead of recursively generating single-item requests.

Regression tests assert one request per failing AniList group and verify that an AniList outage no longer blocks valid negative MangaBaka IDs in the same discovery frontier.


## Thirteenth-pass Search readiness traversal

`has_pending_relation_enrichment` used a Python list as a FIFO queue and removed each
item with `pop(0)`, shifting all remaining frontier entries each iteration. It now
uses `collections.deque.popleft()`, preserving FIFO order and the prior early-return
and visited-item behavior while avoiding repeated array shifts.

Added an exact-behavior regression against the former implementation on a 2,500-item
frontier and a check for uncached related placeholders. A synthetic queue-overhead
benchmark compares the old and new traversals at 1,000–20,000 items. It reports the
queue component only, not whole-app or network speedup.


## Fourteenth-pass Work Details episode snapshot

The initial episode-section worker previously opened separate SQLite connections for
the selected work row, saved episodes and TMDB catalog-version metadata, then could
open more connections for the selected work's mapping and alternate titles. Added
`get_episode_section_snapshot` to read the work row, episodes and optional catalog
metadata on one connection. The existing nonfatal catalog-metadata failure is retained
as a returned error for the UI to log; a missing work returns the same empty state.

The worker consumes the snapshot and uses TMDB mapping fields already present in
`works.*`, eliminating a redundant mapping connection. Alternate titles remain a
conditional lookup only when the catalog needs refresh. Database parity, UI worker
integration and a synthetic SQLite benchmark measure exact data equivalence and
connections per read.


## Fifteenth-pass watched-checkbox progress reads

`set_episode_watched` already recalculates and returns the watched count and total
inside the database transaction. `EpisodeProgressWorker` ignored that result and
opened another connection to fetch every episode row and count them in Python after
each checkbox change. The worker now consumes the returned counters directly. Its
progress signal and status/log fields remain unchanged; the full-row read is removed.
A UI-worker regression test verifies the emitted counters and asserts `get_episodes`
is not called.


## Sixteenth-pass episode-thumbnail path writes

Episode image downloads already ran on a worker, but persisting each cached path opened
a new SQLite connection and committed a transaction per episode. Added
`save_episode_thumbnail_paths`, which validates path values, checks target episode rows,
then updates them on one connection/transaction. The image worker flushes at most 12
downloaded paths per batch and flushes pending successes even if cancellation stops the
queue part-way through. Download errors remain per-episode failures; a write failure
marks only that persistence batch failed so the existing retry mechanism can recover.

Tests cover multi-batch completion, cancellation flush, missing episode rows and final
path values. A synthetic benchmark compares old per-episode writes with batched writes,
reporting connection reduction and median/p95 timing while excluding network time.


## Seventeenth-pass series component union cost

Both Search grouping and Library grouping used union-find, but always attached the
right root to the left root. The larger component could therefore be copied repeatedly
into a singleton component when relations arrived in an adverse order. Added a shared
small-to-large root merge helper; it preserves component membership, exclusions and
saved Search-snapshot rules while bounding set-copy work. The library variant moves
the snapshot-ID set together with its component root.

A deterministic 4,096-member regression compares final component membership with the
old merge rule and checks that the stress case no longer repeatedly copies the growing
component. CI also benchmarks merge overhead and counts members moved between sets.
The benchmark isolates this DSU operation; it is not a whole-library speedup claim.


## Twentieth-pass episode catalog upserts

`save_episodes` previously issued a separate thumbnail `SELECT` before each row upsert.
It now gathers valid episode numbers, reads existing thumbnail paths in bounded 400-ID
chunks on the same connection, and persists the prepared rows with `executemany`.
The thumbnail-preservation rule is unchanged: a real local cache file is kept over a
missing or remote provider URL. Duplicate episode-number records continue to apply in
input order, with the later title/description/date updates and the same thumbnail
coalescing behavior.

A regression test covers cached-local-path protection, remote URL replacement,
duplicate entries, invalid episode numbers, watched state and a single connection.
CI benchmarks the old per-episode read pattern against the batched implementation,
checking exact stored-state parity and recording SQL read count and median/p95 time.


## Twenty-second-pass staff snapshot cleanup

When refreshing a complete staff snapshot, the previous code issued one reference lookup
(and sometimes one person delete) for every old staff ID. It now deletes old candidates
in 400-ID chunks using correlated `NOT EXISTS` checks against both `work_staff` and
the legacy global voice-actor association table. This retains people referenced by
another title's staff or voice-actor credits while removing people no longer referenced.

The regression test replaces a work's full staff snapshot and checks three cases:
a truly orphaned person is removed, a staff member in another work is retained, and
a cast-only person is retained.


## Twenty-third-pass `save_anime` persistence batches

The work-import path now batches alternate-title inserts, studio upserts/links, related
work metadata upserts and outgoing relation rows. The original field/edge validation
stays in its existing order; batches execute rows in their input order so a repeated
relation target still ends with the same latest non-null metadata, while prior values
survive missing provider fields. A regression fixture exercises duplicate aliases and
studio IDs, repeated target IDs, multiple relation types and preservation of absent
cover/date/MAL values.


## Twenty-fourth-pass chapter/volume metadata persistence

`save_reading_item_metadata` now prepares normalized reading-item rows in input order
and upserts them using `executemany`. Duplicate item numbers still apply sequentially,
blank incoming titles still leave saved titles intact, and conflict updates do not touch
the `is_read` flag. The regression test covers explicit and fallback numbering, invalid
labels, duplicate chapter numbers and an existing read flag.


## Twenty-fifth-pass character snapshot cleanup

A full character snapshot refresh previously issued repeated SELECT and DELETE calls
for each stale character, its work-scoped voice actors, global actor associations and
orphan people. The refresh now reads the current work-scoped edges once and uses
temporary tables to set-reconcile removed actor pairs and stale character IDs. Global
associations and characters are deleted only when their last valid reference is gone;
people are deleted only when no character-voice-actor or staff reference remains.

Regression coverage refreshes a 41-character cast to an empty complete snapshot,
checks direct SQL execute calls remain bounded, and verifies that shared adaptation
credits survive while truly stale characters/actors are removed and staff-referenced
people are retained.


## Twenty-sixth-pass cleanup benchmark

Added `experiments/benchmark_character_snapshot_cleanup.py` to compare the prior
per-character SQL cleanup with the set-based implementation over 25, 100 and 250
synthetic cast entries. It compares final rows exactly, records median/p95 time and
counts direct `execute`/ `executemany` calls. The benchmark only uses temporary
databases and is attached to the Rust/backend benchmark matrix. Results measure local
snapshot cleanup only, not network/API time or whole-app performance.


## Twenty-seventh-pass Library grouping-state reads

Library grouping used three independent connections to read manual links, exclusions
and Search's saved automatic-membership snapshots, in addition to reading the work
rows and relation graph. Added `get_library_bundle_grouping_state` to retrieve those
three datasets in one connection, retaining their exact row sets and ordering and
keeping ID lists chunked at 400 values. `get_library_series` now reuses that state for
component exclusions, saved membership grouping and explicit manual-link joins.

The database regression test compares the combined result against all three former
readers and asserts one connection. The CI synthetic benchmark covers 100 to 5,000
works, checks exact output parity, and records time plus connection counts.


## Twenty-eighth-pass bounded Search relation cache

The process-wide relation graph cache previously grew for every unique item encountered
through Search, Library refreshes and Work Details discovery. It is now an LRU cache
limited to 5,000 relation records, releasing older graphs as new ones arrive. Batch
results are also retained in a per-call map until returned, so eviction during a large
batch cannot silently drop results from the current discovery pass.

Regression tests verify recency promotion, oldest-entry eviction and exact return of
all fetched rows even when a deliberately small test cache evicts an item mid-batch.
This pass limits memory growth; it does not claim a CPU speedup.

## Twenty-ninth-pass episode progress writes

Bulk progress updates previously reset every episode to unwatched and then executed a
separate UPDATE for every selected episode number. They now use one set-based UPDATE:
small selections use a bounded CASE/IN expression, while larger selections are loaded
into a temporary keep-set table in 400-ID multi-value chunks. Both paths preserve the
old rule that unselected episodes become unwatched, including missing/noncontiguous IDs.

Both single-episode and bulk progress updates now calculate total and watched counts in
one aggregate query and update the library row directly instead of first querying whether
that row exists. Added a 600-episode regression test that verifies watched-state parity,
one episode UPDATE, bounded temporary-table inserts, a single aggregate count query and
the single-episode toggle's matching counter behavior.

## CI-discovered database consistency fix

A branch audit caught that `work_detail_page.py` imported `prune_episode_catalog` while
the current branch's `database.py` no longer defined it. Restored the function with the
intended large-catalog temporary keep-set implementation; catalogs up to 400 numbers use
the simple `NOT IN` path, while larger catalogs load the keep-set in bounded chunks and
delete stale episodes/reminders without exceeding SQLite's parameter limit. Empty or
invalid catalog responses still never prune saved data.

Two fixture/test defects found by the same CI run were also corrected: the temporary
episode table now has the production `(work_id, episode_number)` unique constraint needed
by the UPSERT, and the character snapshot cleanup test imports `unittest.mock.patch`.
The PR stays draft until the full CI run for the repaired head completes.

## Thirtieth-pass reading-progress round trips

Reading-progress reads previously issued two SELECT statements to obtain the durable read
count and the highest stored chapter/volume number. The same connection now retrieves
both through one SELECT with scalar subqueries. Saving a numeric progress count now returns
the saved value directly and only queries the highest stored item number when no positive
total hint is available; it no longer closes and reopens SQLite just to read back its own
write.

A regression test checks that both the write/read-back path and the standalone aggregate
read use one connection, and that the combined SELECT preserves the read count and stored
highest-item total.

## Thirty-first-pass bundled provider metadata reads

Opening reading-media bundles previously opened SQLite once per member while searching for
saved MangaBaka metadata, then opened separate connections for saved volume and news payloads.
Added `get_provider_metadata_batch`, which reads the requested providers in bounded work-ID
chunks using one connection and preserves the existing JSON-object/array validation.

Work Details now uses the batch result while preserving bundle-member priority, the selected
primary work, provider-specific payload types and a per-provider fallback if the combined
read fails. Temporary-database coverage checks 1,200 work IDs, several provider names,
malformed JSON filtering and one connection; a Qt integration test asserts the detail setup
uses the batch reader and performs no per-work metadata reads on the normal path. The existing
bundle-detail benchmark now compares selected work/payload parity and times the old versus
batched metadata lookup as part of its full-run connection-count report.

## Thirty-second-pass TMDB query deduplication

TMDB series/movie matchers now remove exact duplicate title query strings while retaining
first-seen order and preserving distinct spelling/casing variants. The same helper is used
for candidate scoring, so duplicate aliases no longer multiply string-comparison work.
This does not remove the deliberate second series-search pass without an air-date/year
filter; its request parameters differ and preserve the existing fallback behavior.

Regression tests mock exact TMDB result payloads and assert identical selected candidates
with one network lookup for repeated same-title variants. This pass reduces redundant
requests only when input aliases are exact duplicates; it makes no broad API-latency claim.

## Thirty-third-pass recommendation credit profile memory

`get_recommendation_credit_profile` now consumes character, voice-actor and staff query
rows one 400-work chunk at a time instead of retaining three whole-library row lists before
building the output profile. The output still contains the same ordered normalized records;
only transient database-row retention changes.

A regression test populates 401 works to cross a chunk boundary, verifies exact role/language
credit records at both sides of that boundary, and asserts the profile is still loaded with
one SQLite connection.

## Thirty-fourth-pass relation-cache concurrency

The process-wide 5,000-entry relation LRU is now protected by a re-entrant lock. Cache lookup
and LRU promotion happen atomically, iteration uses a stable key snapshot, and insertion/eviction
are synchronized across Search, Library and Work Details workers. The batch loader also uses a
single `get` per cached ID instead of checking membership and then indexing separately, which
could race with eviction.

The deterministic tests now replace the cache object rather than using `patch.dict` to clear a
live shared `OrderedDict`; this avoids mutating the cache while a background worker is iterating
it. A multithreaded regression exercises writes, reads, eviction and iteration together.

The same CI review fixed two test-only defects: the new 401-work credit-profile fixture now uses
unique person IDs instead of colliding with the shared fixture rows, and the thumbnail batching
test no longer mocks the obsolete single-path writer that the worker no longer calls.


## Thirty-fifth-pass cold-start and Work Details readiness profiling

- Added a bootstrap elapsed-time event spanning the initial module-import/startup path, alongside the existing separately timed user-data preparation, QApplication creation, database initialization and MainWindow creation.
- MainWindow now records the duration of the initial UI build and each major page constructor. These timings will show whether app startup is dominated by one expensive page or by the overall setup path before any lazy-loading changes are attempted.
- Work Details now records when a newly opened view becomes fully ready, including elapsed time and whether the view came from the in-process detail cache. The existing shell timing remains separate, so a fast skeleton attachment cannot be mistaken for a fully loaded detail view.
- The three-view detail-widget cache remains intentionally process-local; Qt widget trees are not persisted across launches. The new measurements will help distinguish this expected cold-cache rebuild from slow provider or database work.
- This is profiling instrumentation only. It does not change loading order, persistence, cache policy or provider behavior, and it makes no whole-app speed claim. Validate the timings on the user's Windows source-mode run before selecting the next startup/detail optimization.

## Thirty-sixth-pass Work Details stylesheet reuse

The Windows source-mode diagnostics showed complete Re:Zero detail readiness at about 543–696 ms on a cold open and about 80 ms on a cached repeat. Episode snapshot reads took about 2 ms and the section data workers were in the low single-digit millisecond range; GUI-side widget rendering remained the larger measured part of the detail path. The page also reapplied its large stylesheet on every cold or cached open.

Work Details now applies its initial stylesheet while the page has no populated detail tree. Repeated open calls still check whether the generated stylesheet differs, but Qt's expensive `setStyleSheet`/child-repolish path is skipped when the theme has not changed. The existing theme-refresh path still updates styles when colors change. This is a targeted UI optimization; the next Windows diagnostic run should confirm the real-world gain.

## Thirty-seventh-pass concurrent Work Details section loading

The latest Windows source-mode trace measured the Re:Zero bundle at about 594 ms from open to complete detail readiness and about 57 ms on an in-process cached repeat. In that cold trace, the Characters, Staff and Relations widget builds took about 44 ms, 27 ms and 56 ms; the sections were queried serially, with each next query scheduled only after the previous section was rendered. Prior runs varied, so these numbers do not establish a repeatable speedup from the stylesheet pass.

The deferred detail path now starts the three independent section-data workers together. Each result still replaces its own skeleton in its original layout position. Detail readiness is recorded only after all three skeletons are gone, and the cacheability checks still require successful section and episode completion. A focused UI regression test verifies all three jobs are scheduled together, run off the GUI thread, and leave the view cacheable only after rendering finishes.

No real-world speed claim is made until a fresh Windows diagnostic run measures this change.

## Thirty-eighth-pass lightweight cold-open placeholders

The latest Windows diagnostic trace measured a cold Re:Zero Work Details open at about 324 ms to full readiness, with the visible shell attached after about 177 ms; a cached repeat took about 54 ms. The active path was synchronously constructing 16 detailed metadata placeholder cards plus four episode placeholder cards before attaching the page, and the metadata placeholders were then replaced by the real sections.

Normal deferred navigation now uses lightweight section-heading placeholders and a text-only episode loading state. The explicit non-deferred fallback/preload path retains its full card-shaped placeholders. Final detail cards, section ordering, and theme styling are unchanged. A focused regression test verifies that the active path stays lightweight while the fallback path keeps its full skeletons.

No speedup is claimed until a fresh Windows diagnostic trace measures this pass.

## Thirty-ninth-pass lazy card network managers

Character, Staff and Relation cards previously allocated a `QNetworkAccessManager` in every card constructor, including cases where artwork was already available from a local cache path or there was no remote image URL. The managers now initialize only when a network request is actually needed. Request completion, image caching and widget-local signal handling remain unchanged.

Added a focused Qt regression test that constructs cards with local cached artwork and verifies they do not allocate network managers. This is an object-allocation reduction only; a new Windows diagnostic run is required before claiming a measurable opening-time improvement.

## Character-snapshot cleanup scale results

The expanded deterministic CI benchmark confirms exact database-state parity while cutting direct SQL calls from 5,502 to 13 at 500 characters and from 11,002 to 13 at 1,000 characters. On Windows/Python 3.14, the 500-character median was 82.325 ms for the per-record reference versus 52.414 ms batched (1.57×); at 1,000, 165.132 ms versus 58.230 ms (2.84×). On Linux/Python 3.14, the corresponding medians were 27.551 ms versus 4.512 ms (6.11×) and 86.933 ms versus 7.977 ms (10.90×).

Small Windows casts were near break-even, but the batched path clearly wins at larger sizes and bounds query-call growth. Keep the current set-based implementation and its exact shared-credit/orphan-cleanup semantics; no further rewrite is justified by this benchmark.

## Fortieth-pass recommendation explanation selection

Candidate credit scoring previously accumulated every matched-credit explanation into a list, even though only the maximum `(boost, explanation)` tuple is returned. It now tracks only the best tuple, builds explanation text only when a credit can match or beat the current best boost, and skips zero-valued entries in the score-aggregation map. The tuple comparison is retained deliberately so equal-score explanations still select the same lexicographically greatest text.

A focused regression test protects that tie rule; existing ranking tests continue to cover candidate scores, saved-creator and favorite-credit explanations, language filtering and deduplication. The ranking benchmark will be checked after CI; no user-visible or end-to-end speedup is claimed without measurements.

## Forty-first-pass batched Release Calendar reads

The Calendar page was loading the library, loading all enabled reminders, then opening another SQLite connection for every anime to fetch every cached episode before filtering to the next 60 days. It now retrieves only saved-anime episodes inside the calendar window in one joined query, with reminder state and work presentation fields included. An additive index on episode air date supports the bounded range query. Python still validates dates after retrieval and performs the same final date/title/episode sorting, so malformed provider dates do not become visible events.

Regression coverage checks a single database connection, library/type/date filtering, reminder state and rejection of invalid ranges. This is a query-count reduction; validate full app startup/Calendar timing before making a whole-app speed claim.

## Forty-second-pass shared Home release query

The Home dashboard preview had the same N+1 episode read as Calendar: it fetched enabled reminders once and then opened a separate SQLite connection for every anime during Home refresh. Home now reuses `get_upcoming_library_episodes`, the same indexed, date-bounded joined query as Calendar. The preview retains its own title fallback, malformed-date guard, 60-day inclusive window, reminder flags and date/title/episode order.

Updated Home regression coverage verifies one batched call and the same visible preview rows. This is a query-count reduction; startup-wide timing should be evaluated separately before claiming a measurable user-facing speedup.

## Forty-third-pass defer hidden Calendar and Favorites refreshes

MainWindow previously constructed Calendar and Favorites with their full initial refresh even though neither is visible on startup; MainWindow refreshes each again when navigating to that destination. These two pages now support an opt-in deferred initial refresh. MainWindow builds only their themed page shells on startup and the existing `_page_changed` handlers load the contents on first open. Direct `CalendarPage()` and `FavoritesPage()` construction keeps its original eager-refresh default for standalone callers and tests.

A UI regression test verifies neither page refreshes during Home startup and each refreshes when navigated to. This removes hidden initial database/render work; whole-startup timing still needs a fresh Windows diagnostics run before quantifying the user-visible benefit.

## Forty-fourth-pass Calendar episode-catalog refresh

The startup episode preloader previously selected only Library anime with zero cached episode rows. A partial, undated, outdated-policy or week-old catalog therefore remained unchanged unless Work Details happened to open that title. A single SQLite candidate query now selects missing catalogs and explicit freshness failures (malformed/incomplete metadata, old matching-policy version, or an expired timestamp). For old databases without catalog metadata, it avoids one-time re-resolving every archived series: a legacy cache is selected only when it has a missing, invalid or upcoming air date relevant to Calendar. Fresh complete catalogs stay out of the queue.

Both Library import and background preload now record the same version, fetch timestamp and completeness metadata used by Work Details. Old matching-policy mappings are re-resolved. A missing AniList start date no longer blocks TMDB lookup, which can use an existing mapping or attempt a title match without a date. Saved episode rows are upserted without overwriting watched state; stale rows/reminders are pruned only when the known expected episode count is met, so an incomplete provider result cannot erase existing progress.

Regression tests cover refresh-candidate selection, one-connection selection, old-policy re-resolution, missing-start-date handling, preserving catalogs when TMDB returns fewer episodes than expected, and refreshing the visible Calendar/Home once after the background batch finishes. CI should confirm this pass before claiming the Calendar refresh path is verified.

## Forty-fifth-pass remove unused Library relation-graph scan

Each Library refresh queried all distinct source/target IDs in work_relations only to write diagnostic counts and a sample. Those values did not participate in the pending-sync calculation, which depends on Library IDs plus the session's completed/failed sets. Removed that whole-table read and its unused log fields while retaining the Library ID query and the actual relation-sync selection. A regression test verifies the plan uses one query and does not touch work_relations merely for diagnostics.

This reduces unnecessary database work; no whole-app speedup is claimed until a real Windows Library-refresh trace is compared.

## Forty-sixth-pass single-connection Library grouping reads

A full Library grouping could open separate SQLite connections for saved manual/exclusion/membership state, cached relation edges, and bundle appearance overrides. The read helpers now accept an optional existing connection, and `get_library_series()` uses one connection for all three. The relation query itself is unchanged, including the <=400-ID single-query path and the large-library rowid-based de-duplication path; standalone helper callers keep their previous self-contained behavior. The grouping method closes the shared connection in `finally`, including when a read or override application fails.

Regression coverage checks grouped title/cover and progress output while asserting one connection for the entire nonempty grouping pass. A separate large-ID test verifies that the relation reader returns the same rows when supplied a connection and leaves that connection open for its owner. This reduces connection churn from up to three connections to one for a populated grouped Library refresh; actual end-to-end timing still needs a Windows diagnostic run.


## Forty-sixth-pass Library grouping read measurements

The green CI matrix's deterministic SQLite benchmark tested 100, 1,000 and 5,000
synthetic Library works on Windows and Linux with Python 3.11 and 3.14. All four
environments returned exactly the same rows. For the state-reader path, connection
factory calls fell from three to one. Median speedup ratios were 1.57–1.77× at 100
works, 1.21–1.42× at 1,000 works, and 1.23–1.36× at 5,000 works. On Windows/Python
3.14, for example, the median at 5,000 works fell from 15.956 ms to 12.043 ms.

These measurements isolate only the three grouping-state reads in a synthetic
database. They do not measure full `get_library_series()`, painting, or a real user
Library, so they are not an end-to-end UI speed claim.

## Forty-seventh-pass bounded series-title normalization cache

`_series_key()` applies several regular-expression substitutions and is invoked from
multiple parts of the relation/grouping path. A bounded 16,384-entry LRU memoizes
the normalized string while preserving prior coercion behavior for `None` and
non-string inputs. The earlier 8,192-entry trial churned on a synthetic 10,000-title
working set, so the bound was raised to fit that case while remaining fixed.

The green Windows/Linux CI matrix (Python 3.11 and 3.14) ran 30,000 normalization
calls for each of 100, 1,000, 5,000 and 10,000 unique titles. Normalized outputs matched
exactly in every case. Observed speedups were 74.1–81.2×, 22.6–23.3×, 5.50–5.57× and
2.83–2.89×, respectively. On Windows/Python 3.14, the 10,000-title median fell from
388.868 ms to 135.904 ms. This measures title normalization only, not full Library,
Search or application speed.

## Forty-eighth-pass allocation-free exclusion neighbor misses

`_components_have_excluded_pair()` previously called `get(member_id, set())` for each
member even when most IDs had no exclusion neighbors, allocating a temporary empty
set for every miss. It now checks the returned neighbor set directly and only calls
`isdisjoint()` for a non-empty set. This preserves exclusion decisions while avoiding
those repeated allocations. The existing randomized cross-product parity tests remain,
with an additional empty-neighbor regression.

The CI benchmark compared the old cartesian baseline, the previous indexed helper
and the allocation-free helper side by side. All four environments returned identical
decisions. Against the previous helper, median time improved 2.24–2.80× for component
sizes of 100–1,000 members per side. At 1,000 members, Windows/Python 3.14 fell from
0.090 ms to 0.039 ms and Linux/Python 3.14 from 0.117 ms to 0.047 ms. These are tiny
per-call savings on a synthetic absence workload; they justify removing the needless
allocations but do not indicate an end-to-end app speedup.


## Forty-ninth-pass Library bundle-preference snapshot

Library grouping now reads only the opt-in bundle settings required by the actual
bundleable formats present in that Library snapshot, and reads each relevant setting
once. The same option snapshot is reused by saved membership, relation compatibility,
and title-grouping checks. TV/TV_SHORT entries still need no opt-in preference, and
calls to `_auto_bundleable()` outside this Library operation retain their original
one-item behavior. A regression test covers Manga, Novel, One Shot, OVA and TV rows
and checks that each relevant preference is read exactly once. CI needs to pass before
this remains; no wall-clock speedup is claimed yet.


## Fiftieth-pass Search bundling preference snapshot reuse

Search bundling already reads the seven opt-in bundle preferences once to include
them in the operation's diagnostic-start event, but previously the relation walker
and grouping stage read them again for candidate entries and graph edges. The same
snapshot is now passed through those stages. If an individual preference lookup
failed during snapshot creation, its `None` value still falls back to the original
getter behavior rather than silently disabling the option. A relation-walk regression
checks that one Search grouping operation reads each preference exactly once. The
Python test matrix (Windows/Linux, Python 3.11/3.12/3.14), Rust parity jobs and
adversarial stress run all passed for this change. The evidence is a bounded getter-call
count, not an end-to-end timing result, so no wall-clock speedup is claimed.


## Fifty-first-pass relation-edge presence fast path

Two branches in relation discovery only need the boolean answer to “does this item
have any valid relation edges?” They previously built a filtered list via
`_search_relation_edges()` and discarded it immediately. The first generator-based
`any()` implementation was slower on empty and short lists. The final helper now
returns immediately for an empty list or a valid first edge. If the first edge is
malformed, it falls back to the original filtered list comprehension to preserve
truthiness without making malformed-only payloads pay for a Python indexing loop.
The actual traversal still uses the filtered list where it needs to iterate edges.

The deterministic synthetic benchmark passed on Windows and Linux with Python 3.11
and 3.14; results and outputs were consistent across all four environments. Relative
to the former filtered-list check, the final fast path measured:

- Empty edge lists: about 1.21–1.53× faster.
- Three valid edges: about 1.49–1.84× faster.
- Ten valid edges: about 2.18–2.71× faster.
- Fifty valid edges: about 5.96–7.29× faster.

For intentionally malformed arrays whose first entry is not a dictionary, timings
were roughly 2–10% slower depending on list size. This is a defensive input path;
normal provider relation arrays are dictionaries or empty. Output parity, Python
regression tests, Rust parity/benchmark jobs, and adversarial stress all passed for
the fast-path revision. These are helper-level synthetic timings, not end-to-end
application speed claims.

## Fifty-second-pass lazy legacy QSettings construction

`ui.preferences.settings()` previously constructed both the current NekoTrack
`QSettings` and the legacy AniTrack `QSettings` on every preferences read, even when
the migration marker already showed that the legacy store was no longer needed. The
legacy object is now constructed only when the one-time migration is pending. This
reduces the common post-migration path from two store constructions to one without
changing the migration copy path.

Regression tests assert that a completed migration opens only the current settings
store and that a pending migration still opens both stores, copies legacy values and
sets the migration marker. This is a deterministic construction-count improvement;
no wall-clock gain is claimed without measurement.


## Fifty-third-pass full synthetic Library grouping benchmark

Added a repeatable CI benchmark for the complete `series.get_library_series()` path.
Unlike the existing SQLite state-reader benchmark, it seeds a temporary synthetic
Library and measures the real grouping function through its row fetch, grouping-state
snapshot, relation reads, component unions, summaries and presentation overrides.
It validates the exact expected four-member bundle sets, every work ID's unique
coverage and two connection factories per refresh (one Library row fetch, one shared
grouping snapshot), and reports cold/warm normalization-cache median/p95 timings at 100, 1,000
and 5,000 works. It also records the top 15 cumulative `cProfile` functions at the
largest requested size, giving the next pass evidence about where grouping CPU time
is actually spent.

The benchmark excludes Qt card painting, actual user data and provider APIs, so its
results are a grouping-path baseline rather than an end-to-end UI refresh claim. Windows
and Linux results are pending for this first full-path run.


## Fifty-fourth-pass bounded season-marker cache

The full Library profile shows `logical_season_count()` and its
`_season_marker()` calls are among the largest cumulative costs during a synthetic
5,000-work refresh. The season-marker parser now memoizes normalized lowercase title
strings in a bounded 16,384-entry LRU. The original parser body and rule precedence
are unchanged, including final/ordinal/word-number/explicit-season/Roman/continuation
handling; coercion still occurs before cache lookup so non-string title-like values
retain the previous behavior.

Regression coverage compares representative marker outputs, checks that differently
cased inputs share a cache entry, and checks the fixed memory bound. The full Library
benchmark already reports cold and warm refresh times, so CI can show whether the
cache provides a repeat-refresh benefit. Keep it only if the matrix passes and cold
behavior does not show a meaningful regression; no speedup is claimed in advance.


The full grouping benchmark now clears both the normalized series-key cache and the
season-marker cache before every cold iteration, and clears both before profiling.
Its JSON field names therefore describe the full normalization-cache state instead of
only the older series-key cache.

## Fifty-fifth-pass single-read media family and format classification

The synthetic full-Library profile showed media-family and bundle-eligibility helpers
repeating type and format normalization in the hot path, including two family
classifications inside every automatic bundleability check. Added a shared helper
returning the normalized family and format, plus a parts-based eligibility helper,
so automatic bundleability, ordinary bundleability and bundle-option lookup each
normalize a row's type and format only once. Existing eligibility rules and
preference decisions are unchanged.

Two regression tests count type and format reads for automatic bundleability and
bundle-option lookup, while existing tests cover TV, TV_SHORT, movie, OVA, ONA,
special, manga, novel, one-shot and ineligible types. The full synthetic Library
benchmark measures cold/warm timing and a refreshed profile; keep this only if the
full test matrix passes without a grouping performance regression.

## Fifty-sixth-pass single-pass Library bundle-option snapshot

The Library settings snapshot previously called the ordinary eligibility helper and
then the option-key helper separately for each row. Even after the media-family
refactor, that normalized type/format twice per row. The snapshot now normalizes
once and passes the normalized parts to small pure helpers, so every Library row is
classified once while building the set of required preferences. A new test counts
field reads across eligible, always-on, and ineligible formats and confirms the
preference values and keys are unchanged.

The media-family refactor passed the full matrix and adversarial stress. Its call
counts fell from 35,000 to 25,000 family classifications and from 161,250 to 111,250
field reads in the synthetic 5,000-work profile. Wall-clock timings varied by CI
runner, so no cross-platform speedup is claimed from that pass. The full synthetic
Library benchmark will measure this additional one-pass snapshot change.

## Fifty-seventh-pass bounded continuation and arc title flags

The 5,000-work profile shows repeated continuation/arc regex predicates inside
logical-season counting. Both checks now normalize the input title once and delegate
to bounded 16,384-entry LRU caches. The predicates and their matching rules are
unchanged; repeated logical-season summaries can reuse the flags, including the
duplicate continuation check that occurs within one summary operation.

Regression tests cover continuation/arc matches and non-matches, None and non-string
coercion, case-normalized cache hits, and each cache's fixed bound. The complete
Library benchmark now clears the series-key, season-marker, continuation and arc
caches before every cold sample and before profiling, with output fields renamed to
title-analysis caches. CI will determine whether the warm path improves enough to keep
this change; no timing gain is claimed in advance.
\n## Fifty-eighth-pass local logical-season title metadata

The full-library profile identified `logical_season_count()` as a substantial cumulative
cost. Its three stages previously re-extracted title text and re-read season-marker /
continuation / arc flags for the same TV member. The function now creates one local
metadata tuple per TV member and reuses it for explicit-marker groups, Part/Cour
relation joins and named-arc checks. The snapshot is local to one summary call, so it
does not persist metadata across mutable provider rows or change relation rules.

Direct tests cover shared explicit season markers, linked Part continuations and the
same-quarter requirement for unnumbered arcs.

## Fifty-ninth-pass paired logical-season benchmark

Added a side-by-side benchmark for the prior logical-season loop and the metadata
snapshot. It compares both implementations in the same process on 1,250 synthetic
four-work bundles (5,000 members), alternates execution order, separately measures
cold and warm title caches, and verifies exact output parity before timing. The
reference uses the original `defaultdict(list)` marker grouping.

All four CI platforms/versions returned identical logical-season counts. Measured
reference → snapshot median timings (milliseconds for all 1,250 groups):

| Platform / Python | Cold: reference → snapshot | Cold speedup | Warm: reference → snapshot | Warm speedup |
|---|---:|---:|---:|---:|
| Ubuntu / 3.11 | 47.543 → 43.902 ms | 1.083× | 15.919 → 13.221 ms | 1.204× |
| Ubuntu / 3.14 | 102.647 → 95.686 ms | 1.073× | 38.009 → 31.964 ms | 1.189× |
| Windows / 3.11 | 88.123 → 81.898 ms | 1.076× | 32.755 → 27.306 ms | 1.200× |
| Windows / 3.14 | 62.846 → 59.197 ms | 1.062× | 24.423 → 20.582 ms | 1.187× |

The paired result supports keeping the snapshot: about 6.2–8.3% faster cold and
18.7–20.4% faster warm on the isolated season-count workload, with exact parity.
This is not an end-to-end Library/UI refresh speed claim. Full regression and
adversarial stress were green on the runtime-change commit; the corrected-reference
benchmark-only commit is running the final full matrix now.

## Sixty-first-pass defer Library database grouping until first use

The October 25 diagnostics file contains nine measured MainWindow UI builds. Their
initial UI-build duration was 286.23–401.92 ms (median 345.26 ms). The Library page
constructor alone took 46.85–155.68 ms (median 83.18 ms) across those runs. Inspection
showed that constructing LibraryPage immediately called refresh(), which synchronously
queries and groups all saved works, creates the Library cards, and starts relation sync
even though the app initially displays Home.

MainWindow now builds the Library's lightweight shell without refreshing its data.
The existing navigation callback refreshes it when Library is first opened; later visits
keep their existing refresh behavior, and direct LibraryPage callers still default to
the original eager refresh unless they explicitly request deferral. This removes the
Library's database grouping and card creation from initial window construction without
changing the default opening page or the normal Library refresh path.

A UI regression test verifies Library is not refreshed during startup or Calendar/Favorites
navigation, and is refreshed when Library is opened. The timings above are the pre-change
baseline from the user's diagnostic export; a new local diagnostic export is still needed
to quantify actual startup improvement. Automated CI must pass before this change is
considered verified.

## Sixtieth-pass compiled series-title regex production change

The paired benchmark found that reusing compiled regex objects reduces elapsed time
for the isolated title-normalization sequence while producing exactly the same keys.
Production _cached_series_key() now uses module-level compiled patterns for all seven
substitutions and the final character cleanup. The bounded cache, input coercion,
pattern order and replacement strings remain unchanged.

A regression test compares the production output against the previous re.sub()-based
sequence across season, final-season, Roman-numeral, Part/Cour, punctuation, unusual
input-type and empty-value cases. The benchmark matrix measured the 5,000-title
workload at 47.044–74.972 ms with compiled patterns versus 56.117–94.558 ms with
re.sub(), corresponding to about 16–23% less elapsed time across Windows/Linux and
Python 3.11/3.14. At 10,000 titles the reduction was about 15–23%.

This is an isolated normalization result, not an end-to-end app speedup. The regular
Python regression matrix and adversarial stress tests must pass before Phase A is
considered ready.