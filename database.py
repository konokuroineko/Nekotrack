import json
import re
import sqlite3
from pathlib import Path

DATABASE_NAME = "anime_tracker.db"


def get_connection():
    connection = sqlite3.connect(DATABASE_NAME)
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


def save_characters(work_id, characters):
    connection = get_connection()
    for edge in characters or []:
        character = edge.get("node") or {}
        character_id = character.get("id")
        name = (character.get("name") or {}).get("full")
        if not character_id or not name:
            continue
        connection.execute("INSERT OR REPLACE INTO characters (id, name, image_url) VALUES (?, ?, ?)",
                           (character_id, name, (character.get("image") or {}).get("large")))
        connection.execute("""
            INSERT INTO work_characters (work_id, character_id, role)
            VALUES (?, ?, ?)
            ON CONFLICT(work_id, character_id) DO UPDATE SET role = excluded.role
        """, (work_id, character_id, edge.get("role") or "UNKNOWN"))
        for actor in edge.get("voiceActors") or []:
            person_id = actor.get("id")
            person_name = actor.get("name") or {}
            if not person_id or not person_name.get("full"):
                continue
            connection.execute("INSERT OR REPLACE INTO people (id, name, image_url) VALUES (?, ?, ?)",
                               (person_id, person_name["full"], (actor.get("image") or {}).get("large")))
            connection.execute("""
                INSERT OR REPLACE INTO character_voice_actors (character_id, person_id, language)
                VALUES (?, ?, ?)
            """, (character_id, person_id, actor.get("language")))
    connection.execute(
        "UPDATE works SET characters_loaded = 1 WHERE id = ?",
        (work_id,),
    )
    connection.commit()
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
    connection = get_connection()
    for edge in staff_edges or []:
        person = edge.get("node") or {}
        person_id = person.get("id")
        person_name = (person.get("name") or {}).get("full")
        role = edge.get("role")
        if not person_id or not person_name or not role:
            continue
        connection.execute("INSERT OR REPLACE INTO people (id, name, image_url) VALUES (?, ?, ?)",
                           (person_id, person_name, (person.get("image") or {}).get("large")))
        connection.execute("INSERT OR IGNORE INTO work_staff (work_id, person_id, role) VALUES (?, ?, ?)",
                           (work_id, person_id, role))
    connection.commit()
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
    """Upsert valid numbered episodes without letting malformed provider rows break a refresh."""
    normalized_episodes = []
    if isinstance(episode_data, (list, tuple)):
        for episode in episode_data:
            if not isinstance(episode, dict):
                continue
            raw_number = episode.get("episodeNumber")
            if isinstance(raw_number, bool):
                continue
            try:
                number = int(raw_number)
            except (TypeError, ValueError, OverflowError):
                continue
            if number < 1:
                continue
            if isinstance(raw_number, float) and not raw_number.is_integer():
                continue
            if isinstance(raw_number, str) and not re.fullmatch(r"\s*\d+\s*", raw_number):
                continue
            normalized = dict(episode)
            normalized["episodeNumber"] = number
            normalized_episodes.append(normalized)

    episodes = normalized_episodes
    connection = get_connection()

    for episode in episodes:
        number = episode["episodeNumber"]
        incoming_thumbnail = str(episode.get("thumbnail") or "").strip() or None
        existing = connection.execute(
            """
            SELECT thumbnail_url
            FROM episodes
            WHERE work_id = ? AND episode_number = ?
            """,
            (int(work_id), number),
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
                title = excluded.title,
                description = excluded.description,
                air_date = excluded.air_date,
                thumbnail_url = excluded.thumbnail_url
        """, (
            int(work_id),
            number,
            episode.get("title"),
            episode.get("description"),
            episode.get("airdate"),
            thumbnail,
        ))

    numbers = sorted({episode["episodeNumber"] for episode in episodes})
    if numbers:
        placeholders = ",".join("?" for _ in numbers)
        connection.execute(
            f"""
            DELETE FROM episodes
            WHERE work_id = ?
              AND episode_number NOT IN ({placeholders})
            """,
            (int(work_id), *numbers),
        )

    connection.commit()
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
    """Create generic numbered placeholders only for the visible reading-list page."""
    item_type = _reading_item_type(item_type)
    try:
        total = max(0, int(total_count or 0))
        start_offset = max(0, int(offset))
        page_size = min(100, max(1, int(limit)))
    except (TypeError, ValueError):
        return []

    if total <= start_offset:
        return []
    end = min(total, start_offset + page_size)
    start_number = start_offset + 1
    connection = get_connection()
    connection.executemany(
        """
        INSERT OR IGNORE INTO reading_items
            (work_id, item_type, item_number, title, is_read)
        VALUES (?, ?, ?, NULL, 0)
        """,
        [
            (int(work_id), item_type, number)
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
        (int(work_id), item_type, start_number, end),
    ).fetchall()
    connection.close()
    return rows


def get_reading_items(work_id, item_type, limit=24, offset=0):
    """Return the already-created placeholder entries for one chapter/volume page."""
    item_type = _reading_item_type(item_type)
    connection = get_connection()
    rows = connection.execute(
        """
        SELECT work_id, item_type, item_number, title, is_read
        FROM reading_items
        WHERE work_id = ? AND item_type = ?
        ORDER BY item_number
        LIMIT ? OFFSET ?
        """,
        (int(work_id), item_type, max(1, min(100, int(limit))), max(0, int(offset))),
    ).fetchall()
    connection.close()
    return rows


def get_reading_progress(work_id, item_type, total_hint=None):
    """Return read and available counts, using AniList's total when known."""
    item_type = _reading_item_type(item_type)
    connection = get_connection()
    row = connection.execute(
        """
        SELECT COALESCE(SUM(is_read), 0) AS read_count,
               COALESCE(MAX(item_number), 0) AS highest_item
        FROM reading_items
        WHERE work_id = ? AND item_type = ?
        """,
        (int(work_id), item_type),
    ).fetchone()
    connection.close()
    try:
        hinted_total = int(total_hint or 0)
    except (TypeError, ValueError):
        hinted_total = 0
    total = hinted_total if hinted_total > 0 else int(row["highest_item"] or 0)
    return int(row["read_count"] or 0), total


def set_reading_item_read(work_id, item_type, item_number, is_read):
    """Save read state and keep the Library's aggregate chapter/volume counters in sync."""
    item_type = _reading_item_type(item_type)
    work_id = int(work_id)
    item_number = int(item_number)
    if item_number < 1:
        raise ValueError("Reading item number must be positive.")

    connection = get_connection()
    connection.execute(
        """
        INSERT OR IGNORE INTO reading_items
            (work_id, item_type, item_number, title, is_read)
        VALUES (?, ?, ?, NULL, 0)
        """,
        (work_id, item_type, item_number),
    )
    connection.execute(
        """
        UPDATE reading_items SET is_read = ?
        WHERE work_id = ? AND item_type = ? AND item_number = ?
        """,
        (1 if is_read else 0, work_id, item_type, item_number),
    )
    chapter_count = connection.execute(
        """
        SELECT COALESCE(SUM(is_read), 0)
        FROM reading_items WHERE work_id = ? AND item_type = 'chapter'
        """,
        (work_id,),
    ).fetchone()[0]
    volume_count = connection.execute(
        """
        SELECT COALESCE(SUM(is_read), 0)
        FROM reading_items WHERE work_id = ? AND item_type = 'volume'
        """,
        (work_id,),
    ).fetchone()[0]
    connection.execute(
        """
        UPDATE user_library
        SET progress_chapters = ?, progress_volumes = ?,
            updated_date = CURRENT_TIMESTAMP
        WHERE work_id = ?
        """,
        (int(chapter_count or 0), int(volume_count or 0), work_id),
    )
    connection.commit()
    connection.close()
    return get_reading_progress(work_id, item_type)


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
    connection = get_connection()
    connection.execute("UPDATE episodes SET watched = ? WHERE work_id = ? AND episode_number = ?",
                       (1 if watched else 0, work_id, episode_number))
    watched_count = connection.execute("SELECT COUNT(*) FROM episodes WHERE work_id = ? AND watched = 1", (work_id,)).fetchone()[0]
    total = connection.execute("SELECT COUNT(*) FROM episodes WHERE work_id = ?", (work_id,)).fetchone()[0]
    if connection.execute("SELECT 1 FROM user_library WHERE work_id = ?", (work_id,)).fetchone():
        status = "Completed" if total and watched_count >= total else "Watching" if watched_count else "Planning"
        connection.execute("""
            UPDATE user_library SET progress_episodes = ?, status = ?, updated_date = CURRENT_TIMESTAMP
            WHERE work_id = ?
        """, (watched_count, status, work_id))
    connection.commit()
    connection.close()
    return watched_count, total


def get_provider_metadata(work_id, provider="mangabaka"):
    """Return preserved raw metadata for a work and provider, if available."""
    connection = get_connection()
    row = connection.execute(
        "SELECT payload_json FROM work_provider_metadata WHERE work_id = ? AND provider = ?",
        (int(work_id), str(provider).lower()),
    ).fetchone()
    connection.close()
    if not row:
        return None
    try:
        payload = json.loads(row["payload_json"])
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, (dict, list)) else None


def save_provider_metadata(work_id, provider, payload, provider_id=None):
    """Persist an unmodified provider payload, including auxiliary endpoint results."""
    connection = get_connection()
    connection.execute("""
        INSERT INTO work_provider_metadata (work_id, provider, provider_id, payload_json, updated_at)
        VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(work_id, provider) DO UPDATE SET
            provider_id = COALESCE(excluded.provider_id, work_provider_metadata.provider_id),
            payload_json = excluded.payload_json,
            updated_at = CURRENT_TIMESTAMP
    """, (
        int(work_id), str(provider).lower(),
        str(provider_id) if provider_id is not None else None,
        json.dumps(payload, ensure_ascii=False),
    ))
    connection.commit()
    connection.close()


def save_reading_item_metadata(work_id, item_type, items):
    """Merge real provider volume/chapter titles into local reading progress rows."""
    kind = str(item_type or "").lower()
    if kind not in {"chapter", "volume"}:
        raise ValueError("item_type must be chapter or volume")
    connection = get_connection()
    saved = 0
    for index, item in enumerate(items or [], start=1):
        if not isinstance(item, dict):
            continue
        raw_number = (
            item.get("number") or item.get("item_number") or item.get("volume_number")
            or item.get("chapter_number") or index
        )
        try:
            match = re.search(r"\d+", str(raw_number))
            number = int(match.group(0)) if match else index
        except (TypeError, ValueError):
            number = index
        if number < 1:
            continue
        title_value = item.get("title") or item.get("name")
        title_value = str(title_value).strip() if title_value is not None else ""
        connection.execute("""
            INSERT INTO reading_items (work_id, item_type, item_number, title, is_read)
            VALUES (?, ?, ?, ?, 0)
            ON CONFLICT(work_id, item_type, item_number) DO UPDATE SET
                title = CASE
                    WHEN excluded.title IS NOT NULL AND TRIM(excluded.title) != ''
                    THEN excluded.title ELSE reading_items.title END
        """, (int(work_id), kind, number, title_value or None))
        saved += 1
    connection.commit()
    connection.close()
    return saved


def save_anime(anime):
    title_data = anime["title"]
    title = title_data.get("english") or title_data.get("romaji") or title_data.get("native")
    start_date = anime.get("startDate") or {}
    start_year = start_date.get("year")
    start_month = start_date.get("month")
    start_day = start_date.get("day")
    cover_image = anime.get("coverImage") or {}
    connection = get_connection()
    connection.execute("""
        INSERT INTO works (
            id, title, type, description, episodes, score, start_year, start_month, start_day,
            cover_url, format, chapters, volumes, source, end_year, duration, mal_id
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            title=excluded.title, type=excluded.type, description=excluded.description,
            episodes=excluded.episodes, score=excluded.score, start_year=excluded.start_year,
            start_month=excluded.start_month, start_day=excluded.start_day,
            cover_url=excluded.cover_url, format=excluded.format, chapters=excluded.chapters,
            volumes=excluded.volumes, source=excluded.source, end_year=excluded.end_year,
            duration=excluded.duration, mal_id=COALESCE(excluded.mal_id, works.mal_id)
    """, (
        anime["id"], title, anime.get("type") or "ANIME", anime.get("description"),
        anime.get("episodes"), anime.get("averageScore"),
        start_year, start_month, start_day, cover_image.get("large"),
        anime.get("format"), anime.get("chapters"), anime.get("volumes"),
        anime.get("source"), (anime.get("endDate") or {}).get("year"),
        anime.get("duration"), anime.get("idMal")
    ))
    for synonym in anime.get("synonyms") or []:
        connection.execute("INSERT OR IGNORE INTO alternate_titles (work_id, title, language) VALUES (?, ?, ?)",
                           (anime["id"], synonym, None))

    # Preserve provider-native metadata instead of flattening it into AniList fields.
    mangabaka_data = anime.get("_mangabaka")
    if isinstance(mangabaka_data, dict):
        import json
        mangabaka_id = anime.get("_mangabaka_id") or mangabaka_data.get("id")
        connection.execute("""
            INSERT INTO work_provider_metadata (work_id, provider, provider_id, payload_json, updated_at)
            VALUES (?, 'mangabaka', ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(work_id, provider) DO UPDATE SET
                provider_id = COALESCE(excluded.provider_id, work_provider_metadata.provider_id),
                payload_json = excluded.payload_json,
                updated_at = CURRENT_TIMESTAMP
        """, (
            anime["id"],
            str(mangabaka_id) if mangabaka_id is not None else None,
            json.dumps(mangabaka_data, ensure_ascii=False),
        ))
        title_records = mangabaka_data.get("titles") or []
        for title_record in title_records:
            if not isinstance(title_record, dict):
                continue
            alt_title = str(title_record.get("title") or "").strip()
            if not alt_title or alt_title.casefold() == str(title or "").casefold():
                continue
            connection.execute(
                "INSERT OR IGNORE INTO alternate_titles (work_id, title, language) VALUES (?, ?, ?)",
                (anime["id"], alt_title, title_record.get("language")),
            )
    for edge in (anime.get("studios") or {}).get("edges") or []:
        studio = edge.get("node") or {}
        if studio.get("id") and studio.get("name"):
            connection.execute("INSERT OR REPLACE INTO studios (id, name, is_main) VALUES (?, ?, ?)",
                               (studio["id"], studio["name"], 1 if edge.get("isMain") else 0))
            connection.execute("INSERT OR IGNORE INTO work_studios (work_id, studio_id) VALUES (?, ?)",
                               (anime["id"], studio["id"]))
    for edge in (anime.get("relations") or {}).get("edges") or []:
        node = edge.get("node") or {}
        target_id = node.get("id")
        relation_type = edge.get("relationType")
        if not target_id or not relation_type:
            continue
        target_title_data = node.get("title") or {}
        target_title = target_title_data.get("english") or target_title_data.get("romaji") or target_title_data.get("native")
        if target_title:
            target_start_date = node.get("startDate") or {}
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
                (node.get("coverImage") or {}).get("large"),
                node.get("idMal"),
            ))
        connection.execute("INSERT OR REPLACE INTO work_relations (source_id, target_id, relation_type) VALUES (?, ?, ?)",
                           (anime["id"], target_id, relation_type))
    connection.commit()
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
    connection = get_connection()
    connection.execute("""
        INSERT OR REPLACE INTO user_library (work_id, status, progress_episodes, updated_date)
        VALUES (?, ?, 0, CURRENT_TIMESTAMP)
    """, (work_id, status))
    connection.commit()
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

    paths = []
    if row["cover_path"]:
        paths.append(Path(str(row["cover_path"])))
    paths.extend(Path(str(path)) for path in override_paths)

    for path in paths:
        try:
            if path.is_file():
                path.unlink()
        except OSError:
            pass

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
               user_library.progress_chapters, user_library.rating, user_library.notes,
               user_library.added_date, user_library.updated_date
        FROM works JOIN user_library ON user_library.work_id = works.id
        ORDER BY user_library.added_date DESC, works.title
    """).fetchall()
    connection.close()
    return results
