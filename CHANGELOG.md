# Changelog

Notable user-facing changes to NekoTrack are documented here. Dates use YYYY-MM-DD.

## [Unreleased]

### Added
- Export saved works and local tracking progress to a UTF-8 CSV file from Settings → Data & Storage.

### Changed
- Continue the staged QML interface migration while keeping the Python, SQLite, and provider layers as the data/backend implementation.

### Fixed
- Add a QML image fallback for detail-page artwork when a remote image cannot be loaded directly.
- Load missing character, staff, and relation details independently in the background rather than treating an empty local cache as a permanent empty result.

## [1.0.0] - 2026-10-18

First stable Windows release.

### Added
- Local library management for anime, manga, and light novels, including watched episodes, manga chapters, and novel/manga volumes.
- Automatic franchise bundling with controls for custom titles, covers, included members, manual relationships, and exclusions.
- Combined AniList and MangaBaka search with provider-aware metadata and filters.
- TMDB-backed episode catalog enrichment when matching episode data is available.
- Personalized recommendations with feedback, upcoming releases, episode reminders, favorites, and custom work identity.
- Character, voice actor, production staff, and related-work profiles.
- Dark themes, light mode, refreshed branding, UI scaling, poster/layout preferences, and a first-run setup wizard.
- Windows installer and portable executable, stable-release update checks, executable backup, manual rollback, and diagnostics export.

### Improved
- Preserve local progress when upstream catalogs are incomplete or refreshed.
- Improve background loading, image caching, shutdown cancellation, and UI responsiveness.
- Expand regression, adversarial, stress, and performance testing.

## [0.1.0-beta.2] - 2026-09-13

### Fixed
- Fixed the AniList voice-actor GraphQL query by removing the unsupported pagination argument from Character.voiceActors.
- Retrieve voice-actor records correctly when AniList returns them for a character.

### Beta notes
- AniList API access is required for online search and metadata retrieval.
- AniList service availability can temporarily affect online features.
- Windows packaging/installer support was not included in this beta.
- Some planned tracking and metadata features remained under development.

## [0.1.0-beta.1] - 2026-09-12

### Added
- First public beta release.
- Anime, manga, and novel search modes.
- Local SQLite library and collection management.
- Episode progress and watched-state tracking.
- Offline cover caching and locally stored media metadata.
- Work relationship/franchise data and character, voice-actor, staff, studio, alternate-title, episode, and song data models.
- Work detail, character, person, and relationship pages.
- Configurable dark desktop theme, library card preferences, maximized startup preference, and a scrollable settings page.

### Beta notes
- AniList API access was required for online search and metadata retrieval.
- AniList service availability could temporarily affect online features.
- Windows packaging/installer support was not included in this beta.
