import sqlite3

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
            rating INTEGER, notes TEXT, added_date DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_date DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (work_id) REFERENCES works(id)
        )
    """)
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
        "source": "TEXT", "end_year": "INTEGER", "duration": "INTEGER", "characters_loaded": "INTEGER NOT NULL DEFAULT 0",
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
            watched INTEGER NOT NULL DEFAULT 0, UNIQUE (work_id, episode_number),
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


def _normalize_work_ids(work_id):
    if isinstance(work_id, (list, tuple, set)):
        values = work_id
    else:
        values = [work_id]

    ids = []
    for value in values:
        try:
            media_id = int(value)
        except (TypeError, ValueError):
            continue
        if media_id not in ids:
            ids.append(media_id)
    return ids


def get_characters(work_id):
    """Return one row per character across one work or a bundle of works."""
    ids = _normalize_work_ids(work_id)
    if not ids:
        return []

    placeholders = ",".join("?" for _ in ids)
    connection = get_connection()
    results = connection.execute(f"""
        SELECT
            characters.id,
            characters.name AS character_name,
            characters.image_path AS character_image_path,
            characters.image_url AS character_image_url,
            (
                SELECT wc.role
                FROM work_characters AS wc
                WHERE wc.work_id IN ({placeholders})
                  AND wc.character_id = characters.id
                ORDER BY
                    CASE UPPER(COALESCE(wc.role, 'UNKNOWN'))
                        WHEN 'MAIN' THEN 0
                        WHEN 'SUPPORTING' THEN 1
                        WHEN 'BACKGROUND' THEN 2
                        ELSE 3
                    END,
                    wc.role
                LIMIT 1
            ) AS character_role,
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
        FROM characters
        WHERE EXISTS (
            SELECT 1
            FROM work_characters AS wc
            WHERE wc.work_id IN ({placeholders})
              AND wc.character_id = characters.id
        )
        ORDER BY
            CASE UPPER(COALEdef get_staff(work_id):
    """Return one row per staff person, combining all of their roles."""
    ids = _normalize_work_ids(work_id)
    if not ids:
        return []

    placeholders = ",".join("?" for _ in ids)
    connection = get_connection()
    results = connection.execute(f"""
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
                    WHERE ws.work_id IN ({placeholders})
                      AND ws.person_id = people.id
                    ORDER BY role
                )
            ) AS role
        FROM people
        WHERE EXISTS (
            SELECT 1
            FROM work_staff AS ws
            WHERE ws.work_id IN ({placeholders})
              AND ws.person_id = people.id
        )
        ORDER BY people.name
    """, [*ids, *ids]).fetchall()
    connection.close()
    return results
or {}).get("large")))
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
                    SELECT role
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
    connection = get_connection()
    for episode in episode_data or []:
        number = episode.get("episodeNumber")
        if number is None:
            continue
        connection.execute("""
            INSERT INTO episodes (work_id, episode_number, title, description, air_date)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(work_id, episode_number) DO UPDATE SET
                title = excluded.title, description = excluded.description, air_date = excluded.air_date
        """, (work_id, number, episode.get("title"), episode.get("description"), episode.get("airdate")))
    connection.commit()
    connection.close()


def get_episodes(work_id):
    connection = get_connection()
    results = connection.execute("SELECT * FROM episodes WHERE work_id = ? ORDER BY episode_number", (work_id,)).fetchall()
    connection.close()
    return results


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


def set_episode_progress(work_id, progress):
    """Set the library episode counter and, when episode rows exist, keep their watched state in sync."""
    connection = get_connection()
    work = connection.execute("SELECT episodes FROM works WHERE id = ?", (work_id,)).fetchone()
    if not work or not connection.execute("SELECT 1 FROM user_library WHERE work_id = ?", (work_id,)).fetchone():
        connection.close()
        return
    total = int(work["episodes"] or 0)
    progress = max(0, min(int(progress), total)) if total else max(0, int(progress))
    episode_count = connection.execute("SELECT COUNT(*) FROM episodes WHERE work_id = ?", (work_id,)).fetchone()[0]
    if episode_count:
        connection.execute("UPDATE episodes SET watched = CASE WHEN episode_number <= ? THEN 1 ELSE 0 END WHERE work_id = ?", (progress, work_id))
        watched_count = connection.execute("SELECT COUNT(*) FROM episodes WHERE work_id = ? AND watched = 1", (work_id,)).fetchone()[0]
        progress = watched_count
    status = "Completed" if total and progress >= total else "Watching" if progress > 0 else "Planning"
    connection.execute("UPDATE user_library SET progress_episodes = ?, status = ?, updated_date = CURRENT_TIMESTAMP WHERE work_id = ?",
                       (progress, status, work_id))
    connection.commit()
    connection.close()


def save_anime(anime):
    title_data = anime["title"]
    title = title_data.get("english") or title_data.get("romaji") or title_data.get("native")
    start_year = (anime.get("startDate") or {}).get("year")
    cover_image = anime.get("coverImage") or {}
    connection = get_connection()
    connection.execute("""
        INSERT INTO works (id, title, type, description, episodes, score, start_year, cover_url,
                           format, chapters, volumes, source, end_year, duration)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            title=excluded.title, type=excluded.type, description=excluded.description,
            episodes=excluded.episodes, score=excluded.score, start_year=excluded.start_year,
            cover_url=excluded.cover_url, format=excluded.format, chapters=excluded.chapters,
            volumes=excluded.volumes, source=excluded.source, end_year=excluded.end_year,
            duration=excluded.duration
    """, (anime["id"], title, anime.get("type") or "ANIME", anime.get("description"), anime.get("episodes"),
          anime.get("averageScore"), start_year, cover_image.get("large"), anime.get("format"),
          anime.get("chapters"), anime.get("volumes"), anime.get("source"), (anime.get("endDate") or {}).get("year"),
          anime.get("duration")))
    for synonym in anime.get("synonyms") or []:
        connection.execute("INSERT OR IGNORE INTO alternate_titles (work_id, title, language) VALUES (?, ?, ?)",
                           (anime["id"], synonym, None))
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
            connection.execute("""
                INSERT INTO works (id, title, type, format, cover_url)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    title = excluded.title,
                    type = excluded.type,
                    format = COALESCE(excluded.format, works.format),
                    cover_url = COALESCE(excluded.cover_url, def get_relations(work_id):
    """Return one row per related work, merging duplicate relations across bundle members."""
    ids = _normalize_work_ids(work_id)
    if not ids:
        return []

    placeholders = ",".join("?" for _ in ids)
    connection = get_connection()
    results = connection.execute(f"""
        SELECT
            MIN(work_relations.source_id) AS source_id,
            work_relations.target_id,
            MIN(work_relations.relation_type) AS relation_type,
            (
                SELECT group_concat(relation_type, char(10))
                FROM (
                    SELECT DISTINCT relation_type
                    FROM work_relations AS wr
                    WHERE wr.target_id = work_relations.target_id
                      AND wr.source_id IN ({placeholders})
                    ORDER BY relation_type
                )
            ) AS relation_types,
            works.title,
            works.format,
            works.type,
            works.cover_url,
            works.cover_path
        FROM work_relations
        LEFT JOIN works ON works.id = work_relations.target_id
        WHERE work_relations.source_id IN ({placeholders})
        GROUP BY work_relations.target_id
        ORDER BY works.title
    """, [*ids, *ids]).fetchall()
    connection.close()
    return results


k_id, cover_path):
    connection = get_connection()
    connection.execute("UPDATE works SET cover_path = ? WHERE id = ?", (cover_path, work_id))
    connection.commit()
    connection.close()


def get_saved_anime():
    connection = get_connection()
    results = connection.execute("SELECT * FROM works ORDER BY title").fetchall()
    connection.close()
    return results


def get_work(work_id):
    connection = get_connection()
    result = connection.execute("""
        SELECT works.*, user_library.status, user_library.progress_episodes,
               user_library.progress_chapters, user_library.rating, user_library.notes,
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


def get_all_relation_cards(relation_type=None, source_id=None):
    """Return stored relations with both sides populated for the Relations explorer."""
    connection = get_connection()
    clauses = []
    params = []
    if relation_type and relation_type != "All":
        clauses.append("work_relations.relation_type = ?")
        params.append(relation_type)
    if source_id is not None:
        clauses.append("work_relations.source_id = ?")
        params.append(source_id)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    results = connection.execute(f"""
        SELECT work_relations.source_id,
               source.title AS source_title,
               work_relations.target_id,
               target.title AS title,
               target.format,
               target.type,
               target.cover_url,
               target.cover_path,
               work_relations.relation_type
        FROM work_relations
        LEFT JOIN works AS source ON source.id = work_relations.source_id
        LEFT JOIN works AS target ON target.id = work_relations.target_id
        {where}
        ORDER BY work_relations.relation_type, source.title, target.title
    """, params).fetchall()
    connection.close()
    return results


def get_relation_type_counts():
    connection = get_connection()
    results = connection.execute("""
        SELECT relation_type, COUNT(*) AS count
        FROM work_relations
        GROUP BY relation_type
        ORDER BY count DESC, relation_type
    """).fetchall()
    connection.close()
    return results


def get_library_relation_sync_ids():
    """Return library works that have not contributed any stored relation edge yet."""
    connection = get_connection()
    results = connection.execute("""
        SELECT works.id
        FROM works
        JOIN user_library ON user_library.work_id = works.id
        WHERE NOT EXISTS (
            SELECT 1 FROM work_relations
            WHERE work_relations.source_id = works.id
               OR work_relations.target_id = works.id
        )
        ORDER BY works.id
    """).fetchall()
    connection.close()
    return [int(row["id"]) for row in results]


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
               user_library.rating, user_library.notes, user_library.added_date, user_library.updated_date
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
