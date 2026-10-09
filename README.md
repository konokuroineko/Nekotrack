# NekoTrack

Your personal anime, manga, and novel tracker.

Track what you watch and read, manage your library, and keep your collection organized — all from a desktop app.

## Features

- Search AniList for anime and combine AniList + MangaBaka for manga and light novels
- Multilingual manga/novel titles, including romanized/native aliases and duplicate-title disambiguation
- MangaBaka metadata: creators, publishers, publication dates, tags, ratings, cross-provider links, and catalog details
- Safe-rated MangaBaka catalog browsing, search, pagination, mix/discovery helpers, tags, and publisher endpoints
- Anime, manga, and novel search modes
- Local SQLite library
- Add works to your personal library
- Episode progress and watched-state tracking
- Local cover caching
- Work relationships and franchise connections shown in work details
- Character, voice-actor, and staff information shown in work details
- Character, staff, studio, alternate-title, episode, and song data models
- Studio data model
- Alternate titles
- Episode data model
- Song/music data model
- Work detail page with related works, characters, voice actors, and staff
- Configurable dark desktop interface built with PySide6
- Library card sizing, spacing, hover, and resize animation preferences
- Maximized startup preference
- Scrollable settings page

## Known limitations

- AniList access is required for online search and metadata retrieval.
- Online features may be unavailable when the AniList service or API is unavailable.
- Voice-actor metadata depends on the fields currently provided by AniList.
- Some planned media, tracking, metadata, and filtering features are still being developed.

## Planned

- More complete anime / manga / novel support
- Better franchise and relationship browsing
- More complete character, staff, and voice-actor pages
- Episode and chapter tracking improvements
- Ratings, notes, and dates
- Improved search and filtering
- Better offline behavior

## Data and privacy

NekoTrack stores its local SQLite database as `anime_tracker.db`. Cover images are cached under `data/images/`. These generated/local files are intentionally ignored by Git.

NekoTrack does not currently require an AniList API token for its public GraphQL requests.

## MangaBaka

NekoTrack uses the MangaBaka public API as an additional manga/novel catalog and metadata source. The integration retains AniList IDs and relationships when a matching link is available, and uses stable local IDs for MangaBaka-only entries. MangaBaka's public API schema may change without notice.

MangaBaka-original data is licensed under CC BY-NC-SA 4.0 and requires attribution; use is restricted to non-commercial contexts unless separately licensed. Metadata collected from other services remains subject to the original providers' terms. NekoTrack shows source attribution in work details and links back to the catalog. See the [MangaBaka API documentation](https://mangabaka.org/data/api), [terms](https://mangabaka.org/pages/policy/18-content-scope-strengths-roadmap), and [API changelog](https://mangabaka.org/data/api/changelog) before distributing a commercial build.

## AniList

NekoTrack uses the AniList GraphQL API for media metadata. AniList data, artwork, and trademarks remain subject to their respective terms and rights. This repository's MIT license applies to NekoTrack's own source code; it does not grant ownership of third-party AniList content.

See the AniList API documentation for current API and usage terms: https://anilist.gitbook.io/anilist-apiv2-docs/

## License

NekoTrack's source code is released under the MIT License. See [LICENSE](LICENSE).

## AI-assisted development

NekoTrack has been developed with assistance from AI coding tools, including GitHub Copilot and OpenAI ChatGPT. The project is still maintained and reviewed by me.

## Personal note

i don't know any coding but i still wanted to make this app because i felt like there were no better options. best i have found was a site and it still has some limits to what i want so i made this. hope if anyone uses it they enjoy!
