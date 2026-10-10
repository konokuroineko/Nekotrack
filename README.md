# NekoTrack

Your personal anime, manga, and novel tracker.

Track what you watch and read, manage your library, and keep your collection organized — all from a desktop app.

## Features

- Search AniList and MangaBaka together in one unified result list, with linked titles deduplicated
- Anime, manga, manhwa, manhua, one-shot, and light-novel searches with provider-aware filters
- AniList anime catalog, relationships, characters, staff, voice actors, and franchise grouping
- MangaBaka-backed manga and novel titles, including English, native Japanese, and romanized titles
- MangaBaka publisher, tag, author, artist, status, licensing, and publication metadata when present; publisher/licensing filters require matching MangaBaka metadata
- Published volume records (including titles, ISBNs, and dates) when MangaBaka has matching collection data
- Local SQLite library and offline watch/read progress
- Chapter and volume checklists; missing upstream item details remain trackable using local placeholders
- Episode progress and watched-state tracking for anime only
- Local cover caching
- Work relationships and franchise connections shown in work details
- Character, voice-actor, and staff information shown in work details
- Configurable dark desktop interface built with PySide6
- Library card sizing, spacing, hover, and resize animation preferences
- Maximized startup preference and scrollable settings page

## Catalogs and fallbacks

AniList remains NekoTrack's primary catalog, especially for anime and relationship data. Discover includes a catalog selector for MangaBaka search and browsing. MangaBaka can also enrich AniList manga/novel entries with alternate title variants and other provider metadata when a cautious ID/title match is available.

MangaBaka-only results use separate local identifiers so they are not accidentally sent to AniList as if their IDs were AniList IDs. MangaBaka lookup failures are non-fatal: AniList results and locally saved reading progress should continue to work when MangaBaka is unavailable. Its API is not yet declared stable and its schema may change without notice, so NekoTrack preserves provider payloads and treats optional enrichment as best-effort.

No external provider can guarantee complete chapter or volume records for every title. NekoTrack keeps local progress as the source of truth and falls back to placeholders when actual item records are unavailable.

## Known limitations

- Online search and metadata enrichment require network access to the selected catalog.
- MangaBaka coverage and its volume collections vary by title; not every light novel has separately listed published volumes.
- MangaBaka relationships can be incomplete, so bundling may not be possible for every entry until provider relationships are available.
- Voice-actor and character metadata depend on the fields available from AniList.
- Some planned media, tracking, metadata, and filtering features are still being developed.

## Adversarial testing

Run the full regression suite, then a seeded fuzz/chaos soak across malformed provider payloads, AniList response handling, unified search, relationship-graph bundling, and randomized SQLite progress/state invariants:

```powershell
python stress_test.py --minutes 10
```

Choose a duration from 1 to 300 minutes (5 hours) and a seed that can reproduce the run:

```powershell
python stress_test.py --minutes 120 --seed 20261010
python stress_test.py --seconds 30 --seed 7
```

Every soak iteration runs all four randomized stress modules (provider/API shapes, search/bundling, SQLite state invariants, and PySide6 search-filter UI state) with a fresh seed. A live-network guard blocks and records unexpected HTTP attempts, and the report records failed seeds and test output in `nekotrack_stress_report.json`. The harness disables live network access and never opens the normal application database; database tests use temporary directories. This is a long-running local fuzz campaign, not a claim that every GUI workflow is automatically covered.

For a hosted run, open **Actions → Adversarial stress → Run workflow** and choose a duration of 1–300 minutes. Pull requests run a ten-minute soak to catch issues that only appear after sustained repetition; use manual dispatch for longer campaigns. The workflow uploads the JSON report as an artifact.
## Data and privacy

NekoTrack stores its local SQLite database as `anime_tracker.db`. Cover images are cached under `data/images/`. These generated/local files are intentionally ignored by Git.

NekoTrack does not currently require an AniList API token for its public GraphQL requests, nor an account token for the public MangaBaka catalogue endpoints used by the app. NekoTrack does not call MangaBaka private-account or moderation routes.

## Data attribution and terms

NekoTrack's source code is MIT-licensed. That license does not grant ownership of catalog data, artwork, or other third-party content.

MangaBaka asks API users to attribute both MangaBaka and the upstream metadata providers. MangaBaka says its original data is licensed under CC BY-NC-SA 4.0 (personal/non-commercial use with attribution); data from AniList, Kitsu, MyAnimeList, MangaUpdates, Anime-Planet, Shikimori, and other providers remains subject to each provider's own terms. Review these conditions before distributing data or using it commercially.

- [MangaBaka API documentation and rate limits](https://mangabaka.org/data/api)
- [MangaBaka database, providers, data licensing, and attribution](https://mangabaka.org/data/database)
- [MangaBaka title variants (English, native, romanized, and alternative titles)](https://mangabaka.org/pages/announcements/15-titles-v2)
- [AniList API documentation](https://docs.anilist.co/)

## License

NekoTrack's source code is released under the MIT License. See [LICENSE](LICENSE).

## AI-assisted development

NekoTrack has been developed with assistance from AI coding tools, including GitHub Copilot and OpenAI ChatGPT. The project is still maintained and reviewed by me.

## Personal note

i don't know any coding but i still wanted to make this app because i felt like there were no better options. best i have found was a site and it still has some limits to what i want so i made this. hope if anyone uses it they enjoy!
