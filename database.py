import json
import math
import re
import sqlite3
from pathlib import Path

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
    connection = sqlite3.connect(DATABASE_NAME, timeout=15)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


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
    """Persist a character snapshot, keeping incomplete payloads retryable."""
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
                connection.execute(
                    """
                    INSERT INTO character_voice_actors (character_id, person_id, language)
                    VALUES (?, ?, ?)
                    ON CONFLICT(character_id, person_id) DO UPDATE SET
                        language = COALESCE(excluded.language, character_voice_actors.language)
                    """,
                    (character["id"], actor["id"], actor["language"]),
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

            # Voice-actor mappings are cached by character ID globally. Replace
            # them only for characters in this complete snapshot; malformed or
            # partial snapshots leave prior mappings untouched for retry.
            for character in normalized:
                desired_actor_ids = {actor["id"] for actor in character["actors"]}
                existing_actor_rows = connection.execute(
                    "SELECT person_id FROM character_voice_actors WHERE character_id = ?",
                    (character["id"],),
                ).fetchall()
                for row in existing_actor_rows:
                    old_actor_id = row["person_id"]
                    if old_actor_id not in desired_actor_ids:
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
    connection = get_connection()
    row = connection.execute(
        "SELECT characters_loaded FROM works WHERE id = ? LIMIT 1",
        (work_id,),
    ).fetchone()
    if not row or not row["characters_loaded"]:
        connection.close()
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
        (work_id,),
    ).fetchone()
    connection.close()
    return missing_role is None


def get_tmdb_mapping(work_id):
    """Return the cached TMDB series/season mapping for one exact work."""
    connection = get_connection()
    row = connection.execute(
        "SELECT tmdb_id, tmdb_season_number FROM works WHERE id = ?",
        (int(work_id),),
    ).fetchone()
    connection.close()
    if row is None:
        return None, None
    return row["tmdb_id"], row["tmdb_season_number"]


def save_tmdb_mapping(work_id, tmdb_id, tmdb_season_number):
    """Cache the TMDB mapping resolved for one exact NekoTrack season."""
    connection = get_connection()
    connection.execute(
        """
        UPDATE works
        SET tmdb_id = ?, tmdb_season_number = ?
        WHERE id = ?
        """,
        (
            int(tmdb_id) if tmdb_id is not None else None,
            int(tmdb_season_number) if tmdb_season_number is not None else None,
            int(work_id),
        ),
    )
    connection.commit()
    connection.close()


def save_character_image_path(character_id, image_path):
    connection = get_connection()
    connection.execute(
        "UPDATE characters SET image_path = ? WHERE id = ?",
        (str(image_path), int(character_id)),
    )
    connection.commit()
    connection.close()


def save_person_image_path(person_id, image_path):
    connection = get_connection()
    connection.execute(
        "UPDATE people SET image_path = ? WHERE id = ?",
        (str(image_path), int(person_id)),
    )
    connection.commit()
    connection.close()


def get_characters(work_id):
    """Return one row per character, with the preferred Japanese voice actor when available."""
    connection = get_connection()
    results = connection.execute("""
        SELECT
            characters.id,
            characters.name AS character_name,
            characters.image_path AS character_image_path,
            characters.image_url AS character_image_url,
            work_characters.role AS character_role,
            (
                SELECT people.id
                FROM character_voice_actors
                JOIN people ON people.id = character_voice_actors.person_id
                WHERE character_voice_actors.character_id = characters.id
                ORDER BY
                    CASE
                        WHEN LOWER(COALESCE(character_voice_actors.language, '')) IN
                             ('japanese', 'ja', 'jpn') THEN 0
                        ELSE 1
                    END,
                    character_voice_actors.language,
                    people.name
                LIMIT 1
            ) AS person_id,
            (
                SELECT people.name
                FROM character_voice_actors
                JOIN people ON people.id = character_voice_actors.person_id
                WHERE character_voice_actors.character_id = characters.id
                ORDER BY
                    CASE
                        WHEN LOWER(COALESCE(character_voice_actors.language, '')) IN
                             ('japanese', 'ja', 'jpn') THEN 0
                        ELSE 1
                    END,
                    character_voice_actors.language,
                    people.name
                LIMIT 1
            ) AS person_name,
            (
                SELECT people.image_path
                FROM character_voice_actors
                JOIN people ON people.id = character_voice_actors.person_id
                WHERE character_voice_actors.character_id = characters.id
                ORDER BY
                    CASE
                        WHEN LOWER(COALESCE(character_voice_actors.language, '')) IN
                             ('japanese', 'ja', 'jpn') THEN 0
                        ELSE 1
                    END,
                    character_voice_actors.language,
                    people.name
                LIMIT 1
            ) AS person_image_path,
            (
                SELECT people.image_url
                FROM character_voice_actors
                JOIN people ON people.id = character_voice_actors.person_id
                WHERE character_voice_actors.character_id = characters.id
                ORDER BY
                    CASE
                        WHEN LOWER(COALESCE(character_voice_actors.language, '')) IN
                             ('japanese', 'ja', 'jpn') THEN 0
                        ELSE 1
                    END,
                    character_voice_actors.language,
                    people.name
                LIMIT 1
            ) AS person_image_url
        FROM work_characters
        JOIN characters ON characters.id = work_characters.character_id
        WHERE work_characters.work_id = ?
        ORDER BY
            CASE UPPER(COALESCE(work_characters.role, 'UNKNOWN'))
                WHEN 'MAIN' THEN 0
                WHEN 'SUPPORTING' THEN 1
                WHEN 'BACKGROUND' THEN 2
                ELSE 3
            END,
            characters.name
    """, (work_id,)).fetchall()
    connection.close()
    return results


def save_staff(work_id, staff_edges):
    """Save staff edges and reconcile stale links only for complete snapshots."""
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
        if snapshot_valid:
            old_person_ids = {
                row["person_id"]
                for row in connection.execute(
                    "SELECT person_id FROM work_staff WHERE work_id = ?",
                    (safe_work_id,),
                ).fetchall()
            }
            # Only a well-formed complete edge list may remove stale roles.
            # A valid empty list is authoritative and clears the old snapshot.
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

        if snapshot_valid:
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
    connection = get_connection()
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
    """, (work_id, work_id)).fetchall()
    connection.close()
    return results


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


def get_episodes(work_id):
    connection = get_connection()
    results = connection.execute("SELECT * FROM episodes WHERE work_id = ? ORDER BY episode_number", (work_id,)).fetchall()
    connection.close()
    return results


def _reading_item_type(value):
    value = str(value or "").strip().lower()
    if value not in {"chapter", "volume"}:
        raise ValueError("Reading item type must be 'chapter' or 'volume'.")
    return value


def ensure_reading_placeholders(work_id, item_type, total_count, offset=0, limit=24):
    """Create bounded generic placeholders only for the visible reading-list page."""
    kind = _reading_item_type(item_type)
    try:
        safe_work_id = _validated_work_id(work_id)
    except (TypeError, ValueError, OverflowError):
        return []

    # The provider's declared total can be absurdly large (or stale).
    # Clamp a valid non-negative hint to the largest trackable item number,
    # while still allowing the requested visible page to be created. The page
    # itself is independently capped below, so this never creates an enormous
    # range or inserts more than 100 placeholders per call.
    total = _safe_optional_integer(total_count, 0, _MAX_SQLITE_INTEGER)
    if total is None:
        return []
    total = min(total, _MAX_TRACKED_EPISODE_NUMBER)
    safe_offset = _safe_optional_integer(offset, 0, _MAX_TRACKED_EPISODE_NUMBER)
    if safe_offset is None:
        return []
    # Accept large-but-valid page-size requests and clamp the actual page;
    # the input limit should not be constrained by the maximum item number.
    parsed_limit = _safe_optional_integer(limit, 0, _MAX_SQLITE_INTEGER)
    if parsed_limit is None:
        return []
    page_size = min(100, max(1, parsed_limit))

    if total <= safe_offset:
        return []
    end = min(total, safe_offset + page_size)
    start_number = safe_offset + 1
    connection = get_connection()
    try:
        connection.executemany(
            """
            INSERT OR IGNORE INTO reading_items
                (work_id, item_type, item_number, title, is_read)
            VALUES (?, ?, ?, NULL, 0)
            """,
            [
                (safe_work_id, kind, number)
                for number in range(start_number, end + 1)
            ],
        )
        connection.commit()
        rows = connection.execute(
            """
            SELECT work_id, item_type, item_number, title, is_read
            FROM reading_items
            WHERE work_id = ? AND item_type = ?
              AND item_number BETWEEN ? AND ?
            ORDER BY item_number
            """,
            (safe_work_id, kind, start_number, end),
        ).fetchall()
        return rows
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def get_reading_items(work_id, item_type, limit=24, offset=0):
    """Return a bounded page of already-created placeholder entries."""
    kind = _reading_item_type(item_type)
    try:
        safe_work_id = _validated_work_id(work_id)
    except (TypeError, ValueError, OverflowError):
        return []

    parsed_limit = _safe_optional_integer(limit, 0, _MAX_SQLITE_INTEGER)
    parsed_offset = _safe_optional_integer(offset, 0, _MAX_TRACKED_EPISODE_NUMBER)
    if parsed_limit is None or parsed_offset is None:
        return []
    safe_limit = min(100, max(1, parsed_limit))

    connection = get_connection()
    try:
        return connection.execute(
            """
            SELECT work_id, item_type, item_number, title, is_read
            FROM reading_items
            WHERE work_id = ? AND item_type = ?
            ORDER BY item_number
            LIMIT ? OFFSET ?
            """,
            (safe_work_id, kind, safe_limit, parsed_offset),
        ).fetchall()
    finally:
        connection.close()


def get_reading_progress(work_id, item_type, total_hint=None):
    """Return read/available counts, using a valid bounded provider total when known."""
    kind = _reading_item_type(item_type)
    try:
        safe_work_id = _validated_work_id(work_id)
    except (TypeError, ValueError, OverflowError):
        return 0, 0

    connection = get_connection()
    try:
        row = connection.execute(
            """
            SELECT COALESCE(SUM(is_read), 0) AS read_count,
                   COALESCE(MAX(item_number), 0) AS highest_item
            FROM reading_items
            WHERE work_id = ? AND item_type = ?
            """,
            (safe_work_id, kind),
        ).fetchone()
    finally:
        connection.close()

    hinted_total = _safe_optional_integer(
        total_hint,
        0,
        _MAX_TRACKED_EPISODE_NUMBER,
    ) if total_hint is not None else None
    total = hinted_total if hinted_total is not None and hinted_total > 0 else int(
        row["highest_item"] or 0
    )
    return int(row["read_count"] or 0), total


def set_reading_item_read(work_id, item_type, item_number, is_read):
    """Save read state and synchronize aggregate chapter/volume progress."""
    kind = _reading_item_type(item_type)
    try:
        safe_work_id = _validated_work_id(work_id)
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError("Work ID must be a non-zero SQLite-safe integer.") from error

    safe_item_number = _safe_optional_integer(
        item_number,
        1,
        _MAX_TRACKED_EPISODE_NUMBER,
    )
    if safe_item_number is None or isinstance(item_number, bool):
        raise ValueError("Reading item number must be an integer from 1 to 1000000.")

    connection = get_connection()
    try:
        connection.execute(
            """
            INSERT OR IGNORE INTO reading_items
                (work_id, item_type, item_number, title, is_read)
            VALUES (?, ?, ?, NULL, 0)
            """,
            (safe_work_id, kind, safe_item_number),
        )
        connection.execute(
            """
            UPDATE reading_items SET is_read = ?
            WHERE work_id = ? AND item_type = ? AND item_number = ?
            """,
            (1 if is_read else 0, safe_work_id, kind, safe_item_number),
        )
        chapter_count = connection.execute(
            """
            SELECT COALESCE(SUM(is_read), 0)
            FROM reading_items WHERE work_id = ? AND item_type = 'chapter'
            """,
            (safe_work_id,),
        ).fetchone()[0]
        volume_count = connection.execute(
            """
            SELECT COALESCE(SUM(is_read), 0)
            FROM reading_items WHERE work_id = ? AND item_type = 'volume'
            """,
            (safe_work_id,),
        ).fetchone()[0]
        connection.execute(
            """
            UPDATE user_library
            SET progress_chapters = ?, progress_volumes = ?,
                updated_date = CURRENT_TIMESTAMP
            WHERE work_id = ?
            """,
            (int(chapter_count or 0), int(volume_count or 0), safe_work_id),
        )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    return get_reading_progress(safe_work_id, kind)


def save_episode_thumbnail_path(work_id, episode_number, thumbnail_path):
    """Persist the local cached image path for one episode."""
    connection = get_connection()
    connection.execute(
        """
        UPDATE episodes
        SET thumbnail_url = ?
        WHERE work_id = ? AND episode_number = ?
        """,
        (str(thumbnail_path) if thumbnail_path else None, int(work_id), int(episode_number)),
    )
    connection.commit()
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
                or (isinstance(target_id, float) and not target_id.is_integer())
                or (isinstance(target_id, str) and not re.fullmatch(r"\s*-?[0-9]+\s*", target_id))
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
    type_is_valid = isinstance(raw_type, str) and bool(raw_type.strip())
    media_type = raw_type.strip().upper() if type_is_valid else "ANIME"
    description = anime.get("description")
    if not isinstance(description, str):
        description = None
    media_format = anime.get("format")
    if not isinstance(media_format, str):
        media_format = None
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
                or (isinstance(target_id, float) and not target_id.is_integer())
                or (isinstance(target_id, str) and not re.fullmatch(r"\s*-?[0-9]+\s*", target_id))
            ):
                continue
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
            if target_title:
                target_start_date = node.get("startDate")
                if not isinstance(target_start_date, dict):
                    target_start_date = {}
                cover_image = node.get("coverImage")
                if not isinstance(cover_image, dict):
                    cover_image = {}
                connection.execute("""
                    INSERT INTO works (
                        id, title, type, format, start_year, start_month, start_day,
                        cover_url, mal_id
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        title = excluded.title,
                        type = excluded.type,
                        format = COALESCE(excluded.format, works.format),
                        start_year = COALESCE(excluded.start_year, works.start_year),
                        start_month = COALESCE(excluded.start_month, works.start_month),
                        start_day = COALESCE(excluded.start_day, works.start_day),
                        cover_url = COALESCE(excluded.cover_url, works.cover_url),
                        mal_id = COALESCE(excluded.mal_id, works.mal_id)
                """, (
                    target_id,
                    target_title,
                    node.get("type") or "ANIME",
                    node.get("format"),
                    target_start_date.get("year"),
                    target_start_date.get("month"),
                    target_start_date.get("day"),
                    cover_image.get("large"),
                    node.get("idMal"),
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
    connection = get_connection()
    connection.execute("UPDATE works SET cover_path = ? WHERE id = ?", (cover_path, work_id))
    connection.commit()
    connection.close()


def get_saved_anime():
    connection = get_connection()
    results = connection.execute("SELECT * FROM works ORDER BY title").fetchall()
    connection.close()
    return results


def get_alternate_titles(work_id):
    """Return locally stored alternate titles for one work."""
    connection = get_connection()
    rows = connection.execute(
        """
        SELECT title
        FROM alternate_titles
        WHERE work_id = ?
        ORDER BY rowid
        """,
        (int(work_id),),
    ).fetchall()
    connection.close()
    return [str(row["title"]) for row in rows if str(row["title"] or "").strip()]


def get_work(work_id):
    connection = get_connection()
    result = connection.execute("""
        SELECT works.*, user_library.status, user_library.progress_episodes,
               user_library.progress_chapters, user_library.progress_volumes,
               user_library.rating, user_library.notes,
               user_library.added_date, user_library.updated_date
        FROM works LEFT JOIN user_library ON user_library.work_id = works.id
        WHERE works.id = ?
    """, (work_id,)).fetchone()
    connection.close()
    return result


def get_relations(work_id):
    connection = get_connection()
    results = connection.execute("""
        SELECT work_relations.*, works.title, works.format, works.type, works.cover_url, works.cover_path
        FROM work_relations LEFT JOIN works ON works.id = work_relations.target_id
        WHERE work_relations.source_id = ? ORDER BY relation_type, title
    """, (work_id,)).fetchall()
    connection.close()
    return results

def get_bundle_characters(work_ids):
    """Return unique characters from every work represented by a bundle."""
    unique = {}

    for work_id in work_ids or []:
        for row in get_characters(work_id):
            character_id = row["id"]
            if character_id not in unique:
                unique[int(character_id)] = dict(row)

    return sorted(
        unique.values(),
        key=lambda row: (
            0 if str(row.get("character_role") or "").upper() == "MAIN" else
            1 if str(row.get("character_role") or "").upper() == "SUPPORTING" else
            2 if str(row.get("character_role") or "").upper() == "BACKGROUND" else
            3,
            str(row.get("character_name") or "").lower(),
        ),
    )


def get_bundle_staff(work_ids):
    """Return one card per staff person with unique roles merged across the bundle."""
    unique = {}

    for work_id in work_ids or []:
        for row in get_staff(work_id):
            person_id = int(row["person_id"])
            entry = unique.get(person_id)

            if entry is None:
                entry = dict(row)
                entry["_roles"] = []
                unique[person_id] = entry

            role_text = str(row["role"] or "")
            for role in role_text.split("\n"):
                role = role.strip()
                if role and role not in entry["_roles"]:
                    entry["_roles"].append(role)

    for entry in unique.values():
        entry["role"] = "\n".join(entry.pop("_roles", []))

    return sorted(
        unique.values(),
        key=lambda row: str(row.get("name") or "").lower(),
    )


def get_bundle_relations(work_ids):
    """Return unique external relations from every work in a bundle."""
    ids = {int(work_id) for work_id in (work_ids or [])}
    unique = {}

    for work_id in ids:
        for row in get_relations(work_id):
            target_id = row["target_id"]
            if target_id is None:
                continue

            target_id = int(target_id)

            # A relation between two members of the same bundle is internal,
            # so it should not appear in the combined Relations section.
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

    return sorted(
        unique.values(),
        key=lambda row: str(row.get("title") or "").lower(),
    )


def add_manual_bundle_link(work_a, work_b):
    """Persist an explicit user-selected bundle link between two works."""
    work_a, work_b = sorted((int(work_a), int(work_b)))
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
    work_a, work_b = sorted((int(work_a), int(work_b)))
    connection = get_connection()
    cursor = connection.execute(
        "DELETE FROM manual_bundle_links WHERE work_a = ? AND work_b = ?",
        (work_a, work_b),
    )
    changed = cursor.rowcount > 0
    connection.commit()
    connection.close()
    return changed


def get_manual_bundle_links(work_ids=None):
    """Return explicit bundle links, optionally limited to works touching these IDs."""
    connection = get_connection()

    if work_ids is None:
        rows = connection.execute(
            "SELECT work_a, work_b FROM manual_bundle_links ORDER BY work_a, work_b"
        ).fetchall()
    else:
        ids = sorted({int(work_id) for work_id in work_ids if work_id is not None})
        if not ids:
            connection.close()
            return []

        placeholders = ",".join("?" for _ in ids)
        rows = connection.execute(
            f"""
            SELECT work_a, work_b
            FROM manual_bundle_links
            WHERE work_a IN ({placeholders}) OR work_b IN ({placeholders})
            ORDER BY work_a, work_b
            """,
            [*ids, *ids],
        ).fetchall()

    connection.close()
    return rows


def add_bundle_exclusion(work_a, work_b):
    """Prevent two works from being automatically grouped together."""
    work_a, work_b = sorted((int(work_a), int(work_b)))
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
    work_id = int(work_id)
    target_id = int(target_id)
    member_ids = {int(value) for value in (bundle_member_ids or []) if value is not None}
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
    connection = get_connection()
    try:
        if work_ids is None:
            rows = connection.execute(
                "SELECT work_a, work_b FROM bundle_exclusions ORDER BY work_a, work_b"
            ).fetchall()
        else:
            ids = sorted({int(work_id) for work_id in work_ids if work_id is not None})
            if not ids:
                return []
            placeholders = ",".join("?" for _ in ids)
            rows = connection.execute(
                f"""
                SELECT work_a, work_b
                FROM bundle_exclusions
                WHERE work_a IN ({placeholders}) OR work_b IN ({placeholders})
                ORDER BY work_a, work_b
                """,
                [*ids, *ids],
            ).fetchall()
        return rows
    finally:
        connection.close()


def get_manual_bundle_partners(work_id):
    """Return the works explicitly manually linked to one work."""
    work_id = int(work_id)
    connection = get_connection()
    rows = connection.execute(
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
        (work_id, work_id, work_id, work_id),
    ).fetchall()
    connection.close()
    return rows




def get_bundle_override(work_ids):
    """Return the saved presentation override for a bundle touching these works."""
    ids = sorted({int(work_id) for work_id in work_ids if work_id is not None})
    if not ids:
        return None

    placeholders = ",".join("?" for _ in ids)
    connection = get_connection()
    order_cases = " ".join(
        f"WHEN ? THEN {index}"
        for index, _ in enumerate(ids)
    )
    row = connection.execute(
        f"""
        SELECT bundle_anchor_id, custom_title, cover_work_id, custom_cover_path
        FROM bundle_overrides
        WHERE bundle_anchor_id IN ({placeholders})
        ORDER BY CASE bundle_anchor_id {order_cases} ELSE {len(ids)} END
        LIMIT 1
        """,
        [*ids, *ids],
    ).fetchone()
    connection.close()
    return row


def save_bundle_override(work_ids, anchor_id, custom_title=None, cover_work_id=None, custom_cover_path=None):
    """Save a bundle presentation override against its current earliest member."""
    ids = sorted({int(work_id) for work_id in work_ids if work_id is not None})
    anchor_id = int(anchor_id)
    if not ids or anchor_id not in ids:
        return False

    if cover_work_id is not None:
        cover_work_id = int(cover_work_id)
        if cover_work_id not in ids:
            return False

    custom_title = str(custom_title).strip() if custom_title is not None else None
    custom_title = custom_title or None
    custom_cover_path = str(custom_cover_path).strip() if custom_cover_path else None

    connection = get_connection()
    placeholders = ",".join("?" for _ in ids)
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
        (anchor_id, custom_title, cover_work_id, custom_cover_path),
    )
    connection.commit()
    connection.close()
    return True


def clear_bundle_override(work_ids):
    """Remove a bundle presentation override."""
    ids = sorted({int(work_id) for work_id in work_ids if work_id is not None})
    if not ids:
        return False

    placeholders = ",".join("?" for _ in ids)
    connection = get_connection()
    cursor = connection.execute(
        f"DELETE FROM bundle_overrides WHERE bundle_anchor_id IN ({placeholders})",
        ids,
    )
    connection.commit()
    connection.close()
    return cursor.rowcount > 0


def add_to_library(work_id, status="Planning"):
    """Add a work or update its status without erasing saved progress and notes.

    Progress is reconstructed from cached episode/reading rows only when a
    library membership is newly created (including re-adding a removed work).
    On conflict, existing counters, ratings, notes, and added_date are retained.
    """
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
                (SELECT COALESCE(SUM(is_read), 0) FROM reading_items
                 WHERE work_id = ? AND item_type = 'chapter'),
                (SELECT COALESCE(SUM(is_read), 0) FROM reading_items
                 WHERE work_id = ? AND item_type = 'volume'),
                CURRENT_TIMESTAMP
            )
            ON CONFLICT(work_id) DO UPDATE SET
                status = excluded.status,
                updated_date = CURRENT_TIMESTAMP
        """, (int(work_id), status, int(work_id), int(work_id), int(work_id)))
        connection.commit()
    finally:
        connection.close()


def remove_from_library(work_id):
    """Remove a work from the user's Library while keeping its cached work data."""
    connection = get_connection()
    cursor = connection.execute(
        "DELETE FROM user_library WHERE work_id = ?",
        (int(work_id),),
    )
    connection.commit()
    connection.close()
    return cursor.rowcount > 0


def delete_work_data(work_id):
    """Permanently delete one exact work ID and verify all work-owned rows are gone."""
    from pathlib import Path

    work_id = int(work_id)
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
                """,
                (work_id, work_id),
            ).fetchall()
            if item["custom_cover_path"]
        ]

        # Delete every row that can keep this exact work in the Library,
        # bundle system, relation graph, or cached work data.
        for table in (
            "episodes",
            "reading_items",
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
        connection.execute(
            "DELETE FROM works WHERE id = ?",
            (work_id,),
        )

        # Do not claim success unless the exact ID is gone everywhere it can
        # affect Library/bundle state. Roll back the whole deletion on failure.
        checks = (
            ("works", "SELECT 1 FROM works WHERE id = ? LIMIT 1"),
            ("user_library", "SELECT 1 FROM user_library WHERE work_id = ? LIMIT 1"),
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
