# NekoTrack roadmap

This is a priority order, not a promise of release dates. The guiding product decision is to stay local-first: a user should be able to keep and update a library without creating a NekoTrack account.

## P0 — Finish the current interface migration safely

- [ ] Complete populated-library testing for the staged QML interface in [PR #102](https://github.com/konokuroineko/Nekotrack/pull/102).
- [ ] Verify artwork loading on detail pages, character/staff/relation sections, Home recommendation pagination, Search, bundles, manga/novel progress, Calendar, and every Settings category on Windows.
- [ ] Verify startup, shutdown, QML-to-legacy fallback, installer packaging, and update/rollback behavior on a clean Windows installation.
- [ ] Keep the migration draft until the actual app has passed those checks.

## P1 — Protect and move user data

- [ ] Add a versioned, portable full-profile backup containing a consistent SQLite snapshot, cached/custom artwork, and exportable application preferences.
- [ ] Add restore preview and validation before touching the live profile; automatically preserve the current profile before restore.
- [ ] Add a lossless NekoTrack JSON export/import for migration between installs.
- [x] Add CSV export for spreadsheet use (Settings → Data & Storage).
- [ ] Add optional AniList and MyAnimeList import/export paths, with explicit duplicate matching and conflict previews.
- [ ] Document exactly what is included in every export format. Diagnostics export must remain separate from library backup.

A safe full backup should use SQLite's backup API rather than copying an open database file blindly. Restores should validate the archive manifest, hashes, supported schema version, and file paths before replacing anything.

## P2 — Bring manga and light novels closer to anime parity

- [ ] Keep chapter/volume progress editable even when providers have no chapter list or publish incomplete volume data.
- [ ] Improve manual chapter/volume metadata entry and correction.
- [ ] Show whether a total is provider-supplied, user-entered, or unknown.
- [ ] Improve matching and deduplication for editions, translations, omnibus releases, and linked manga/novel adaptations.
- [ ] Preserve per-member progress inside bundles and make the edited member obvious.

## P3 — Modularize without breaking existing libraries

- [ ] Separate AniList, MangaBaka, and TMDB adapters behind a stable provider interface.
- [ ] Split database persistence by domain while retaining database.py compatibility wrappers during the migration.
- [ ] Break Work Details into workers, episode handling, credits, relations, and page composition.
- [ ] Split QML routes and the Python bridge by feature.
- [ ] Keep tests for schema migrations, progress preservation, provider failure, shutdown cancellation, and old import paths throughout the refactor.

Do not do a big-bang rewrite. Each extraction should preserve public function signatures until callers and tests have moved.

## P4 — Improve the daily-use experience

- [ ] Make the first ten minutes clearer: explain catalog differences, how bundles work, what is local, and what requires a network connection.
- [ ] Give users an explicit reason for each recommendation (shared genres, staff, cast, source title, or other evidence).
- [ ] Improve filters and saved views for large libraries.
- [ ] Polish keyboard navigation, focus order, screen-reader names, contrast, and scalable text.
- [ ] Add localization infrastructure before translating individual screens.

## P5 — Decide the platform and sync policy

- [ ] Decide whether Windows-only is a deliberate long-term product choice or whether Linux packaging is worth supporting first.
- [ ] If Linux is pursued, add a real packaged-app smoke test before advertising support; Ubuntu CI alone is not a Linux release.
- [ ] Evaluate macOS only after the desktop packaging and Qt platform behavior are understood.
- [ ] Keep cloud sync out of the default experience. Consider optional encrypted sync only after backup/restore and conflict handling are reliable.

## P6 — Make the project easier to discover and contribute to

- [ ] Add screenshots from the current stable app and a short demo showing the series-bundle workflow.
- [ ] Keep the README, changelog, user guide, and release notes synchronized.
- [ ] Add issue templates and a small, prioritized public backlog.
- [ ] Publish clear release notes with limitations and data-provider attribution.
- [ ] Ask for external feedback only after the installation, onboarding, import, and backup paths are understandable.

## Deliberately not a priority yet

- A NekoTrack account or mandatory cloud service.
- Public social feeds, comments, or friend activity.
- A plugin system before provider boundaries and extension contracts exist.
- A mobile companion before the data export and migration story is dependable.
