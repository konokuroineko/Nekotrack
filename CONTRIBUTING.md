# Contributing to NekoTrack

NekoTrack is a Windows desktop application built with Python, PySide6, SQLite, and external catalog APIs. The repository is maintained by one owner, but focused bug reports and well-tested contributions are welcome.

## Before changing code

1. Check the existing implementation and tests before adding a parallel code path.
2. Keep local library progress authoritative. Provider refreshes must not silently reset user progress.
3. Preserve existing SQLite databases. Do not replace the user's database with a freshly initialized one.
4. Keep network calls out of the UI thread. Use the established worker/cancellation patterns.
5. Keep AniList, MangaBaka, and TMDB behavior inside the provider/backend layer; pages should call the supported application APIs or bridge methods.
6. For UI changes, preserve theme behavior, loading/error/empty states, keyboard navigation, and the legacy fallback where one exists.

## Development setup

Use a Python version exercised by CI (3.11, 3.12, or 3.14), install the requirements, and run the app:

~~~powershell
python -m pip install -r requirements.txt
python main.py
~~~

The optional Rust acceleration crate lives under rust/nekotrack_core. Python behavior must remain correct when the native extension is unavailable; do not make the Rust module a required runtime dependency.

## Validation

Run the same core checks used by GitHub Actions before opening a pull request:

~~~powershell
ruff check --select F .
python -m compileall -q main.py api.py native_acceleration.py catalog_search.py debug_tools.py database.py image_cache.py library_export.py series.py updater.py stress_test.py installer ui tests
python -m unittest discover -s tests -v
python stress_test.py --seconds 1 --seed 17 --report stress-smoke.json
~~~

The CI workflow additionally builds and checks native/Python parity for the optional Rust extension on Windows and Ubuntu. A passing unit suite does not replace a real Windows app launch when a change affects Qt, QML, packaging, image loading, or shutdown.

## Database and migration rules

- Treat the existing SQLite schema as user data. Add explicit, repeatable migrations rather than dropping/recreating tables.
- Use transactions for multi-table changes and roll back on failure.
- Test with an existing database containing works, user_library progress, episode rows, reading progress, provider metadata, bundle links/overrides, favorites, and recommendation history.
- Test both an empty database and a populated database.
- Avoid broad destructive cleanup during metadata refresh. Missing provider data is not proof that a saved local record should be deleted.
- When changing backup/restore behavior, test interrupted writes, SQLite WAL state, corrupted archives, path traversal, and restoring over an existing library.

## Pull requests

A pull request should explain the user-visible problem, the chosen fix, compatibility implications, and how it was tested. Include regression tests for bugs. Keep changes grouped by feature rather than making unrelated edits in one patch. Do not mark UI work ready to merge until it has been opened on Windows with a populated library.

For bug reports, include the NekoTrack version, Windows version, whether the app is installed or portable, reproduction steps, and a diagnostics report when it is safe to share. Diagnostics can contain catalog titles and error details; review the report before posting it publicly.
