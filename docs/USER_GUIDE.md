# NekoTrack user guide

This guide describes the workflows available in the v1.0.0 Windows release. Some screens may change as the staged QML interface work is completed.

## First launch

1. Install NekoTrack using the setup executable, or launch the portable executable.
2. Complete the setup wizard and choose a theme.
3. TMDB is optional. A TMDB Read Access Token can improve episode metadata when AniList does not provide suitable episode details; it is not required for basic library tracking.
4. Open Search to find a work and add it to your Library.

## Search and catalogs

NekoTrack combines AniList and MangaBaka search results. AniList is the main source for anime and franchise relationships. MangaBaka adds manga/novel catalog coverage and metadata such as alternate titles, publishers, authors, artists, licensing, and published-volume records when available.

Use the media type/format and provider filters to narrow results. Provider metadata is not guaranteed to exist for every title. An unavailable MangaBaka match does not prevent an AniList result or saved local progress from working.

## Your Library

The Library is local to this device. You can keep a work in your collection, change its tracking status, and use its detail page to view metadata and progress.

Related works can be grouped into bundles. Bundle controls let you adjust which members belong together and customize the displayed title and cover. Manual links and exclusions are available when provider relationships are incomplete or do not reflect how you want your collection organized.

## Tracking progress

- **Anime:** use the episode list and watched-state controls. Episode titles, descriptions, air dates, and thumbnails depend on the available AniList/TMDB catalog data.
- **Manga and light novels:** use chapter or volume progress. When the provider has no item-level list, local progress placeholders let you record counts without inventing provider records.
- **Bundles:** progress belongs to individual works/members; the app can display the aggregate for a bundle. Check the member being edited when a bundle contains multiple seasons or editions.

Local progress is the source of truth. A metadata refresh should not be treated as an instruction to reset progress.

## Home, recommendations, and calendar

Home provides continue-tracking and recommendation content. Recommendation feedback is saved locally and can influence future ranking. Upcoming episode information and release reminders depend on the catalog schedule data available for the selected works.

## Characters, staff, relations, and favorites

Work details can show characters, voice actors, production staff, and related works. Select a person or character to open its profile. Profile favorites are available separately from work favorites.

These sections depend on provider metadata and network access when information has not yet been cached. A missing record may mean that the provider has not supplied it, not that the person or relationship does not exist.

## Updates and troubleshooting

Stable updates are checked through the GitHub release feed. Preview updates are intended for testing, not normal use. The updater saves recovery material before replacing an installed executable and Settings can restore the previous application version.

Use **Settings → Data & Storage → Export diagnostics report** when reporting a problem. The report combines retained logs and is intended for troubleshooting. It excludes the library database and cached artwork; review its contents before sharing.

## Where your data lives

The default user-data directory is:

~~~text
%APPDATA%\NekoTrack
~~~

The SQLite database is **anime_tracker.db**. Cached artwork is under **data/images**. Logs and updater recovery files are stored in the same user-data area. An older source/portable data folder is migrated to the per-user location on startup when the new database does not yet exist.

For isolated testing, the **NEKOTRACK_DATA_DIR** environment variable can point the app at a separate data directory.

### Manual safety copy

NekoTrack does not yet have a complete in-app library backup/restore workflow.

To make a manual copy of the database and cached artwork:

1. Close NekoTrack completely.
2. Copy the entire **%APPDATA%\NekoTrack** folder to another drive or a safe location.
3. Keep the copy separate from the live folder. Do not edit the SQLite database while NekoTrack is running.

This copies the app-data files, including the database and artwork. Qt-managed application preferences are stored separately from this folder, so this manual copy is not a complete profile export. The updater's rollback snapshot is also not a substitute for a user backup.

## Current limitations

- There is no general AniList/MAL list import or export, CSV library export, or one-click full-profile backup/restore yet.
- There is no account-based multi-device synchronization.
- MangaBaka volume and relationship coverage varies by work; local placeholders cover missing item-level tracking but do not create real publisher catalog metadata.
- The supported desktop distribution is Windows. An Ubuntu CI job is for automated validation, not a supported Linux package.
