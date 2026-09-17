# NekoTrack

Your personal anime & manga tracker.

Track what you watch and read, explore characters and staff, manage your library, and keep your collection organized — all from a clean desktop app.

> **Status: Beta — v0.1.0-beta.2**
>
> NekoTrack is usable, but it is still under active development. Expect unfinished features, UI changes, and occasional bugs while the beta is being developed.

## Features

- Search AniList
- Anime, manga, and novel search modes
- Local SQLite library
- Add works to your personal library
- Episode progress and watched-state tracking
- Local cover caching
- Work relationships and franchise connections
- Character and voice-actor data model
- Staff data model
- Studio data model
- Alternate titles
- Episode data model
- Song/music data model
- Work detail, character, person, and relationship pages
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

NekoTrack stores its local SQLite database as `anime_tracker.db` inside the per-user application data directory (`%APPDATA%\NekoTrack` on Windows). Cover images are cached under `data/images/` there. These generated/local files are intentionally ignored by Git.

NekoTrack does not currently require an AniList API token for its public GraphQL requests.

## Development

Requires Python 3.9+.

```bash
# Create a virtual environment and install dependencies
python -m venv .venv
# Windows: .venv\Scripts\activate
source .venv/bin/activate
pip install -e ".[dev]"

# Run the app
python main.py

# Run the offline test suite (no network, no UI required)
pytest
```

The core logic (`api`, `database`, `season_count`, `series`, `updater`) is fully testable without PySide6; only the `ui/` package and `main.py` need a desktop session.

## AniList

NekoTrack uses the AniList GraphQL API for media metadata. AniList data, artwork, and trademarks remain subject to their respective terms and rights. This repository's MIT license applies to NekoTrack's own source code; it does not grant ownership of third-party AniList content.

See the AniList API documentation for current API and usage terms: https://anilist.gitbook.io/anilist-apiv2-docs/

## License

NekoTrack's source code is released under the MIT License. See [LICENSE](LICENSE).

## AI-assisted development

NekoTrack has been developed with assistance from AI coding tools, including GitHub Copilot and OpenAI ChatGPT. The project is still maintained and reviewed by me.

## Personal note

i don't know any coding but i still wanted to make this app because i felt like there were no better options. best i have found was a site and it still has some limits to what i want so i made this. hope if anyone uses it they enjoy!
