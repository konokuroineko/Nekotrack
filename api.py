import datetime as _dt
import hashlib
import re
import requests
import time
from pathlib import Path
from urllib.parse import urlparse
from ui.preferences import get
from mangabaka_api import (
    enrich_anilist_media,
    get_related_series as get_mangabaka_related_series,
    get_series as get_mangabaka_series,
    normalize_series as normalize_mangabaka_series,
)


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
        status
        season
        seasonYear
        genres
        tags { name }
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
        hostname = (parsed.hostname or "").lower()
        path = parsed.path
    except ValueError:
        return None

    if parsed.scheme.lower() not in {"http", "https"}:
        return None
    if hostname not in {"anilist.co", "www.anilist.co"}:
        return None

    parts = [part for part in path.split("/") if part]
    if len(parts) < 2 or parts[0].lower() not in {"anime", "manga"}:
        return None

    try:
        media_id = int(parts[1])
    except (TypeError, ValueError, OverflowError):
        return None
    return media_id if media_id > 0 else None


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

    def _filter_terms(value):
        if not value:
            return []
        values = value if isinstance(value, (list, tuple, set)) else str(value).split(",")
        return list(dict.fromkeys(
            str(part).strip() for part in values if str(part).strip()
        ))

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
        # AniList uses a strict greater-than comparison; the UI cutoff is inclusive.
        variables["minScore"] = max(0, int(min_score) - 1)

    genre_values = _filter_terms(genre)
    if genre_values:
        variable_lines.append("$genres: [String]")
        argument_lines.append("genre_in: $genres")
        variables["genres"] = genre_values

    tag_values = _filter_terms(tag)
    if tag_values:
        variable_lines.append("$tags: [String]")
        argument_lines.append("tag_in: $tags")
        variables["tags"] = tag_values

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
    if int(media_id) < 0:
        details = get_media_details(media_id)
        return details or {
            "id": int(media_id), "type": "MANGA", "format": "MANGA",
            "title": {"english": "MangaBaka entry"}, "relations": {"edges": []},
        }
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
    # MangaBaka-only works use negative local IDs and are deliberately
    # excluded from AniList relation queries.
    ids = sorted({
        int(media_id) for media_id in media_ids
        if media_id is not None and int(media_id) > 0
    })
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


def get_media_details(media_id):
    """Fetch the complete provider-aware media record used by detail/import workflows."""
    try:
        numeric_id = int(media_id)
    except (TypeError, ValueError):
        numeric_id = 0

    # Negative local IDs represent MangaBaka-only series. Never send them to
    # AniList's GraphQL Media(id:) query as if they were AniList IDs.
    if numeric_id < 0:
        payload = get_mangabaka_series(abs(numeric_id), full=True)
        record = payload.get("data", payload) if isinstance(payload, dict) else payload
        if isinstance(record, list):
            record = record[0] if record else None
        if not isinstance(record, dict):
            raise RuntimeError("MangaBaka returned no details for this series.")
        media = normalize_mangabaka_series(record, preferred_id=numeric_id)
        # Bring in the provider's native relationship graph where it exists.
        try:
            related_payload = get_mangabaka_related_series(abs(numeric_id))
            related_data = related_payload.get("data", related_payload) if isinstance(related_payload, dict) else related_payload
            if isinstance(related_data, dict):
                related_data = related_data.get("related") or related_data.get("series") or related_data.get("items") or []
            edges = []
            for related in related_data if isinstance(related_data, list) else []:
                if not isinstance(related, dict):
                    continue
                raw_node = related.get("series") if isinstance(related.get("series"), dict) else related
                if not raw_node.get("id"):
                    continue
                node = normalize_mangabaka_series(raw_node)
                edges.append({
                    "relationType": str(related.get("relation_type") or related.get("relationType") or "RELATED").upper(),
                    "node": {
                        "id": node["id"],
                        "idMal": node.get("idMal"),
                        "type": node.get("type"),
                        "format": node.get("format"),
                        "title": node.get("title"),
                        "coverImage": node.get("coverImage"),
                        "startDate": node.get("startDate"),
                    },
                })
            media["relations"] = {"edges": edges}
        except Exception as error:
            print(f"MangaBaka related-series lookup skipped: {error}")
        return media
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

    # Add MangaBaka's complete series payload for reading-media details. The
    # lookup is best-effort and the AniList record remains the canonical one.
    if str(media.get("type") or "").upper() == "MANGA":
        enrich_anilist_media(media, fetch_full=True)

    return media


# ---------------------------------------------------------------------------
# TMDB episode provider
# ---------------------------------------------------------------------------

TMDB_BASE_URL = "https://api.themoviedb.org/3"
TMDB_IMAGE_BASE_URL = "https://image.tmdb.org/t/p/w780"
TMDB_EPISODE_CACHE_DIRECTORY = Path("data") / "images" / "episodes"


def _tmdb_token():
    return str(get("tmdb_api_token") or "").strip()


def _tmdb_get(path, params=None):
    token = _tmdb_token()
    if not token:
        raise RuntimeError(
            "TMDB API token is not configured. Open Settings and enter your TMDB API Read Access Token."
        )

    response = requests.get(
        f"{TMDB_BASE_URL}/{str(path).lstrip('/')}",
        params=params or {},
        headers={
            "Authorization": f"Bearer {token}",
            "accept": "application/json",
        },
        timeout=20,
    )
    response.raise_for_status()
    time.sleep(0.15)
    return response.json() or {}


def _parse_date(value):
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return _dt.date.fromisoformat(text[:10])
    except ValueError:
        return None


def _normalize_title(value):
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def _candidate_score(candidate, title_variants, target_date):
    names = {
        _normalize_title(candidate.get("name")),
        _normalize_title(candidate.get("original_name")),
    }
    queries = {
        _normalize_title(value)
        for value in (title_variants or [])
        if str(value or "").strip()
    }

    score = 0
    if names & queries:
        score += 1000

    candidate_date = _parse_date(candidate.get("first_air_date"))
    if candidate_date and target_date:
        score -= abs((candidate_date - target_date).days) / 10

    if "JP" in {str(value).upper() for value in (candidate.get("origin_country") or [])}:
        score += 20

    score += min(float(candidate.get("popularity") or 0), 20)
    return score


def _find_tmdb_series(title_variants, target_date):
    variants = [
        str(value).strip()
        for value in (title_variants or [])
        if str(value or "").strip()
    ]
    if not variants:
        raise RuntimeError("No title is available for TMDB series search.")

    candidates = {}
    year = target_date.year if target_date else None

    for query in variants[:6]:
        params = {
            "query": query,
            "include_adult": "false",
        }
        if year:
            params["first_air_date_year"] = year

        payload = _tmdb_get("/search/tv", params)
        for candidate in payload.get("results") or []:
            if candidate.get("id") is not None:
                candidates[int(candidate["id"])] = candidate

    if not candidates:
        for query in variants[:3]:
            payload = _tmdb_get(
                "/search/tv",
                {
                    "query": query,
                    "include_adult": "false",
                },
            )
            for candidate in payload.get("results") or []:
                if candidate.get("id") is not None:
                    candidates[int(candidate["id"])] = candidate

    if not candidates:
        raise RuntimeError("TMDB could not find a matching TV series.")

    return max(
        candidates.values(),
        key=lambda candidate: _candidate_score(
            candidate,
            variants,
            target_date,
        ),
    )


def _find_tmdb_season(series_details, target_date):
    seasons = [
        season
        for season in (series_details.get("seasons") or [])
        if int(season.get("season_number") or -1) >= 0
    ]
    if not seasons:
        raise RuntimeError("TMDB series has no usable seasons.")

    def score(season):
        season_date = _parse_date(season.get("air_date"))
        if season_date is None or target_date is None:
            return (1, 999999, int(season.get("season_number") or 0))
        return (
            0,
            abs((season_date - target_date).days),
            int(season.get("season_number") or 0),
        )

    return min(seasons, key=score)


def _episode_still_url(path):
    if not path:
        return None
    return f"{TMDB_IMAGE_BASE_URL}{path}"


def _pick_best_episode_still(series_id, season_number, episode):
    primary = _episode_still_url(episode.get("still_path"))
    if primary:
        return primary, 1

    try:
        payload = _tmdb_get(
            f"/tv/{int(series_id)}/season/{int(season_number)}/episode/{int(episode['episode_number'])}/images",
            {
                "include_image_language": "en,null",
            },
        )
    except requests.RequestException:
        return None, 0

    stills = payload.get("stills") or []
    if not stills:
        return None, 0

    stills.sort(
        key=lambda item: (
            float(item.get("vote_average") or 0),
            int(item.get("vote_count") or 0),
            int(item.get("width") or 0),
        ),
        reverse=True,
    )
    return _episode_still_url(stills[0].get("file_path")), len(stills)


def _movie_title_similarity(candidate, title_variants):
    names = [
        _normalize_title(candidate.get("title")),
        _normalize_title(candidate.get("original_title")),
    ]
    names = [name for name in names if name]

    queries = [
        _normalize_title(value)
        for value in (title_variants or [])
        if str(value or "").strip()
    ]
    queries = [query for query in queries if query]

    best = 0.0
    for name in names:
        for query in queries:
            if name == query:
                return 1.0
            if name in query or query in name:
                best = max(
                    best,
                    min(len(name), len(query)) / max(len(name), len(query)),
                )
            else:
                prefix = 0
                for left, right in zip(name, query):
                    if left != right:
                        break
                    prefix += 1
                best = max(
                    best,
                    prefix / max(len(name), len(query)),
                )
    return best


def _candidate_movie_score(candidate, title_variants, target_date):
    similarity = _movie_title_similarity(candidate, title_variants)
    score = similarity * 1000

    release_date = _parse_date(candidate.get("release_date"))
    if release_date and target_date:
        score -= abs((release_date - target_date).days) / 10

    score += min(float(candidate.get("popularity") or 0), 20)
    return score, similarity, release_date


def _find_tmdb_movie(title_variants, target_date):
    variants = [
        str(value).strip()
        for value in (title_variants or [])
        if str(value or "").strip()
    ]
    if not variants:
        raise RuntimeError("No title is available for TMDB movie search.")

    candidates = {}
    year = target_date.year if target_date else None

    for query in variants[:10]:
        params = {
            "query": query,
            "include_adult": "false",
            "include_video": "false",
        }
        if year:
            params["primary_release_year"] = year

        payload = _tmdb_get("/search/movie", params)
        for candidate in payload.get("results") or []:
            if candidate.get("id") is not None:
                candidates[int(candidate["id"])] = candidate

    if not candidates:
        for query in variants[:10]:
            payload = _tmdb_get(
                "/search/movie",
                {
                    "query": query,
                    "include_adult": "false",
                    "include_video": "false",
                },
            )
            for candidate in payload.get("results") or []:
                if candidate.get("id") is not None:
                    candidates[int(candidate["id"])] = candidate

    if not candidates:
        raise RuntimeError("TMDB could not find a matching OVA movie.")

    ranked = sorted(
        candidates.values(),
        key=lambda candidate: _candidate_movie_score(
            candidate,
            variants,
            target_date,
        ),
        reverse=True,
    )
    best = ranked[0]
    _, similarity, release_date = _candidate_movie_score(
        best,
        variants,
        target_date,
    )

    if similarity < 0.70:
        raise RuntimeError(
            "TMDB could not confidently match this OVA by title."
        )
    if (
        release_date is not None
        and target_date is not None
        and abs((release_date - target_date).days) > 365
        and similarity < 0.95
    ):
        raise RuntimeError(
            "TMDB found a title match for this OVA, but its release date is too far away."
        )

    return best


def _find_tmdb_ova_movies(title_variants, target_date, expected_episodes):
    """Resolve one TMDB movie per OVA episode using AniList alternate titles."""
    variants = [
        str(value).strip()
        for value in (title_variants or [])
        if str(value or "").strip()
    ]
    variants = list(dict.fromkeys(value for value in variants if value))
    try:
        expected = max(1, int(expected_episodes or 1))
    except (TypeError, ValueError):
        expected = 1

    if expected == 1:
        return [_find_tmdb_movie(variants, target_date)]

    # Search every title independently. AniList alternate titles can contain
    # the actual names of individual bundled OVA episodes (for example
    # "Memory Snow" and "The Frozen Bond").
    selected = []
    selected_ids = set()

    for query in variants:
        candidates = _tmdb_search_movies(query, target_date)
        candidates.sort(
            key=lambda candidate: _candidate_movie_score(
                candidate,
                [query],
                target_date,
            ),
            reverse=True,
        )

        for candidate in candidates:
            _, similarity, release_date = _candidate_movie_score(
                candidate,
                [query],
                target_date,
            )
            if similarity < 0.70:
                continue
            if (
                release_date is not None
                and target_date is not None
                and abs((release_date - target_date).days) > 365
                and similarity < 0.95
            ):
                continue
            candidate_id = int(candidate["id"])
            if candidate_id in selected_ids:
                continue

            selected.append(candidate)
            selected_ids.add(candidate_id)
            break

        if len(selected) >= expected:
            break

    if len(selected) < expected:
        raise RuntimeError(
            f"TMDB matched only {len(selected)} of {expected} OVA episodes by title."
        )

    return selected[:expected]


def _tmdb_search_movies(query, target_date):
    query = str(query or "").strip()
    if not query:
        return []

    def fetch(params):
        payload = _tmdb_get("/search/movie", params)
        return [
            candidate
            for candidate in (payload.get("results") or [])
            if candidate.get("id") is not None
        ]

    base_params = {
        "query": query,
        "include_adult": "false",
        "include_video": "false",
    }

    candidates = []
    seen_ids = set()

    if target_date is not None:
        year_candidates = fetch({
            **base_params,
            "primary_release_year": target_date.year,
        })
        for candidate in year_candidates:
            candidate_id = int(candidate["id"])
            if candidate_id not in seen_ids:
                candidates.append(candidate)
                seen_ids.add(candidate_id)

    # A title may have a different TMDB release year from the AniList start
    # year. Only make the broader request when the year-constrained results do
    # not contain a convincing title match.
    best_similarity = max(
        (
            _movie_title_similarity(candidate, [query])
            for candidate in candidates
        ),
        default=0.0,
    )
    if best_similarity < 0.70:
        for candidate in fetch(base_params):
            candidate_id = int(candidate["id"])
            if candidate_id not in seen_ids:
                candidates.append(candidate)
                seen_ids.add(candidate_id)

    return candidates


def cache_tmdb_episode_image(url, work_id, episode_number):
    """Download one TMDB episode image into NekoTrack's persistent cache."""
    if not url:
        return None

    url = str(url).strip()
    if not url:
        return None

    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
    directory = TMDB_EPISODE_CACHE_DIRECTORY / str(int(work_id))
    directory.mkdir(parents=True, exist_ok=True)

    parsed_path = Path(urlparse(url).path)
    suffix = parsed_path.suffix.lower() or ".jpg"
    if suffix not in {".jpg", ".jpeg", ".png", ".webp"}:
        suffix = ".jpg"

    path = directory / f"{int(episode_number)}_{digest}{suffix}"
    if path.is_file() and path.stat().st_size > 0:
        return str(path)

    response = requests.get(url, timeout=20)
    response.raise_for_status()
    data = response.content
    if not data:
        return None

    path.write_bytes(data)
    if not path.is_file() or path.stat().st_size == 0:
        return None
    return str(path)


def _pick_best_movie_image(movie_id, movie):
    primary = _episode_still_url(movie.get("backdrop_path"))
    if primary:
        return primary, 1

    try:
        payload = _tmdb_get(
            f"/movie/{int(movie_id)}/images",
            {
                "include_image_language": "en,null",
            },
        )
    except requests.RequestException:
        return None, 0

    backdrops = payload.get("backdrops") or []
    if not backdrops:
        return None, 0

    backdrops.sort(
        key=lambda item: (
            float(item.get("vote_average") or 0),
            int(item.get("vote_count") or 0),
            int(item.get("width") or 0),
        ),
        reverse=True,
    )
    return _episode_still_url(backdrops[0].get("file_path")), len(backdrops)


def _get_tmdb_movie_episode(
    title_variants,
    start_date,
    expected_episodes=None,
    tmdb_id=None,
):
    target_date = _parse_date(start_date)
    if target_date is None:
        raise RuntimeError("NekoTrack needs a valid start date to match the OVA.")

    try:
        expected = max(1, int(expected_episodes or 1))
    except (TypeError, ValueError):
        expected = 1

    if expected > 1:
        candidates = _find_tmdb_ova_movies(
            title_variants,
            target_date,
            expected,
        )
    elif tmdb_id is not None:
        candidate = _tmdb_get(f"/movie/{int(tmdb_id)}")
        _, similarity, _ = _candidate_movie_score(
            candidate,
            title_variants,
            target_date,
        )
        if similarity < 0.70:
            candidate = _find_tmdb_movie(title_variants, target_date)
        candidates = [candidate]
    else:
        candidates = [_find_tmdb_movie(title_variants, target_date)]

    episodes = []
    for index, movie in enumerate(candidates, start=1):
        movie_id = int(movie["id"])
        release_date = _parse_date(movie.get("release_date")) or target_date
        image_url, image_count = _pick_best_movie_image(movie_id, movie)

        episodes.append({
            "episodeNumber": index,
            "title": (
                movie.get("title")
                or movie.get("original_title")
                or f"Episode {index}"
            ),
            "description": movie.get("overview") or None,
            "airdate": release_date.isoformat() if release_date else None,
            "thumbnail": image_url,
            "episode_type": "ova",
            "tmdb_episode_id": movie_id,
            "tmdb_image_count": image_count,
        })

    return {
        "tmdb_id": int(candidates[0]["id"]),
        "tmdb_season_number": None,
        "episodes": episodes,
        "tmdb_count": len(episodes),
    }


def get_tmdb_episode_data(
    title_variants,
    start_date,
    end_date=None,
    expected_episodes=None,
    tmdb_id=None,
    tmdb_season_number=None,
    media_format=None,
):
    """Resolve one NekoTrack season and fetch its TMDB episode data."""
    if str(media_format or "").upper() == "OVA":
        return _get_tmdb_movie_episode(
            title_variants,
            start_date,
            expected_episodes,
            tmdb_id,
        )

    target_start = _parse_date(start_date)
    target_end = _parse_date(end_date)

    if target_start is None:
        raise RuntimeError("NekoTrack needs a valid start date to match TMDB.")

    if tmdb_id is None:
        candidate = _find_tmdb_series(title_variants, target_start)
        tmdb_id = int(candidate["id"])

    series_details = _tmdb_get(f"/tv/{int(tmdb_id)}")
    if tmdb_season_number is None:
        selected_season = _find_tmdb_season(series_details, target_start)
        tmdb_season_number = int(selected_season["season_number"])

    season = _tmdb_get(
        f"/tv/{int(tmdb_id)}/season/{int(tmdb_season_number)}",
        {"language": "en-US"},
    )

    selected = []
    for episode in season.get("episodes") or []:
        air_date = _parse_date(episode.get("air_date"))
        if air_date is None or air_date < target_start:
            continue
        if target_end is not None and air_date >= target_end:
            continue

        thumbnail, image_variants = _pick_best_episode_still(
            tmdb_id,
            tmdb_season_number,
            episode,
        )

        selected.append({
            "episodeNumber": int(episode["episode_number"]),
            "title": episode.get("name") or f"Episode {episode['episode_number']}",
            "description": episode.get("overview") or None,
            "airdate": air_date.isoformat(),
            "thumbnail": thumbnail,
            "episode_type": episode.get("episode_type"),
            "tmdb_episode_id": episode.get("id"),
            "tmdb_image_count": image_variants,
        })

    selected.sort(key=lambda item: item["episodeNumber"])

    if expected_episodes:
        try:
            expected = int(expected_episodes)
        except (TypeError, ValueError):
            expected = 0
        if expected > 0 and len(selected) > expected:
            selected = selected[:expected]

    return {
        "tmdb_id": int(tmdb_id),
        "tmdb_season_number": int(tmdb_season_number),
        "episodes": selected,
        "tmdb_count": len(selected),
    }


def get_tmdb_episode_sample(
    title_variants,
    start_date,
    end_date=None,
    expected_episodes=None,
    tmdb_id=None,
    tmdb_season_number=None,
    media_format=None,
):
    """Fetch one lightweight TMDB season sample for in-app testing."""
    data = get_tmdb_episode_data(
        title_variants,
        start_date,
        end_date,
        expected_episodes,
        tmdb_id,
        tmdb_season_number,
        media_format,
    )

    episode = next(
        (row for row in data["episodes"] if int(row["episodeNumber"]) == 1),
        None,
    )

    return {
        **data,
        "sample_episode_1": episode or {},
    }
