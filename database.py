import json
import math
import re
import sqlite3
from pathlib import Path

from diagnostics import log_exception

DATABASE_NAME = "anime_tracker.db"
_MAX_SQLITE_INTEGER = (1 << 63) - 1
_MIN_SQLITE_INTEGER = -(1 << 63)
_MAX_TRACKED_EPISODE_NUMBER = 1_000_000


def _validated_work_id(value):
    """Normalize a provider media ID into SQLite's signed 64-bit integer range."""
    if isinstance(value, bool):
        raise ValueError("A work ID must be a non-zero integer.")
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, float):
        if not math.isfinite(value) or not value.is_integer():
            raise ValueError("A work ID must be a non-zero integer.")
        parsed = int(value)
    elif isinstance(value, str):
        text = value.strip()
        if not text or len(text) > 20 or not re.fullmatch(r"[+-]?[0-9]+", text):
            raise ValueError("A work ID must be a non-zero integer.")
        try:
            parsed = int(text)
        except (TypeError, ValueError, OverflowError) as error:
            raise ValueError("A work ID must be a non-zero integer.") from error
    else:
        raise ValueError("A work ID must be a non-zero integer.")

    if (
        parsed == 0
        or parsed < _MIN_SQLITE_INTEGER
        or parsed > _MAX_SQLITE_INTEGER
    ):
        raise ValueError("A work ID is outside SQLite's supported integer range.")
    return parsed


def _validated_work_ids(values):
    """Normalize an optional collection of work IDs; return None if any are malformed."""
    if values is None:
        return []
    if not isinstance(values, (list, tuple, set, frozenset)):
        return None
    ids = set()
    for value in values:
        if value is None:
            continue
        try:
            ids.add(_validated_work_id(value))
        except (TypeError, ValueError, OverflowError):
            return None
    return sorted(ids)


def _safe_optional_integer(value, minimum=0, maximum=_MAX_SQLITE_INTEGER):
    """Normalize optional integer metadata while rejecting malformed provider values."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, float):
        if not math.isfinite(value) or not value.is_integer():
            return None
        parsed = int(value)
    elif isinstance(value, str):
        text = value.strip()
        if not text or len(text) > 20 or not re.fullmatch(r"[+-]?[0-9]+", text):
            return None
        try:
            parsed = int(text)
        except (TypeError, ValueError, OverflowError):
            return None
    else:
        return None
    return parsed if minimum <= parsed <= maximum else None


def _safe_optional_score(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        score = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return score if math.isfinite(score) and 0 <= score <= 100 else None


def get_connection():
    # The application performs catalog imports and progress writes from worker
    # threads. Give SQLite time to serialize short concurrent write transactions
    # instead of raising "database is locked" after its default 5-second wait.
    connection = None
    try:
        connection = sqlite3.connect(DATABASE_NAME, timeout=15)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection
    except Exception as error:
        if connection is not None:
            try:
                connection.close()
            except sqlite3.Error:
                pass
        log_exception("database.connection_failed", error, database_name=DATABASE_NAME)
        raise


def initialize_database():
    connection = get_connection()
    cursor = connection.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS works (
            id INTEGER PRIMARY KEY, title TEXT NOT NULL, type TEXT NOT NULL,
            description TEXT, episodes INTEGER, score REAL, start_year INTEGER,
            cover_url TEXT, format TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS work_relations (
            source_id INTEGER NOT NULL, target_id INTEGER NOT NULL, relation_type TEXT NOT NULL,
            PRIMARY KEY (source_id, target_id, relation_type)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS manual_bundle_links (
            work_a INTEGER NOT NULL, work_b INTEGER NOT NULL,
            PRIMARY KEY (work_a, work_b),
            FOREIGN KEY (work_a) REFERENCES works(id),
            FOREIGN KEY (work_b) REFERENCES works(id),
            CHECK (work_a < work_b)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS bundle_exclusions (
            work_a INTEGER NOT NULL, work_b INTEGER NOT NULL,
            PRIMARY KEY (work_a, work_b),
            FOREIGN KEY (work_a) REFERENCES works(id),
            FOREIGN KEY (work_b) REFERENCES works(id),
            CHECK (work_a < work_b)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS automatic_bundle_memberships (
            bundle_id INTEGER NOT NULL,
            work_id INTEGER NOT NULL,
            PRIMARY KEY (bundle_id, work_id),
            FOREIGN KEY (work_id) REFERENCES works(id)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS bundle_overrides (
            bundle_anchor_id INTEGER PRIMARY KEY,
            custom_title TEXT,
            cover_work_id INTEGER,
            custom_cover_path TEXT,
            FOREIGN KEY (bundle_anchor_id) REFERENCES works(id),
            FOREIGN KEY (cover_work_id) REFERENCES works(id)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_library (
            work_id INTEGER PRIMARY KEY, status TEXT NOT NULL DEFAULT 'Planning',
            progress_episodes INTEGER DEFAULT 0, progress_chapters INTEGER DEFAULT 0,
            progress_volumes INTEGER DEFAULT 0,
            rating INTEGER, notes TEXT, added_date DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_date DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (work_id) REFERENCES works(id)
        )
    """)
    library_columns = {
        column["name"]
        for column in cursor.execute("PRAGMA table_info(user_library)").fetchall()
    }
    if "progress_volumes" not in library_columns:
        cursor.execute(
            "ALTER TABLE user_library ADD COLUMN progress_volumes INTEGER NOT NULL DEFAULT 0"
        )

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS characters (
            id INTEGER PRIMARY KEY, name TEXT NOT NULL, image_url TEXT, image_path TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS people (
            id INTEGER PRIMARY KEY, name TEXT NOT NULL, image_url TEXT, image_path TEXT
        )
    """)
    voice_actor_scope_existed = cursor.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'work_character_voice_actors'"
    ).fetchone() is not None
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS work_characters (
            work_id INTEGER NOT NULL, character_id INTEGER NOT NULL, role TEXT,
            PRIMARY KEY (work_id, character_id), FOREIGN KEY (work_id) REFERENCES works(id),
            FOREIGN KEY (character_id) REFERENCES characters(id)
        )
    """)
    character_columns = cursor.execute("PRAGMA table_info(work_characters)").fetchall()
    character_column_names = {column["name"] for column in character_columns}
    if "role" not in character_column_names:
        cursor.execute("ALTER TABLE work_characters ADD COLUMN role TEXT")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS character_voice_actors (
            character_id INTEGER NOT NULL, person_id INTEGER NOT NULL, language TEXT,
            PRIMARY KEY (character_id, person_id), FOREIGN KEY (character_id) REFERENCES characters(id),
            FOREIGN KEY (person_id) REFERENCES people(id)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS work_character_voice_actors (
            work_id INTEGER NOT NULL,
            character_id INTEGER NOT NULL,
            person_id INTEGER NOT NULL,
            language TEXT,
            PRIMARY KEY (work_id, character_id, person_id),
            FOREIGN KEY (work_id) REFERENCES works(id),
            FOREIGN KEY (character_id) REFERENCES characters(id),
            FOREIGN KEY (person_id) REFERENCES people(id)
        )
    """)
    if not voice_actor_scope_existed:
        # The old cache stored voices globally by character, which lost the
        # work-specific distinction between adaptations. Seed the new table
        # with the legacy associations, then refresh each work on demand.
        cursor.execute("""
            INSERT OR IGNORE INTO work_character_voice_actors
                (work_id, character_id, person_id, language)
            SELECT work_characters.work_id, character_voice_actors.character_id,
                   character_voice_actors.person_id, character_voice_actors.language
            FROM work_characters
            JOIN character_voice_actors
              ON character_voice_actors.character_id = work_characters.character_id
        """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS work_staff (
            work_id INTEGER NOT NULL, person_id INTEGER NOT NULL, role TEXT NOT NULL,
            PRIMARY KEY (work_id, person_id, role), FOREIGN KEY (work_id) REFERENCES works(id), FOREIGN KEY (person_id) REFERENCES people(id)
        )
    """)
    columns = cursor.execute("PRAGMA table_info(works)").fetchall()
    column_names = {column["name"] for column in columns}
    for column, definition in {
        "format": "TEXT", "cover_path": "TEXT", "chapters": "INTEGER", "volumes": "INTEGER",
        "source": "TEXT", "end_year": "INTEGER", "duration": "INTEGER", "mal_id": "INTEGER",
        "start_month": "INTEGER", "start_day": "INTEGER",
        "tmdb_id": "INTEGER", "tmdb_season_number": "INTEGER",
        "characters_loaded": "INTEGER NOT NULL DEFAULT 0",
    }.items():
        if column not in column_names:
            cursor.execute(f"ALTER TABLE works ADD COLUMN {column} {definition}")
    if not voice_actor_scope_existed:
        # Only cached works with character associations need a cast refresh;
        # don't queue MangaBaka-only novels or titles with a valid empty cast.
        cursor.execute("""
            UPDATE works
            SET characters_loaded = 0
            WHERE characters_loaded = 1
              AND EXISTS (
                  SELECT 1 FROM work_characters
                  WHERE work_characters.work_id = works.id
              )
        """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS alternate_titles (
            work_id INTEGER NOT NULL, title TEXT NOT NULL, language TEXT,
            PRIMARY KEY (work_id, title, language), FOREIGN KEY (work_id) REFERENCES works(id)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS work_provider_metadata (
            work_id INTEGER NOT NULL,
            provider TEXT NOT NULL,
            provider_id TEXT,
            payload_json TEXT NOT NULL,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (work_id, provider),
            FOREIGN KEY (work_id) REFERENCES works(id) ON DELETE CASCADE
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS studios (
            id INTEGER PRIMARY KEY, name TEXT NOT NULL, is_main INTEGER NOT NULL DEFAULT 0
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS work_studios (
            work_id INTEGER NOT NULL, studio_id INTEGER NOT NULL,
            PRIMARY KEY (work_id, studio_id), FOREIGN KEY (work_id) REFERENCES works(id)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS episodes (
            id INTEGER PRIMARY KEY AUTOINCREMENT, work_id INTEGER NOT NULL,
            episode_number INTEGER NOT NULL, title TEXT, description TEXT, air_date TEXT,
            thumbnail_url TEXT, watched INTEGER NOT NULL DEFAULT 0,
            UNIQUE (work_id, episode_number),
            FOREIGN KEY (work_id) REFERENCES works(id)
        )
    """)
    episode_columns = cursor.execute("PRAGMA table_info(episodes)").fetchall()
    episode_column_names = {column["name"] for column in episode_columns}
    if "thumbnail_url" not in episode_column_names:
        cursor.execute("ALTER TABLE episodes ADD COLUMN thumbnail_url TEXT")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS release_reminders (
            work_id INTEGER NOT NULL,
            episode_number INTEGER NOT NULL CHECK (episode_number >= 1),
            notified_date TEXT,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (work_id, episode_number),
            FOREIGN KEY (work_id) REFERENCES works(id) ON DELETE CASCADE
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_favorites (
            work_id INTEGER PRIMARY KEY,
            work_data_json TEXT NOT NULL DEFAULT '{}',
            added_date DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS recommendation_history (
            work_id INTEGER PRIMARY KEY,
            impressions INTEGER NOT NULL DEFAULT 0 CHECK (impressions >= 0),
            feedback TEXT CHECK (feedback IN (
                'like', 'dislike', 'more_like_this', 'less_like_this', 'never_show'
            ) OR feedback IS NULL),
            metadata_json TEXT NOT NULL DEFAULT '{}',
            first_seen_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            last_seen_at DATETIME
        )
    """)
    history_schema_row = cursor.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'recommendation_history'"
    ).fetchone()
    history_schema = str(history_schema_row["sql"] or "").casefold() if history_schema_row else ""
    if any(action not in history_schema for action in (
        "more_like_this", "less_like_this", "never_show",
    )):
        # SQLite cannot alter a CHECK constraint in place. Rebuild only this
        # small history table while preserving every previous impression/choice.
        cursor.execute(
            "ALTER TABLE recommendation_history RENAME TO recommendation_history_legacy"
        )
        cursor.execute("""
            CREATE TABLE recommendation_history (
                work_id INTEGER PRIMARY KEY,
                impressions INTEGER NOT NULL DEFAULT 0 CHECK (impressions >= 0),
                feedback TEXT CHECK (feedback IN (
                    'like', 'dislike', 'more_like_this', 'less_like_this', 'never_show'
                ) OR feedback IS NULL),
                metadata_json TEXT NOT NULL DEFAULT '{}',
                first_seen_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                last_seen_at DATETIME
            )
        """)
        cursor.execute("""
            INSERT INTO recommendation_history
                (work_id, impressions, feedback, metadata_json, first_seen_at, last_seen_at)
            SELECT work_id, impressions, feedback, metadata_json, first_seen_at, last_seen_at
            FROM recommendation_history_legacy
        """)
        cursor.execute("DROP TABLE recommendation_history_legacy")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS entity_favorites (
            entity_type TEXT NOT NULL CHECK (entity_type IN ('character', 'staff', 'voice_actor')),
            entity_id INTEGER NOT NULL CHECK (entity_id > 0),
            entity_name TEXT NOT NULL DEFAULT '',
            language TEXT,
            added_date DATETIME DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (entity_type, entity_id)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS work_display_overrides (
            work_id INTEGER PRIMARY KEY,
            custom_title TEXT,
            custom_cover_path TEXT,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS reading_items (
            work_id INTEGER NOT NULL,
            item_type TEXT NOT NULL CHECK(item_type IN ('chapter', 'volume')),
            item_number INTEGER NOT NULL CHECK(item_number >= 1),
            title TEXT,
            is_read INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (work_id, item_type, item_number),
            FOREIGN KEY (work_id) REFERENCES works(id)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS reading_progress (
            work_id INTEGER NOT NULL,
            item_type TEXT NOT NULL CHECK(item_type IN ('chapter', 'volume')),
            read_count INTEGER NOT NULL DEFAULT 0 CHECK(read_count >= 0),
            updated_date DATETIME DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (work_id, item_type),
            FOREIGN KEY (work_id) REFERENCES works(id)
        )
    """)
    # Migrate old per-item progress once into durable counters before removing
    # generated placeholder rows. Counters stay after Library membership is
    # removed, matching the previous remove/re-add behavior without fake rows.
    progress_row_count = cursor.execute(
        "SELECT COUNT(*) FROM reading_progress"
    ).fetchone()[0]
    if progress_row_count == 0:
        cursor.execute("""
            INSERT INTO reading_progress (work_id, item_type, read_count)
            SELECT work_id, item_type, SUM(is_read)
            FROM reading_items
            GROUP BY work_id, item_type
            HAVING SUM(is_read) > 0
        """)
        for item_type, progress_column in (
            ("chapter", "progress_chapters"),
            ("volume", "progress_volumes"),
        ):
            cursor.execute(
                f"""
                INSERT INTO reading_progress (work_id, item_type, read_count)
                SELECT work_id, ?, COALESCE({progress_column}, 0)
                FROM user_library
                WHERE COALESCE({progress_column}, 0) > 0
                ON CONFLICT(work_id, item_type) DO UPDATE SET
                    read_count = MAX(reading_progress.read_count, excluded.read_count)
                """,
                (item_type,),
            )
    # Unnamed rows were generated as Chapter N / Volume N placeholders.
    # Keep genuine provider-titled volume metadata, but never render or retain
    # the old fictional entries after their aggregate counts have been migrated.
    cursor.execute("DELETE FROM reading_items WHERE title IS NULL")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS songs (
            id INTEGER PRIMARY KEY, title TEXT NOT NULL, artist TEXT, image_url TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS work_songs (
            work_id INTEGER NOT NULL, song_id INTEGER NOT NULL, song_type TEXT NOT NULL,
            song_number INTEGER, PRIMARY KEY (work_id, song_id, song_type),
            FOREIGN KEY (work_id) REFERENCES works(id), FOREIGN KEY (song_id) REFERENCES songs(id)
        )
    """)
    # TV episode records and TMDB season mappings are only valid for anime.
    # Remove accidental TV episode imports from Manga entries from older builds.
    cursor.execute("""
        DELETE FROM episodes
        WHERE work_id IN (
            SELECT id FROM works
            WHERE UPPER(COALESCE(type, '')) != 'ANIME'
        )
    """)
    cursor.execute("""
        UPDATE works
        SET tmdb_id = NULL, tmdb_season_number = NULL
        WHERE UPPER(COALESCE(type, '')) != 'ANIME'
          AND (tmdb_id IS NOT NULL OR tmdb_season_number IS NOT NULL)
    """)
    connection.commit()
    connection.close()


def _cast_provider_id(value):
    """Return a positive provider ID safe for SQLite, or None for malformed input."""
    try:
        numeric_id = _validated_work_id(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return numeric_id if numeric_id > 0 else None


def save_characters(work_id, characters):
    """Persist one work's character and voice-actor snapshot.

    Character identity is shared across titles, but voice-actor credits are not:
    adaptations may use different casts, so their actor links must be work-scoped.
    """
    try:
        safe_work_id = _validated_work_id(work_id)
    except (TypeError, ValueError, OverflowError):
        return
    work_id = safe_work_id
    if not isinstance(characters, (list, tuple)):
        try:
            safe_work_id = _validated_work_id(work_id)
        except (TypeError, ValueError, OverflowError):
            return
        connection = get_connection()
        try:
            connection.execute(
                "UPDATE works SET characters_loaded = 0 WHERE id = ?",
                (safe_work_id,),
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        return

    normalized = []
    snapshot_valid = True
    for edge in characters:
        if not isinstance(edge, dict):
            snapshot_valid = False
            continue
        character = edge.get("node")
        if not isinstance(character, dict):
            snapshot_valid = False
            continue
        character_id = _cast_provider_id(character.get("id"))
        name_data = character.get("name")
        name = name_data.get("full") if isinstance(name_data, dict) else None
        if character_id is None or not isinstance(name, str) or not name.strip():
            snapshot_valid = False
            continue

        image_data = character.get("image")
        if image_data is not None and not isinstance(image_data, dict):
            snapshot_valid = False
            image_data = {}
        image_url = image_data.get("large") if isinstance(image_data, dict) else None
        if image_url is not None and not isinstance(image_url, str):
            snapshot_valid = False
            image_url = None

        raw_role = edge.get("role")
        if raw_role is None or raw_role == "":
            role = "UNKNOWN"
        elif isinstance(raw_role, str):
            role = raw_role.strip() or "UNKNOWN"
        else:
            snapshot_valid = False
            role = "UNKNOWN"

        if "voiceActors" not in edge:
            snapshot_valid = False
            raw_actors = []
        else:
            raw_actors = edge.get("voiceActors")
            if raw_actors is None:
                snapshot_valid = False
                raw_actors = []
            elif not isinstance(raw_actors, list):
                snapshot_valid = False
                raw_actors = []

        actors = []
        for actor in raw_actors:
            if not isinstance(actor, dict):
                snapshot_valid = False
                continue
            person_id = _cast_provider_id(actor.get("id"))
            person_name_data = actor.get("name")
            person_name = (
                person_name_data.get("full")
                if isinstance(person_name_data, dict)
                else None
            )
            if person_id is None or not isinstance(person_name, str) or not person_name.strip():
                snapshot_valid = False
                continue

            actor_image_data = actor.get("image")
            if actor_image_data is not None and not isinstance(actor_image_data, dict):
                snapshot_valid = False
                actor_image_data = {}
            actor_image_url = (
                actor_image_data.get("large")
                if isinstance(actor_image_data, dict)
                else None
            )
            if actor_image_url is not None and not isinstance(actor_image_url, str):
                snapshot_valid = False
                actor_image_url = None

            language = actor.get("language")
            if language is not None and not isinstance(language, str):
                snapshot_valid = False
                language = None
            actors.append({
                "id": person_id,
                "name": person_name.strip(),
                "image_url": actor_image_url,
                "language": language,
            })

        normalized.append({
            "id": character_id,
            "name": name.strip(),
            "image_url": image_url,
            "role": role,
            "actors": actors,
        })

    connection = get_connection()

    def remove_person_if_orphaned(person_id):
        references = connection.execute(
            """
            SELECT 1 FROM character_voice_actors WHERE person_id = ?
            UNION ALL
            SELECT 1 FROM work_staff WHERE person_id = ?
            LIMIT 1
            """,
            (person_id, person_id),
        ).fetchone()
        if references is None:
            connection.execute("DELETE FROM people WHERE id = ?", (person_id,))

    try:
        for character in normalized:
            connection.execute(
                """
                INSERT INTO characters (id, name, image_url) VALUES (?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name,
                    image_path = CASE
                        WHEN excluded.image_url IS NOT NULL
                         AND excluded.image_url IS NOT characters.image_url
                        THEN NULL ELSE characters.image_path END,
                    image_url = COALESCE(excluded.image_url, characters.image_url)
                """,
                (character["id"], character["name"], character["image_url"]),
            )
            connection.execute(
                """
                INSERT INTO work_characters (work_id, character_id, role)
                VALUES (?, ?, ?)
                ON CONFLICT(work_id, character_id) DO UPDATE SET role = excluded.role
                """,
                (work_id, character["id"], character["role"]),
            )
            for actor in character["actors"]:
                connection.execute(
                    """
                    INSERT INTO people (id, name, image_url) VALUES (?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        name = excluded.name,
                        image_path = CASE
                            WHEN excluded.image_url IS NOT NULL
                             AND excluded.image_url IS NOT people.image_url
                            THEN NULL ELSE people.image_path END,
                        image_url = COALESCE(excluded.image_url, people.image_url)
                    """,
                    (actor["id"], actor["name"], actor["image_url"]),
                )
                # Keep the legacy global association table as a union for
                # migrations/cleanup, but read credits from this work-scoped row.
                connection.execute(
                    """
                    INSERT INTO character_voice_actors (character_id, person_id, language)
                    VALUES (?, ?, ?)
                    ON CONFLICT(character_id, person_id) DO UPDATE SET
                        language = COALESCE(excluded.language, character_voice_actors.language)
                    """,
                    (character["id"], actor["id"], actor["language"]),
                )
                connection.execute(
                    """
                    INSERT INTO work_character_voice_actors
                        (work_id, character_id, person_id, language)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(work_id, character_id, person_id) DO UPDATE SET
                        language = COALESCE(
                            excluded.language, work_character_voice_actors.language
                        )
                    """,
                    (work_id, character["id"], actor["id"], actor["language"]),
                )

        if snapshot_valid:
            incoming_character_ids = {character["id"] for character in normalized}
            existing_character_rows = connection.execute(
                "SELECT character_id FROM work_characters WHERE work_id = ?",
                (work_id,),
            ).fetchall()
            for row in existing_character_rows:
                old_character_id = row["character_id"]
                if old_character_id not in incoming_character_ids:
                    connection.execute(
                        "DELETE FROM work_characters WHERE work_id = ? AND character_id = ?",
                        (work_id, old_character_id),
                    )
                    old_scoped_actors = connection.execute(
                        """
                        SELECT person_id FROM work_character_voice_actors
                        WHERE work_id = ? AND character_id = ?
                        """,
                        (work_id, old_character_id),
                    ).fetchall()
                    connection.execute(
                        "DELETE FROM work_character_voice_actors WHERE work_id = ? AND character_id = ?",
                        (work_id, old_character_id),
                    )
                    for old_actor_row in old_scoped_actors:
                        still_assigned = connection.execute(
                            """
                            SELECT 1 FROM work_character_voice_actors
                            WHERE character_id = ? AND person_id = ? LIMIT 1
                            """,
                            (old_character_id, old_actor_row["person_id"]),
                        ).fetchone()
                        if still_assigned is None:
                            connection.execute(
                                """
                                DELETE FROM character_voice_actors
                                WHERE character_id = ? AND person_id = ?
                                """,
                                (old_character_id, old_actor_row["person_id"]),
                            )
                            remove_person_if_orphaned(old_actor_row["person_id"])
                    still_linked = connection.execute(
                        "SELECT 1 FROM work_characters WHERE character_id = ? LIMIT 1",
                        (old_character_id,),
                    ).fetchone()
                    if still_linked is None:
                        # Character and voice-actor rows are globally keyed.
                        # Remove them only after the character is no longer used
                        # by any work, preserving shared cast entities.
                        old_actor_rows = connection.execute(
                            "SELECT person_id FROM character_voice_actors WHERE character_id = ?",
                            (old_character_id,),
                        ).fetchall()
                        connection.execute(
                            "DELETE FROM character_voice_actors WHERE character_id = ?",
                            (old_character_id,),
                        )
                        for old_actor_row in old_actor_rows:
                            remove_person_if_orphaned(old_actor_row["person_id"])
                        connection.execute(
                            "DELETE FROM characters WHERE id = ?",
                            (old_character_id,),
                        )

            # A complete snapshot can remove actors from this work, but it must
            # not erase the same character's valid actor credits in other works.
            for character in normalized:
                desired_actor_ids = {actor["id"] for actor in character["actors"]}
                existing_actor_rows = connection.execute(
                    """
                    SELECT person_id FROM work_character_voice_actors
                    WHERE work_id = ? AND character_id = ?
                    """,
                    (work_id, character["id"]),
                ).fetchall()
                for row in existing_actor_rows:
                    old_actor_id = row["person_id"]
                    if old_actor_id not in desired_actor_ids:
                        connection.execute(
                            """
                            DELETE FROM work_character_voice_actors
                            WHERE work_id = ? AND character_id = ? AND person_id = ?
                            """,
                            (work_id, character["id"], old_actor_id),
                        )
                        still_assigned = connection.execute(
                            """
                            SELECT 1 FROM work_character_voice_actors
                            WHERE character_id = ? AND person_id = ? LIMIT 1
                            """,
                            (character["id"], old_actor_id),
                        ).fetchone()
                        if still_assigned is None:
                            connection.execute(
                                """
                                DELETE FROM character_voice_actors
                                WHERE character_id = ? AND person_id = ?
                                """,
                                (character["id"], old_actor_id),
                            )
                            remove_person_if_orphaned(old_actor_id)

            connection.execute(
                "UPDATE works SET characters_loaded = 1 WHERE id = ?",
                (work_id,),
            )
        else:
            # A previously complete cache is no longer authoritative if the
            # provider response is partial or malformed. Keep its rows intact,
            # but allow the next detail view to retry the cast fetch.
            connection.execute(
                "UPDATE works SET characters_loaded = 0 WHERE id = ?",
                (work_id,),
            )
        connection.commit()
    finally:
        connection.close()


def characters_are_loaded(work_id):
    try:
        safe_work_id = _validated_work_id(work_id)
    except (TypeError, ValueError, OverflowError):
        return False

    connection = get_connection()
    try:
        row = connection.execute(
            "SELECT characters_loaded FROM works WHERE id = ? LIMIT 1",
            (safe_work_id,),
        ).fetchone()
        if not row or not row["characters_loaded"]:
            return False

        # Older character imports did not store the AniList role. Treat those
        # entries as needing one refresh so existing titles get their role data.
        missing_role = connection.execute(
            """
            SELECT 1
            FROM work_characters
            WHERE work_id = ? AND role IS NULL
            LIMIT 1
            """,
            (safe_work_id,),
        ).fetchone()
        return missing_role is None
    finally:
        connection.close()


def invalidate_character_snapshots(work_ids):
    """Mark cached cast snapshots stale so a targeted refresh can retry them."""
    ids = _validated_work_ids(work_ids)
    if ids is None or not ids:
        return 0

    placeholders = ",".join("?" for _ in ids)
    connection = get_connection()
    try:
        cursor = connection.execute(
            f"UPDATE works SET characters_loaded = 0 WHERE id IN ({placeholders})",
            ids,
        )
        connection.commit()
        return max(0, cursor.rowcount)
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def get_tmdb_mapping(work_id):
    """Return the cached TMDB series/season mapping for one exact work."""
    try:
        safe_work_id = _validated_work_id(work_id)
    except (TypeError, ValueError, OverflowError):
        return None, None
    if safe_work_id <= 0:
        return None, None
    connection = get_connection()
    try:
        row = connection.execute(
            "SELECT tmdb_id, tmdb_season_number FROM works WHERE id = ?",
            (safe_work_id,),
        ).fetchone()
    finally:
        connection.close()
    if row is None:
        return None, None
    return row["tmdb_id"], row["tmdb_season_number"]


def save_tmdb_mapping(work_id, tmdb_id, tmdb_season_number):
    """Cache only valid TMDB identifiers; malformed refreshes keep the old mapping."""
    try:
        safe_work_id = _validated_work_id(work_id)
    except (TypeError, ValueError, OverflowError):
        return False

    if safe_work_id <= 0:
        return False
    safe_tmdb_id = (
        _safe_optional_integer(tmdb_id, 1, (1 << 31) - 1)
        if tmdb_id is not None else None
    )
    safe_season = (
        _safe_optional_integer(tmdb_season_number, 0, 10000)
        if tmdb_season_number is not None else None
    )
    if (
        (tmdb_id is not None and safe_tmdb_id is None)
        or (tmdb_season_number is not None and safe_season is None)
    ):
        return False

    connection = get_connection()
    try:
        cursor = connection.execute(
            """
            UPDATE works
            SET tmdb_id = ?, tmdb_season_number = ?
            WHERE id = ?
            """,
            (safe_tmdb_id, safe_season, safe_work_id),
        )
        connection.commit()
        return cursor.rowcount > 0
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def save_character_image_path(character_id, image_path):
    safe_id = _cast_provider_id(character_id)
    if safe_id is None:
        return False
    stored_path = str(image_path) if image_path is not None else None
    if stored_path is not None and len(stored_path) > 4096:
        return False
    connection = get_connection()
    try:
        cursor = connection.execute(
            "UPDATE characters SET image_path = ? WHERE id = ?",
            (stored_path, safe_id),
        )
        connection.commit()
        return cursor.rowcount > 0
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def save_person_image_path(person_id, image_path):
    safe_id = _cast_provider_id(person_id)
    if safe_id is None:
        return False
    stored_path = str(image_path) if image_path is not None else None
    if stored_path is not None and len(stored_path) > 4096:
        return False
    connection = get_connection()
    try:
        cursor = connection.execute(
            "UPDATE people SET image_path = ? WHERE id = ?",
            (stored_path, safe_id),
        )
        connection.commit()
        return cursor.rowcount > 0
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def get_characters(work_id):
    """Return work-specific character credits and the preferred Japanese voice actor."""
    try:
        safe_work_id = _validated_work_id(work_id)
    except (TypeError, ValueError, OverflowError):
        return []
    connection = get_connection()
    try:
        return connection.execute("""
            WITH ranked_actors AS (
                SELECT
                    work_character_voice_actors.work_id,
                    work_character_voice_actors.character_id,
                    people.id AS person_id,
                    people.name AS person_name,
                    people.image_path AS person_image_path,
                    people.image_url AS person_image_url,
                    work_character_voice_actors.language AS person_language,
                    ROW_NUMBER() OVER (
                        PARTITION BY work_character_voice_actors.work_id,
                                     work_character_voice_actors.character_id
                        ORDER BY
                            CASE
                                WHEN LOWER(COALESCE(work_character_voice_actors.language, ''))
                                     IN ('japanese', 'ja', 'jpn') THEN 0
                                ELSE 1
                            END,
                            work_character_voice_actors.language,
                            people.name
                    ) AS actor_rank
                FROM work_character_voice_actors
                JOIN people
                  ON people.id = work_character_voice_actors.person_id
                WHERE work_character_voice_actors.work_id = ?
            )
            SELECT
                characters.id,
                characters.name AS character_name,
                characters.image_path AS character_image_path,
                characters.image_url AS character_image_url,
                work_characters.role AS character_role,
                ranked_actors.person_id,
                ranked_actors.person_name,
                ranked_actors.person_image_path,
                ranked_actors.person_image_url,
                ranked_actors.person_language
            FROM work_characters
            JOIN characters ON characters.id = work_characters.character_id
            LEFT JOIN ranked_actors
              ON ranked_actors.work_id = work_characters.work_id
             AND ranked_actors.character_id = work_characters.character_id
             AND ranked_actors.actor_rank = 1
            WHERE work_characters.work_id = ?
            ORDER BY
                CASE UPPER(COALESCE(work_characters.role, 'UNKNOWN'))
                    WHEN 'MAIN' THEN 0
                    WHEN 'SUPPORTING' THEN 1
                    WHEN 'BACKGROUND' THEN 2
                    ELSE 3
                END,
                characters.name
        """, (safe_work_id, safe_work_id)).fetchall()
    finally:
        connection.close()


def _voice_actor_language_label(value):
    """Return a readable, stable language label while preserving actor identity."""
    if not isinstance(value, str):
        return ""
    raw = " ".join(value.strip().replace("_", " ").replace("-", " ").split())
    if not raw:
        return ""
    normalized = raw.casefold()
    aliases = {
        "ja": "Japanese",
        "jpn": "Japanese",
        "jp": "Japanese",
        "japanese": "Japanese",
        "en": "English",
        "eng": "English",
        "english": "English",
    }
    return aliases.get(normalized, raw.title())


def get_bundle_character_voice_actors(work_ids, character_id):
    """Return each distinct actor once, retaining language credits and work attribution.

    AniList can credit the same staff ID across multiple bundled adaptations, and
    language labels may vary in spelling. Person IDs define identity; individual
    work/language credits remain available in the credits list instead of multiplying
    the same person into duplicate profile cards.
    """
    ids = _validated_work_ids(work_ids)
    if not ids:
        return []
    safe_character_id = _cast_provider_id(character_id)
    if safe_character_id is None:
        return []
    placeholders = ",".join("?" for _ in ids)
    connection = get_connection()
    try:
        rows = connection.execute(
            f"""
            SELECT
                people.id AS person_id,
                people.name AS name,
                people.image_path AS image_path,
                people.image_url AS image_url,
                work_character_voice_actors.language AS source_language,
                work_character_voice_actors.work_id AS work_id,
                COALESCE(
                    NULLIF(TRIM(works.title), ''),
                    'Work ' || CAST(work_character_voice_actors.work_id AS TEXT)
                ) AS work_title
            FROM work_character_voice_actors
            JOIN people ON people.id = work_character_voice_actors.person_id
            LEFT JOIN works ON works.id = work_character_voice_actors.work_id
            WHERE work_character_voice_actors.work_id IN ({placeholders})
              AND work_character_voice_actors.character_id = ?
            ORDER BY people.id, work_character_voice_actors.work_id,
                     work_character_voice_actors.language
            """,
            [*ids, safe_character_id],
        ).fetchall()
    finally:
        connection.close()

    grouped = {}
    for raw_row in rows:
        row = dict(raw_row)
        person_id = row.get("person_id")
        if person_id is None:
            continue
        try:
            person_id = int(person_id)
        except (TypeError, ValueError, OverflowError):
            continue

        actor = grouped.setdefault(person_id, {
            "person_id": person_id,
            "name": row.get("name") or "Unknown voice actor",
            "image_path": row.get("image_path"),
            "image_url": row.get("image_url"),
            "language": None,
            "languages": [],
            "work_ids": [],
            "work_titles": [],
            "credits": [],
        })

        source_language = row.get("source_language")
        language = _voice_actor_language_label(source_language) or None
        work_id = row.get("work_id")
        try:
            work_id = int(work_id)
        except (TypeError, ValueError, OverflowError):
            work_id = None
        work_title = str(row.get("work_title") or "").strip()
        if not work_title and work_id is not None:
            work_title = f"Work {work_id}"

        if work_id is not None and work_id not in actor["work_ids"]:
            actor["work_ids"].append(work_id)
        if work_title and work_title not in actor["work_titles"]:
            actor["work_titles"].append(work_title)

        credit = {
            "work_id": work_id,
            "work_title": work_title,
            "language": language,
            "source_language": (
                str(source_language).strip()
                if isinstance(source_language, str) and source_language.strip()
                else None
            ),
        }
        if not any(
            old.get("work_id") == credit["work_id"]
            and old.get("language") == credit["language"]
            for old in actor["credits"]
        ):
            actor["credits"].append(credit)

        if language and language not in actor["languages"]:
            actor["languages"].append(language)
        if language and (
            actor["language"] is None
            or (language == "Japanese" and actor["language"] != "Japanese")
        ):
            actor["language"] = language

    def language_key(language):
        return (
            0 if language == "Japanese" else 1,
            str(language or "").casefold(),
        )

    result = list(grouped.values())
    for actor in result:
        actor["work_ids"].sort()
        actor["languages"].sort(key=language_key)
        actor["credits"].sort(key=lambda credit: (
            credit["work_id"] if credit["work_id"] is not None else _MAX_SQLITE_INTEGER,
            language_key(credit["language"]),
            str(credit["work_title"] or "").casefold(),
        ))
        if actor["language"] is None and actor["languages"]:
            actor["language"] = actor["languages"][0]

        # Keep titles in the same deterministic order as their corresponding IDs.
        titles_by_id = {}
        for credit in actor["credits"]:
            work_id = credit["work_id"]
            title = credit["work_title"]
            if work_id is not None and title and work_id not in titles_by_id:
                titles_by_id[work_id] = title
        actor["work_titles"] = [
            titles_by_id[work_id]
            for work_id in actor["work_ids"]
            if work_id in titles_by_id
        ]

    return sorted(
        result,
        key=lambda actor: (
            0 if "Japanese" in actor["languages"] else 1,
            str(actor["name"] or "").casefold(),
            actor["person_id"],
        ),
    )

def save_staff(work_id, staff_edges, replace_snapshot=True):
    """Save staff edges; allow additional pages to be merged without deleting prior credits."""
    try:
        safe_work_id = _validated_work_id(work_id)
    except (TypeError, ValueError, OverflowError):
        return
    if not isinstance(staff_edges, (list, tuple)):
        # Missing/malformed connection shapes are not proof the work has no
        # staff. Leave existing links intact and let a later detail fetch retry.
        return

    normalized = []
    snapshot_valid = True
    for edge in staff_edges:
        if not isinstance(edge, dict):
            snapshot_valid = False
            continue
        person = edge.get("node")
        if not isinstance(person, dict):
            snapshot_valid = False
            continue
        person_id = _cast_provider_id(person.get("id"))
        name_data = person.get("name")
        person_name = name_data.get("full") if isinstance(name_data, dict) else None
        role = edge.get("role")
        if (
            person_id is None
            or not isinstance(person_name, str)
            or not person_name.strip()
            or not isinstance(role, str)
            or not role.strip()
        ):
            snapshot_valid = False
            continue

        image_data = person.get("image")
        if image_data is not None and not isinstance(image_data, dict):
            snapshot_valid = False
            image_data = {}
        image_url = image_data.get("large") if isinstance(image_data, dict) else None
        if image_url is not None and not isinstance(image_url, str):
            snapshot_valid = False
            image_url = None
        normalized.append((person_id, person_name.strip(), image_url, role.strip()))

    connection = get_connection()
    try:
        old_person_ids = set()
        if snapshot_valid and replace_snapshot:
            old_person_ids = {
                row["person_id"]
                for row in connection.execute(
                    "SELECT person_id FROM work_staff WHERE work_id = ?",
                    (safe_work_id,),
                ).fetchall()
            }
            # Only a complete snapshot may remove stale roles. Paginated pages
            # use replace_snapshot=False and only add newly encountered credits.
            connection.execute(
                "DELETE FROM work_staff WHERE work_id = ?",
                (safe_work_id,),
            )

        for person_id, person_name, image_url, role in normalized:
            connection.execute(
                """
                INSERT INTO people (id, name, image_url) VALUES (?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name,
                    image_path = CASE
                        WHEN excluded.image_url IS NOT NULL
                         AND excluded.image_url IS NOT people.image_url
                        THEN NULL ELSE people.image_path END,
                    image_url = COALESCE(excluded.image_url, people.image_url)
                """,
                (person_id, person_name, image_url),
            )
            connection.execute(
                "INSERT OR IGNORE INTO work_staff (work_id, person_id, role) VALUES (?, ?, ?)",
                (safe_work_id, person_id, role),
            )

        if snapshot_valid and replace_snapshot:
            for person_id in old_person_ids:
                still_referenced = connection.execute(
                    """
                    SELECT 1 FROM work_staff WHERE person_id = ?
                    UNION ALL
                    SELECT 1 FROM character_voice_actors WHERE person_id = ?
                    LIMIT 1
                    """,
                    (person_id, person_id),
                ).fetchone()
                if still_referenced is None:
                    connection.execute("DELETE FROM people WHERE id = ?", (person_id,))

        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def get_staff(work_id):
    try:
        safe_work_id = _validated_work_id(work_id)
    except (TypeError, ValueError, OverflowError):
        return []
    connection = get_connection()
    try:
        results = connection.execute("""
            SELECT
                people.id AS person_id,
                people.name,
                people.image_path,
                people.image_url,
                (
                    SELECT group_concat(role, char(10))
                    FROM (
                        SELECT DISTINCT role
                        FROM work_staff AS ws
                        WHERE ws.work_id = ? AND ws.person_id = people.id
                        ORDER BY role
                    )
                ) AS role
            FROM people
            WHERE EXISTS (
                SELECT 1
                FROM work_staff AS ws
                WHERE ws.work_id = ? AND ws.person_id = people.id
            )
            ORDER BY people.name
        """, (safe_work_id, safe_work_id)).fetchall()
        from recommendation_engine import staff_role_weight
        return sorted(
            results,
            key=lambda row: (
                -max(
                    (staff_role_weight(role) for role in str(row["role"] or "").split("\n")),
                    default=0.30,
                ),
                str(row["name"] or "").casefold(),
            ),
        )
    finally:
        connection.close()

def save_episodes(work_id, episode_data):
    """Upsert episode metadata without erasing useful cached/user-owned fields."""
    safe_work_id = _validated_work_id(work_id)
    try:
        episodes = list(episode_data or [])
    except TypeError:
        episodes = []

    def valid_episode_number(value):
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            number = value
        elif isinstance(value, float):
            if not math.isfinite(value) or not value.is_integer():
                return None
            number = int(value)
        elif isinstance(value, str):
            text = value.strip()
            if not text or len(text) > 7 or not re.fullmatch(r"[0-9]+", text):
                return None
            try:
                number = int(text)
            except (TypeError, ValueError, OverflowError):
                return None
        else:
            return None
        return number if 1 <= number <= _MAX_TRACKED_EPISODE_NUMBER else None

    def optional_text(value):
        if not isinstance(value, str):
            return None
        return value.strip() or None

    connection = get_connection()
    try:
        for episode in episodes:
            if not isinstance(episode, dict):
                continue
            number = valid_episode_number(episode.get("episodeNumber"))
            if number is None:
                continue

            incoming_thumbnail = optional_text(episode.get("thumbnail"))
            existing = connection.execute(
                """
                SELECT thumbnail_url
                FROM episodes
                WHERE work_id = ? AND episode_number = ?
                """,
                (safe_work_id, number),
            ).fetchone()
            existing_thumbnail = (
                str(existing["thumbnail_url"]).strip()
                if existing and existing["thumbnail_url"]
                else None
            )

            # Once a thumbnail has been downloaded locally, never replace it
            # with the provider's remote URL during a normal metadata refresh.
            if (
                existing_thumbnail
                and Path(existing_thumbnail).is_file()
                and (
                    not incoming_thumbnail
                    or not Path(incoming_thumbnail).is_file()
                )
            ):
                thumbnail = existing_thumbnail
            else:
                thumbnail = incoming_thumbnail

            connection.execute("""
                INSERT INTO episodes (
                    work_id, episode_number, title, description, air_date, thumbnail_url
                )
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(work_id, episode_number) DO UPDATE SET
                    title = COALESCE(excluded.title, episodes.title),
                    description = COALESCE(excluded.description, episodes.description),
                    air_date = COALESCE(excluded.air_date, episodes.air_date),
                    thumbnail_url = COALESCE(excluded.thumbnail_url, episodes.thumbnail_url)
            """, (
                safe_work_id,
                number,
                optional_text(episode.get("title")),
                optional_text(episode.get("description")),
                optional_text(episode.get("airdate")),
                thumbnail,
            ))
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def prune_episode_catalog(work_id, episode_data):
    """Remove stale episode rows after a verified replacement catalog loads.

    Rows with the same episode number remain, preserving their watched state.
    Empty or invalid provider responses never prune existing data.
    """
    safe_work_id = _validated_work_id(work_id)
    try:
        episodes = list(episode_data or [])
    except TypeError:
        return 0

    valid_numbers = set()
    for episode in episodes:
        if not isinstance(episode, dict):
            continue
        number = _safe_optional_integer(
            episode.get("episodeNumber"), 1, _MAX_TRACKED_EPISODE_NUMBER
        )
        if number is not None:
            valid_numbers.add(number)
    if not valid_numbers:
        return 0

    numbers = sorted(valid_numbers)
    placeholders = ", ".join("?" for _ in numbers)
    params = (safe_work_id, *numbers)
    connection = get_connection()
    try:
        connection.execute(
            f"""
            DELETE FROM release_reminders
            WHERE work_id = ? AND episode_number NOT IN ({placeholders})
            """,
            params,
        )
        cursor = connection.execute(
            f"""
            DELETE FROM episodes
            WHERE work_id = ? AND episode_number NOT IN ({placeholders})
            """,
            params,
        )
        connection.execute(
            """
            UPDATE user_library
            SET progress_episodes = MIN(COALESCE(progress_episodes, 0), ?)
            WHERE work_id = ?
            """,
            (len(numbers), safe_work_id),
        )
        connection.commit()
        return max(0, int(cursor.rowcount))
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def get_episodes(work_id):
    try:
        safe_work_id = _validated_work_id(work_id)
    except (TypeError, ValueError, OverflowError):
        return []
    connection = get_connection()
    try:
        return connection.execute(
            "SELECT * FROM episodes WHERE work_id = ? ORDER BY episode_number",
            (safe_work_id,),
        ).fetchall()
    finally:
        connection.close()


def _reading_item_type(value):
    value = str(value or "").strip().lower()
    if value not in {"chapter", "volume"}:
        raise ValueError("Reading item type must be 'chapter' or 'volume'.")
    return value


def get_reading_progress(work_id, item_type, total_hint=None):
    """Return durable aggregate read progress and the best available total."""
    kind = _reading_item_type(item_type)
    try:
        safe_work_id = _validated_work_id(work_id)
    except (TypeError, ValueError, OverflowError):
        return 0, 0

    progress_column = (
        "progress_chapters" if kind == "chapter" else "progress_volumes"
    )
    connection = get_connection()
    try:
        row = connection.execute(
            f"""
            SELECT COALESCE(
                (SELECT read_count FROM reading_progress
                 WHERE work_id = ? AND item_type = ?),
                (SELECT {progress_column} FROM user_library
                 WHERE work_id = ?),
                0
            ) AS read_count
            """,
            (safe_work_id, kind, safe_work_id),
        ).fetchone()
        item_row = connection.execute(
            """
            SELECT COALESCE(MAX(item_number), 0) AS highest_item
            FROM reading_items
            WHERE work_id = ? AND item_type = ?
            """,
            (safe_work_id, kind),
        ).fetchone()
    finally:
        connection.close()

    hinted_total = (
        _safe_optional_integer(total_hint, 0, _MAX_TRACKED_EPISODE_NUMBER)
        if total_hint is not None else None
    )
    stored_total = int(item_row["highest_item"] or 0) if item_row else 0
    total = (
        hinted_total if hinted_total is not None and hinted_total > 0
        else stored_total
    )
    return (int(row["read_count"] or 0) if row else 0), total


def set_reading_progress_count(work_id, item_type, read_count, total_hint=None):
    """Save chapter/volume progress durably without generating per-item placeholders."""
    kind = _reading_item_type(item_type)
    try:
        safe_work_id = _validated_work_id(work_id)
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError("Work ID must be a non-zero SQLite-safe integer.") from error

    parsed_count = _safe_optional_integer(
        read_count, 0, _MAX_TRACKED_EPISODE_NUMBER
    )
    if parsed_count is None or isinstance(read_count, bool):
        raise ValueError("Read progress must be a non-negative integer.")

    parsed_total = (
        _safe_optional_integer(total_hint, 0, _MAX_TRACKED_EPISODE_NUMBER)
        if total_hint is not None else None
    )
    if parsed_total is not None and parsed_total > 0:
        parsed_count = min(parsed_count, parsed_total)

    progress_column = (
        "progress_chapters" if kind == "chapter" else "progress_volumes"
    )
    connection = get_connection()
    try:
        connection.execute(
            """
            INSERT INTO reading_progress (work_id, item_type, read_count, updated_date)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(work_id, item_type) DO UPDATE SET
                read_count = excluded.read_count,
                updated_date = CURRENT_TIMESTAMP
            """,
            (safe_work_id, kind, parsed_count),
        )
        connection.execute(
            f"""
            UPDATE user_library
            SET {progress_column} = ?, updated_date = CURRENT_TIMESTAMP
            WHERE work_id = ?
            """,
            (parsed_count, safe_work_id),
        )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    return get_reading_progress(safe_work_id, kind, parsed_total)


def save_episode_thumbnail_path(work_id, episode_number, thumbnail_path):
    """Persist the local cached image path for one episode."""
    try:
        safe_work_id = _validated_work_id(work_id)
    except (TypeError, ValueError, OverflowError):
        return False
    if safe_work_id <= 0:
        return False
    safe_episode_number = _safe_optional_integer(
        episode_number, 1, _MAX_TRACKED_EPISODE_NUMBER
    )
    if safe_episode_number is None or isinstance(episode_number, bool):
        return False

    if thumbnail_path in (None, ""):
        stored_path = None
    elif isinstance(thumbnail_path, (str, Path)):
        stored_path = str(thumbnail_path).strip() or None
        if stored_path is not None and len(stored_path) > 4096:
            return False
    else:
        return False

    connection = get_connection()
    try:
        cursor = connection.execute(
            """
            UPDATE episodes
            SET thumbnail_url = ?
            WHERE work_id = ? AND episode_number = ?
            """,
            (stored_path, safe_work_id, safe_episode_number),
        )
        connection.commit()
        return cursor.rowcount > 0
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def set_episode_watched(work_id, episode_number, watched):
    """Set one episode's watched state after validating the local IDs."""
    try:
        safe_work_id = _validated_work_id(work_id)
    except (TypeError, ValueError, OverflowError):
        return 0, 0

    safe_episode_number = _safe_optional_integer(
        episode_number,
        1,
        _MAX_TRACKED_EPISODE_NUMBER,
    )
    if safe_episode_number is None or isinstance(episode_number, bool):
        return 0, 0

    connection = get_connection()
    try:
        connection.execute(
            """
            UPDATE episodes SET watched = ?
            WHERE work_id = ? AND episode_number = ?
            """,
            (1 if watched else 0, safe_work_id, safe_episode_number),
        )
        watched_count = connection.execute(
            "SELECT COUNT(*) FROM episodes WHERE work_id = ? AND watched = 1",
            (safe_work_id,),
        ).fetchone()[0]
        total = connection.execute(
            "SELECT COUNT(*) FROM episodes WHERE work_id = ?",
            (safe_work_id,),
        ).fetchone()[0]
        if connection.execute(
            "SELECT 1 FROM user_library WHERE work_id = ?",
            (safe_work_id,),
        ).fetchone():
            status = (
                "Completed" if total and watched_count >= total
                else "Watching" if watched_count
                else "Planning"
            )
            connection.execute(
                """
                UPDATE user_library
                SET progress_episodes = ?, status = ?, updated_date = CURRENT_TIMESTAMP
                WHERE work_id = ?
                """,
                (watched_count, status, safe_work_id),
            )
        connection.commit()
        return watched_count, total
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()



def set_episode_progress(work_id, watched_episode_numbers):
    """Set watched progress for an ordered selection of episode primary keys.

    The caller converts a display-order progress value to saved episode IDs.
    Rows not included are set unwatched so a user can move progress backwards.
    """
    try:
        safe_work_id = _validated_work_id(work_id)
    except (TypeError, ValueError, OverflowError):
        return 0, 0

    try:
        values = list(watched_episode_numbers or [])
    except TypeError:
        values = []
    safe_numbers = []
    seen = set()
    for value in values:
        number = _safe_optional_integer(
            value, 1, _MAX_TRACKED_EPISODE_NUMBER
        )
        if number is None or isinstance(value, bool) or number in seen:
            continue
        seen.add(number)
        safe_numbers.append(number)

    connection = get_connection()
    try:
        connection.execute(
            "UPDATE episodes SET watched = 0 WHERE work_id = ?",
            (safe_work_id,),
        )
        connection.executemany(
            """
            UPDATE episodes SET watched = 1
            WHERE work_id = ? AND episode_number = ?
            """,
            ((safe_work_id, number) for number in safe_numbers),
        )
        watched_count = connection.execute(
            "SELECT COUNT(*) FROM episodes WHERE work_id = ? AND watched = 1",
            (safe_work_id,),
        ).fetchone()[0]
        total = connection.execute(
            "SELECT COUNT(*) FROM episodes WHERE work_id = ?",
            (safe_work_id,),
        ).fetchone()[0]
        if connection.execute(
            "SELECT 1 FROM user_library WHERE work_id = ?",
            (safe_work_id,),
        ).fetchone():
            status = (
                "Completed" if total and watched_count >= total
                else "Watching" if watched_count
                else "Planning"
            )
            connection.execute(
                """
                UPDATE user_library
                SET progress_episodes = ?, status = ?, updated_date = CURRENT_TIMESTAMP
                WHERE work_id = ?
                """,
                (watched_count, status, safe_work_id),
            )
        connection.commit()
        return watched_count, total
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def get_provider_metadata(work_id, provider="mangabaka"):
    """Return preserved raw metadata for a work and provider, if available."""
    try:
        safe_work_id = _validated_work_id(work_id)
        normalized_provider = str(provider).strip().lower()
    except (TypeError, ValueError, OverflowError):
        return None
    if not normalized_provider:
        return None

    connection = get_connection()
    try:
        row = connection.execute(
            "SELECT payload_json FROM work_provider_metadata WHERE work_id = ? AND provider = ?",
            (safe_work_id, normalized_provider),
        ).fetchone()
    finally:
        connection.close()
    if not row:
        return None
    try:
        payload = json.loads(row["payload_json"])
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, (dict, list)) else None


def save_provider_metadata(work_id, provider, payload, provider_id=None):
    """Persist a JSON-compatible provider payload before opening a DB connection."""
    safe_work_id = _validated_work_id(work_id)
    normalized_provider = str(provider).strip().lower()
    if not normalized_provider:
        raise ValueError("A provider name is required.")
    if not isinstance(payload, (dict, list)):
        raise ValueError("Provider metadata must be a JSON object or array.")
    try:
        payload_json = json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError, OverflowError, RecursionError) as error:
        raise ValueError("Provider metadata is not valid JSON data.") from error

    connection = get_connection()
    try:
        connection.execute("""
            INSERT INTO work_provider_metadata (work_id, provider, provider_id, payload_json, updated_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(work_id, provider) DO UPDATE SET
                provider_id = COALESCE(excluded.provider_id, work_provider_metadata.provider_id),
                payload_json = excluded.payload_json,
                updated_at = CURRENT_TIMESTAMP
        """, (
            safe_work_id,
            normalized_provider,
            str(provider_id) if provider_id is not None else None,
            payload_json,
        ))
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def save_reading_item_metadata(work_id, item_type, items):
    """Merge bounded provider reading-item metadata without disturbing progress."""
    safe_work_id = _validated_work_id(work_id)
    kind = str(item_type or "").strip().lower()
    if kind not in {"chapter", "volume"}:
        raise ValueError("item_type must be chapter or volume")
    if not isinstance(items, (list, tuple)):
        return 0

    def parse_item_number(raw_number):
        if isinstance(raw_number, bool):
            return None
        if isinstance(raw_number, (int, float)):
            try:
                numeric = float(raw_number)
                if not math.isfinite(numeric) or not numeric.is_integer() or numeric < 1:
                    return None
                number = int(numeric)
            except (TypeError, ValueError, OverflowError):
                return None
        else:
            if not isinstance(raw_number, str):
                return None
            raw_text = raw_number.strip()
            if re.fullmatch(r"[0-9]+(?:\\.[0-9]+)?", raw_text):
                try:
                    numeric = float(raw_text)
                    if not math.isfinite(numeric) or not numeric.is_integer() or numeric < 1:
                        return None
                    number = int(numeric)
                except (TypeError, ValueError, OverflowError):
                    return None
            else:
                match = re.search(r"(?<![-0-9])\\d+", raw_text)
                if not match:
                    return None
                try:
                    number = int(match.group(0))
                except (TypeError, ValueError, OverflowError):
                    return None
        return number if 1 <= number <= _MAX_TRACKED_EPISODE_NUMBER else None

    connection = get_connection()
    saved = 0
    try:
        for index, item in enumerate(items, start=1):
            if not isinstance(item, dict):
                continue
            raw_number = None
            has_explicit_number = False
            for key in ("number", "item_number", "volume_number", "chapter_number"):
                candidate = item.get(key)
                if candidate not in (None, ""):
                    raw_number = candidate
                    has_explicit_number = True
                    break

            number = index if not has_explicit_number else parse_item_number(raw_number)
            if number is None or not 1 <= number <= _MAX_TRACKED_EPISODE_NUMBER:
                continue

            title_value = item.get("title")
            if not isinstance(title_value, str) or not title_value.strip():
                title_value = item.get("name")
            title = title_value.strip() if isinstance(title_value, str) else None
            connection.execute("""
                INSERT INTO reading_items (work_id, item_type, item_number, title, is_read)
                VALUES (?, ?, ?, ?, 0)
                ON CONFLICT(work_id, item_type, item_number) DO UPDATE SET
                    title = CASE
                        WHEN excluded.title IS NOT NULL AND TRIM(excluded.title) != ''
                        THEN excluded.title ELSE reading_items.title END
            """, (safe_work_id, kind, number, title or None))
            saved += 1
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    return saved



def save_anime(anime):
    work_id = _validated_work_id(anime.get("id") if isinstance(anime, dict) else None)
    # Reconcile outgoing relations only when a complete, well-formed edge list
    # is present. Search/partial records may omit relations entirely, and a
    # malformed response must not erase previously cached relationships.
    # Like relations, studio associations come from a connection that can
    # be missing on lightweight records. Reconcile them only when a complete,
    # well-formed snapshot is supplied.
    studio_snapshot_valid = None
    studios_data = anime.get("studios")
    studio_edges = studios_data.get("edges") if isinstance(studios_data, dict) else None
    if isinstance(studio_edges, list):
        studio_snapshot_valid = True
        for edge in studio_edges:
            if not isinstance(edge, dict):
                studio_snapshot_valid = False
                break
            studio = edge.get("node")
            if not isinstance(studio, dict):
                studio_snapshot_valid = False
                break
            studio_id = studio.get("id")
            studio_name = studio.get("name")
            if (
                isinstance(studio_id, bool)
                or isinstance(studio_id, float) and not studio_id.is_integer()
                or isinstance(studio_id, str) and not re.fullmatch(r"\s*[0-9]+\s*", studio_id)
                or not isinstance(studio_name, str)
                or not studio_name.strip()
            ):
                studio_snapshot_valid = False
                break
            try:
                studio_id = int(studio_id)
            except (TypeError, ValueError, OverflowError):
                studio_snapshot_valid = False
                break
            if studio_id <= 0 or studio_id > _MAX_SQLITE_INTEGER:
                studio_snapshot_valid = False
                break

    relation_snapshot = None
    relations = anime.get("relations")
    relation_edges = relations.get("edges") if isinstance(relations, dict) else None
    if isinstance(relation_edges, list):
        snapshot = set()
        complete_snapshot = True
        for edge in relation_edges:
            if not isinstance(edge, dict):
                complete_snapshot = False
                break
            node = edge.get("node")
            target_id = node.get("id") if isinstance(node, dict) else None
            relation_type = edge.get("relationType")
            if (
                isinstance(target_id, bool)
                or not isinstance(relation_type, str)
                or not relation_type.strip()
                or len(relation_type.strip()) > 64
                or (isinstance(target_id, float) and not target_id.is_integer())
                or (
                    isinstance(target_id, str)
                    and (
                        len(target_id.strip()) > 20
                        or not target_id.strip().isascii()
                        or not re.fullmatch(r"\s*[+-]?[0-9]+\s*", target_id)
                    )
                )
            ):
                complete_snapshot = False
                break
            try:
                target_id = int(target_id)
            except (TypeError, ValueError, OverflowError):
                complete_snapshot = False
                break
            if (
                target_id == 0
                or target_id < _MIN_SQLITE_INTEGER
                or target_id > _MAX_SQLITE_INTEGER
                or (target_id < 0 and work_id >= 0)
            ):
                complete_snapshot = False
                break

            # Relations are only a complete snapshot when each referenced node
            # has a usable title. Otherwise a sparse provider payload could
            # falsely remove cached edges during reconciliation.
            node_title = node.get("title") if isinstance(node, dict) else None
            has_node_title = isinstance(node_title, dict) and any(
                isinstance(value, str) and value.strip()
                for value in (
                    node_title.get("english"),
                    node_title.get("romaji"),
                    node_title.get("native"),
                )
            )
            if not has_node_title:
                complete_snapshot = False
                break
            snapshot.add((target_id, relation_type))
        if complete_snapshot:
            relation_snapshot = snapshot

    title_data = anime.get("title")
    if isinstance(title_data, dict):
        title = next(
            (
                candidate.strip()
                for candidate in (
                    title_data.get("english"),
                    title_data.get("romaji"),
                    title_data.get("native"),
                )
                if isinstance(candidate, str) and candidate.strip()
            ),
            None,
        )
    elif isinstance(title_data, str):
        title = title_data.strip() or None
    else:
        title = None
    if not title:
        raise ValueError("A work record must include a non-empty title.")

    start_date = anime.get("startDate")
    if not isinstance(start_date, dict):
        start_date = {}
    start_year = _safe_optional_integer(start_date.get("year"), 1, 9999)
    start_month = _safe_optional_integer(start_date.get("month"), 1, 12)
    start_day = _safe_optional_integer(start_date.get("day"), 1, 31)

    cover_image = anime.get("coverImage")
    if not isinstance(cover_image, dict):
        cover_image = {}
    cover_url = cover_image.get("large")
    if not isinstance(cover_url, str):
        cover_url = None

    end_date = anime.get("endDate")
    if not isinstance(end_date, dict):
        end_date = {}
    end_year = _safe_optional_integer(end_date.get("year"), 1, 9999)

    raw_type = anime.get("type")
    normalized_type = raw_type.strip().upper() if isinstance(raw_type, str) else ""
    type_is_valid = normalized_type in {"ANIME", "MANGA"}
    # Unknown strings aren't valid MediaType values. Existing records retain
    # their previous type through the upsert flag; newly inserted records use
    # the schema-safe ANIME fallback instead of persisting arbitrary provider text.
    media_type = normalized_type if type_is_valid else "ANIME"

    description = anime.get("description")
    if not isinstance(description, str):
        description = None

    valid_formats = {
        "TV", "TV_SHORT", "MOVIE", "SPECIAL", "OVA", "ONA", "MUSIC",
        "MANGA", "NOVEL", "ONE_SHOT",
    }
    raw_format = anime.get("format")
    normalized_format = raw_format.strip().upper() if isinstance(raw_format, str) else ""
    media_format = normalized_format if normalized_format in valid_formats else None
    source = anime.get("source")
    if not isinstance(source, str):
        source = None

    episodes = _safe_optional_integer(anime.get("episodes"))
    score = _safe_optional_score(anime.get("averageScore"))
    chapters = _safe_optional_integer(anime.get("chapters"))
    volumes = _safe_optional_integer(anime.get("volumes"))
    duration = _safe_optional_integer(anime.get("duration"))
    mal_id = _safe_optional_integer(anime.get("idMal"), 1)

    # Provider-native JSON is useful when it is valid, but it is optional.
    # Non-JSON objects, circular references, non-finite floats, or deeply
    # nested payloads must not abort otherwise usable metadata persistence.
    mangabaka_data = anime.get("_mangabaka")
    mangabaka_payload_json = None
    if isinstance(mangabaka_data, dict):
        try:
            mangabaka_payload_json = json.dumps(
                mangabaka_data,
                ensure_ascii=False,
                allow_nan=False,
            )
        except (TypeError, ValueError, OverflowError, RecursionError):
            mangabaka_data = None

    connection = get_connection()
    try:
        connection.execute("""
            INSERT INTO works (
                id, title, type, description, episodes, score, start_year, start_month, start_day,
                cover_url, format, chapters, volumes, source, end_year, duration, mal_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                title=excluded.title,
                type=CASE WHEN ? THEN excluded.type ELSE works.type END,
                description=COALESCE(excluded.description, works.description),
                episodes=COALESCE(excluded.episodes, works.episodes),
                score=COALESCE(excluded.score, works.score),
                start_year=CASE
                    WHEN excluded.start_year IS NULL
                     AND excluded.start_month IS NULL
                     AND excluded.start_day IS NULL
                    THEN works.start_year ELSE excluded.start_year END,
                start_month=CASE
                    WHEN excluded.start_year IS NULL
                     AND excluded.start_month IS NULL
                     AND excluded.start_day IS NULL
                    THEN works.start_month ELSE excluded.start_month END,
                start_day=CASE
                    WHEN excluded.start_year IS NULL
                     AND excluded.start_month IS NULL
                     AND excluded.start_day IS NULL
                    THEN works.start_day ELSE excluded.start_day END,
                cover_url=COALESCE(excluded.cover_url, works.cover_url),
                format=COALESCE(excluded.format, works.format),
                chapters=COALESCE(excluded.chapters, works.chapters),
                volumes=COALESCE(excluded.volumes, works.volumes),
                source=COALESCE(excluded.source, works.source),
                end_year=COALESCE(excluded.end_year, works.end_year),
                duration=COALESCE(excluded.duration, works.duration),
                mal_id=COALESCE(excluded.mal_id, works.mal_id)
        """, (
            work_id, title, media_type, description,
            episodes, score,
            start_year, start_month, start_day, cover_url,
            media_format, chapters, volumes,
            source, end_year, duration, mal_id,
            1 if type_is_valid else 0,
        ))
        synonyms = anime.get("synonyms")
        if isinstance(synonyms, (list, tuple)):
            for synonym in synonyms:
                if not isinstance(synonym, str) or not synonym.strip():
                    continue
                connection.execute(
                    "INSERT OR IGNORE INTO alternate_titles (work_id, title, language) VALUES (?, ?, ?)",
                    (work_id, synonym.strip(), None),
                )

        # Preserve provider-native metadata instead of flattening it into AniList fields.
        if isinstance(mangabaka_data, dict) and mangabaka_payload_json is not None:
            mangabaka_id = anime.get("_mangabaka_id") or mangabaka_data.get("id")
            connection.execute("""
                INSERT INTO work_provider_metadata (work_id, provider, provider_id, payload_json, updated_at)
                VALUES (?, 'mangabaka', ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(work_id, provider) DO UPDATE SET
                    provider_id = COALESCE(excluded.provider_id, work_provider_metadata.provider_id),
                    payload_json = excluded.payload_json,
                    updated_at = CURRENT_TIMESTAMP
            """, (
                work_id,
                str(mangabaka_id) if mangabaka_id is not None else None,
                mangabaka_payload_json,
            ))
            title_records = mangabaka_data.get("titles") or []
            for title_record in title_records:
                if not isinstance(title_record, dict):
                    continue
                raw_alt_title = title_record.get("title")
                if not isinstance(raw_alt_title, str):
                    continue
                alt_title = raw_alt_title.strip()
                if not alt_title or alt_title.casefold() == title.casefold():
                    continue
                language = title_record.get("language")
                if not isinstance(language, str):
                    language = None
                connection.execute(
                    "INSERT OR IGNORE INTO alternate_titles (work_id, title, language) VALUES (?, ?, ?)",
                    (work_id, alt_title, language),
                )
        if studio_snapshot_valid is True:
            connection.execute(
                "DELETE FROM work_studios WHERE work_id = ?",
                (work_id,),
            )

        for edge in studio_edges if isinstance(studio_edges, list) else []:
            if not isinstance(edge, dict):
                continue
            studio = edge.get("node")
            if not isinstance(studio, dict):
                continue
            studio_id = studio.get("id")
            studio_name = studio.get("name")
            if (
                isinstance(studio_id, bool)
                or isinstance(studio_id, float) and not studio_id.is_integer()
                or isinstance(studio_id, str) and not re.fullmatch(r"\s*[0-9]+\s*", studio_id)
                or not isinstance(studio_name, str)
                or not studio_name.strip()
            ):
                continue
            try:
                studio_id = int(studio_id)
            except (TypeError, ValueError, OverflowError):
                continue
            if studio_id <= 0 or studio_id > _MAX_SQLITE_INTEGER:
                continue
            connection.execute(
                "INSERT OR REPLACE INTO studios (id, name, is_main) VALUES (?, ?, ?)",
                (studio_id, studio_name.strip(), 1 if edge.get("isMain") else 0),
            )
            connection.execute(
                "INSERT OR IGNORE INTO work_studios (work_id, studio_id) VALUES (?, ?)",
                (work_id, studio_id),
            )
        if relation_snapshot is not None:
            # Relation details are a cached snapshot, not an append-only history.
            # Delete stale outgoing edges within this transaction before writing
            # the current list. A valid empty list intentionally clears all edges.
            connection.execute(
                "DELETE FROM work_relations WHERE source_id = ?",
                (work_id,),
            )

        for edge in relation_edges if isinstance(relation_edges, list) else []:
            if not isinstance(edge, dict):
                continue
            node = edge.get("node")
            if not isinstance(node, dict):
                continue
            target_id = node.get("id")
            relation_type = edge.get("relationType")
            if (
                isinstance(target_id, bool)
                or not isinstance(relation_type, str)
                or not relation_type.strip()
                or len(relation_type.strip()) > 64
                or (isinstance(target_id, float) and not target_id.is_integer())
                or (isinstance(target_id, str) and (
                    len(target_id.strip()) > 20
                    or not target_id.strip().isascii()
                    or not re.fullmatch(r"\s*[+-]?[0-9]+\s*", target_id)
                ))
            ):
                continue
            relation_type = relation_type.strip().upper()
            try:
                target_id = int(target_id)
            except (TypeError, ValueError, OverflowError):
                continue
            if (
                target_id == 0
                or target_id < _MIN_SQLITE_INTEGER
                or target_id > _MAX_SQLITE_INTEGER
                or (target_id < 0 and work_id >= 0)
            ):
                continue

            target_title_data = node.get("title")
            if not isinstance(target_title_data, dict):
                target_title_data = {}
            target_title = next(
                (
                    value.strip()
                    for value in (
                        target_title_data.get("english"),
                        target_title_data.get("romaji"),
                        target_title_data.get("native"),
                    )
                    if isinstance(value, str) and value.strip()
                ),
                None,
            )
            if not target_title:
                # Do not cache dangling graph edges when the provider omitted
                # the referenced work's identifying title fields.
                continue
            if target_title:
                target_start_date = node.get("startDate")
                if not isinstance(target_start_date, dict):
                    target_start_date = {}
                cover_image = node.get("coverImage")
                if not isinstance(cover_image, dict):
                    cover_image = {}

                raw_target_type = node.get("type")
                normalized_target_type = (
                    raw_target_type.strip().upper()
                    if isinstance(raw_target_type, str)
                    else ""
                )
                target_type_is_valid = normalized_target_type in {"ANIME", "MANGA"}
                target_type = normalized_target_type if target_type_is_valid else "ANIME"

                valid_formats = {
                    "TV", "TV_SHORT", "MOVIE", "SPECIAL", "OVA", "ONA", "MUSIC",
                    "MANGA", "NOVEL", "ONE_SHOT",
                }
                raw_target_format = node.get("format")
                normalized_target_format = (
                    raw_target_format.strip().upper()
                    if isinstance(raw_target_format, str)
                    else ""
                )
                target_format = (
                    normalized_target_format
                    if normalized_target_format in valid_formats
                    else None
                )
                target_start_year = _safe_optional_integer(target_start_date.get("year"), 1, 9999)
                target_start_month = _safe_optional_integer(target_start_date.get("month"), 1, 12)
                target_start_day = _safe_optional_integer(target_start_date.get("day"), 1, 31)
                target_cover_url = cover_image.get("large")
                if (
                    not isinstance(target_cover_url, str)
                    or not target_cover_url.strip()
                    or len(target_cover_url) > 4096
                ):
                    target_cover_url = None
                else:
                    target_cover_url = target_cover_url.strip()
                target_mal_id = _safe_optional_integer(node.get("idMal"), 1)

                connection.execute("""
                    INSERT INTO works (
                        id, title, type, format, start_year, start_month, start_day,
                        cover_url, mal_id
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        title = excluded.title,
                        type = CASE
                            WHEN ? THEN excluded.type ELSE works.type END,
                        format = COALESCE(excluded.format, works.format),
                        start_year = CASE
                            WHEN excluded.start_year IS NULL
                             AND excluded.start_month IS NULL
                             AND excluded.start_day IS NULL
                            THEN works.start_year ELSE excluded.start_year END,
                        start_month = CASE
                            WHEN excluded.start_year IS NULL
                             AND excluded.start_month IS NULL
                             AND excluded.start_day IS NULL
                            THEN works.start_month ELSE excluded.start_month END,
                        start_day = CASE
                            WHEN excluded.start_year IS NULL
                             AND excluded.start_month IS NULL
                             AND excluded.start_day IS NULL
                            THEN works.start_day ELSE excluded.start_day END,
                        cover_url = COALESCE(excluded.cover_url, works.cover_url),
                        mal_id = COALESCE(excluded.mal_id, works.mal_id)
                """, (
                    target_id,
                    target_title,
                    target_type,
                    target_format,
                    target_start_year,
                    target_start_month,
                    target_start_day,
                    target_cover_url,
                    target_mal_id,
                    1 if target_type_is_valid else 0,
                ))
            connection.execute(
                "INSERT OR REPLACE INTO work_relations (source_id, target_id, relation_type) VALUES (?, ?, ?)",
                (work_id, target_id, relation_type),
            )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()

def save_cover_path(work_id, cover_path):
    try:
        safe_work_id = _validated_work_id(work_id)
    except (TypeError, ValueError, OverflowError):
        return False
    if cover_path in (None, ""):
        stored_path = None
    elif isinstance(cover_path, (str, Path)):
        stored_path = str(cover_path).strip() or None
        if stored_path is not None and len(stored_path) > 4096:
            return False
    else:
        return False

    connection = get_connection()
    try:
        cursor = connection.execute(
            "UPDATE works SET cover_path = ? WHERE id = ?",
            (stored_path, safe_work_id),
        )
        connection.commit()
        return cursor.rowcount > 0
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def get_saved_anime():
    connection = get_connection()
    results = connection.execute("SELECT * FROM works ORDER BY title").fetchall()
    connection.close()
    return results


def get_alternate_titles(work_id):
    """Return locally stored alternate titles for one work."""
    try:
        safe_work_id = _validated_work_id(work_id)
    except (TypeError, ValueError, OverflowError):
        return []
    connection = get_connection()
    try:
        rows = connection.execute(
            """
            SELECT title
            FROM alternate_titles
            WHERE work_id = ?
            ORDER BY rowid
            """,
            (safe_work_id,),
        ).fetchall()
    finally:
        connection.close()
    return [str(row["title"]) for row in rows if str(row["title"] or "").strip()]


def is_work_in_library(work_id):
    """Return actual user-library membership, separate from provider publication status."""
    try:
        safe_work_id = _validated_work_id(work_id)
    except (TypeError, ValueError, OverflowError):
        return False
    connection = get_connection()
    try:
        return connection.execute(
            "SELECT 1 FROM user_library WHERE work_id = ? LIMIT 1",
            (safe_work_id,),
        ).fetchone() is not None
    finally:
        connection.close()


def get_work(work_id):
    try:
        safe_work_id = _validated_work_id(work_id)
    except (TypeError, ValueError, OverflowError):
        return None
    connection = get_connection()
    try:
        return connection.execute("""
            SELECT works.*, user_library.status, user_library.progress_episodes,
                   user_library.progress_chapters, user_library.progress_volumes,
                   user_library.rating, user_library.notes,
                   user_library.added_date, user_library.updated_date
            FROM works LEFT JOIN user_library ON user_library.work_id = works.id
            WHERE works.id = ?
        """, (safe_work_id,)).fetchone()
    finally:
        connection.close()


def get_relations(work_id):
    try:
        safe_work_id = _validated_work_id(work_id)
    except (TypeError, ValueError, OverflowError):
        return []
    connection = get_connection()
    try:
        return connection.execute("""
            SELECT work_relations.*, works.title, works.format, works.type, works.cover_url, works.cover_path
            FROM work_relations LEFT JOIN works ON works.id = work_relations.target_id
            WHERE work_relations.source_id = ? ORDER BY relation_type, title
        """, (safe_work_id,)).fetchall()
    finally:
        connection.close()


def _bundle_member_work_ids(work_ids):
    """Return valid work IDs in first-seen order for bundle aggregation."""
    try:
        iterator = iter(work_ids or [])
    except (TypeError, ValueError):
        return []
    result, seen = [], set()
    for value in iterator:
        try:
            work_id = _validated_work_id(value)
        except (TypeError, ValueError, OverflowError):
            continue
        if work_id not in seen:
            seen.add(work_id)
            result.append(work_id)
    return result


def _bundle_id_chunks(work_ids, size=400):
    """Keep IN-clause queries below SQLite's conservative parameter limit."""
    for start in range(0, len(work_ids), size):
        yield work_ids[start:start + size]


def _load_bundle_character_rows(work_ids):
    """Load per-work character and voice-actor rows with batched SQL queries."""
    rows_by_work = {}
    if not work_ids:
        return rows_by_work
    connection = get_connection()
    try:
        for chunk in _bundle_id_chunks(work_ids):
            placeholders = ",".join("?" for _ in chunk)
            query = f"""
                WITH ranked_actors AS (
                    SELECT
                        wcv.work_id, wcv.character_id,
                        people.id AS person_id,
                        people.name AS person_name,
                        people.image_path AS person_image_path,
                        people.image_url AS person_image_url,
                        wcv.language AS person_language,
                        ROW_NUMBER() OVER (
                            PARTITION BY wcv.work_id, wcv.character_id
                            ORDER BY
                                CASE
                                    WHEN LOWER(COALESCE(wcv.language, ''))
                                         IN ('japanese', 'ja', 'jpn') THEN 0
                                    ELSE 1
                                END,
                                wcv.language, people.name
                        ) AS actor_rank
                    FROM work_character_voice_actors AS wcv
                    JOIN people ON people.id = wcv.person_id
                    WHERE wcv.work_id IN ({placeholders})
                )
                SELECT
                    wc.work_id AS _bundle_work_id,
                    characters.id,
                    characters.name AS character_name,
                    characters.image_path AS character_image_path,
                    characters.image_url AS character_image_url,
                    wc.role AS character_role,
                    ranked_actors.person_id,
                    ranked_actors.person_name,
                    ranked_actors.person_image_path,
                    ranked_actors.person_image_url,
                    ranked_actors.person_language
                FROM work_characters AS wc
                JOIN characters ON characters.id = wc.character_id
                LEFT JOIN ranked_actors
                  ON ranked_actors.work_id = wc.work_id
                 AND ranked_actors.character_id = wc.character_id
                 AND ranked_actors.actor_rank = 1
                WHERE wc.work_id IN ({placeholders})
                ORDER BY
                    wc.work_id,
                    CASE UPPER(COALESCE(wc.role, 'UNKNOWN'))
                        WHEN 'MAIN' THEN 0 WHEN 'SUPPORTING' THEN 1
                        WHEN 'BACKGROUND' THEN 2 ELSE 3
                    END,
                    characters.name
            """
            rows = connection.execute(query, (*chunk, *chunk)).fetchall()
            for raw in rows:
                row = dict(raw)
                work_id = int(row.pop("_bundle_work_id"))
                rows_by_work.setdefault(work_id, []).append(row)
    finally:
        connection.close()
    return rows_by_work


def get_bundle_characters(work_ids):
    """Return unique characters, preferring their strongest role across a bundle."""
    ids = _bundle_member_work_ids(work_ids)
    if not ids:
        return []
    per_work_rows = _load_bundle_character_rows(ids)
    unique = {}
    role_priority = {"MAIN": 0, "SUPPORTING": 1, "BACKGROUND": 2}
    for work_id in ids:
        for raw_row in per_work_rows.get(work_id, ()):
            # Keep accepting sqlite3.Row-like payloads from alternate callers/tests.
            row = dict(raw_row)
            try:
                character_id = int(row["id"])
            except (KeyError, TypeError, ValueError, OverflowError):
                continue
            role = str(row.get("character_role") or "").upper()
            existing = unique.get(character_id)
            if existing is None:
                unique[character_id] = row
                continue
            existing_role = str(existing.get("character_role") or "").upper()
            if role_priority.get(role, 3) < role_priority.get(existing_role, 3):
                existing["character_role"] = row.get("character_role")

            def voice_priority(item):
                try:
                    person_id = int(item.get("person_id") or 0)
                except (TypeError, ValueError, OverflowError):
                    person_id = 0
                if person_id <= 0:
                    return (2, "", 0)
                language = _voice_actor_language_label(item.get("person_language"))
                return (
                    0 if language == "Japanese" else 1,
                    str(item.get("person_name") or "").casefold(),
                    person_id,
                )

            if voice_priority(row) < voice_priority(existing):
                for key in (
                    "person_id", "person_name", "person_image_path",
                    "person_image_url", "person_language",
                ):
                    existing[key] = row.get(key)
    return sorted(unique.values(), key=lambda row: (
        role_priority.get(str(row.get("character_role") or "").upper(), 3),
        str(row.get("character_name") or "").lower(),
    ))


def _load_bundle_staff_rows(work_ids):
    """Load staff rows in batches and retain each work's original row/role order."""
    grouped = {}
    if not work_ids:
        return grouped
    connection = get_connection()
    try:
        for chunk in _bundle_id_chunks(work_ids):
            placeholders = ",".join("?" for _ in chunk)
            rows = connection.execute(
                f"""
                SELECT DISTINCT
                    ws.work_id AS _bundle_work_id, people.id AS person_id,
                    people.name, people.image_path, people.image_url, ws.role
                FROM work_staff AS ws
                JOIN people ON people.id = ws.person_id
                WHERE ws.work_id IN ({placeholders})
                ORDER BY ws.work_id, people.name, people.id, ws.role
                """,
                chunk,
            ).fetchall()
            for raw in rows:
                work_id = int(raw["_bundle_work_id"])
                person_id = int(raw["person_id"])
                by_person = grouped.setdefault(work_id, {})
                entry = by_person.get(person_id)
                if entry is None:
                    entry = {
                        "person_id": person_id, "name": raw["name"],
                        "image_path": raw["image_path"], "image_url": raw["image_url"],
                        "_roles": [],
                    }
                    by_person[person_id] = entry
                if raw["role"] is not None:
                    entry["_roles"].append(str(raw["role"]))
    finally:
        connection.close()

    from recommendation_engine import staff_role_weight
    rows_by_work = {}
    for work_id, by_person in grouped.items():
        work_rows = []
        for entry in by_person.values():
            entry["role"] = "\n".join(entry.pop("_roles", []))
            work_rows.append(entry)
        work_rows.sort(key=lambda row: (
            -max(
                (staff_role_weight(role) for role in str(row.get("role") or "").split("\n")),
                default=0.30,
            ),
            str(row.get("name") or "").casefold(),
        ))
        rows_by_work[work_id] = work_rows
    return rows_by_work


def get_bundle_staff(work_ids):
    """Return one card per staff person with unique roles merged across the bundle."""
    ids = _bundle_member_work_ids(work_ids)
    if not ids:
        return []
    per_work_rows = _load_bundle_staff_rows(ids)
    unique = {}
    for work_id in ids:
        for row in per_work_rows.get(work_id, ()):
            person_id = int(row["person_id"])
            entry = unique.get(person_id)
            if entry is None:
                entry = dict(row)
                entry["_roles"] = []
                unique[person_id] = entry
            for role in str(row["role"] or "").split("\n"):
                role = role.strip()
                if role and role not in entry["_roles"]:
                    entry["_roles"].append(role)
    for entry in unique.values():
        entry["role"] = "\n".join(entry.pop("_roles", []))
    from recommendation_engine import staff_role_weight
    return sorted(unique.values(), key=lambda row: (
        -max(
            (staff_role_weight(role) for role in str(row.get("role") or "").split("\n")),
            default=0.30,
        ),
        str(row.get("name") or "").casefold(),
    ))


def get_bundle_relations(work_ids):
    """Return unique external relations from every work in a bundle."""
    ids = _validated_work_ids(work_ids)
    if not ids:
        return []
    rows_by_source = {}
    connection = get_connection()
    try:
        for chunk in _bundle_id_chunks(ids):
            placeholders = ",".join("?" for _ in chunk)
            rows = connection.execute(
                f"""
                SELECT work_relations.*, works.title, works.format, works.type,
                       works.cover_url, works.cover_path
                FROM work_relations
                LEFT JOIN works ON works.id = work_relations.target_id
                WHERE work_relations.source_id IN ({placeholders})
                ORDER BY work_relations.source_id, relation_type, title
                """,
                chunk,
            ).fetchall()
            for row in rows:
                rows_by_source.setdefault(int(row["source_id"]), []).append(row)
    finally:
        connection.close()

    unique = {}
    for work_id in ids:
        for row in rows_by_source.get(work_id, ()):
            target_id = row["target_id"]
            if target_id is None:
                continue
            target_id = int(target_id)
            if target_id in ids:
                continue
            entry = unique.get(target_id)
            if entry is None:
                entry = dict(row)
                entry["_relation_types"] = []
                unique[target_id] = entry
            relation_type = str(row["relation_type"] or "OTHER")
            if relation_type not in entry["_relation_types"]:
                entry["_relation_types"].append(relation_type)
    for entry in unique.values():
        entry["relation_types"] = "\n".join(entry.pop("_relation_types", []))
    return sorted(unique.values(), key=lambda row: str(row.get("title") or "").lower())

def add_manual_bundle_link(work_a, work_b):
    """Persist an explicit user-selected bundle link between two works."""
    try:
        work_a = _validated_work_id(work_a)
        work_b = _validated_work_id(work_b)
    except (TypeError, ValueError, OverflowError):
        return False
    work_a, work_b = sorted((work_a, work_b))
    if work_a == work_b:
        return False

    connection = get_connection()
    existing_count = connection.execute(
        "SELECT COUNT(*) FROM works WHERE id IN (?, ?)",
        (work_a, work_b),
    ).fetchone()[0]
    if existing_count != 2:
        connection.close()
        return False

    connection.execute(
        "INSERT OR IGNORE INTO manual_bundle_links (work_a, work_b) VALUES (?, ?)",
        (work_a, work_b),
    )
    connection.execute(
        "DELETE FROM bundle_exclusions WHERE work_a = ? AND work_b = ?",
        (work_a, work_b),
    )
    changed = connection.total_changes > 0
    connection.commit()
    connection.close()
    return changed


def remove_manual_bundle_link(work_a, work_b):
    try:
        work_a = _validated_work_id(work_a)
        work_b = _validated_work_id(work_b)
    except (TypeError, ValueError, OverflowError):
        return False
    work_a, work_b = sorted((work_a, work_b))
    connection = get_connection()
    try:
        cursor = connection.execute(
            "DELETE FROM manual_bundle_links WHERE work_a = ? AND work_b = ?",
            (work_a, work_b),
        )
        connection.commit()
        return cursor.rowcount > 0
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def get_manual_bundle_links(work_ids=None):
    """Return explicit bundle links, optionally limited to works touching these IDs."""
    ids = None if work_ids is None else _validated_work_ids(work_ids)
    if work_ids is not None and (ids is None or not ids):
        return []

    connection = get_connection()
    try:
        if ids is None:
            return connection.execute(
                "SELECT work_a, work_b FROM manual_bundle_links ORDER BY work_a, work_b"
            ).fetchall()

        placeholders = ",".join("?" for _ in ids)
        return connection.execute(
            f"""
            SELECT work_a, work_b
            FROM manual_bundle_links
            WHERE work_a IN ({placeholders}) OR work_b IN ({placeholders})
            ORDER BY work_a, work_b
            """,
            [*ids, *ids],
        ).fetchall()
    finally:
        connection.close()


def save_automatic_bundle_membership(bundle_id, work_ids):
    """Replace the saved member snapshot for an automatically grouped Search result."""
    try:
        safe_bundle_id = _validated_work_id(bundle_id)
    except (TypeError, ValueError, OverflowError):
        return False
    safe_ids = _validated_work_ids(work_ids)
    if safe_ids is None:
        return False

    connection = get_connection()
    try:
        connection.execute(
            "DELETE FROM automatic_bundle_memberships WHERE bundle_id = ?",
            (safe_bundle_id,),
        )
        if safe_ids:
            placeholders = ",".join("?" for _ in safe_ids)
            existing = {
                int(row["id"])
                for row in connection.execute(
                    f"SELECT id FROM works WHERE id IN ({placeholders})",
                    safe_ids,
                ).fetchall()
            }
        else:
            existing = set()
        member_ids = sorted(existing)
        if len(member_ids) >= 2:
            connection.executemany(
                """
                INSERT OR IGNORE INTO automatic_bundle_memberships (bundle_id, work_id)
                VALUES (?, ?)
                """,
                [(safe_bundle_id, work_id) for work_id in member_ids],
            )
        connection.commit()
        return True
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def get_automatic_bundle_memberships(work_ids=None):
    """Return full saved Search-bundle snapshots touching these works."""
    if work_ids is None:
        ids = None
    else:
        ids = _validated_work_ids(work_ids)
        if ids is None or not ids:
            return []

    connection = get_connection()
    try:
        if ids is None:
            return connection.execute(
                """
                SELECT bundle_id, work_id
                FROM automatic_bundle_memberships
                ORDER BY bundle_id, work_id
                """
            ).fetchall()

        placeholders = ",".join("?" for _ in ids)
        bundle_ids = [
            int(row["bundle_id"])
            for row in connection.execute(
                f"""
                SELECT DISTINCT bundle_id
                FROM automatic_bundle_memberships
                WHERE bundle_id IN ({placeholders})
                   OR work_id IN ({placeholders})
                ORDER BY bundle_id
                """,
                [*ids, *ids],
            ).fetchall()
        ]
        if not bundle_ids:
            return []
        group_placeholders = ",".join("?" for _ in bundle_ids)
        return connection.execute(
            f"""
            SELECT bundle_id, work_id
            FROM automatic_bundle_memberships
            WHERE bundle_id IN ({group_placeholders})
            ORDER BY bundle_id, work_id
            """,
            bundle_ids,
        ).fetchall()
    finally:
        connection.close()


def add_bundle_exclusion(work_a, work_b):
    """Prevent two works from being automatically grouped together."""
    try:
        work_a = _validated_work_id(work_a)
        work_b = _validated_work_id(work_b)
    except (TypeError, ValueError, OverflowError):
        return False
    work_a, work_b = sorted((work_a, work_b))
    if work_a == work_b:
        return False

    connection = get_connection()
    try:
        exists = connection.execute(
            "SELECT COUNT(*) FROM works WHERE id IN (?, ?)",
            (work_a, work_b),
        ).fetchone()[0]
        if exists != 2:
            return False

        cursor = connection.execute(
            "INSERT OR IGNORE INTO bundle_exclusions (work_a, work_b) VALUES (?, ?)",
            (work_a, work_b),
        )
        connection.commit()
        return cursor.rowcount > 0
    finally:
        connection.close()


def remove_bundle_member(work_id, target_id, bundle_member_ids):
    """Remove target_id from a bundle while keeping it in the Library."""
    try:
        work_id = _validated_work_id(work_id)
        target_id = _validated_work_id(target_id)
    except (TypeError, ValueError, OverflowError):
        return False
    validated_members = _validated_work_ids(bundle_member_ids)
    if validated_members is None:
        return False
    member_ids = set(validated_members)
    member_ids.discard(target_id)

    if work_id == target_id or work_id not in member_ids:
        return False

    all_ids = member_ids | {work_id, target_id}
    placeholders = ",".join("?" for _ in all_ids)

    connection = get_connection()
    try:
        existing = connection.execute(
            f"SELECT id FROM works WHERE id IN ({placeholders})",
            tuple(all_ids),
        ).fetchall()
        if len(existing) != len(all_ids):
            return False

        changed = False
        for other_id in member_ids | {work_id}:
            if other_id == target_id:
                continue

            left, right = sorted((target_id, other_id))

            cursor = connection.execute(
                "DELETE FROM manual_bundle_links WHERE work_a = ? AND work_b = ?",
                (left, right),
            )
            changed = cursor.rowcount > 0 or changed

            cursor = connection.execute(
                "INSERT OR IGNORE INTO bundle_exclusions (work_a, work_b) VALUES (?, ?)",
                (left, right),
            )
            changed = cursor.rowcount > 0 or changed

        connection.commit()
        return changed
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def get_bundle_exclusions(work_ids=None):
    """Return persisted bundle exclusions."""
    ids = None if work_ids is None else _validated_work_ids(work_ids)
    if work_ids is not None and (ids is None or not ids):
        return []

    connection = get_connection()
    try:
        if ids is None:
            return connection.execute(
                "SELECT work_a, work_b FROM bundle_exclusions ORDER BY work_a, work_b"
            ).fetchall()
        placeholders = ",".join("?" for _ in ids)
        return connection.execute(
            f"""
            SELECT work_a, work_b
            FROM bundle_exclusions
            WHERE work_a IN ({placeholders}) OR work_b IN ({placeholders})
            ORDER BY work_a, work_b
            """,
            [*ids, *ids],
        ).fetchall()
    finally:
        connection.close()


def get_manual_bundle_partners(work_id):
    """Return the works explicitly manually linked to one work."""
    try:
        safe_work_id = _validated_work_id(work_id)
    except (TypeError, ValueError, OverflowError):
        return []
    connection = get_connection()
    try:
        return connection.execute(
            """
            SELECT
                CASE WHEN links.work_a = ? THEN links.work_b ELSE links.work_a END AS partner_id,
                works.title AS partner_title,
                works.format AS partner_format,
                works.type AS partner_type
            FROM manual_bundle_links AS links
            JOIN works ON works.id =
                CASE WHEN links.work_a = ? THEN links.work_b ELSE links.work_a END
            WHERE links.work_a = ? OR links.work_b = ?
            ORDER BY works.title
            """,
            (safe_work_id, safe_work_id, safe_work_id, safe_work_id),
        ).fetchall()
    finally:
        connection.close()




def get_bundle_override(work_ids):
    """Return the saved presentation override for a bundle touching these works."""
    ids = _validated_work_ids(work_ids)
    if not ids:
        return None

    placeholders = ",".join("?" for _ in ids)
    order_cases = " ".join(
        f"WHEN ? THEN {index}"
        for index, _ in enumerate(ids)
    )
    connection = get_connection()
    try:
        return connection.execute(
            f"""
            SELECT bundle_anchor_id, custom_title, cover_work_id, custom_cover_path
            FROM bundle_overrides
            WHERE bundle_anchor_id IN ({placeholders})
            ORDER BY CASE bundle_anchor_id {order_cases} ELSE {len(ids)} END
            LIMIT 1
            """,
            [*ids, *ids],
        ).fetchone()
    finally:
        connection.close()


def save_bundle_override(work_ids, anchor_id, custom_title=None, cover_work_id=None, custom_cover_path=None):
    """Save a bundle presentation override against its current earliest member."""
    ids = _validated_work_ids(work_ids)
    if not ids:
        return False
    try:
        safe_anchor_id = _validated_work_id(anchor_id)
    except (TypeError, ValueError, OverflowError):
        return False
    if safe_anchor_id not in ids:
        return False

    if cover_work_id is not None:
        try:
            cover_work_id = _validated_work_id(cover_work_id)
        except (TypeError, ValueError, OverflowError):
            return False
        if cover_work_id not in ids:
            return False

    if custom_title is not None and not isinstance(custom_title, str):
        return False
    custom_title = custom_title.strip() if custom_title is not None else None
    custom_title = custom_title or None
    if custom_title is not None and len(custom_title) > 500:
        return False

    if custom_cover_path in (None, ""):
        custom_cover_path = None
    elif isinstance(custom_cover_path, (str, Path)):
        custom_cover_path = str(custom_cover_path).strip() or None
        if custom_cover_path is not None and len(custom_cover_path) > 4096:
            return False
    else:
        return False

    connection = get_connection()
    placeholders = ",".join("?" for _ in ids)
    try:
        connection.execute(
            f"DELETE FROM bundle_overrides WHERE bundle_anchor_id IN ({placeholders})",
            ids,
        )
        connection.execute(
            """
            INSERT INTO bundle_overrides (
                bundle_anchor_id, custom_title, cover_work_id, custom_cover_path
            )
            VALUES (?, ?, ?, ?)
            """,
            (safe_anchor_id, custom_title, cover_work_id, custom_cover_path),
        )
        connection.commit()
        return True
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def clear_bundle_override(work_ids):
    """Remove a bundle presentation override."""
    ids = _validated_work_ids(work_ids)
    if not ids:
        return False

    placeholders = ",".join("?" for _ in ids)
    connection = get_connection()
    try:
        cursor = connection.execute(
            f"DELETE FROM bundle_overrides WHERE bundle_anchor_id IN ({placeholders})",
            ids,
        )
        connection.commit()
        return cursor.rowcount > 0
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def add_to_library(work_id, status="Planning"):
    """Add a work or update its status without erasing saved progress and notes.

    Progress is reconstructed from cached episode/reading rows only when a
    library membership is newly created (including re-adding a removed work).
    On conflict, existing counters, ratings, notes, and added_date are retained.
    """
    safe_work_id = _validated_work_id(work_id)
    if not isinstance(status, str) or not status.strip():
        raise ValueError("Library status must be a non-empty string.")
    status = status.strip()
    connection = get_connection()
    try:
        connection.execute("""
            INSERT INTO user_library (
                work_id, status, progress_episodes, progress_chapters,
                progress_volumes, updated_date
            )
            VALUES (
                ?, ?,
                (SELECT COUNT(*) FROM episodes WHERE work_id = ? AND watched = 1),
                COALESCE((SELECT read_count FROM reading_progress
                 WHERE work_id = ? AND item_type = 'chapter'), 0),
                COALESCE((SELECT read_count FROM reading_progress
                 WHERE work_id = ? AND item_type = 'volume'), 0),
                CURRENT_TIMESTAMP
            )
            ON CONFLICT(work_id) DO UPDATE SET
                status = excluded.status,
                updated_date = CURRENT_TIMESTAMP
        """, (safe_work_id, status, safe_work_id, safe_work_id, safe_work_id))
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def remove_from_library(work_id):
    """Remove a work from the user's Library while keeping its cached work data."""
    try:
        safe_work_id = _validated_work_id(work_id)
    except (TypeError, ValueError, OverflowError):
        return False
    connection = get_connection()
    try:
        cursor = connection.execute(
            "DELETE FROM user_library WHERE work_id = ?",
            (safe_work_id,),
        )
        connection.commit()
        return cursor.rowcount > 0
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def delete_work_data(work_id):
    """Permanently delete one exact work ID and verify all work-owned rows are gone."""
    from pathlib import Path

    work_id = _validated_work_id(work_id)
    connection = get_connection()

    try:
        row = connection.execute(
            "SELECT cover_path FROM works WHERE id = ?",
            (work_id,),
        ).fetchone()
        if row is None:
            connection.close()
            return False

        override_paths = [
            item["custom_cover_path"]
            for item in connection.execute(
                """
                SELECT custom_cover_path
                FROM bundle_overrides
                WHERE bundle_anchor_id = ? OR cover_work_id = ?
                UNION ALL
                SELECT custom_cover_path
                FROM work_display_overrides
                WHERE work_id = ?
                """,
                (work_id, work_id, work_id),
            ).fetchall()
            if item["custom_cover_path"]
        ]

        # Delete every row that can keep this exact work in the Library,
        # bundle system, relation graph, or cached work data.
        for table in (
            "episodes",
            "reading_items",
            "reading_progress",
            "work_character_voice_actors",
            "work_characters",
            "work_staff",
            "work_studios",
            "work_songs",
            "alternate_titles",
            "work_provider_metadata",
        ):
            connection.execute(
                f"DELETE FROM {table} WHERE work_id = ?",
                (work_id,),
            )

        connection.execute(
            "DELETE FROM automatic_bundle_memberships WHERE bundle_id = ? OR work_id = ?",
            (work_id, work_id),
        )
        connection.execute(
            """
            DELETE FROM automatic_bundle_memberships
            WHERE bundle_id IN (
                SELECT bundle_id
                FROM automatic_bundle_memberships
                GROUP BY bundle_id
                HAVING COUNT(*) < 2
            )
            """
        )
        connection.execute(
            "DELETE FROM manual_bundle_links WHERE work_a = ? OR work_b = ?",
            (work_id, work_id),
        )
        connection.execute(
            "DELETE FROM bundle_exclusions WHERE work_a = ? OR work_b = ?",
            (work_id, work_id),
        )
        connection.execute(
            "DELETE FROM bundle_overrides WHERE bundle_anchor_id = ? OR cover_work_id = ?",
            (work_id, work_id),
        )
        connection.execute(
            "DELETE FROM work_relations WHERE source_id = ? OR target_id = ?",
            (work_id, work_id),
        )
        connection.execute(
            "DELETE FROM user_library WHERE work_id = ?",
            (work_id,),
        )
        # A permanent deletion removes independent favorites and display identity
        # customizations too. Removing a work from Library uses remove_from_library
        # instead and deliberately leaves these preferences untouched.
        connection.execute(
            "DELETE FROM user_favorites WHERE work_id = ?",
            (work_id,),
        )
        connection.execute(
            "DELETE FROM work_display_overrides WHERE work_id = ?",
            (work_id,),
        )
        connection.execute(
            "DELETE FROM works WHERE id = ?",
            (work_id,),
        )

        # Do not claim success unless the exact ID is gone everywhere it can
        # affect Library/bundle state. Roll back the whole deletion on failure.
        checks = (
            ("works", "SELECT 1 FROM works WHERE id = ? LIMIT 1"),
            ("user_library", "SELECT 1 FROM user_library WHERE work_id = ? LIMIT 1"),
            ("user_favorites", "SELECT 1 FROM user_favorites WHERE work_id = ? LIMIT 1"),
            ("work_display_overrides", "SELECT 1 FROM work_display_overrides WHERE work_id = ? LIMIT 1"),
            (
                "automatic_bundle_memberships",
                "SELECT 1 FROM automatic_bundle_memberships WHERE bundle_id = ? OR work_id = ? LIMIT 1",
            ),
            (
                "manual_bundle_links",
                "SELECT 1 FROM manual_bundle_links WHERE work_a = ? OR work_b = ? LIMIT 1",
            ),
            (
                "bundle_overrides",
                "SELECT 1 FROM bundle_overrides WHERE bundle_anchor_id = ? OR cover_work_id = ? LIMIT 1",
            ),
            (
                "work_relations",
                "SELECT 1 FROM work_relations WHERE source_id = ? OR target_id = ? LIMIT 1",
            ),
            ("episodes", "SELECT 1 FROM episodes WHERE work_id = ? LIMIT 1"),
            ("reading_items", "SELECT 1 FROM reading_items WHERE work_id = ? LIMIT 1"),
            ("work_characters", "SELECT 1 FROM work_characters WHERE work_id = ? LIMIT 1"),
            ("work_staff", "SELECT 1 FROM work_staff WHERE work_id = ? LIMIT 1"),
            ("work_studios", "SELECT 1 FROM work_studios WHERE work_id = ? LIMIT 1"),
            ("work_songs", "SELECT 1 FROM work_songs WHERE work_id = ? LIMIT 1"),
            ("alternate_titles", "SELECT 1 FROM alternate_titles WHERE work_id = ? LIMIT 1"),
            ("work_provider_metadata", "SELECT 1 FROM work_provider_metadata WHERE work_id = ? LIMIT 1"),
        )

        residual = []
        for table_name, query in checks:
            params = (work_id, work_id) if " OR " in query else (work_id,)
            if connection.execute(query, params).fetchone() is not None:
                residual.append(table_name)

        if residual:
            connection.rollback()
            connection.close()
            return False

        connection.commit()
        connection.close()
    except Exception:
        connection.rollback()
        connection.close()
        raise

    # A custom/cache image path can be shared by multiple works or bundle
    # overrides. Delete the file only after the database commit and only when
    # no remaining row references that exact stored path.
    candidate_paths = {
        str(path)
        for path in ([row["cover_path"]] if row["cover_path"] else []) + override_paths
        if path
    }
    if candidate_paths:
        # Only remove files in directories owned by NekoTrack's generated
        # artwork cache. Custom covers can fall back to the user's original
        # selected file when copying fails; deleting a work must never unlink
        # that original file merely because its path was stored in the database.
        managed_image_roots = (
            (Path("data") / "images" / "works").resolve(),
            (Path("data") / "images" / "bundles").resolve(),
            (Path("data") / "display_overrides").resolve(),
        )
        connection = get_connection()
        try:
            references = connection.execute(
                """
                SELECT cover_path AS stored_path
                FROM works
                WHERE cover_path IS NOT NULL
                UNION ALL
                SELECT custom_cover_path AS stored_path
                FROM bundle_overrides
                WHERE custom_cover_path IS NOT NULL
                UNION ALL
                SELECT custom_cover_path AS stored_path
                FROM work_display_overrides
                WHERE custom_cover_path IS NOT NULL
                """
            ).fetchall()

            referenced_paths = set()
            for reference in references:
                try:
                    referenced_paths.add(Path(reference["stored_path"]).resolve())
                except (OSError, RuntimeError, TypeError, ValueError):
                    continue

            for stored_path in candidate_paths:
                try:
                    path = Path(stored_path).resolve()
                except (OSError, RuntimeError, TypeError, ValueError):
                    continue

                # resolve() prevents a symlink under the cache from redirecting
                # deletion to an arbitrary path outside an app-owned directory.
                managed = False
                for root in managed_image_roots:
                    try:
                        path.relative_to(root)
                    except ValueError:
                        continue
                    if path != root:
                        managed = True
                    break
                if not managed or path in referenced_paths:
                    continue

                try:
                    if path.is_file():
                        path.unlink()
                except OSError:
                    pass
        finally:
            connection.close()

    return True


def get_library_by_status(status):
    connection = get_connection()
    results = connection.execute("""
        SELECT works.*, user_library.status, user_library.progress_episodes, user_library.progress_chapters,
               user_library.progress_volumes, user_library.rating, user_library.notes,
               user_library.added_date, user_library.updated_date
        FROM works JOIN user_library ON user_library.work_id = works.id
        WHERE user_library.status = ? ORDER BY user_library.added_date DESC
    """, (status,)).fetchall()
    connection.close()
    return results



def set_release_reminder(work_id, episode_number, enabled=True):
    """Enable or remove a reminder for one cached episode release date."""
    safe_work_id = _validated_work_id(work_id)
    number = _safe_optional_integer(
        episode_number, 1, _MAX_TRACKED_EPISODE_NUMBER
    )
    if number is None or isinstance(episode_number, bool):
        raise ValueError("Episode number must be a positive integer.")
    if not isinstance(enabled, bool):
        raise ValueError("Reminder enabled state must be boolean.")

    connection = get_connection()
    try:
        exists = connection.execute(
            "SELECT 1 FROM episodes WHERE work_id = ? AND episode_number = ?",
            (safe_work_id, number),
        ).fetchone()
        if exists is None:
            raise ValueError("A reminder can only be set for a cached episode.")
        if enabled:
            connection.execute("""
                INSERT INTO release_reminders (work_id, episode_number, notified_date, updated_at)
                VALUES (?, ?, NULL, CURRENT_TIMESTAMP)
                ON CONFLICT(work_id, episode_number) DO UPDATE SET
                    notified_date = NULL,
                    updated_at = CURRENT_TIMESTAMP
            """, (safe_work_id, number))
        else:
            connection.execute(
                "DELETE FROM release_reminders WHERE work_id = ? AND episode_number = ?",
                (safe_work_id, number),
            )
        connection.commit()
        return enabled
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def get_release_reminders():
    """Return enabled reminders with their current cached episode and title data."""
    connection = get_connection()
    try:
        return connection.execute("""
            SELECT
                reminders.work_id, reminders.episode_number,
                reminders.notified_date, reminders.updated_at,
                episodes.title AS episode_title, episodes.air_date,
                works.title AS work_title, works.type, works.cover_url, works.cover_path
            FROM release_reminders AS reminders
            JOIN episodes
              ON episodes.work_id = reminders.work_id
             AND episodes.episode_number = reminders.episode_number
            JOIN works ON works.id = reminders.work_id
            ORDER BY episodes.air_date, works.title, reminders.episode_number
        """).fetchall()
    finally:
        connection.close()


def get_due_release_reminders(today=None):
    """Return reminders whose release date is today and have not notified today."""
    import datetime

    if today is None:
        today = datetime.date.today().isoformat()
    try:
        parsed = datetime.date.fromisoformat(str(today))
    except (TypeError, ValueError):
        raise ValueError("today must be a valid ISO date.")
    date_text = parsed.isoformat()
    connection = get_connection()
    try:
        return connection.execute("""
            SELECT
                reminders.work_id, reminders.episode_number,
                episodes.title AS episode_title, episodes.air_date,
                works.title AS work_title
            FROM release_reminders AS reminders
            JOIN episodes
              ON episodes.work_id = reminders.work_id
             AND episodes.episode_number = reminders.episode_number
            JOIN works ON works.id = reminders.work_id
            WHERE episodes.air_date = ?
              AND (reminders.notified_date IS NULL OR reminders.notified_date != ?)
            ORDER BY works.title, reminders.episode_number
        """, (date_text, date_text)).fetchall()
    finally:
        connection.close()


def mark_release_reminder_notified(work_id, episode_number, notified_date=None):
    """Record that today's desktop notification has already been attempted."""
    import datetime

    safe_work_id = _validated_work_id(work_id)
    number = _safe_optional_integer(
        episode_number, 1, _MAX_TRACKED_EPISODE_NUMBER
    )
    if number is None or isinstance(episode_number, bool):
        raise ValueError("Episode number must be a positive integer.")
    if notified_date is None:
        notified_date = datetime.date.today().isoformat()
    try:
        date_text = datetime.date.fromisoformat(str(notified_date)).isoformat()
    except (TypeError, ValueError):
        raise ValueError("notified_date must be a valid ISO date.")

    connection = get_connection()
    try:
        cursor = connection.execute("""
            UPDATE release_reminders
            SET notified_date = ?, updated_at = CURRENT_TIMESTAMP
            WHERE work_id = ? AND episode_number = ?
        """, (date_text, safe_work_id, number))
        connection.commit()
        return cursor.rowcount > 0
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()



def _favorite_snapshot(work_data):
    """Keep only small, display-oriented fields so favorites survive cache eviction."""
    if not isinstance(work_data, dict):
        return {}
    allowed = (
        "id", "title", "type", "format", "episodes", "chapters", "volumes",
        "description", "cover_url", "coverImage", "cover_path", "start_year",
        "startDate", "score", "averageScore", "seasonYear", "status",
        "progress_episodes", "progress_chapters", "progress_volumes",
        "_series_count", "_bundle_summary", "_bundle_cover_work_id",
        "_bundle_default_member_id",
    )
    snapshot = {
        key: work_data[key]
        for key in allowed
        if key in work_data and work_data[key] is not None
    }
    members = work_data.get("_series_members")
    if isinstance(members, list):
        snapshot["_series_members"] = [
            {
                key: member[key]
                for key in (
                    "id", "title", "type", "format", "episodes", "chapters",
                    "volumes", "cover_url", "cover_path", "start_year",
                )
                if key in member and member[key] is not None
            }
            for member in members[:24]
            if isinstance(member, dict)
        ]
    try:
        json.dumps(snapshot, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError, OverflowError, RecursionError):
        safe_title = snapshot.get("title")
        snapshot = {"id": snapshot.get("id"), "title": safe_title}
        if snapshot.get("id") is None:
            snapshot.pop("id", None)
    return snapshot


def is_work_favorite(work_id):
    """Return whether a title is saved as a favorite, even if its cache is cold."""
    try:
        safe_work_id = _validated_work_id(work_id)
    except (TypeError, ValueError, OverflowError):
        return False
    connection = get_connection()
    try:
        return connection.execute(
            "SELECT 1 FROM user_favorites WHERE work_id = ? LIMIT 1",
            (safe_work_id,),
        ).fetchone() is not None
    finally:
        connection.close()


def set_work_favorite(work_id, favorite, work_data=None):
    """Persist favorite state independently of Library membership."""
    safe_work_id = _validated_work_id(work_id)
    if not isinstance(favorite, bool):
        raise ValueError("Favorite state must be boolean.")
    snapshot = _favorite_snapshot(work_data)
    if snapshot.get("id") is not None:
        try:
            snapshot["id"] = _validated_work_id(snapshot["id"])
        except (TypeError, ValueError, OverflowError):
            snapshot.pop("id", None)
    try:
        payload = json.dumps(snapshot, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError, OverflowError, RecursionError) as error:
        raise ValueError("Favorite metadata could not be serialized safely.") from error
    if len(payload) > 512 * 1024:
        raise ValueError("Favorite metadata is too large to store.")

    connection = get_connection()
    try:
        if favorite:
            connection.execute("""
                INSERT INTO user_favorites (work_id, work_data_json, added_date)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(work_id) DO UPDATE SET
                    work_data_json = CASE
                        WHEN excluded.work_data_json != '{}' THEN excluded.work_data_json
                        ELSE user_favorites.work_data_json
                    END
            """, (safe_work_id, payload))
        else:
            connection.execute(
                "DELETE FROM user_favorites WHERE work_id = ?",
                (safe_work_id,),
            )
        connection.commit()
        return favorite
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def get_favorite_works():
    """Return favorite cards using a stored snapshot with cached data when available."""
    connection = get_connection()
    try:
        rows = connection.execute("""
            SELECT
                favorites.work_id, favorites.work_data_json, favorites.added_date,
                works.title AS cached_title, works.type AS cached_type,
                works.format AS cached_format, works.episodes AS cached_episodes,
                works.chapters AS cached_chapters, works.volumes AS cached_volumes,
                works.score AS cached_score, works.start_year AS cached_start_year,
                works.cover_url AS cached_cover_url, works.cover_path AS cached_cover_path,
                works.description AS cached_description,
                user_library.status, user_library.progress_episodes,
                user_library.progress_chapters, user_library.progress_volumes,
                user_library.rating, user_library.notes,
                user_library.updated_date
            FROM user_favorites AS favorites
            LEFT JOIN works ON works.id = favorites.work_id
            LEFT JOIN user_library ON user_library.work_id = favorites.work_id
            ORDER BY favorites.added_date DESC, works.title
        """).fetchall()
    finally:
        connection.close()

    results = []
    for row in rows:
        try:
            snapshot = json.loads(row["work_data_json"] or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            snapshot = {}
        if not isinstance(snapshot, dict):
            snapshot = {}
        work = dict(snapshot)
        work["id"] = int(row["work_id"])
        is_bundle = len(work.get("_series_members") or []) > 1
        if not is_bundle:
            if row["cached_title"]:
                work["title"] = row["cached_title"]
            for target, source in (
                ("type", "cached_type"),
                ("format", "cached_format"),
                ("episodes", "cached_episodes"),
                ("chapters", "cached_chapters"),
                ("volumes", "cached_volumes"),
                ("cover_url", "cached_cover_url"),
                ("cover_path", "cached_cover_path"),
                ("description", "cached_description"),
                ("start_year", "cached_start_year"),
            ):
                if row[source] is not None:
                    work[target] = row[source]
            if row["cached_score"] is not None:
                work["score"] = row["cached_score"]
                work["averageScore"] = row["cached_score"]
        for key in (
            "status", "progress_episodes", "progress_chapters", "progress_volumes",
            "rating", "notes", "updated_date",
        ):
            work[key] = row[key]
        work["_is_favorite"] = True
        work["_favorite_added_date"] = row["added_date"]
        results.append(work)
    return results


def get_work_display_override(work_id):
    """Return a title/cover override only for a safe, managed custom-cover path."""
    try:
        safe_work_id = _validated_work_id(work_id)
    except (TypeError, ValueError, OverflowError):
        return {}
    connection = get_connection()
    try:
        row = connection.execute("""
            SELECT work_id, custom_title, custom_cover_path, updated_at
            FROM work_display_overrides WHERE work_id = ?
        """, (safe_work_id,)).fetchone()
    finally:
        connection.close()
    if row is None:
        return {}
    result = dict(row)
    stored_path = result.get("custom_cover_path")
    if stored_path:
        candidate = Path(stored_path)
        if not candidate.is_absolute():
            candidate = Path.cwd() / candidate
        try:
            resolved = candidate.resolve()
            managed_root = (Path.cwd() / "data" / "display_overrides").resolve()
            resolved.relative_to(managed_root)
            if resolved.is_file():
                result["custom_cover_path"] = resolved.as_posix()
            else:
                result["custom_cover_path"] = None
        except (OSError, ValueError, RuntimeError):
            result["custom_cover_path"] = None
    return result


def save_work_display_override(work_id, custom_title=None, custom_cover_path=None):
    """Save a global title/cover override; custom artwork must be app-managed."""
    safe_work_id = _validated_work_id(work_id)
    if custom_title is not None:
        if not isinstance(custom_title, str):
            raise ValueError("Custom title must be text.")
        custom_title = " ".join(custom_title.split()).strip() or None
        if custom_title and (len(custom_title) > 200 or any(ord(char) < 32 for char in custom_title)):
            raise ValueError("Custom title must be at most 200 printable characters.")

    stored_cover = None
    if custom_cover_path is not None:
        if not isinstance(custom_cover_path, str) or not custom_cover_path.strip():
            raise ValueError("Custom cover path must be a valid managed image.")
        candidate = Path(custom_cover_path.strip())
        if not candidate.is_absolute():
            candidate = Path.cwd() / candidate
        try:
            resolved = candidate.resolve()
            managed_root = (Path.cwd() / "data" / "display_overrides").resolve()
            resolved.relative_to(managed_root)
        except (OSError, ValueError, RuntimeError) as error:
            raise ValueError("Custom cover must live in NekoTrack's display-overrides folder.") from error
        if not resolved.is_file():
            raise ValueError("Custom cover file could not be found.")
        stored_cover = resolved.relative_to(Path.cwd().resolve()).as_posix()

    connection = get_connection()
    try:
        if custom_title is None and stored_cover is None:
            connection.execute(
                "DELETE FROM work_display_overrides WHERE work_id = ?",
                (safe_work_id,),
            )
        else:
            connection.execute("""
                INSERT INTO work_display_overrides
                    (work_id, custom_title, custom_cover_path, updated_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(work_id) DO UPDATE SET
                    custom_title = excluded.custom_title,
                    custom_cover_path = excluded.custom_cover_path,
                    updated_at = CURRENT_TIMESTAMP
            """, (safe_work_id, custom_title, stored_cover))
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    return get_work_display_override(safe_work_id)


def clear_work_display_override(work_id):
    """Remove all global title/cover overrides for one title."""
    return save_work_display_override(work_id, None, None)


def get_all_library():
    connection = get_connection()
    results = connection.execute("""
        SELECT works.*, user_library.status, user_library.progress_episodes,
               user_library.progress_chapters, user_library.progress_volumes,
               user_library.rating, user_library.notes,
               user_library.added_date, user_library.updated_date
        FROM works JOIN user_library ON user_library.work_id = works.id
        ORDER BY user_library.added_date DESC, works.title
    """).fetchall()
    connection.close()
    return results


# ---------------------------------------------------------------------------
# Personalized recommendation feedback and entity favorites
# ---------------------------------------------------------------------------

def get_work_favorites():
    """Return saved media favorites as lightweight work dictionaries."""
    connection = get_connection()
    try:
        rows = connection.execute(
            "SELECT work_id, work_data_json FROM user_favorites ORDER BY added_date DESC"
        ).fetchall()
        results = []
        for row in rows:
            try:
                item = json.loads(row["work_data_json"] or "{}")
            except (TypeError, ValueError, json.JSONDecodeError):
                item = {}
            if not isinstance(item, dict):
                item = {}
            item.setdefault("id", int(row["work_id"]))
            results.append(item)
        return results
    finally:
        connection.close()


def _recommendation_metadata_json(metadata):
    if not isinstance(metadata, dict):
        return "{}"
    allowed = (
        "id", "title", "type", "format", "genres", "tags", "averageScore",
        "popularity", "coverImage", "cover_url", "startDate", "start_year",
        "_recommendation_source_titles", "_recommendation_source_ids",
        "_recommendation_reason",
    )
    snapshot = {key: metadata[key] for key in allowed if key in metadata}

    raw_source_ids = metadata.get("_recommendation_source_ids")
    if isinstance(raw_source_ids, (list, tuple, set)):
        source_ids = []
        for value in list(raw_source_ids)[:50]:
            try:
                source_id = _validated_work_id(value)
            except (TypeError, ValueError, OverflowError):
                continue
            if source_id > 0 and source_id not in source_ids:
                source_ids.append(source_id)
        snapshot["_recommendation_source_ids"] = source_ids

    # Persist only the relationship fields needed for local learning. Keep
    # records deliberately small and numeric; provider biographies, images and
    # other unexpected payload cannot balloon the recommendation-history DB.
    characters = metadata.get("characters")
    if isinstance(characters, dict):
        edges = characters.get("edges")
        if isinstance(edges, list):
            safe_edges = []
            for edge in edges[:30]:
                if not isinstance(edge, dict):
                    continue
                node = edge.get("node")
                try:
                    character_id = _validated_work_id(node.get("id")) if isinstance(node, dict) else None
                except (TypeError, ValueError, OverflowError):
                    character_id = None
                if character_id is None or character_id <= 0:
                    continue
                safe_edge = {
                    "role": str(edge.get("role") or "UNKNOWN")[:40],
                    "node": {"id": character_id},
                }
                voices = edge.get("voiceActors")
                if isinstance(voices, list):
                    safe_voices = []
                    for voice in voices[:20]:
                        if not isinstance(voice, dict):
                            continue
                        try:
                            actor_id = _validated_work_id(voice.get("id"))
                        except (TypeError, ValueError, OverflowError):
                            continue
                        if actor_id is None or actor_id <= 0:
                            continue
                        safe_voices.append({
                            "id": actor_id,
                            "language": str(voice.get("language") or "")[:30],
                        })
                    safe_edge["voiceActors"] = safe_voices
                safe_edges.append(safe_edge)
            snapshot["characters"] = {"edges": safe_edges}

    staff = metadata.get("staff")
    if isinstance(staff, dict):
        edges = staff.get("edges")
        if isinstance(edges, list):
            safe_edges = []
            for edge in edges[:40]:
                if not isinstance(edge, dict):
                    continue
                node = edge.get("node")
                try:
                    person_id = _validated_work_id(node.get("id")) if isinstance(node, dict) else None
                except (TypeError, ValueError, OverflowError):
                    person_id = None
                if person_id is None or person_id <= 0:
                    continue
                safe_edges.append({
                    "role": str(edge.get("role") or "")[:250],
                    "node": {"id": person_id},
                })
            snapshot["staff"] = {"edges": safe_edges}

    try:
        encoded = json.dumps(snapshot, ensure_ascii=False, allow_nan=False)
        return encoded if len(encoded) <= 128 * 1024 else "{}"
    except (TypeError, ValueError, OverflowError, RecursionError):
        return "{}"


def record_recommendation_impressions(items):
    """Increment impressions only for recommendations that actually entered view."""
    prepared = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        try:
            work_id = _validated_work_id(item.get("id"))
        except (TypeError, ValueError, OverflowError):
            continue
        if work_id <= 0:
            continue
        prepared.append((work_id, _recommendation_metadata_json(item)))

    if not prepared:
        return 0
    connection = get_connection()
    try:
        connection.executemany(
            """
            INSERT INTO recommendation_history
                (work_id, impressions, metadata_json, first_seen_at, last_seen_at)
            VALUES (?, 1, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ON CONFLICT(work_id) DO UPDATE SET
                impressions = recommendation_history.impressions + 1,
                metadata_json = CASE
                    WHEN excluded.metadata_json != '{}' THEN excluded.metadata_json
                    ELSE recommendation_history.metadata_json
                END,
                last_seen_at = CURRENT_TIMESTAMP
            """,
            prepared,
        )
        connection.commit()
        return len(prepared)
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def set_recommendation_feedback(work_id, feedback, metadata=None):
    """Persist recommendation preference or a permanent exact-title exclusion."""
    try:
        safe_work_id = _validated_work_id(work_id)
    except (TypeError, ValueError, OverflowError):
        return False
    if safe_work_id <= 0 or feedback not in (
        None, "like", "dislike", "more_like_this", "less_like_this", "never_show",
    ):
        return False
    metadata_json = _recommendation_metadata_json(metadata)
    connection = get_connection()
    try:
        connection.execute(
            """
            INSERT INTO recommendation_history
                (work_id, impressions, feedback, metadata_json, first_seen_at)
            VALUES (?, 0, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(work_id) DO UPDATE SET
                feedback = excluded.feedback,
                metadata_json = CASE
                    WHEN excluded.metadata_json != '{}' THEN excluded.metadata_json
                    ELSE recommendation_history.metadata_json
                END
            """,
            (safe_work_id, feedback, metadata_json),
        )
        connection.commit()
        return True
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def get_recommendation_history():
    """Return recommendation feedback/exposure history keyed by media ID."""
    connection = get_connection()
    try:
        rows = connection.execute(
            """
            SELECT work_id, impressions, feedback, metadata_json, first_seen_at, last_seen_at
            FROM recommendation_history
            ORDER BY work_id
            """
        ).fetchall()
        history = {}
        for row in rows:
            try:
                metadata = json.loads(row["metadata_json"] or "{}")
            except (TypeError, ValueError, json.JSONDecodeError):
                metadata = {}
            history[int(row["work_id"])] = {
                "work_id": int(row["work_id"]),
                "impressions": max(0, int(row["impressions"] or 0)),
                "feedback": row["feedback"],
                "metadata": metadata if isinstance(metadata, dict) else {},
                "first_seen_at": row["first_seen_at"],
                "last_seen_at": row["last_seen_at"],
            }
        return history
    finally:
        connection.close()


def _normalize_entity_favorite_type(entity_type):
    value = str(entity_type or "").strip().casefold().replace(" ", "_")
    aliases = {
        "character": "character",
        "characters": "character",
        "staff": "staff",
        "person": "staff",
        "people": "staff",
        "voice_actor": "voice_actor",
        "voice_actors": "voice_actor",
        "voiceactor": "voice_actor",
    }
    return aliases.get(value)


def is_entity_favorite(entity_type, entity_id):
    kind = _normalize_entity_favorite_type(entity_type)
    try:
        numeric_id = int(entity_id)
    except (TypeError, ValueError, OverflowError):
        return False
    if kind is None or isinstance(entity_id, bool) or numeric_id <= 0:
        return False
    connection = get_connection()
    try:
        return connection.execute(
            "SELECT 1 FROM entity_favorites WHERE entity_type = ? AND entity_id = ?",
            (kind, numeric_id),
        ).fetchone() is not None
    finally:
        connection.close()


def set_entity_favorite(entity_type, entity_id, favorite, name="", language=None):
    """Persist a favorite character, production staff member, or voice actor."""
    kind = _normalize_entity_favorite_type(entity_type)
    try:
        numeric_id = int(entity_id)
    except (TypeError, ValueError, OverflowError):
        return False
    if kind is None or isinstance(entity_id, bool) or numeric_id <= 0:
        return False
    if not isinstance(favorite, bool):
        return False

    connection = get_connection()
    try:
        if favorite:
            connection.execute(
                """
                INSERT INTO entity_favorites (entity_type, entity_id, entity_name, language)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(entity_type, entity_id) DO UPDATE SET
                    entity_name = CASE WHEN excluded.entity_name != ''
                                       THEN excluded.entity_name
                                       ELSE entity_favorites.entity_name END,
                    language = COALESCE(excluded.language, entity_favorites.language)
                """,
                (kind, numeric_id, str(name or "").strip(), str(language).strip() if language else None),
            )
        else:
            connection.execute(
                "DELETE FROM entity_favorites WHERE entity_type = ? AND entity_id = ?",
                (kind, numeric_id),
            )
        connection.commit()
        return True
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def get_entity_favorites(entity_type=None):
    """Return saved entity favorites, optionally for one normalized entity type."""
    kind = _normalize_entity_favorite_type(entity_type) if entity_type is not None else None
    if entity_type is not None and kind is None:
        return []
    connection = get_connection()
    try:
        if kind is None:
            rows = connection.execute(
                "SELECT entity_type, entity_id, entity_name, language, added_date "
                "FROM entity_favorites ORDER BY added_date DESC, entity_name"
            ).fetchall()
        else:
            rows = connection.execute(
                "SELECT entity_type, entity_id, entity_name, language, added_date "
                "FROM entity_favorites WHERE entity_type = ? "
                "ORDER BY added_date DESC, entity_name",
                (kind,),
            ).fetchall()
        return [dict(row) for row in rows]
    finally:
        connection.close()



def get_recommendation_credit_profile(work_ids):
    """Return role- and language-aware credits for local works, keyed by work ID."""
    ids = _validated_work_ids(work_ids)
    if ids is None or not ids:
        return {}
    profile = {
        work_id: {"characters": [], "voice_actors": [], "staff": []}
        for work_id in ids
    }
    placeholders = ",".join("?" for _ in ids)
    connection = get_connection()
    try:
        character_rows = connection.execute(
            f"""
            SELECT wc.work_id, c.id AS entity_id, wc.role
            FROM work_characters AS wc
            JOIN characters AS c ON c.id = wc.character_id
            WHERE wc.work_id IN ({placeholders})
            ORDER BY wc.work_id, wc.character_id
            """, ids
        ).fetchall()
        actor_rows = connection.execute(
            f"""
            SELECT wcv.work_id, wcv.person_id AS entity_id, wcv.language,
                   wc.role AS character_role, wcv.character_id
            FROM work_character_voice_actors AS wcv
            JOIN work_characters AS wc
              ON wc.work_id = wcv.work_id
             AND wc.character_id = wcv.character_id
            WHERE wcv.work_id IN ({placeholders})
            ORDER BY wcv.work_id, wcv.character_id, wcv.person_id, wcv.language
            """, ids
        ).fetchall()
        staff_rows = connection.execute(
            f"""
            SELECT ws.work_id, ws.person_id AS entity_id, ws.role
            FROM work_staff AS ws
            WHERE ws.work_id IN ({placeholders})
            ORDER BY ws.work_id, ws.person_id, ws.role
            """, ids
        ).fetchall()
    finally:
        connection.close()

    for row in character_rows:
        profile[int(row["work_id"])]["characters"].append({
            "id": int(row["entity_id"]), "role": str(row["role"] or "UNKNOWN"),
        })
    for row in actor_rows:
        profile[int(row["work_id"])]["voice_actors"].append({
            "id": int(row["entity_id"]), "language": str(row["language"] or ""),
            "character_id": int(row["character_id"]),
            "character_role": str(row["character_role"] or "UNKNOWN"),
        })
    for row in staff_rows:
        profile[int(row["work_id"])]["staff"].append({
            "id": int(row["entity_id"]), "role": str(row["role"] or ""),
        })
    return profile
