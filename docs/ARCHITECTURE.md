# NekoTrack architecture

This document describes the current implementation and a safe direction for modularization. It is not a claim that the refactor has already happened.

## Current runtime shape

NekoTrack is a Python/PySide6 desktop application backed by SQLite. External metadata is fetched through AniList, MangaBaka, and optional TMDB integrations. The app has both the established Qt Widgets interface and a staged Qt Quick/QML shell; the Python layer remains responsible for data access and application behavior.

### Main modules

| Area | Current responsibility |
|---|---|
| main.py | Startup, per-user data directory, application identity, updater integration, setup, and shutdown |
| api.py | AniList GraphQL operations, TMDB search/episode/artwork enrichment, MangaBaka API/cache/normalization |
| catalog_search.py | Coordinating catalog searches and combining/deduplicating provider results |
| database.py | SQLite connection/schema setup and persistence for works, library status/progress, episodes, reading items, credits, provider metadata, bundles, favorites, and recommendations |
| series.py | Series identity normalization, relation grouping, bundle membership, manual overrides, and exclusions |
| recommendation_engine.py | Candidate ranking and recommendation scoring |
| image_cache.py | Shared artwork caching support |
| library_export.py | UTF-8 CSV export of saved works and local progress |
| updater.py and installer/ | Release checks, staging, verification, rollback, and Windows packaging |
| ui/main_window.py | Existing Qt Widgets host and application navigation |
| ui/pages/ | Existing feature pages, including the large Work Details implementation |
| ui/qml_app_bridge.py | Application-facing QML bridge, page state, workers, settings, search, recommendations, profiles, and progress actions |
| ui/qml_bridge.py | QML Library model, image URL/path handling, and QML image-cache support |
| ui/qml/ApplicationShell.qml | QML application shell and page layouts |
| ui/preferences.py | Qt-managed preferences and migrations |
| diagnostics.py | Structured local diagnostics and report export |

## Data flow

### Search
The UI requests a search through the Python bridge or existing page. catalog_search.py coordinates the available providers. Provider data is normalized and deduplicated before results are displayed. Adding a provider should not require direct HTTP code in a QML component or page widget.

### Library and progress
The database stores canonical work records and user-specific tracking separately. The user_library table owns list status, progress counters, rating, notes, and timestamps. Episode-level data is stored separately from manga/novel reading item records. Local progress must remain authoritative even when catalog refreshes are partial or providers change their schema.

### Series and bundles
series.py derives series identity and groups related works. database.py persists automatic memberships, manual links, exclusions, and display overrides. A missing provider relation must not erase a user's manual organization.

### Work details and profiles
Work detail and profile views request provider data through workers, persist reusable snapshots in SQLite, and render cached/local state. Network and image work must not block the UI thread. A failed optional metadata request should not make the basic work detail or progress controls unusable.

### Recommendations
recommendation_engine.py ranks candidate works. database.py stores local recommendation history and feedback. UI code should collect feedback and display ranked candidates, not own scoring policy.

## Current architectural pressure points

The current code has several unusually large mixed-responsibility modules:

- api.py combines three provider integrations and their normalization/cache/network logic.
- database.py combines schema initialization with many persistence domains.
- ui/pages/work_detail_page.py mixes page composition, detail workers, episode synchronization, bundle controls, and several detail sections.
- ui/qml/ApplicationShell.qml currently contains the overall shell and multiple major page layouts in one QML source file.
- ui/qml_app_bridge.py is a broad bridge for many unrelated page operations.

Large files are not automatically bugs, and splitting them without boundaries can make the project worse. The problem is that provider policy, domain behavior, persistence, workers, and presentation are difficult to test and change independently.

## Recommended target structure

A gradual target could look like this:

~~~text
nekotrack/
  domain/
    works.py
    series_identity.py
    progress.py
    recommendations.py
  providers/
    anilist.py
    mangabaka.py
    tmdb.py
    common.py
  repositories/
    works.py
    library.py
    episodes.py
    reading_progress.py
    credits.py
    relations.py
    bundles.py
    recommendations.py
  services/
    catalog_search.py
    library_import.py
    image_cache.py
    backup_restore.py
  ui/
    bridges/
      application.py
      library.py
      details.py
      profiles.py
    pages/
      work_detail/
        view.py
        workers.py
        episodes.py
        credits.py
        relations.py
~~~

The names are a proposed destination, not existing files.

## Safe migration sequence

1. **Characterize behavior first.** Add tests around existing public functions, SQLite migrations, provider request limits/cancellation, bundle identity, progress preservation, and image-cache paths.
2. **Create provider modules.** Move one provider at a time. Keep api.py as a compatibility facade that re-exports its public functions until all imports have migrated.
3. **Split persistence by domain.** Keep one connection/transaction policy and the existing schema. Move repository functions in groups while database.py re-exports the stable API.
4. **Split Work Details.** Move workers, section builders, and dialogs into focused modules. Keep the existing WorkDetailPage import path as a compatibility facade during migration.
5. **Split the QML shell and bridge by route/domain.** Keep QML page components declarative and small; keep data orchestration in Python services and repositories.
6. **Remove compatibility facades only after repository-wide import checks and tests prove no callers remain.**

## Non-negotiable data rules

- Never drop user data to simplify a refactor.
- Keep schema changes additive and migration-driven.
- Use transactions for multi-table writes and the SQLite backup API for consistent snapshots.
- Preserve local progress, custom bundle relationships, favorites, and recommendation feedback across upgrades.
- Keep external IDs provider-qualified; do not treat a MangaBaka ID as an AniList ID.
- Handle absent provider metadata as incomplete/unknown, not as proof a local record is invalid.
- Keep workers cancellable and shut them down before destroying the UI/bridge objects they reference.
- Preserve a correct pure-Python fallback when optional Rust acceleration is not installed.
