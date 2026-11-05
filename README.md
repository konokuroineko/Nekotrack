# NekoTrack

A local-first Windows desktop tracker for anime, manga, and light novels.

NekoTrack brings your watch/read library, progress, franchise bundles, discovery, and work details into one desktop app. Your saved library and progress live in a local SQLite database; online catalogs supply search results and optional metadata.

**Current stable release:** [v1.0.0](https://github.com/konokuroineko/Nekotrack/releases/tag/v1.0.0)

## What it does

### Library and tracking
- Keep anime, manga, manhwa, manhua, one-shots, and light novels in one local library.
- Track anime episode progress and watched states.
- Track manga chapters and light-novel/manga volumes. Local placeholders keep progress usable when a provider has no item-level catalog.
- Save ratings, notes, favorites, and custom display titles/covers.
- Group related entries into series bundles, with manual links, exclusions, custom bundle identity, and member controls.

### Catalogs and work details
- Search AniList and MangaBaka through a combined search flow.
- Filter by media type/format, year, season, score, genres/tags, and provider metadata where available.
- View AniList characters, voice actors, staff, studios, and related works.
- Use TMDB as an optional source of episode metadata and artwork.
- Keep provider payloads and local progress separate so an upstream refresh does not become the source of truth for your progress.

### Discovery and desktop experience
- Get personalized recommendations and give feedback that influences future suggestions.
- View upcoming episodes and manage release reminders.
- Browse character, voice-actor, and production-staff profiles and save profile favorites.
- Choose a theme and light mode; customize poster size, spacing, text size, corner radius, animations, and startup behavior.
- Export your saved titles and tracking progress to UTF-8 CSV, and export a redacted diagnostics report when troubleshooting.
- Use the Windows installer or portable executable, with stable/preview update channels and rollback support.

## Install

1. Open the [v1.0.0 release page](https://github.com/konokuroineko/Nekotrack/releases/tag/v1.0.0).
2. Download **NekoTrack-Setup-1.0.0.exe** for a normal installation, or **NekoTrack.exe** for the portable build.
3. Launch NekoTrack and complete the setup wizard.

The installer keeps application files separate from your user data. Updating or reinstalling should not remove your library.

## Run from source

NekoTrack is a Python/PySide6 application. The CI test matrix currently exercises Python 3.11, 3.12, and 3.14 on Windows and Ubuntu.

From the repository root:

~~~powershell
python -m pip install -r requirements.txt
python main.py
~~~

To run the regression suite:

~~~powershell
python -m unittest discover -s tests -v
~~~

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full validation commands and development notes.

## Data, privacy, and network use

By default, NekoTrack keeps its application data under **%APPDATA%\NekoTrack**. This includes the SQLite file **anime_tracker.db**, cached artwork under **data/images**, logs, and update-recovery files. Older source/portable data is migrated into the per-user location on startup when applicable. The **NEKOTRACK_DATA_DIR** environment variable can override the data directory for isolated testing.

Your library and watch/read progress are local. Online search and fresh metadata requests contact the selected catalog providers; NekoTrack does not currently sign in to an AniList account or synchronize a private AniList/MAL list. It does not currently provide multi-device cloud sync.

The app's diagnostics export is for troubleshooting logs. It deliberately excludes the library database and artwork; it is **not** a library backup.

## Known limitations

- Windows is the supported desktop distribution target. CI also tests on Ubuntu, but that does not mean a supported Linux desktop package exists.
- AniList is the primary source for anime and relationship data. MangaBaka enrichment and volume collections vary by title, and MangaBaka's API/schema may change.
- Chapter and volume catalogs are not complete for every work. NekoTrack keeps local progress and uses placeholders when provider item records are missing.
- Characters, voice actors, and staff depend on the metadata AniList provides.
- CSV export is available, but there is no full library backup/restore or general-purpose import workflow yet. The updater's rollback snapshot protects an application update; it is not a portable user-data backup.
- There is no account-based cloud sync, social feed, plugin system, or mobile companion today.
- The interface is English-only at present.

See [the roadmap](docs/ROADMAP.md) for the prioritized work list and [the user guide](docs/USER_GUIDE.md) for current workflows.

## Data attribution and terms

NekoTrack's source code is MIT-licensed. That license does not grant ownership of catalog data, artwork, or other third-party content.

MangaBaka asks API users to attribute MangaBaka and upstream metadata providers. MangaBaka states that its original data is licensed under CC BY-NC-SA 4.0 for personal/non-commercial use with attribution; data from AniList, Kitsu, MyAnimeList, MangaUpdates, Anime-Planet, Shikimori, and other providers remains subject to each provider's own terms. Review those terms before redistributing data or using it commercially.

- [MangaBaka API documentation and rate limits](https://mangabaka.org/data/api)
- [MangaBaka database, providers, licensing, and attribution](https://mangabaka.org/data/database)
- [MangaBaka title variants](https://mangabaka.org/pages/announcements/15-titles-v2)
- [AniList API documentation](https://docs.anilist.co/)
- [TMDB API documentation](https://developer.themoviedb.org/docs)

## Project documentation

- [User guide](docs/USER_GUIDE.md)
- [Architecture and refactoring plan](docs/ARCHITECTURE.md)
- [Prioritized roadmap](docs/ROADMAP.md)
- [Contributing and test instructions](CONTRIBUTING.md)

## License and development

NekoTrack's source code is released under the MIT License; see [LICENSE](LICENSE).

NekoTrack has been developed with assistance from AI coding tools, including GitHub Copilot and OpenAI ChatGPT. The project is maintained and reviewed by its owner.
