import requests
import time
import re
from urllib.parse import urlparse


ANILIST_URL = "https://graphql.anilist.co"

MAX_RETRIES = 5
RETRY_DELAY = 1


def anilist_request(query, variables=None):
    """Make a request to AniList GraphQL API with retry logic."""
    last_error = None

    for attempt in range(MAX_RETRIES):
        try:
            response = requests.post(
                ANILIST_URL,
                json={"query": query, "variables": variables or {}},
                timeout=30,
            )
            try:
                data = response.json()
            except ValueError:
                data = {}

            if response.status_code == 429:
                if attempt < MAX_RETRIES - 1:
                    retry_after = response.headers.get("Retry-After")
                    try:
                        wait_time = max(1.0, float(retry_after)) if retry_after is not None else RETRY_DELAY * (2 ** attempt)
                    except (TypeError, ValueError):
                        wait_time = RETRY_DELAY * (2 ** attempt)
                    print(
                        f"AniList rate limited the request (attempt {attempt + 1}/{MAX_RETRIES}). "
                        f"Retrying in {wait_time:g}s..."
                    )
                    time.sleep(wait_time)
                    continue

                errors = data.get("errors") or []
                message = errors[0].get("message") if errors else response.reason
                raise Exception(f"AniList request failed (429): {message}")

            if response.status_code >= 500:
                last_error = Exception(f"AniList server error ({response.status_code}): {response.reason}")
                if attempt < MAX_RETRIES - 1:
                    wait_time = RETRY_DELAY * (2 ** attempt)
                    print(
                        f"AniList server error (attempt {attempt + 1}/{MAX_RETRIES}). "
                        f"Retrying in {wait_time:g}s..."
                    )
                    time.sleep(wait_time)
                    continue
                raise last_error

            if response.status_code >= 400:
                errors = data.get("errors") or []
                message = errors[0].get("message") if errors else response.reason
                raise Exception(f"AniList request failed ({response.status_code}): {message}")

            if "errors" in data:
                raise Exception(data["errors"][0]["message"])

            return data["data"]

        except (
            requests.exceptions.ConnectionError,
            requests.exceptions.Timeout,
            requests.exceptions.ChunkedEncodingError,
        ) as error:
            last_error = error
            if attempt < MAX_RETRIES - 1:
                wait_time = RETRY_DELAY * (2 ** attempt)
                print(f"Network error (attempt {attempt + 1}/{MAX_RETRIES}): {error}. Retrying in {wait_time}s...")
                time.sleep(wait_time)
            else:
                print(f"Failed after {MAX_RETRIES} attempts: {error}")
        except requests.exceptions.RequestException as error:
            raise error

    raise Exception(
        f"Network error after {MAX_RETRIES} attempts. Please check your internet connection and try again. "
        f"(Last error: {str(last_error)[:100]})"
    )


def _media_fields(include_details=False, include_relations=True):
    """Return GraphQL fields shared by search and detail queries."""
    base = """
        id
        idMal
        type
        title { romaji english native }
        episodes
        averageScore
        startDate { year month day }
        coverImage { large }
        format
    """
    if not include_details:
        if not include_relations:
            return base
        return base + """
        relations {
            edges {
                relationType
                node {
                    id
                    idMal
                    type
                    format
                    title { romaji english native }
                    coverImage { large }
                    startDate { year month day }
                }
            }
        }
        """

    return base + """
        description
        status
        endDate { year month day }
        synonyms
        chapters
        volumes
        source
        duration
        streamingEpisodes {
            title
            thumbnail
            url
            site
        }
        studios {
            edges {
                isMain
                node { id name }
            }
        }
        characters(page: 1, perPage: 25, sort: ROLE) {
            edges {
                node {
                    id
                    name { full }
                    image { large }
                }
                role
                voiceActors {
                    id
                    name { full }
                    language
                    image { large }
                }
            }
            pageInfo {
                currentPage
                lastPage
                hasNextPage
            }
        }
        staff(perPage: 15) {
            edges {
                role
                node {
                    id
                    name { full }
                    image { large }
                }
            }
        }
        relations {
            edges {
                relationType
                node {
                    id
                    idMal
                    type
                    format
                    title { romaji english native }
                    coverImage { large }
                    startDate { year month day }
                }
            }
        }
    """


def parse_anilist_url(value):
    """Return the AniList media ID when value is a supported AniList media URL."""
    if not isinstance(value, str):
        return None

    text = value.strip()
    if not text:
        return None

    try:
        parsed = urlparse(text)
    except ValueError:
        return None

    hostname = (parsed.hostname or "").lower()
    if hostname not in {"anilist.co", "www.anilist.co"}:
        return None

    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 2 or parts[0].lower() not in {"anime", "manga"}:
        return None

    try:
        return int(parts[1])
    except ValueError:
        return None


def get_media_by_anilist_url(url, include_relations=False):
    """Fetch the exact AniList media entry referenced by an AniList URL."""
    media_id = parse_anilist_url(url)
    if media_id is None:
        raise ValueError("Invalid AniList media URL")

    query = """
    query ($id: Int) {
        Media(id: $id) {
            %s
        }
    }
    """ % _media_fields(include_details=False, include_relations=include_relations)
    data = anilist_request(query, {"id": media_id})
    return data.get("Media")


def search_anime(
    search,
    page=1,
    per_page=20,
    media_type=None,
    media_format=None,
    format_filter=None,
    status=None,
    season=None,
    year=None,
    sort=None,
    min_score=None,
    genre=None,
    tag=None,
    include_relations=True,
):
    """Search or browse AniList media with optional filters."""
    if media_type not in {None, "ANIME", "MANGA"}:
        raise ValueError("media_type must be None, ANIME, or MANGA")

    if media_type == "MANGA" and media_format not in {None, "MANGA", "NOVEL", "ONE_SHOT"}:
        raise ValueError("Invalid manga media_format")

    if media_type == "ANIME" and media_format is not None:
        if media_format not in {"TV", "TV_SHORT", "MOVIE", "SPECIAL", "OVA", "ONA", "MUSIC"}:
            raise ValueError("Invalid anime media_format")

    valid_formats = {
        "TV", "TV_SHORT", "MOVIE", "SPECIAL", "OVA", "ONA", "MUSIC",
        "MANGA", "NOVEL", "ONE_SHOT",
    }
    if format_filter and format_filter not in valid_formats:
        raise ValueError("Invalid format_filter")

    if status and status not in {"FINISHED", "RELEASING", "NOT_YET_RELEASED", "CANCELLED", "HIATUS"}:
        raise ValueError("Invalid status")

    if season and season not in {"WINTER", "SPRING", "SUMMER", "FALL"}:
        raise ValueError("Invalid season")

    if sort and sort not in {
        "ID", "ID_DESC", "TITLE_ROMAJI", "TITLE_ROMAJI_DESC",
        "START_DATE", "START_DATE_DESC", "END_DATE", "END_DATE_DESC",
        "SCORE", "SCORE_DESC", "POPULARITY", "POPULARITY_DESC",
        "UPDATED_AT", "UPDATED_AT_DESC", "SEARCH_MATCH",
    }:
        raise ValueError("Invalid sort")

    if min_score is not None and not 0 <= int(min_score) <= 100:
        raise ValueError("min_score must be between 0 and 100")

    clean_search = search.strip() if search else None

    effective_formats = None
    if format_filter:
        effective_formats = [format_filter]
    elif media_format:
        effective_formats = [media_format]

    effective_sort = sort
    if not clean_search and effective_sort == "SEARCH_MATCH":
        effective_sort = "POPULARITY_DESC"
    elif clean_search and effective_sort is None:
        effective_sort = "SEARCH_MATCH"

    argument_lines = []
    variable_lines = ["$page: Int", "$perPage: Int"]
    variables = {"page": page, "perPage": per_page}

    if clean_search:
        variable_lines.append("$search: String")
        argument_lines.append("search: $search")
        variables["search"] = clean_search

    if media_type:
        variable_lines.append("$type: MediaType")
        argument_lines.append("type: $type")
        variables["type"] = media_type

    if effective_formats:
        variable_lines.append("$formatFilter: [MediaFormat]")
        argument_lines.append("format_in: $formatFilter")
        variables["formatFilter"] = effective_formats

    if status:
        variable_lines.append("$status: MediaStatus")
        argument_lines.append("status: $status")
        variables["status"] = status

    if season:
        variable_lines.append("$season: MediaSeason")
        argument_lines.append("season: $season")
        variables["season"] = season

    if season and year:
        variable_lines.append("$seasonYear: Int")
        argument_lines.append("seasonYear: $seasonYear")
        variables["seasonYear"] = int(year)
    elif year:
        variable_lines.append("$year: String")
        argument_lines.append("startDate_like: $year")
        variables["year"] = str(year)

    if effective_sort:
        variable_lines.append("$sort: [MediaSort]")
        argument_lines.append("sort: $sort")
        variables["sort"] = [effective_sort]

    if min_score is not None:
        variable_lines.append("$minScore: Int")
        argument_lines.append("averageScore_greater: $minScore")
        variables["minScore"] = int(min_score)

    if genre and genre.strip():
        variable_lines.append("$genres: [String]")
        argument_lines.append("genre_in: $genres")
        variables["genres"] = [genre.strip()]

    if tag and tag.strip():
        variable_lines.append("$tags: [String]")
        argument_lines.append("tag_in: $tags")
        variables["tags"] = [tag.strip()]

    argument_block = ",\n                ".join(argument_lines)
    variable_block = ",\n        ".join(variable_lines)

    query = f"""
    query ({variable_block}) {{
        Page(page: $page, perPage: $perPage) {{
            pageInfo {{
                currentPage
                lastPage
                hasNextPage
            }}
            media(
                {argument_block}
            ) {{
                {_media_fields(include_details=False, include_relations=include_relations)}
            }}
        }}
    }}
    """

    data = anilist_request(query, variables)
    return data["Page"]


def get_media_relations(media_id):
    """Fetch only the lightweight relation data used by series grouping."""
    query = """
    query ($id: Int) {
        Media(id: $id) {
            id
            type
            format
            title { romaji english native }
            coverImage { large }
            episodes
            relations {
                edges {
                    relationType
                    node {
                        id
                        type
                        format
                        title { romaji english native }
                        coverImage { large }
                        episodes
                    }
                }
            }
        }
    }
    """
    data = anilist_request(query, {"id": media_id})
    return data["Media"]

def get_media_relations_batch(media_ids):
    """Fetch lightweight relation data for multiple media IDs in one request."""
    ids = sorted({int(media_id) for media_id in media_ids if media_id is not None})
    if not ids:
        return {}

    # `id_in` is a Media filter exposed on the Page.media field. The top-level
    # Media query returns one Media object, not a list, so using
    # `Media(id_in: ...)` here made the batch enrichment iterate over the
    # object's dictionary keys and crash. Keep this request batched through
    # Page.media so the result is always a list of media records.
    query = """
    query ($ids: [Int], $perPage: Int) {
        Page(page: 1, perPage: $perPage) {
            media(id_in: $ids) {
                id
                type
                format
                title { romaji english native }
                coverImage { large }
                episodes
                startDate { year month day }
                relations {
                    edges {
                        relationType
                        node {
                            id
                            type
                            format
                            title { romaji english native }
                            coverImage { large }
                            episodes
                            startDate { year month day }
                        }
                    }
                }
            }
        }
    }
    """
    data = anilist_request(query, {"ids": ids, "perPage": len(ids)})
    media = (data.get("Page") or {}).get("media") or []
    if isinstance(media, dict):
        media = [media]
    return {
        int(item["id"]): item
        for item in media
        if isinstance(item, dict) and item.get("id") is not None
    }


def get_media_episodes(media_id):
    """Fetch and normalize an AniList airing schedule into local episode rows."""
    query = """
    query ($id: Int) {
        Media(id: $id) {
            airingSchedule(perPage: 50) {
                nodes {
                    airingAt
                    episode
                }
            }
        }
    }
    """
    data = anilist_request(query, {"id": media_id})
    schedule = ((data.get("Media") or {}).get("airingSchedule") or {}).get("nodes") or []

    import datetime

    return [
        {
            "episodeNumber": node.get("episode"),
            "title": f"Episode {node.get('episode')}",
            "description": None,
            "airdate": (
                datetime.datetime.fromtimestamp(int(node["airingAt"])).strftime("%Y-%m-%d")
                if node.get("airingAt") is not None
                else None
            ),
        }
        for node in schedule
        if node.get("episode") is not None
    ]


def _jikan_get(path, params=None):
    """Request Jikan data without bursting its public rate limit."""
    url = f"https://api.jikan.moe/v4/{str(path).lstrip('/')}"
    last_error = None

    for attempt in range(3):
        try:
            response = requests.get(
                url,
                params=params or {},
                timeout=20,
            )
            if response.status_code == 429:
                time.sleep(1.0 + attempt)
                continue
            response.raise_for_status()
            payload = response.json() or {}
            time.sleep(0.35)
            return payload
        except (requests.RequestException, ValueError) as error:
            last_error = error
            if attempt < 2:
                time.sleep(1.0 + attempt)

    if last_error is not None:
        raise last_error
    raise RuntimeError(f"Jikan request failed: {url}")


def _kitsu_get(path, params=None):
    """Request Kitsu JSON:API data for episode fallback fields."""
    url = f"https://kitsu.io/api/edge/{str(path).lstrip('/')}"
    last_error = None

    for attempt in range(3):
        try:
            response = requests.get(
                url,
                params=params or {},
                headers={
                    "Accept": "application/vnd.api+json",
                    "Content-Type": "application/vnd.api+json",
                },
                timeout=20,
            )
            if response.status_code == 429:
                retry_after = response.headers.get("Retry-After")
                try:
                    wait_time = max(1.0, float(retry_after)) if retry_after else 1.0 + attempt
                except (TypeError, ValueError):
                    wait_time = 1.0 + attempt
                time.sleep(wait_time)
                continue
            response.raise_for_status()
            payload = response.json() or {}
            time.sleep(0.25)
            return payload
        except (requests.RequestException, ValueError) as error:
            last_error = error
            if attempt < 2:
                time.sleep(1.0 + attempt)

    if last_error is not None:
        raise last_error
    raise RuntimeError(f"Kitsu request failed: {url}")


def _kitsu_anime_id_for_mal(mal_id):
    """Resolve a Kitsu anime ID from an exact MAL anime ID mapping."""
    payload = _kitsu_get(
        "/mappings",
        {
            "filter[externalSite]": "myanimelist/anime",
            "filter[externalId]": str(int(mal_id)),
            "include": "item",
            "page[limit]": 20,
        },
    )

    for row in payload.get("data") or []:
        relationships = row.get("relationships") or {}
        item = relationships.get("item") or {}
        item_data = item.get("data") or {}
        if item_data.get("type") == "anime" and item_data.get("id") is not None:
            return str(item_data["id"])

    included = payload.get("included") or []
    for row in included:
        if row.get("type") == "anime" and row.get("id") is not None:
            return str(row["id"])

    return None


def _kitsu_episode_map(mal_id, season_number=None):
    """Return Kitsu episodes keyed by episode number for one Kitsu season."""
    kitsu_id = _kitsu_anime_id_for_mal(mal_id)
    if kitsu_id is None:
        return {}

    episodes = []
    offset = 0
    limit = 20

    while True:
        payload = _kitsu_get(
            "/episodes",
            {
                "filter[anime_id]": kitsu_id,
                "page[limit]": limit,
                "page[offset]": offset,
            },
        )
        rows = payload.get("data") or []
        episodes.extend(rows)

        links = payload.get("links") or {}
        if not links.get("next") or not rows:
            break

        # Kitsu returns the next collection URL; use its presence as the
        # authoritative pagination signal and advance by the actual page size.
        offset += len(rows)

    result = {}
    for row in episodes:
        attributes = row.get("attributes") or {}

        if season_number is not None:
            kitsu_season = attributes.get("seasonNumber")
            try:
                if kitsu_season is not None and int(kitsu_season) != int(season_number):
                    continue
            except (TypeError, ValueError):
                continue

        # relativeNumber is the within-season number. Only use absolute
        # number when Kitsu has no usable relative number.
        number = attributes.get("relativeNumber")
        if number is None:
            number = attributes.get("number")
        if number is None:
            continue

        try:
            number = int(number)
        except (TypeError, ValueError):
            continue

        result[number] = {
            **attributes,
            "_kitsu_id": row.get("id"),
        }

    return result


def get_episode_data(media_id, mal_id=None, season_number=None):
    """Fetch episode data from Jikan with a season-aware Kitsu fallback."""
    identity_query = """
    query ($id: Int) {
        Media(id: $id) {
            idMal
        }
    }
    """
    identity = anilist_request(identity_query, {"id": int(media_id)})
    fresh_mal_id = ((identity.get("Media") or {}).get("idMal"))

    # Prefer the fresh AniList cross-reference on every sync. Local MAL IDs
    # can be stale after older bundle/relationship imports.
    resolved_mal_id = fresh_mal_id or mal_id
    if resolved_mal_id is None:
        return {"mal_id": None, "episodes": []}

    resolved_mal_id = int(resolved_mal_id)
    jikan_by_number = {}
    video_by_number = {}

    # Fetch Jikan's complete paginated episode list.
    try:
        page = 1
        while True:
            payload = _jikan_get(
                f"/anime/{resolved_mal_id}/episodes",
                {"page": page},
            )

            for row in payload.get("data") or []:
                number = row.get("mal_id")
                match = re.search(
                    r"/episode/(\d+)(?:/|$)",
                    str(row.get("url") or ""),
                    re.IGNORECASE,
                )
                if match:
                    number = int(match.group(1))
                if number is not None:
                    try:
                        jikan_by_number[int(number)] = row
                    except (TypeError, ValueError):
                        continue

            pagination = payload.get("pagination") or {}
            if not pagination.get("has_next_page"):
                break
            page += 1
    except requests.RequestException as error:
        raise RuntimeError(f"Jikan episode list failed: {error}") from error

    # Jikan's episode-video endpoint is still the same provider, but its
    # results are kept separate so an episode-list failure cannot corrupt them.
    try:
        page = 1
        while True:
            payload = _jikan_get(
                f"/anime/{resolved_mal_id}/videos/episodes",
                {"page": page},
            )

            for row in payload.get("data") or []:
                number_text = str(row.get("episode") or "")
                url_text = str(row.get("url") or "")
                match = re.search(
                    r"\b(?:episode|ep)\s*#?\s*(\d+)\b",
                    number_text,
                    re.IGNORECASE,
                )
                if not match:
                    match = re.search(
                        r"/episode/(\d+)(?:/|$)",
                        url_text,
                        re.IGNORECASE,
                    )
                if match:
                    video_by_number[int(match.group(1))] = row

            pagination = payload.get("pagination") or {}
            if not pagination.get("has_next_page"):
                break
            page += 1
    except requests.RequestException:
        video_by_number = {}

    # The collection endpoint does not reliably include synopsis/artwork for
    # every episode, so fetch only the exact episode records missing either.
    missing_detail = [
        number
        for number, row in jikan_by_number.items()
        if not str(row.get("synopsis") or "").strip()
        or not (
            ((row.get("images") or {}).get("jpg") or {}).get("image_url")
            or ((row.get("images") or {}).get("webp") or {}).get("image_url")
        )
    ]

    for number in missing_detail:
        try:
            detail = _jikan_get(
                f"/anime/{resolved_mal_id}/episodes/{number}"
            ).get("data") or {}
            if detail:
                jikan_by_number[number].update(detail)
        except requests.RequestException:
            continue

    kitsu_by_number = {}
    # Kitsu is deliberately queried only as a field-level fallback. Jikan's
    # episode numbers/titles/dates remain primary whenever they exist.
    try:
        kitsu_by_number = _kitsu_episode_map(resolved_mal_id, season_number)
    except requests.RequestException:
        kitsu_by_number = {}

    result = []
    all_numbers = set(jikan_by_number)
    all_numbers.update(video_by_number)
    all_numbers.update(kitsu_by_number)

    for number in sorted(all_numbers):
        jikan = jikan_by_number.get(number) or {}
        video = video_by_number.get(number) or {}
        kitsu = kitsu_by_number.get(number) or {}
        aired = jikan.get("aired") or {}

        jikan_images = jikan.get("images") or {}
        jikan_jpg = jikan_images.get("jpg") or {}
        jikan_webp = jikan_images.get("webp") or {}
        video_images = video.get("images") or {}
        video_jpg = video_images.get("jpg") or {}
        video_webp = video_images.get("webp") or {}

        kitsu_thumbnail = kitsu.get("thumbnail") or {}
        if isinstance(kitsu_thumbnail, dict):
            kitsu_thumbnail = (
                kitsu_thumbnail.get("original")
                or kitsu_thumbnail.get("large")
                or kitsu_thumbnail.get("medium")
                or kitsu_thumbnail.get("small")
            )

        result.append({
            "episodeNumber": number,
            "title": (
                jikan.get("title")
                or video.get("title")
                or kitsu.get("canonicalTitle")
                or (kitsu.get("titles") or {}).get("en")
                or (kitsu.get("titles") or {}).get("en_us")
                or f"Episode {number}"
            ),
            "description": (
                jikan.get("synopsis")
                or kitsu.get("synopsis")
            ),
            "airdate": (
                str(aired.get("from") or "")[:10]
                or str(kitsu.get("airdate") or "")
                or None
            ),
            "thumbnail": (
                jikan_jpg.get("image_url")
                or jikan_webp.get("image_url")
                or video_jpg.get("image_url")
                or video_webp.get("image_url")
                or kitsu_thumbnail
                or None
            ),
        })

    return {
        "mal_id": resolved_mal_id,
        "episodes": result,
        "jikan_count": len(jikan_by_number),
        "kitsu_count": len(kitsu_by_number),
    }


def get_media_details(media_id):
    """Fetch the complete media record needed by detail/import workflows."""
    query = """
    query ($id: Int) {
        Media(id: $id) {
            %s
            airingSchedule(page: 1, perPage: 50) {
                nodes {
                    airingAt
                    episode
                }
                pageInfo {
                    currentPage
                    lastPage
                    hasNextPage
                }
            }
        }
    }
    """ % _media_fields(include_details=True)
    data = anilist_request(query, {"id": media_id})
    media = data["Media"]

    # AniList paginates character connections. Fetch every page so imports
    # never stop at the first 25 characters.
    characters_connection = (media.get("characters") or {}) if isinstance(media, dict) else {}
    all_character_edges = list(characters_connection.get("edges") or [])
    page_info = characters_connection.get("pageInfo") or {}
    page = int(page_info.get("currentPage") or 1)

    while page_info.get("hasNextPage"):
        page += 1
        characters_query = """
        query ($id: Int, $page: Int) {
            Media(id: $id) {
                characters(page: $page, perPage: 25, sort: ROLE) {
                    edges {
                        node {
                            id
                            name { full }
                            image { large }
                        }
                        role
                        voiceActors {
                            id
                            name { full }
                            language
                            image { large }
                        }
                    }
                    pageInfo {
                        currentPage
                        lastPage
                        hasNextPage
                    }
                }
            }
        }
        """
        page_data = anilist_request(characters_query, {"id": media_id, "page": page})
        connection = ((page_data.get("Media") or {}).get("characters") or {})
        all_character_edges.extend(connection.get("edges") or [])
        page_info = connection.get("pageInfo") or {}

    if isinstance(media, dict):
        media["characters"] = {
            **characters_connection,
            "edges": all_character_edges,
            "pageInfo": {
                **page_info,
                "currentPage": page,
                "hasNextPage": False,
            },
        }

        # Normalize AniList's airing schedule into the episode shape used by
        # the local database. The detail/import code expects episodeNumber,
        # title, and airdate, while the current AniList query provides
        # episode numbers and timestamps through airingSchedule.
        schedule_connection = media.get("airingSchedule") or {}
        schedule = list(schedule_connection.get("nodes") or [])
        schedule_page_info = schedule_connection.get("pageInfo") or {}
        schedule_page = int(schedule_page_info.get("currentPage") or 1)

        while schedule_page_info.get("hasNextPage"):
            schedule_page += 1
            schedule_query = """
            query ($id: Int, $page: Int) {
                Media(id: $id) {
                    airingSchedule(page: $page, perPage: 50) {
                        nodes {
                            airingAt
                            episode
                        }
                        pageInfo {
                            currentPage
                            lastPage
                            hasNextPage
                        }
                    }
                }
            }
            """
            schedule_data = anilist_request(
                schedule_query,
                {"id": media_id, "page": schedule_page},
            )
            schedule_connection = (
                (schedule_data.get("Media") or {}).get("airingSchedule") or {}
            )
            schedule.extend(schedule_connection.get("nodes") or [])
            schedule_page_info = schedule_connection.get("pageInfo") or {}

        # Keep AniList streamingEpisodes raw; it has no reliable episode-number key.\n

    return media
