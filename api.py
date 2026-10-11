import copy
import datetime as _dt
import hashlib
import math
import re
import requests
import tempfile
import threading
import time
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import urljoin, urlparse
from ui.preferences import get
# All media-provider implementations are maintained in this module. Keep provider
# helpers private where possible and expose the supported operations through __all__.


# Explicit public API surface. Application modules should import provider
# operations here rather than depending on a provider adapter directly.
__all__ = [
    "ANILIST_URL",
    "MangaBakaAPIError",
    "anilist_request",
    "parse_anilist_url",
    "get_media_by_anilist_url",
    "search_anime",
    "get_media_relations",
    "get_media_relations_batch",
    "get_media_episodes",
    "get_media_details",
    "get_tmdb_episode_data",
    "get_tmdb_episode_sample",
    "test_tmdb_connection",
    "cache_tmdb_episode_image",
    "enrich_anilist_media",
    "enrich_anilist_results",
    "get_mangabaka_external_id",
    "get_mangabaka_collection_works",
    "get_mangabaka_public_data",
    "get_mangabaka_publisher",
    "get_mangabaka_publisher_stats",
    "get_mangabaka_related_series",
    "get_mangabaka_series",
    "get_mangabaka_series_collections",
    "get_mangabaka_series_mix",
    "get_mangabaka_series_news",
    "get_mangabaka_similar_publishers",
    "get_mangabaka_volume_records",
    "get_mangabaka_hidden_gems",
    "get_mangabaka_work",
    "get_mangabaka_publishers",
    "normalize_mangabaka_series",
    "search_mangabaka_media",
    "search_mangabaka_series",
]

ANILIST_URL = "https://graphql.anilist.co"

MAX_RETRIES = 5
RETRY_DELAY = 1
MAX_ANILIST_MEDIA_ID = (1 << 31) - 1
MIN_LOCAL_MEDIA_ID = -((1 << 63) - 1)


def _validated_media_id(value):
    """Normalize a local/AniList media ID without truncation or scalar overflow."""
    if isinstance(value, bool):
        raise ValueError("Media ID must be a non-zero integer.")
    if isinstance(value, str):
        text_id = value.strip()
        if not text_id or len(text_id) > 20 or not re.fullmatch(r"[+-]?[0-9]+", text_id):
            raise ValueError("Media ID must be a non-zero integer.")
        value = text_id
    elif isinstance(value, float):
        if not math.isfinite(value) or not value.is_integer():
            raise ValueError("Media ID must be a non-zero integer.")
    elif not isinstance(value, int):
        raise ValueError("Media ID must be a non-zero integer.")

    try:
        numeric_id = int(value)
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError("Media ID must be a non-zero integer.") from error
    if numeric_id == 0:
        raise ValueError("Media ID must be a non-zero integer.")
    # Positive IDs go to AniList's signed 32-bit GraphQL Int. Negative IDs are
    # local MangaBaka references stored in signed 64-bit SQLite keys. Reject
    # the signed-64 minimum too, because abs(min_int64) cannot be represented.
    if numeric_id > MAX_ANILIST_MEDIA_ID or numeric_id < MIN_LOCAL_MEDIA_ID:
        raise ValueError("Media ID is outside the supported provider ID range.")
    return numeric_id


def anilist_request(query, variables=None):
    """Make a request to AniList GraphQL API with retry logic."""
    last_error = None

    def error_message(payload, fallback):
        errors = payload.get("errors") if isinstance(payload, dict) else None
        if isinstance(errors, list):
            for error in errors:
                if not isinstance(error, dict):
                    continue
                message = error.get("message")
                if isinstance(message, str) and message.strip():
                    return message.strip()
        return str(fallback or "AniList returned an unreadable error response.")

    for attempt in range(MAX_RETRIES):
        try:
            response = requests.post(
                ANILIST_URL,
                json={"query": query, "variables": variables or {}},
                timeout=30,
            )
            try:
                data = response.json()
            except (ValueError, TypeError):
                data = None
            if not isinstance(data, dict):
                data = {}

            if response.status_code == 429:
                if attempt < MAX_RETRIES - 1:
                    retry_after = response.headers.get("Retry-After")
                    fallback_wait = RETRY_DELAY * (2 ** attempt)
                    try:
                        requested_wait = (
                            float(retry_after)
                            if retry_after is not None
                            else fallback_wait
                        )
                        # Retry-After is provider-controlled. Values such as
                        # "1e309" become infinity, while huge finite values can
                        # effectively hang a worker. Keep all waits finite and
                        # bounded, with exponential backoff for malformed input.
                        wait_time = (
                            min(60.0, max(1.0, requested_wait))
                            if math.isfinite(requested_wait)
                            else fallback_wait
                        )
                    except (TypeError, ValueError, OverflowError):
                        wait_time = fallback_wait
                    print(
                        f"AniList rate limited the request (attempt {attempt + 1}/{MAX_RETRIES}). "
                        f"Retrying in {wait_time:g}s..."
                    )
                    time.sleep(wait_time)
                    continue

                message = error_message(data, getattr(response, "reason", None))
                raise RuntimeError(f"AniList request failed (429): {message}")

            if response.status_code >= 500:
                last_error = RuntimeError(
                    f"AniList server error ({response.status_code}): "
                    f"{getattr(response, 'reason', '')}"
                )
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
                message = error_message(data, getattr(response, "reason", None))
                raise RuntimeError(
                    f"AniList request failed ({response.status_code}): {message}"
                )

            errors = data.get("errors")
            if errors:
                message = error_message(data, None)
                raise RuntimeError(f"AniList GraphQL request failed: {message}")
            if "errors" in data and errors not in (None, []):
                raise RuntimeError("AniList returned a malformed GraphQL error payload.")

            result = data.get("data")
            if not isinstance(result, dict):
                raise RuntimeError(
                    "AniList returned an unexpected GraphQL response: missing data object."
                )
            return result

        except (
            requests.exceptions.ConnectionError,
            requests.exceptions.Timeout,
            requests.exceptions.ChunkedEncodingError,
        ) as error:
            last_error = error
            if attempt < MAX_RETRIES - 1:
                wait_time = RETRY_DELAY * (2 ** attempt)
                print(
                    f"Network error (attempt {attempt + 1}/{MAX_RETRIES}): "
                    f"{error}. Retrying in {wait_time:g}s..."
                )
                time.sleep(wait_time)
            else:
                print(f"Failed after {MAX_RETRIES} attempts: {error}")
        except requests.exceptions.RequestException:
            raise

    raise RuntimeError(
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
    """Return a positive AniList media ID from a canonical HTTP(S) media URL."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    try:
        parsed = urlparse(text)
        hostname = (parsed.hostname or "").lower()
        port = parsed.port
    except ValueError:
        return None
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"}:
        return None
    if hostname not in {"anilist.co", "www.anilist.co"}:
        return None
    if parsed.username is not None or parsed.password is not None:
        return None
    if scheme == "https" and port not in (None, 443):
        return None
    if scheme == "http" and port not in (None, 80):
        return None
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 2 or parts[0].lower() not in {"anime", "manga"}:
        return None
    id_text = parts[1]
    # AniList's GraphQL Int is signed 32-bit. Reject oversized strings before
    # converting them, so malformed URLs cannot trigger expensive integer parsing.
    if not id_text.isascii() or len(id_text) > 10 or not re.fullmatch(r"[0-9]+", id_text):
        return None
    try:
        media_id = int(id_text)
    except (TypeError, ValueError, OverflowError):
        return None
    return media_id if 1 <= media_id <= MAX_ANILIST_MEDIA_ID else None

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
    media_id = _validated_media_id(media_id)
    if media_id < 0:
        details = get_media_details(media_id)
        return details or {
            "id": media_id, "type": "MANGA", "format": "MANGA",
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
    """Fetch relation details for positive AniList IDs and negative MangaBaka IDs."""
    if not isinstance(media_ids, (list, tuple, set, frozenset)):
        return {}
    valid_ids = set()
    local_ids = set()
    for media_id in media_ids or []:
        if isinstance(media_id, bool):
            continue
        if isinstance(media_id, int):
            numeric_id = media_id
        elif isinstance(media_id, float):
            if not math.isfinite(media_id) or not media_id.is_integer():
                continue
            numeric_id = int(media_id)
        elif isinstance(media_id, str):
            text_id = media_id.strip()
            if (
                not text_id
                or len(text_id) > 20
                or not text_id.isascii()
                or not re.fullmatch(r"[+-]?[0-9]+", text_id)
            ):
                continue
            try:
                numeric_id = int(text_id)
            except (TypeError, ValueError, OverflowError):
                continue
        else:
            continue

        if 1 <= numeric_id <= MAX_ANILIST_MEDIA_ID:
            valid_ids.add(numeric_id)
        elif MIN_LOCAL_MEDIA_ID <= numeric_id < 0:
            # Local MangaBaka IDs are negative in SQLite. Resolve them through
            # the provider-aware detail path rather than passing them to AniList.
            local_ids.add(numeric_id)

    ids = sorted(valid_ids)
    if not ids and not local_ids:
        return {}

    result = {}
    if ids:
        # id_in is a Media filter exposed on Page.media. Keep each request at
        # AniList's supported page size, even if a large local library asks for
        # relation data for hundreds or thousands of entries at once.
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

        batch_size = 50
        for start_index in range(0, len(ids), batch_size):
            batch_ids = ids[start_index:start_index + batch_size]
            data = anilist_request(
                query,
                {"ids": batch_ids, "perPage": len(batch_ids)},
            )
            page_data = data.get("Page") if isinstance(data, dict) else None
            if not isinstance(page_data, dict):
                raise RuntimeError("AniList returned malformed relation-batch page data.")
            media = page_data.get("media")
            if isinstance(media, dict):
                media = [media]
            if not isinstance(media, list):
                raise RuntimeError("AniList returned malformed relation-batch media data.")

            requested_ids = set(batch_ids)
            for item in media:
                if not isinstance(item, dict):
                    continue
                item_id = item.get("id")
                if isinstance(item_id, bool):
                    continue
                if isinstance(item_id, float):
                    if not math.isfinite(item_id) or not item_id.is_integer():
                        continue
                    item_id = int(item_id)
                elif isinstance(item_id, str):
                    text_id = item_id.strip()
                    if (
                        not text_id
                        or len(text_id) > 10
                        or not text_id.isascii()
                        or not text_id.isdigit()
                    ):
                        continue
                    try:
                        item_id = int(text_id)
                    except (TypeError, ValueError, OverflowError):
                        continue
                elif not isinstance(item_id, int):
                    continue
                if item_id in requested_ids:
                    result[item_id] = item

    # MangaBaka-only works are not visible to AniList's id_in query. Resolve
    # each such local ID using get_media_relations(), which fetches its native
    # relation graph from MangaBaka. One failed record must not discard valid
    # AniList batch results or prevent other MangaBaka IDs from being resolved.
    for local_id in sorted(local_ids):
        try:
            details = get_media_relations(local_id)
        except Exception as error:
            print(f"MangaBaka relation lookup skipped for {local_id}: {error}")
            continue
        if isinstance(details, dict) and details.get("id") == local_id:
            result[local_id] = details

    return result


def get_media_episodes(media_id):
    """Fetch all available AniList airing-schedule pages as local episode rows."""
    try:
        media_id = _validated_media_id(media_id)
    except ValueError:
        return []
    if media_id < 1:
        return []

    query = """
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

    data = anilist_request(query, {"id": media_id, "page": 1})
    media = data.get("Media") if isinstance(data, dict) else None
    connection = media.get("airingSchedule") if isinstance(media, dict) else None
    if not isinstance(connection, dict):
        return []

    def safe_page(value, fallback=1):
        try:
            result = int(value)
        except (TypeError, ValueError, OverflowError):
            return fallback
        return result if result >= 1 else fallback

    def clean_nodes(value):
        return value if isinstance(value, list) else []

    schedule = []
    seen_episodes = set()
    raw_nodes = clean_nodes(connection.get("nodes"))
    page_info = connection.get("pageInfo")
    if not isinstance(page_info, dict):
        page_info = {}
    page = safe_page(page_info.get("currentPage"))
    max_page = min(safe_page(page_info.get("lastPage"), 100), 100)

    def append_nodes(nodes):
        added = 0
        for node in clean_nodes(nodes):
            if not isinstance(node, dict):
                continue
            try:
                episode_number = int(node.get("episode"))
            except (TypeError, ValueError, OverflowError):
                continue
            if episode_number < 1 or episode_number in seen_episodes:
                continue
            seen_episodes.add(episode_number)
            schedule.append(node)
            added += 1
        return added

    append_nodes(raw_nodes)
    while page_info.get("hasNextPage") is True and page < max_page:
        requested_page = page + 1
        page_data = anilist_request(query, {"id": media_id, "page": requested_page})
        page_media = page_data.get("Media") if isinstance(page_data, dict) else None
        connection = page_media.get("airingSchedule") if isinstance(page_media, dict) else None
        if not isinstance(connection, dict):
            break
        previous_count = len(schedule)
        append_nodes(connection.get("nodes"))
        page_info = connection.get("pageInfo")
        if not isinstance(page_info, dict):
            page_info = {}
        page = requested_page
        if len(schedule) == previous_count:
            break

    import datetime

    output = []
    for node in sorted(schedule, key=lambda item: safe_page(item.get("episode"), 10**9)):
        try:
            episode_number = int(node.get("episode"))
        except (TypeError, ValueError, OverflowError):
            continue

        airdate = None
        airing_at = node.get("airingAt")
        if airing_at is not None:
            try:
                airdate = datetime.datetime.fromtimestamp(int(airing_at)).strftime("%Y-%m-%d")
            except (TypeError, ValueError, OverflowError, OSError):
                airdate = None

        output.append({
            "episodeNumber": episode_number,
            "title": f"Episode {episode_number}",
            "description": None,
            "airdate": airdate,
        })
    return output


def get_media_details(media_id):
    """Fetch the complete provider-aware media record used by detail/import workflows."""
    numeric_id = _validated_media_id(media_id)
    media_id = numeric_id

    # Negative local IDs represent MangaBaka-only series. Never send them to
    # AniList's GraphQL Media(id:) query as if they were AniList IDs.
    if numeric_id < 0:
        payload = get_mangabaka_series(abs(numeric_id), full=True)
        record = payload.get("data", payload) if isinstance(payload, dict) else payload
        if isinstance(record, list):
            record = record[0] if record else None
        if not isinstance(record, dict):
            raise RuntimeError("MangaBaka returned no details for this series.")

        # Never attach a response for a different provider series to this local
        # ID. A mismatch here would poison both the cached work row and all of
        # the relation edges derived from it.
        raw_record_id = record.get("id")
        if isinstance(raw_record_id, bool):
            raise RuntimeError("MangaBaka returned a malformed series ID.")
        if isinstance(raw_record_id, float):
            if not math.isfinite(raw_record_id) or not raw_record_id.is_integer():
                raise RuntimeError("MangaBaka returned a malformed series ID.")
        elif isinstance(raw_record_id, str):
            text_record_id = raw_record_id.strip()
            if (
                not text_record_id
                or len(text_record_id) > 19
                or not text_record_id.isascii()
                or not text_record_id.isdigit()
            ):
                raise RuntimeError("MangaBaka returned a malformed series ID.")
            raw_record_id = text_record_id
        elif not isinstance(raw_record_id, int):
            raise RuntimeError("MangaBaka returned a malformed series ID.")
        try:
            returned_id = int(raw_record_id)
        except (TypeError, ValueError, OverflowError) as error:
            raise RuntimeError("MangaBaka returned a malformed series ID.") from error
        if returned_id != abs(numeric_id):
            raise RuntimeError("MangaBaka returned details for a different series ID.")

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
    media = data.get("Media") if isinstance(data, dict) else None
    if not isinstance(media, dict):
        raise RuntimeError(f"AniList returned no media details for ID {media_id}.")

    # AniList paginates character and airing-schedule connections. Guard against
    # malformed pageInfo and repeated pages so a provider bug cannot create an
    # unbounded request loop.
    MAX_DETAIL_PAGES = 100

    def _safe_page(value, fallback=1):
        try:
            page_number = int(value)
        except (TypeError, ValueError, OverflowError):
            return fallback
        return page_number if page_number >= 1 else fallback

    def _append_unique_records(existing, incoming, key_function):
        result = []
        seen = set()
        existing_records = existing if isinstance(existing, list) else []
        incoming_records = incoming if isinstance(incoming, list) else []
        for record in existing_records + incoming_records:
            if not isinstance(record, dict):
                continue
            key = key_function(record)
            if key in seen:
                continue
            seen.add(key)
            result.append(record)
        return result

    def _character_key(edge):
        node = edge.get("node") if isinstance(edge, dict) else None
        if isinstance(node, dict) and node.get("id") is not None:
            return ("character", str(node["id"]), str(edge.get("role") or ""))
        return ("raw", repr(edge))

    def _schedule_key(node):
        if node.get("episode") is not None:
            return ("episode", str(node.get("episode")), str(node.get("airingAt")))
        return ("raw", repr(node))

    def _page_limit(page_info):
        return min(_safe_page(page_info.get("lastPage"), MAX_DETAIL_PAGES), MAX_DETAIL_PAGES)

    raw_characters_connection = media.get("characters")
    characters_snapshot_valid = isinstance(raw_characters_connection, dict)
    characters_connection = (
        raw_characters_connection if isinstance(raw_characters_connection, dict) else {}
    )
    raw_character_edges = characters_connection.get("edges")
    if not isinstance(raw_character_edges, list):
        characters_snapshot_valid = False
        raw_character_edges = []
    elif any(not isinstance(edge, dict) for edge in raw_character_edges):
        # Deduplication intentionally drops non-dictionary entries; remember
        # that doing so made this response incomplete, not an authoritative
        # empty/smaller cast snapshot.
        characters_snapshot_valid = False

    page_info = characters_connection.get("pageInfo")
    if not isinstance(page_info, dict):
        characters_snapshot_valid = False
        page_info = {}
    elif not isinstance(page_info.get("hasNextPage"), bool):
        characters_snapshot_valid = False

    all_character_edges = _append_unique_records(
        [], raw_character_edges, _character_key
    )
    page = _safe_page(page_info.get("currentPage"))
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
    while page_info.get("hasNextPage") is True and page < _page_limit(page_info):
        requested_page = page + 1
        page_data = anilist_request(
            characters_query, {"id": media_id, "page": requested_page}
        )
        page_media = page_data.get("Media") if isinstance(page_data, dict) else None
        connection = page_media.get("characters") if isinstance(page_media, dict) else None
        if not isinstance(connection, dict):
            characters_snapshot_valid = False
            break
        incoming_edges = connection.get("edges")
        if not isinstance(incoming_edges, list):
            characters_snapshot_valid = False
            incoming_edges = []
        elif any(not isinstance(edge, dict) for edge in incoming_edges):
            characters_snapshot_valid = False
        previous_count = len(all_character_edges)
        all_character_edges = _append_unique_records(
            all_character_edges, incoming_edges, _character_key
        )
        page_info = connection.get("pageInfo")
        if not isinstance(page_info, dict):
            characters_snapshot_valid = False
            page_info = {}
        elif not isinstance(page_info.get("hasNextPage"), bool):
            characters_snapshot_valid = False
        page = requested_page
        # A repeated/empty page despite hasNextPage=True is a broken provider
        # response. Stop instead of repeatedly downloading the same page.
        if len(all_character_edges) == previous_count:
            if page_info.get("hasNextPage") is True:
                characters_snapshot_valid = False
            break

    if page_info.get("hasNextPage") is True and page >= _page_limit(page_info):
        # The page cap is a safety stop, not proof that every page was fetched.
        characters_snapshot_valid = False

    media["characters"] = {
        **characters_connection,
        "edges": all_character_edges,
        "pageInfo": {
            **page_info,
            "currentPage": page,
            "hasNextPage": False,
        },
    }
    media["_characters_snapshot_valid"] = characters_snapshot_valid

    # The schedule data is used by detail/import views; write the complete
    # deduplicated node list back onto the returned media object.
    schedule_connection = media.get("airingSchedule")
    if not isinstance(schedule_connection, dict):
        schedule_connection = {}
    schedule_page_info = schedule_connection.get("pageInfo")
    if not isinstance(schedule_page_info, dict):
        schedule_page_info = {}
    schedule = _append_unique_records(
        [], schedule_connection.get("nodes"), _schedule_key
    )
    schedule_page = _safe_page(schedule_page_info.get("currentPage"))
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
    while (
        schedule_page_info.get("hasNextPage") is True
        and schedule_page < _page_limit(schedule_page_info)
    ):
        requested_page = schedule_page + 1
        schedule_data = anilist_request(
            schedule_query, {"id": media_id, "page": requested_page}
        )
        schedule_media = (
            schedule_data.get("Media") if isinstance(schedule_data, dict) else None
        )
        schedule_connection = (
            schedule_media.get("airingSchedule")
            if isinstance(schedule_media, dict)
            else None
        )
        if not isinstance(schedule_connection, dict):
            break
        previous_count = len(schedule)
        schedule = _append_unique_records(
            schedule, schedule_connection.get("nodes"), _schedule_key
        )
        schedule_page_info = schedule_connection.get("pageInfo")
        if not isinstance(schedule_page_info, dict):
            schedule_page_info = {}
        schedule_page = requested_page
        if len(schedule) == previous_count:
            break

    media["airingSchedule"] = {
        **schedule_connection,
        "nodes": schedule,
        "pageInfo": {
            **schedule_page_info,
            "currentPage": schedule_page,
            "hasNextPage": False,
        },
    }

    # Normalize the remaining connection containers without converting
    # missing/malformed data into an authoritative empty snapshot. Preserve
    # edge members as received; database persistence validates each edge and
    # will only reconcile stale links for a complete, well-formed list.
    for connection_name in ("staff", "studios", "relations"):
        raw_connection = media.get(connection_name)
        if not isinstance(raw_connection, dict):
            media[connection_name] = {"edges": None}
            continue

        raw_edges = raw_connection.get("edges")
        media[connection_name] = {
            **raw_connection,
            "edges": raw_edges if isinstance(raw_edges, list) else None,
        }

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
MAX_TMDB_EPISODE_IMAGE_BYTES = 20 * 1024 * 1024
MAX_TMDB_EPISODE_IMAGE_WIDTH = 8192
MAX_TMDB_EPISODE_IMAGE_HEIGHT = 8192
MAX_TMDB_EPISODE_IMAGE_PIXELS = 32_000_000
MAX_TMDB_IMAGE_REDIRECTS = 5


def _tmdb_token():
    return str(get("tmdb_api_token") or "").strip()


def test_tmdb_connection(token):
    """Validate a TMDB API token through the same shared API module as lookups."""
    token = str(token or "").strip()
    if not token:
        raise ValueError("TMDB API token is required.")

    response = requests.get(
        f"{TMDB_BASE_URL}/configuration",
        headers={
            "Authorization": f"Bearer {token}",
            "accept": "application/json",
        },
        timeout=10,
    )
    try:
        response.raise_for_status()
    finally:
        response.close()
    return True


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
    try:
        payload = response.json()
    except (ValueError, TypeError) as error:
        raise RuntimeError(f"TMDB returned invalid JSON for {path}.") from error
    if not isinstance(payload, dict):
        raise RuntimeError(f"TMDB returned an unexpected response for {path}.")
    return payload

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
    candidate = candidate if isinstance(candidate, dict) else {}
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

    countries = candidate.get("origin_country") or []
    if isinstance(countries, str):
        countries = [countries]
    if isinstance(countries, (list, tuple, set)) and "JP" in {
        str(value).upper() for value in countries
    }:
        score += 20

    score += min(max(_safe_float(candidate.get("popularity")), 0.0), 20.0)
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
        params = {"query": query, "include_adult": "false"}
        if year:
            params["first_air_date_year"] = year
        for candidate in _tmdb_result_records(_tmdb_get("/search/tv", params)):
            candidates[candidate["id"]] = candidate

    if not candidates:
        for query in variants[:3]:
            payload = _tmdb_get(
                "/search/tv",
                {"query": query, "include_adult": "false"},
            )
            for candidate in _tmdb_result_records(payload):
                candidates[candidate["id"]] = candidate

    if not candidates:
        raise RuntimeError("TMDB could not find a matching TV series.")

    return max(
        candidates.values(),
        key=lambda candidate: _candidate_score(candidate, variants, target_date),
    )

def _find_tmdb_season(series_details, target_date):
    if not isinstance(series_details, dict):
        raise RuntimeError("TMDB returned an invalid TV series payload.")
    raw_seasons = series_details.get("seasons")
    if not isinstance(raw_seasons, list):
        raw_seasons = []

    seasons = []
    for season in raw_seasons:
        if not isinstance(season, dict):
            continue
        try:
            season_number = int(season.get("season_number"))
        except (TypeError, ValueError, OverflowError):
            continue
        # Season 0 is valid in TMDB and represents specials.
        if season_number >= 0:
            seasons.append({**season, "season_number": season_number})

    if not seasons:
        raise RuntimeError("TMDB series has no usable seasons.")

    def score(season):
        season_date = _parse_date(season.get("air_date"))
        if season_date is None or target_date is None:
            return (1, 999999, season["season_number"])
        return (
            0,
            abs((season_date - target_date).days),
            season["season_number"],
        )

    return min(seasons, key=score)

def _episode_still_url(path):
    if not isinstance(path, str):
        return None
    path = path.strip()
    if not path.startswith("/") or path.startswith("//"):
        return None
    return f"{TMDB_IMAGE_BASE_URL}{path}"

def _pick_best_episode_still(series_id, season_number, episode):
    if not isinstance(episode, dict):
        return None, 0
    primary = _episode_still_url(episode.get("still_path"))
    if primary:
        return primary, 1

    try:
        episode_number = int(episode.get("episode_number"))
        payload = _tmdb_get(
            f"/tv/{int(series_id)}/season/{int(season_number)}/episode/{episode_number}/images",
            {"include_image_language": "en,null"},
        )
    except (requests.RequestException, RuntimeError, TypeError, ValueError, OverflowError, KeyError):
        return None, 0

    if not isinstance(payload, dict):
        return None, 0
    raw_stills = payload.get("stills")
    if not isinstance(raw_stills, list):
        return None, 0
    stills = [item for item in raw_stills if isinstance(item, dict)]
    if not stills:
        return None, 0

    stills.sort(
        key=lambda item: (
            _safe_float(item.get("vote_average")),
            _safe_float(item.get("vote_count")),
            _safe_float(item.get("width")),
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
    candidate = candidate if isinstance(candidate, dict) else {}
    similarity = _movie_title_similarity(candidate, title_variants)
    score = similarity * 1000

    release_date = _parse_date(candidate.get("release_date"))
    if release_date and target_date:
        score -= abs((release_date - target_date).days) / 10

    score += min(max(_safe_float(candidate.get("popularity")), 0.0), 20.0)
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
        for candidate in _tmdb_result_records(_tmdb_get("/search/movie", params)):
            candidates[candidate["id"]] = candidate

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
            for candidate in _tmdb_result_records(payload):
                candidates[candidate["id"]] = candidate

    if not candidates:
        raise RuntimeError("TMDB could not find a matching OVA movie.")

    ranked = sorted(
        candidates.values(),
        key=lambda candidate: _candidate_movie_score(candidate, variants, target_date),
        reverse=True,
    )
    best = ranked[0]
    _, similarity, release_date = _candidate_movie_score(best, variants, target_date)

    if similarity < 0.70:
        raise RuntimeError("TMDB could not confidently match this OVA by title.")
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


def _tmdb_result_records(payload):
    """Return only TMDB result objects with usable positive numeric IDs."""
    if not isinstance(payload, dict):
        return []
    records = payload.get("results")
    if not isinstance(records, list):
        return []
    output = []
    for candidate in records:
        if not isinstance(candidate, dict):
            continue
        try:
            candidate_id = int(candidate.get("id"))
        except (TypeError, ValueError, OverflowError):
            continue
        if candidate_id <= 0:
            continue
        normalized = dict(candidate)
        normalized["id"] = candidate_id
        output.append(normalized)
    return output


def _safe_float(value, fallback=0.0):
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return fallback
    return result if math.isfinite(result) else fallback


def _tmdb_search_movies(query, target_date):
    query = str(query or "").strip()
    if not query:
        return []

    def fetch(params):
        return _tmdb_result_records(_tmdb_get("/search/movie", params))

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
            candidate_id = candidate["id"]
            if candidate_id not in seen_ids:
                candidates.append(candidate)
                seen_ids.add(candidate_id)

    # A title may have a different TMDB release year from the AniList start
    # year. Only make the broader request when the year-constrained results do
    # not contain a convincing title match.
    best_similarity = max(
        (_movie_title_similarity(candidate, [query]) for candidate in candidates),
        default=0.0,
    )
    if best_similarity < 0.70:
        for candidate in fetch(base_params):
            candidate_id = candidate["id"]
            if candidate_id not in seen_ids:
                candidates.append(candidate)
                seen_ids.add(candidate_id)

    return candidates

def _valid_image_data(data):
    """Decode bounded image bytes, rejecting pathological dimensions before full decode."""
    if not isinstance(data, (bytes, bytearray, memoryview)) or not data:
        return False
    if len(data) > MAX_TMDB_EPISODE_IMAGE_BYTES:
        return False

    raw = bytes(data)
    try:
        from PySide6.QtCore import QByteArray, QBuffer, QIODevice
        from PySide6.QtGui import QImageReader
    except Exception:
        # The application normally has Qt available. Keep a conservative
        # signature-only fallback for test/tooling environments without Qt.
        return (
            raw.startswith(b"\xFF\xD8\xFF")
            or raw.startswith(b"\x89PNG\r\n\x1a\n")
            or (len(raw) >= 12 and raw[:4] == b"RIFF" and raw[8:12] == b"WEBP")
        )

    buffer = QBuffer()
    try:
        buffer.setData(QByteArray(raw))
        if not buffer.open(QIODevice.ReadOnly):
            return False
        reader = QImageReader(buffer)
        reader.setDecideFormatFromContent(True)
        dimensions = reader.size()
        if not dimensions.isValid():
            return False

        width = dimensions.width()
        height = dimensions.height()
        if (
            width < 1
            or height < 1
            or width > MAX_TMDB_EPISODE_IMAGE_WIDTH
            or height > MAX_TMDB_EPISODE_IMAGE_HEIGHT
            or width * height > MAX_TMDB_EPISODE_IMAGE_PIXELS
        ):
            return False

        image = reader.read()
        return not image.isNull()
    except Exception:
        return False
    finally:
        buffer.close()


def _is_safe_tmdb_episode_image_url(value):
    """Only allow HTTPS artwork URLs served by TMDB's dedicated image host."""
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        parsed = urlparse(value.strip())
        hostname = (parsed.hostname or "").lower()
        port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme.lower() == "https"
        and hostname == "image.tmdb.org"
        and port in (None, 443)
        and parsed.username is None
        and parsed.password is None
        and parsed.path.startswith("/t/p/")
        and not parsed.fragment
    )


def _get_tmdb_episode_image_response(url):
    """Follow a small number of redirects, revalidating every destination."""
    current_url = url
    for redirect_count in range(MAX_TMDB_IMAGE_REDIRECTS + 1):
        if not _is_safe_tmdb_episode_image_url(current_url):
            raise ValueError("Only HTTPS TMDB image URLs are allowed.")

        response = requests.get(
            current_url,
            timeout=20,
            stream=True,
            allow_redirects=False,
        )
        status_code = getattr(response, "status_code", 200)
        if status_code in {301, 302, 303, 307, 308}:
            headers = getattr(response, "headers", {}) or {}
            location = headers.get("Location") or headers.get("location")
            response.close()
            if not isinstance(location, str) or not location.strip():
                raise ValueError("TMDB image redirect did not include a destination.")
            destination = urljoin(current_url, location.strip())
            if not _is_safe_tmdb_episode_image_url(destination):
                raise ValueError("TMDB image redirect destination is not trusted.")
            if redirect_count >= MAX_TMDB_IMAGE_REDIRECTS:
                raise ValueError("TMDB image exceeded the redirect limit.")
            current_url = destination
            continue

        final_url = getattr(response, "url", None)
        if isinstance(final_url, str) and final_url.strip():
            if not _is_safe_tmdb_episode_image_url(final_url):
                response.close()
                raise ValueError("TMDB image response ended at an untrusted URL.")
        try:
            response.raise_for_status()
        except Exception:
            response.close()
            raise
        return response

    raise ValueError("TMDB image exceeded the redirect limit.")


def _read_bounded_tmdb_image_response(response):
    headers = getattr(response, "headers", {}) or {}
    declared_length = headers.get("Content-Length") or headers.get("content-length")
    if declared_length not in (None, ""):
        try:
            parsed_length = int(declared_length)
        except (TypeError, ValueError, OverflowError) as error:
            raise ValueError("TMDB image has an invalid Content-Length header.") from error
        if parsed_length < 0:
            raise ValueError("TMDB image has an invalid Content-Length header.")
        if parsed_length > MAX_TMDB_EPISODE_IMAGE_BYTES:
            raise ValueError("TMDB episode image exceeds the download size limit.")

    chunks = []
    total_bytes = 0
    for chunk in response.iter_content(chunk_size=64 * 1024):
        if not chunk:
            continue
        total_bytes += len(chunk)
        if total_bytes > MAX_TMDB_EPISODE_IMAGE_BYTES:
            raise ValueError("TMDB episode image exceeds the download size limit.")
        chunks.append(chunk)
    return b"".join(chunks)


def cache_tmdb_episode_image(url, work_id, episode_number):
    """Download one bounded, validated TMDB episode image into the persistent cache."""
    if not url:
        return None

    url = str(url).strip()
    if not url:
        return None
    if not _is_safe_tmdb_episode_image_url(url):
        raise ValueError("Only HTTPS TMDB image URLs are allowed.")

    def positive_integer(value, label):
        if isinstance(value, bool):
            raise ValueError(f"{label} must be an integer.")
        if isinstance(value, float) and (
            not math.isfinite(value) or not value.is_integer()
        ):
            raise ValueError(f"{label} must be an integer.")
        if isinstance(value, str) and not re.fullmatch(r"\s*\+?[0-9]+\s*", value):
            raise ValueError(f"{label} must be an integer.")
        try:
            parsed = int(value)
        except (TypeError, ValueError, OverflowError) as error:
            raise ValueError(f"{label} must be an integer.") from error
        if parsed <= 0:
            raise ValueError(f"{label} must be positive.")
        return parsed

    work_number = positive_integer(work_id, "Work ID")
    episode_number = positive_integer(episode_number, "Episode number")

    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
    directory = TMDB_EPISODE_CACHE_DIRECTORY / str(work_number)
    directory.mkdir(parents=True, exist_ok=True)

    parsed_path = Path(urlparse(url).path)
    suffix = parsed_path.suffix.lower() or ".jpg"
    if suffix not in {".jpg", ".jpeg", ".png", ".webp"}:
        suffix = ".jpg"

    path = directory / f"{episode_number}_{digest}{suffix}"
    if path.is_file():
        try:
            cached_size = path.stat().st_size
            # Do not read an untrusted/corrupt cache file into memory unless
            # its size is already within the same limit as fresh downloads.
            cached_data = (
                path.read_bytes()
                if 0 < cached_size <= MAX_TMDB_EPISODE_IMAGE_BYTES
                else b""
            )
        except OSError:
            cached_data = b""
        if cached_data and _valid_image_data(cached_data):
            return str(path)
        try:
            path.unlink()
        except OSError:
            pass

    response = _get_tmdb_episode_image_response(url)
    try:
        data = _read_bounded_tmdb_image_response(response)
    finally:
        response.close()

    if not _valid_image_data(data):
        return None

    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=f".{path.stem}.",
            suffix=".tmp",
            dir=str(directory),
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            handle.write(data)
        temporary_path.replace(path)
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass

    if not path.is_file() or path.stat().st_size == 0:
        return None
    return str(path)


def _pick_best_movie_image(movie_id, movie):
    if not isinstance(movie, dict):
        return None, 0
    primary = _episode_still_url(movie.get("backdrop_path"))
    if primary:
        return primary, 1

    try:
        payload = _tmdb_get(
            f"/movie/{int(movie_id)}/images",
            {"include_image_language": "en,null"},
        )
    except (requests.RequestException, RuntimeError, TypeError, ValueError, OverflowError):
        return None, 0

    if not isinstance(payload, dict):
        return None, 0
    raw_backdrops = payload.get("backdrops")
    if not isinstance(raw_backdrops, list):
        return None, 0
    backdrops = [item for item in raw_backdrops if isinstance(item, dict)]
    if not backdrops:
        return None, 0

    backdrops.sort(
        key=lambda item: (
            _safe_float(item.get("vote_average")),
            _safe_float(item.get("vote_count")),
            _safe_float(item.get("width")),
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
        tmdb_id = candidate["id"]
    try:
        tmdb_id = int(tmdb_id)
    except (TypeError, ValueError, OverflowError) as error:
        raise RuntimeError("NekoTrack has an invalid TMDB series ID.") from error
    if tmdb_id <= 0:
        raise RuntimeError("NekoTrack has an invalid TMDB series ID.")

    # When the season is already mapped, skip the unnecessary series-details request.
    if tmdb_season_number is None:
        series_details = _tmdb_get(f"/tv/{tmdb_id}")
        selected_season = _find_tmdb_season(series_details, target_start)
        tmdb_season_number = selected_season["season_number"]
    try:
        tmdb_season_number = int(tmdb_season_number)
    except (TypeError, ValueError, OverflowError) as error:
        raise RuntimeError("NekoTrack has an invalid TMDB season number.") from error
    if tmdb_season_number < 0:
        raise RuntimeError("NekoTrack has an invalid TMDB season number.")

    season = _tmdb_get(
        f"/tv/{tmdb_id}/season/{tmdb_season_number}",
        {"language": "en-US"},
    )
    if not isinstance(season, dict):
        raise RuntimeError("TMDB returned an invalid season payload.")

    raw_episodes = season.get("episodes")
    if not isinstance(raw_episodes, list):
        raw_episodes = []

    selected = []
    for episode in raw_episodes:
        if not isinstance(episode, dict):
            continue
        try:
            episode_number = int(episode.get("episode_number"))
        except (TypeError, ValueError, OverflowError):
            continue
        if episode_number < 1:
            continue

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
        name = episode.get("name")
        overview = episode.get("overview")
        selected.append({
            "episodeNumber": episode_number,
            "title": name if isinstance(name, str) and name.strip() else f"Episode {episode_number}",
            "description": overview if isinstance(overview, str) and overview.strip() else None,
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
        except (TypeError, ValueError, OverflowError):
            expected = 0
        if expected > 0 and len(selected) > expected:
            selected = selected[:expected]

    return {
        "tmdb_id": tmdb_id,
        "tmdb_season_number": tmdb_season_number,
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


# ---------------------------------------------------------------------------
# MangaBaka catalogue API (implementation lives here; there is no separate
# mangabaka_api module).
# ---------------------------------------------------------------------------

MANGABAKA_BASE_URL = "https://api.mangabaka.org/v2/"
REQUEST_TIMEOUT = 18
MANGABAKA_MAX_RETRIES = 3
MAX_PROVIDER_PAGES = 10000
_MAX_ANILIST_MEDIA_ID = (1 << 31) - 1
_CACHE_TTL = 300
_CACHE_LIMIT = 160
_cache = {}
_cache_lock = threading.RLock()


class MangaBakaAPIError(RuntimeError):
    """An API response failed or could not be decoded."""


def _freeze_cache_value(value):
    """Recursively convert nested request parameters to stable hashable values."""
    if isinstance(value, dict):
        return tuple(sorted(
            ((str(key), _freeze_cache_value(item)) for key, item in value.items()),
            key=lambda pair: pair[0],
        ))
    if isinstance(value, (list, tuple, set, frozenset)):
        frozen = [_freeze_cache_value(item) for item in value]
        return tuple(sorted(frozen, key=repr))
    if isinstance(value, float) and not math.isfinite(value):
        return repr(value)
    if value is None or isinstance(value, (str, int, float, bool, bytes)):
        return value
    try:
        hash(value)
    except TypeError:
        return repr(value)
    return value


def _cache_key(path, params):
    stable = [
        (str(key), _freeze_cache_value(value))
        for key, value in (params or {}).items()
    ]
    return str(path or ""), tuple(sorted(stable, key=lambda pair: pair[0]))


def _unwrap(payload):
    return payload.get("data") if isinstance(payload, dict) and "data" in payload else payload


def _request(path, params=None, use_cache=True):
    """GET a public MangaBaka route with bounded retries and a short cache."""
    clean_path = str(path or "").lstrip("/")
    if clean_path.startswith(("http://", "https://")):
        raise ValueError("Pass an API path, not a full URL.")
    if any(part in {"my", "mod", "auth"} for part in clean_path.split("/")):
        raise ValueError("Account, moderation, and authentication routes are not used by NekoTrack.")

    key = _cache_key(clean_path, params)
    now = time.monotonic()
    if use_cache:
        with _cache_lock:
            cached = _cache.get(key)
            if cached and cached[0] > now:
                return copy.deepcopy(cached[1])

    url = urljoin(MANGABAKA_BASE_URL, clean_path)
    last_error = None
    for attempt in range(MANGABAKA_MAX_RETRIES):
        try:
            response = requests.get(
                url,
                params=params or {},
                headers={
                    "Accept": "application/json",
                    "User-Agent": "NekoTrack/0.1 (desktop media tracker)",
                },
                timeout=REQUEST_TIMEOUT,
            )
            if response.status_code == 429 or response.status_code >= 500:
                last_error = MangaBakaAPIError(
                    f"MangaBaka returned HTTP {response.status_code}."
                )
                if attempt < MANGABAKA_MAX_RETRIES - 1:
                    retry_after = response.headers.get("Retry-After")
                    try:
                        wait = min(8.0, max(0.5, float(retry_after)))
                    except (TypeError, ValueError):
                        wait = 0.75 * (2 ** attempt)
                    time.sleep(wait)
                    continue
            if response.status_code >= 400:
                detail = response.text[:240].strip()
                raise MangaBakaAPIError(
                    f"MangaBaka API returned HTTP {response.status_code}"
                    + (f": {detail}" if detail else "")
                )
            try:
                payload = response.json()
            except ValueError as error:
                raise MangaBakaAPIError("MangaBaka returned invalid JSON.") from error
            if isinstance(payload, dict):
                status = payload.get("status")
                if isinstance(status, int) and status >= 400:
                    raise MangaBakaAPIError(
                        str(payload.get("message") or f"MangaBaka API status {status}.")
                    )
            if use_cache:
                with _cache_lock:
                    if len(_cache) >= _CACHE_LIMIT:
                        oldest = min(_cache, key=lambda item: _cache[item][0])
                        _cache.pop(oldest, None)
                    _cache[key] = (time.monotonic() + _CACHE_TTL, copy.deepcopy(payload))
            return payload
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError,
                requests.exceptions.ChunkedEncodingError) as error:
            last_error = error
            if attempt < MANGABAKA_MAX_RETRIES - 1:
                time.sleep(0.5 * (2 ** attempt))
        except requests.exceptions.RequestException as error:
            raise MangaBakaAPIError(str(error)) from error
    raise MangaBakaAPIError(f"Could not reach MangaBaka: {last_error}")


def get_mangabaka_public_data(endpoint, params=None, use_cache=True):
    """Access a public catalogue endpoint, including fields not yet mapped by NekoTrack."""
    return _request(endpoint, params=params, use_cache=use_cache)


def _records(payload):
    data = _unwrap(payload)
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        for key in ("items", "results", "series", "collections", "works", "records"):
            candidate = data.get(key)
            if isinstance(candidate, list):
                return [item for item in candidate if isinstance(item, dict)]
        return [data]
    return []


def _pagination(payload):
    """Return well-formed pagination metadata, never a raw scalar/list."""
    if not isinstance(payload, dict):
        return {}
    value = payload.get("pagination")
    return value if isinstance(value, dict) else {}


def _safe_int(value, default=0):
    """Parse provider numeric fields without letting malformed metadata abort a request."""
    if isinstance(value, bool) or value in (None, ""):
        return default
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return default


_MAX_PROVIDER_FILTER_ID = (1 << 63) - 1


def _bounded_positive_filter_int(value, maximum=_MAX_PROVIDER_FILTER_ID):
    """Parse a bounded user/provider filter integer without unbounded digit conversion."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        number = value
    elif isinstance(value, str):
        text = value.strip()
        if not text or len(text) > 19 or not text.isascii() or not text.isdigit():
            return None
        try:
            number = int(text)
        except (TypeError, ValueError, OverflowError):
            return None
    else:
        return None
    return number if 1 <= number <= maximum else None


def _safe_page_parameter(value, default=1, maximum=MAX_PROVIDER_PAGES):
    """Clamp page/limit inputs before any provider request is built."""
    if isinstance(value, bool):
        number = default
    elif isinstance(value, int):
        number = value
    elif isinstance(value, float):
        number = int(value) if math.isfinite(value) and value.is_integer() else default
    elif isinstance(value, str):
        text = value.strip()
        if not text or len(text) > 20 or not text.isascii() or not text.isdigit():
            number = default
        else:
            try:
                number = int(text)
            except (TypeError, ValueError, OverflowError):
                number = default
    else:
        number = default
    return min(maximum, max(1, number))


def _filter_values(values):
    if values is None or values == "":
        return None
    if isinstance(values, str):
        return [part.strip() for part in values.split(",") if part.strip()]
    if isinstance(values, (list, tuple, set)):
        return [value for value in values if value not in (None, "")]
    return [values]


def _local_filter_terms(value):
    if value in (None, ""):
        return []
    values = value if isinstance(value, (list, tuple, set)) else str(value).split(",")
    return [str(part).strip() for part in values if str(part).strip()]


def _record_term_values(values):
    if values is None:
        return []
    if isinstance(values, (str, int, float)):
        return [str(values).strip()]
    if isinstance(values, dict):
        values = [values]
    output = []
    for value in values:
        if isinstance(value, dict):
            for key in ("name", "title", "name_path", "slug"):
                candidate = value.get(key)
                if isinstance(candidate, str) and candidate.strip():
                    output.append(candidate.strip())
        elif value is not None:
            candidate = str(value).strip()
            if candidate:
                output.append(candidate)
    return output


def _contains_requested_term(available, requested):
    available_terms = {
        str(value).strip().casefold()
        for value in available if str(value).strip()
    }
    return any(term.casefold() in available_terms for term in requested)


def _publisher_ids(value):
    if value is None:
        return set()
    if isinstance(value, bool):
        return set()
    if isinstance(value, (int, str)):
        try:
            parsed = int(value)
            return {parsed} if parsed > 0 else set()
        except (TypeError, ValueError, OverflowError):
            return set()
    if isinstance(value, (list, tuple, set)):
        result = set()
        for item in value:
            result.update(_publisher_ids(item))
        return result
    if isinstance(value, dict):
        result = set()
        for key in ("id", "publisher_id", "publisherId"):
            candidate = value.get(key)
            if candidate is not None:
                result.update(_publisher_ids(candidate))
        return result
    return set()


def _as_bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().casefold()
        if normalized in {"true", "yes", "1", "licensed"}:
            return True
        if normalized in {"false", "no", "0", "unlicensed"}:
            return False
    return None


def _matches_local_filters(record, picked_format, filters):
    """Enforce requested filters locally when the provider ignores/falls back on them."""
    if not isinstance(record, dict):
        return False
    raw_type = str(record.get("type") or "manga").strip().casefold()
    if picked_format == "NOVEL" and raw_type != "novel":
        return False
    if picked_format == "MANGA" and raw_type == "novel":
        return False

    status_map = {
        "FINISHED": {"completed", "finished"},
        "RELEASING": {"releasing", "ongoing"},
        "NOT_YET_RELEASED": {"upcoming", "not yet released", "not_yet_released"},
        "CANCELLED": {"cancelled", "canceled"},
        "HIATUS": {"hiatus", "on hiatus"},
    }
    wanted_status = str(filters.get("status") or "").strip().upper()
    if wanted_status in status_map:
        actual_status = str(record.get("status") or "").strip().casefold().replace("_", " ")
        allowed_statuses = {value.replace("_", " ") for value in status_map[wanted_status]}
        if actual_status not in allowed_statuses:
            return False

    min_score = filters.get("min_score")
    if min_score is not None:
        try:
            rating = float(record.get("rating"))
            threshold = float(min_score)
            if (
                not math.isfinite(rating)
                or not math.isfinite(threshold)
                or not 0 <= threshold <= 100
                or rating < threshold
            ):
                return False
        except (TypeError, ValueError, OverflowError):
            return False

    year = filters.get("year")
    if year and str(year).isdigit():
        published_year = (_date_parts(record) or {}).get("year")
        try:
            if int(published_year) != int(year):
                return False
        except (TypeError, ValueError):
            return False

    for key in ("genre", "tag"):
        requested = _local_filter_terms(filters.get(key))
        if not requested:
            continue
        tags = record.get("tags") or record.get("tag") or []
        if isinstance(tags, dict):
            tags = [tags]
        if not isinstance(tags, list):
            tags = [tags]

        explicit_genres = _record_term_values(record.get("genres") or record.get("genre"))
        all_tags = _record_term_values(tags)
        genre_tags = []
        for tag in tags:
            if isinstance(tag, dict) and tag.get("is_genre") is True:
                genre_tags.extend(_record_term_values(tag))
        available = (
            explicit_genres or genre_tags or all_tags
            if key == "genre"
            else all_tags
        )
        if not _contains_requested_term(available, requested):
            return False

    publisher_id = filters.get("publisher_id")
    if publisher_id not in (None, ""):
        if not str(publisher_id).isdigit():
            return False
        known_ids = set()
        for key in ("publisher_id", "publisherId", "publisher_ids", "publisher", "publishers"):
            known_ids.update(_publisher_ids(record.get(key)))
        if int(publisher_id) not in known_ids:
            return False

    expected_license = filters.get("is_licensed")
    if expected_license is not None:
        wanted_license = _as_bool(expected_license)
        actual_license = None
        for key in ("is_licensed", "isLicensed", "licensed"):
            if record.get(key) is not None:
                actual_license = _as_bool(record.get(key))
                break
        if wanted_license is None or actual_license is None or actual_license is not wanted_license:
            return False

    return True




def search_mangabaka_series(query="", page=1, limit=20, **filters):
    """Search series with filters. Basic title search survives filter-schema changes."""
    params = {
        "q": (query or "").strip(),
        "page": _safe_page_parameter(page, 1, MAX_PROVIDER_PAGES),
        "limit": _safe_page_parameter(limit, 20, 50),
        "content_rating": ["safe", "suggestive"],
    }
    valid_filters = {
        "type", "status", "genre", "tag", "publisher_id", "is_licensed",
        "rating_lower", "rating_upper", "start_year", "end_year", "sort_by", "boost",
    }
    for key, value in filters.items():
        if key not in valid_filters or value is None or value == "":
            continue
        clean = _filter_values(value)
        if clean is not None:
            params[key] = clean if len(clean) > 1 else clean[0]

    try:
        return _request("series/search", params=params)
    except MangaBakaAPIError as error:
        if not filters or not any(token in str(error).lower()
                                  for token in ("400", "422", "validation", "invalid")):
            raise
        basic = {
            "q": (query or "").strip(),
            "page": _safe_page_parameter(page, 1, MAX_PROVIDER_PAGES),
            "limit": _safe_page_parameter(limit, 20, 50),
            "content_rating": ["safe", "suggestive"],
        }
        return _request("series/search", params=basic)


def get_mangabaka_series(series_id, full=False):
    series_id = _bounded_positive_filter_int(series_id)
    if series_id is None:
        raise ValueError("MangaBaka series IDs must be positive bounded integers.")
    # MangaBaka selects the expanded schema with ?schema=full; /full is not
    # a separate endpoint. The fallback keeps the core record usable if this
    # optional query parameter changes in a future API revision.
    if full:
        try:
            return _request(f"series/{series_id}", params={"schema": "full"})
        except MangaBakaAPIError:
            return _request(f"series/{series_id}")
    return _request(f"series/{series_id}")


def get_mangabaka_series_collections(series_id, page=1, limit=50):
    series_id = _bounded_positive_filter_int(series_id)
    if series_id is None:
        raise ValueError("MangaBaka series IDs must be positive bounded integers.")
    return _request(
        f"series/{series_id}/collections",
        params={
            "page": _safe_page_parameter(page, 1, MAX_PROVIDER_PAGES),
            "limit": _safe_page_parameter(limit, 50, 100),
        },
    )


def get_mangabaka_collection_works(collection_id, page=1, limit=50):
    collection_id = _bounded_positive_filter_int(collection_id)
    if collection_id is None:
        raise ValueError("Collection IDs must be positive bounded integers.")
    return _request(
        f"collections/{collection_id}/works",
        params={
            "page": _safe_page_parameter(page, 1, MAX_PROVIDER_PAGES),
            "limit": _safe_page_parameter(limit, 50, 100),
        },
    )


def get_mangabaka_work(work_id):
    work_id = _bounded_positive_filter_int(work_id)
    if work_id is None:
        raise ValueError("MangaBaka work IDs must be positive bounded integers.")
    return _request(f"works/{work_id}")


def get_mangabaka_related_series(series_id):
    series_id = _bounded_positive_filter_int(series_id)
    if series_id is None:
        raise ValueError("MangaBaka series IDs must be positive bounded integers.")
    return _request(f"series/{series_id}/related")


def get_mangabaka_series_news(series_id, page=1, limit=20):
    series_id = _bounded_positive_filter_int(series_id)
    if series_id is None:
        raise ValueError("MangaBaka series IDs must be positive bounded integers.")
    return _request(
        f"series/{series_id}/news",
        params={
            "page": _safe_page_parameter(page, 1, MAX_PROVIDER_PAGES),
            "limit": _safe_page_parameter(limit, 20, 50),
        },
    )


def get_mangabaka_series_mix(page=1, limit=20, **filters):
    params = {
        "page": _safe_page_parameter(page, 1, MAX_PROVIDER_PAGES),
        "limit": _safe_page_parameter(limit, 20, 50),
        "content_rating": ["safe", "suggestive"],
    }
    params.update({key: value for key, value in filters.items() if value not in (None, "")})
    return _request("series/mix", params=params)


def get_mangabaka_hidden_gems(page=1, limit=20, **filters):
    params = {
        "page": _safe_page_parameter(page, 1, MAX_PROVIDER_PAGES),
        "limit": _safe_page_parameter(limit, 20, 50),
        "content_rating": ["safe", "suggestive"],
    }
    params.update({key: value for key, value in filters.items() if value not in (None, "")})
    return _request("series/discover/hidden-gems", params=params)


def get_mangabaka_publishers(page=1, limit=20, **filters):
    params = {
        "page": _safe_page_parameter(page, 1, MAX_PROVIDER_PAGES),
        "limit": _safe_page_parameter(limit, 20, 100),
    }
    params.update({key: value for key, value in filters.items() if value not in (None, "")})
    return _request("publishers", params=params)


def get_mangabaka_publisher(publisher_id):
    publisher_id = _bounded_positive_filter_int(publisher_id)
    if publisher_id is None:
        raise ValueError("Publisher IDs must be positive bounded integers.")
    return _request(f"publishers/{publisher_id}")


def get_mangabaka_similar_publishers(publisher_id, page=1, limit=20):
    publisher_id = _bounded_positive_filter_int(publisher_id)
    if publisher_id is None:
        raise ValueError("Publisher IDs must be positive bounded integers.")
    return _request(
        f"publishers/{publisher_id}/similar",
        params={
            "page": _safe_page_parameter(page, 1, MAX_PROVIDER_PAGES),
            "limit": _safe_page_parameter(limit, 20, 50),
        },
    )


def get_mangabaka_publisher_stats(publisher_id):
    publisher_id = _bounded_positive_filter_int(publisher_id)
    if publisher_id is None:
        raise ValueError("Publisher IDs must be positive bounded integers.")
    return _request(f"publishers/{publisher_id}/stats")


def get_mangabaka_external_id(series, provider):
    """Find a bounded upstream provider ID in MangaBaka source/response structures."""
    provider_key = str(provider or "").lower().replace("-", "").replace("_", "")
    # AniList IDs become GraphQL Int variables and must fit signed 32-bit.
    # Other external catalogues can use their own larger numeric namespaces,
    # but all stored provider IDs still need to fit SQLite's signed integer.
    max_provider_id = (
        _MAX_ANILIST_MEDIA_ID
        if provider_key == "anilist"
        else _MAX_PROVIDER_FILTER_ID
    )
    candidates = []

    def parse_candidate(value):
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            number = value
        elif isinstance(value, str):
            text = value.strip()
            if (
                not text
                or len(text) > 10
                or not text.isascii()
                or not text.isdigit()
            ):
                return None
            try:
                number = int(text)
            except (TypeError, ValueError, OverflowError):
                return None
        else:
            return None
        return number if 1 <= number <= max_provider_id else None

    def add_candidate(value):
        candidate = parse_candidate(value)
        if candidate is not None:
            candidates.append(candidate)

    def walk(value, path=""):
        if isinstance(value, dict):
            for key, child in value.items():
                key_text = str(key)
                new_path = f"{path}.{key_text}".lower()
                normalized_path = new_path.replace("-", "").replace("_", "")
                if provider_key in normalized_path and "id" in key_text.lower():
                    add_candidate(child)
                # Upstream source objects often use a plain ID field.
                if provider_key in normalized_path and key_text.lower() in {
                    "id", "idmal", "media_id", "series_id", "mal_id"
                }:
                    add_candidate(child)
                walk(child, new_path)
        elif isinstance(value, list):
            for item in value:
                walk(item, path)

    walk(series)
    return candidates[0] if candidates else None


def _title_records(series):
    records = series.get("titles")
    if isinstance(records, list):
        return [item for item in records if isinstance(item, dict) and item.get("title")]
    return []


def _pick_title(records, language):
    language = str(language or "").lower()
    localized = [
        item for item in records
        if str(item.get("language") or "").lower() == language
    ]
    for item in localized:
        if item.get("is_primary"):
            return str(item["title"])

    # The documented API uses a list of trait strings, but corrupted or
    # version-skewed payloads may return a scalar, dict, or non-string value.
    # Normalize to exact tokens so e.g. "unofficial" does not match "official".
    for trait in ("official", "native", "alternative"):
        for item in localized:
            raw_traits = item.get("traits")
            if isinstance(raw_traits, str):
                traits = {raw_traits.strip().casefold()} if raw_traits.strip() else set()
            elif isinstance(raw_traits, (list, tuple, set)):
                traits = {
                    value.strip().casefold()
                    for value in raw_traits
                    if isinstance(value, str) and value.strip()
                }
            else:
                traits = set()
            if trait in traits:
                return str(item["title"])
    return str(localized[0]["title"]) if localized else ""


def _first_text(*values):
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _cover_url(series):
    cover = series.get("cover")
    if isinstance(cover, str):
        return cover
    if isinstance(cover, dict):
        return _first_text(cover.get("x350"), cover.get("x250"), cover.get("raw"),
                           cover.get("x150"), cover.get("url"))
    return _first_text(series.get("cover_url"))


def _date_parts(series):
    """Parse optional publication dates strictly; ignore invalid provider fields."""
    from datetime import date
    if not isinstance(series, dict):
        return {"year": None, "month": None, "day": None}
    published = series.get("published")
    candidates = []
    if isinstance(published, dict):
        candidates.extend([
            published.get("start"), published.get("from"),
            published.get("start_date"), published.get("date"),
        ])
    candidates.extend([
        series.get("published_start"), series.get("start_date"),
        series.get("published_at"), series.get("created_at"),
    ])
    for value in candidates:
        if isinstance(value, dict):
            year = value.get("year")
            month = value.get("month")
            day = value.get("day")
            if year in (None, ""):
                continue
            year = _safe_int(year, 0)
            month = 1 if month in (None, "") else _safe_int(month, 0)
            day = 1 if day in (None, "") else _safe_int(day, 0)
        elif isinstance(value, str) and value.strip():
            match = re.fullmatch(
                r"([0-9]{4})(?:-([0-9]{1,2}))?(?:-([0-9]{1,2}))?(?:[T ].*)?",
                value.strip(),
            )
            if not match:
                continue
            year = int(match.group(1))
            month = int(match.group(2) or 1)
            day = int(match.group(3) or 1)
        else:
            continue
        try:
            date(year, month, day)
        except (TypeError, ValueError, OverflowError):
            continue
        return {"year": year, "month": month, "day": day}
    return {"year": None, "month": None, "day": None}

def _count_or_none(value):
    """Normalize positive whole-number counts bounded to the supported local range."""
    if value in (None, "") or isinstance(value, bool):
        return None
    maximum = _MAX_PROVIDER_FILTER_ID
    if isinstance(value, int):
        return value if 1 <= value <= maximum else None
    if isinstance(value, float):
        if (
            not math.isfinite(value)
            or value <= 0
            or not value.is_integer()
            or value > maximum
        ):
            return None
        return int(value)

    raw = str(value).strip()
    if not raw:
        return None
    # Do not reinterpret a negative count such as "-12 chapters" as positive 12.
    match = re.search(r"(?<![-0-9])[0-9]+", raw)
    if not match:
        return None
    digits = match.group(0)
    if len(digits) > 19:
        return None
    try:
        number = int(digits)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if 1 <= number <= maximum else None

def normalize_mangabaka_series(series, preferred_id=None):
    """Convert a MangaBaka series record to NekoTrack's AniList-like media shape."""
    if not isinstance(series, dict):
        raise TypeError("A MangaBaka series record must be an object.")
    raw_id = series.get("id")
    if isinstance(raw_id, bool):
        raise ValueError("MangaBaka response did not include a positive numeric series ID.")
    if isinstance(raw_id, float) and (
        not math.isfinite(raw_id) or not raw_id.is_integer()
    ):
        raise ValueError("MangaBaka response did not include a positive numeric series ID.")
    if isinstance(raw_id, str):
        text_id = raw_id.strip()
        if (
            not text_id
            or len(text_id) > 19
            or not text_id.isascii()
            or not text_id.isdigit()
        ):
            raise ValueError("MangaBaka response did not include a positive numeric series ID.")
        raw_id = text_id
    elif not isinstance(raw_id, (int, float)):
        raise ValueError("MangaBaka response did not include a positive numeric series ID.")
    try:
        mb_id = int(raw_id)
    except (TypeError, ValueError, OverflowError):
        raise ValueError("MangaBaka response did not include a positive numeric series ID.")
    if not 1 <= mb_id <= _MAX_PROVIDER_FILTER_ID:
        raise ValueError("MangaBaka series ID is outside the supported numeric range.")

    titles = _title_records(series)
    english = _first_text(_pick_title(titles, "en"), series.get("title"), series.get("english_title"))
    romanized = _first_text(_pick_title(titles, "ja-Latn"), series.get("romanized_title"),
                            _pick_title(titles, "ja-ro"))
    native = _first_text(_pick_title(titles, "ja"), series.get("native_title"))
    primary = english or romanized or native or f"Untitled MangaBaka series {mb_id}"
    if preferred_id is None:
        anilist_id = get_mangabaka_external_id(series, "anilist")
    else:
        if isinstance(preferred_id, bool):
            raise ValueError("Preferred media ID must be a valid AniList or local MangaBaka ID.")
        if isinstance(preferred_id, float) and (
            not math.isfinite(preferred_id) or not preferred_id.is_integer()
        ):
            raise ValueError("Preferred media ID must be a valid AniList or local MangaBaka ID.")
        if isinstance(preferred_id, str):
            text_preferred_id = preferred_id.strip()
            if (
                not text_preferred_id
                or len(text_preferred_id) > 20
                or not text_preferred_id.isascii()
                or not re.fullmatch(r"[+-]?[0-9]+", text_preferred_id)
            ):
                raise ValueError("Preferred media ID must be a valid AniList or local MangaBaka ID.")
            preferred_id = text_preferred_id
        elif not isinstance(preferred_id, (int, float)):
            raise ValueError("Preferred media ID must be a valid AniList or local MangaBaka ID.")
        try:
            preferred_id = int(preferred_id)
        except (TypeError, ValueError, OverflowError) as error:
            raise ValueError("Preferred media ID must be a valid AniList or local MangaBaka ID.") from error
        if (
            preferred_id == 0
            or preferred_id > _MAX_ANILIST_MEDIA_ID
            or preferred_id < -_MAX_PROVIDER_FILTER_ID
        ):
            raise ValueError("Preferred media ID is outside the supported numeric range.")
        anilist_id = preferred_id
    local_id = anilist_id if anilist_id else -mb_id
    mal_id = get_mangabaka_external_id(series, "myanimelist") or get_mangabaka_external_id(series, "mal")

    raw_type = str(series.get("type") or "manga").strip().lower()
    media_format = "NOVEL" if raw_type == "novel" else "MANGA"
    rating = series.get("rating")
    try:
        rating = float(rating) if rating is not None else None
        if rating is not None and not 0 <= rating <= 100:
            rating = None
    except (TypeError, ValueError):
        rating = None

    synonyms = []
    for record in titles:
        title = str(record.get("title") or "").strip()
        if title and title.casefold() != primary.casefold() and title not in synonyms:
            synonyms.append(title)
    legacy = series.get("secondary_titles")
    if isinstance(legacy, dict):
        legacy = [title for values in legacy.values()
                  for title in (values if isinstance(values, list) else [values])]
    if isinstance(legacy, list):
        for title in legacy:
            if isinstance(title, str) and title.strip() and title.casefold() != primary.casefold():
                if title.strip() not in synonyms:
                    synonyms.append(title.strip())

    return {
        "id": local_id,
        "idMal": mal_id,
        "type": "MANGA",
        "title": {"english": english or primary, "romaji": romanized, "native": native},
        "format": media_format,
        "episodes": None,
        "chapters": _count_or_none(series.get("total_chapters", series.get("chapters"))),
        "volumes": _count_or_none(series.get("final_volume", series.get("total_volumes", series.get("volumes")))),
        "averageScore": rating,
        "startDate": _date_parts(series),
        "endDate": {"year": None, "month": None, "day": None},
        "coverImage": {"large": _cover_url(series)},
        "description": series.get("description"),
        "status": str(series.get("status") or "").upper() or None,
        "synonyms": synonyms,
        "source": "MangaBaka",
        "duration": None,
        "relations": {"edges": []},
        "characters": {"edges": [], "pageInfo": {"hasNextPage": False}},
        "staff": {"edges": []},
        "_provider": "MangaBaka",
        "_mangabaka_id": mb_id,
        "_mangabaka": copy.deepcopy(series),
    }


def _mangabaka_normalize_title(value):
    value = str(value or "").casefold()
    value = re.sub(r"[\W_]+", " ", value, flags=re.UNICODE)
    return " ".join(value.split())


def _series_title_candidates(series):
    candidates = [str(item.get("title")) for item in _title_records(series) if item.get("title")]
    for key in ("title", "native_title", "romanized_title", "english_title"):
        value = series.get(key)
        if isinstance(value, str) and value.strip():
            candidates.append(value.strip())
    synonyms = series.get("secondary_titles") or series.get("synonyms") or []
    if isinstance(synonyms, dict):
        synonyms = [title for values in synonyms.values()
                    for title in (values if isinstance(values, list) else [values])]
    if isinstance(synonyms, list):
        candidates.extend(value for value in synonyms if isinstance(value, str))
    return list(dict.fromkeys(value for value in candidates if value.strip()))


def match_series_for_anilist(anilist_media, candidates):
    """Prefer exact AniList IDs; title-match only when the result is unambiguous."""
    try:
        anilist_id = int(anilist_media.get("id"))
    except (AttributeError, TypeError, ValueError):
        anilist_id = None
    candidates = [item for item in candidates if isinstance(item, dict)]
    if anilist_id:
        for candidate in candidates:
            if get_mangabaka_external_id(candidate, "anilist") == anilist_id:
                return candidate

    title_data = anilist_media.get("title") or {}
    aliases = [title_data.get("english"), title_data.get("romaji"),
               title_data.get("native"), *(anilist_media.get("synonyms") or [])]
    normalized_aliases = {_mangabaka_normalize_title(value) for value in aliases if value}
    normalized_aliases.discard("")
    if not normalized_aliases:
        return None
    scored = []
    for candidate in candidates:
        candidate_titles = {_mangabaka_normalize_title(value) for value in _series_title_candidates(candidate)}
        candidate_titles.discard("")
        exact = bool(normalized_aliases.intersection(candidate_titles))
        score = 1.0 if exact else max(
            (SequenceMatcher(None, left, right).ratio()
             for left in normalized_aliases for right in candidate_titles),
            default=0.0,
        )
        scored.append((score, candidate))
    scored.sort(key=lambda row: row[0], reverse=True)
    if not scored or scored[0][0] < 0.90:
        return None
    if len(scored) > 1 and abs(scored[0][0] - scored[1][0]) < 0.025:
        return None
    return scored[0][1]


def _attach_mangabaka_record(media, raw):
    if not isinstance(media, dict) or not isinstance(raw, dict):
        return media
    title_data = media.get("title") or {}
    query = _first_text(title_data.get("english"), title_data.get("romaji"), title_data.get("native"))
    raw_copy = copy.deepcopy(raw)
    media["_mangabaka"] = raw_copy
    media["_mangabaka_id"] = raw_copy.get("id")
    for title in _series_title_candidates(raw_copy):
        if title.casefold() != query.casefold() and title not in (media.get("synonyms") or []):
            media.setdefault("synonyms", []).append(title)
    if not ((media.get("coverImage") or {}).get("large")):
        cover = _cover_url(raw_copy)
        if cover:
            media["coverImage"] = {"large": cover}
    if not media.get("description"):
        media["description"] = raw_copy.get("description")
    return media


def enrich_anilist_results(media_items, query, candidates=None):
    """Attach unambiguous MangaBaka matches, optionally using current search results."""
    items = [item for item in (media_items or []) if isinstance(item, dict)]
    manga_items = [item for item in items if str(item.get("type") or "").upper() == "MANGA"]
    query = str(query or "").strip()
    if not manga_items or (not query and candidates is None):
        return items
    try:
        if candidates is None:
            candidates = _records(search_mangabaka_series(query, page=1, limit=50))
        else:
            candidates = [item for item in candidates if isinstance(item, dict)]
        used_ids = set()
        for item in manga_items:
            matched = match_series_for_anilist(item, candidates)
            if not matched:
                continue
            try:
                matched_id = int(matched.get("id"))
            except (AttributeError, TypeError, ValueError):
                matched_id = None
            if matched_id is not None and matched_id in used_ids:
                continue
            _attach_mangabaka_record(item, matched)
            if matched_id is not None:
                used_ids.add(matched_id)
    except Exception as error:
        print(f"MangaBaka result enrichment skipped: {error}")
    return items


def _response_record(payload):
    data = _unwrap(payload)
    if isinstance(data, list):
        return data[0] if data and isinstance(data[0], dict) else None
    return data if isinstance(data, dict) else None


def enrich_anilist_media(media, fetch_full=False):
    """Enrich an AniList manga/novel; optionally retrieve MangaBaka's full schema."""
    if not isinstance(media, dict) or str(media.get("type") or "").upper() != "MANGA":
        return media
    title_data = media.get("title") or {}
    query = _first_text(title_data.get("english"), title_data.get("romaji"), title_data.get("native"))
    if not query:
        return media
    try:
        candidates = _records(search_mangabaka_series(query, page=1, limit=10))
        matched = match_series_for_anilist(media, candidates)
        if matched:
            chosen = matched
            if fetch_full and matched.get("id") is not None:
                try:
                    full_record = _response_record(get_mangabaka_series(matched["id"], full=True))
                    if full_record and int(full_record.get("id") or 0) == int(matched["id"]):
                        chosen = full_record
                except Exception as error:
                    print(f"MangaBaka full-detail lookup skipped: {error}")
            _attach_mangabaka_record(media, chosen)
    except Exception as error:
        print(f"MangaBaka enrichment skipped: {error}")
    return media


def search_mangabaka_media(query="", page=1, media_type=None, media_format=None, filters=None,
                limit=20, browse_mode="search"):
    """Return MangaBaka search results in the envelope expected by SearchPage."""
    try:
        filters = dict(filters or {})
    except (TypeError, ValueError):
        filters = {}
    try:
        page = min(MAX_PROVIDER_PAGES, max(1, int(page or 1)))
    except (TypeError, ValueError, OverflowError):
        page = 1
    try:
        limit = min(200, max(1, int(limit or 20)))
    except (TypeError, ValueError, OverflowError):
        limit = 20

    if str(media_type or "").upper() == "ANIME" or (filters.get("format_filter") or media_format) == "ONE_SHOT":
        return {"pageInfo": {"currentPage": page, "lastPage": 1, "hasNextPage": False},
                "media": [], "_catalog": "MangaBaka"}

    query_filters = {}
    picked_format = filters.get("format_filter") or media_format
    if picked_format == "NOVEL":
        query_filters["type"] = ["novel"]
    elif picked_format == "MANGA":
        query_filters["type"] = ["manga", "manhwa", "manhua", "oel", "other"]

    status_map = {"FINISHED": "completed", "RELEASING": "releasing",
                  "NOT_YET_RELEASED": "upcoming", "CANCELLED": "cancelled", "HIATUS": "hiatus"}
    if filters.get("status") in status_map:
        query_filters["status"] = [status_map[filters["status"]]]
    if filters.get("min_score") is not None:
        try:
            score_threshold = float(filters["min_score"])
            if math.isfinite(score_threshold) and 0 <= score_threshold <= 100:
                query_filters["rating_lower"] = int(score_threshold)
        except (TypeError, ValueError, OverflowError):
            pass
    year = filters.get("year")
    if year:
        parsed_year = _bounded_positive_filter_int(year, maximum=9999)
        if parsed_year is None:
            return {
                "pageInfo": {"currentPage": page, "lastPage": 1, "hasNextPage": False},
                "media": [],
                "_catalog": "MangaBaka",
            }
        query_filters["start_year"] = parsed_year
        query_filters["end_year"] = parsed_year
    for key in ("genre", "tag"):
        value = filters.get(key)
        if value:
            query_filters[key] = [part.strip() for part in str(value).split(",") if part.strip()]
    publisher_id = filters.get("publisher_id")
    if publisher_id:
        parsed_publisher_id = _bounded_positive_filter_int(publisher_id)
        if parsed_publisher_id is None:
            return {
                "pageInfo": {"currentPage": page, "lastPage": 1, "hasNextPage": False},
                "media": [],
                "_catalog": "MangaBaka",
            }
        query_filters["publisher_id"] = parsed_publisher_id
    if filters.get("is_licensed") is not None:
        licensed_filter = _as_bool(filters.get("is_licensed"))
        if licensed_filter is not None:
            query_filters["is_licensed"] = licensed_filter
    sort_map = {"SEARCH_MATCH": "relevance", "POPULARITY_DESC": "popular_desc",
                "SCORE_DESC": "rating_desc", "START_DATE_DESC": "newest",
                "START_DATE": "oldest", "TITLE_ROMAJI": "title_asc",
                "TITLE_ROMAJI_DESC": "title_desc"}
    if filters.get("sort") in sort_map:
        query_filters["sort_by"] = sort_map[filters["sort"]]

    mode = str(browse_mode or "search").lower()
    if mode == "hidden_gems" and not str(query or "").strip():
        # This endpoint is a discovery feed, not a title search.
        payload = get_mangabaka_hidden_gems(page=page, limit=limit, **query_filters)
    elif mode == "popular" and not str(query or "").strip():
        query_filters.setdefault("sort_by", "popular_desc")
        payload = get_mangabaka_series_mix(page=page, limit=limit, **query_filters)
    elif str(query or "").strip():
        if mode == "popular":
            query_filters.setdefault("sort_by", "popular_desc")
        payload = search_mangabaka_series(query, page=page, limit=limit, **query_filters)
    else:
        payload = get_mangabaka_series_mix(page=page, limit=limit, **query_filters)

    pagination = _pagination(payload)
    normalized = []
    for item in _records(payload):
        # One malformed catalogue row must not hide otherwise usable results.
        try:
            # The query filter is sent upstream, but also enforce it locally in
            # case a future API revision ignores or changes that filter.
            if str(item.get("content_rating") or "").casefold() not in {"safe", "suggestive"}:
                continue
            if not _matches_local_filters(item, picked_format, filters):
                continue
            normalized.append(normalize_mangabaka_series(item))
        except (TypeError, ValueError, KeyError, AttributeError, OverflowError):
            continue

    def safe_int(value, fallback, minimum=0):
        try:
            parsed = int(value)
        except (TypeError, ValueError, OverflowError):
            return fallback
        return parsed if parsed >= minimum else fallback

    current_page = min(
        MAX_PROVIDER_PAGES,
        safe_int(pagination.get("page"), page, minimum=1),
    )
    limit_value = safe_int(pagination.get("limit"), limit, minimum=1)
    total = safe_int(pagination.get("count"), len(normalized), minimum=0)
    last_page = min(
        MAX_PROVIDER_PAGES,
        max(current_page, (total + limit_value - 1) // limit_value),
    )
    has_next = bool(
        pagination.get("next") or (total and current_page < last_page)
    )
    return {
        "pageInfo": {
            "currentPage": current_page,
            "lastPage": last_page,
            "hasNextPage": has_next and current_page < last_page,
        },
        "media": normalized,
        "_catalog": "MangaBaka",
    }


def get_mangabaka_volume_records(series_id, max_pages=4, limit=50):
    """Resolve published volume records when a MangaBaka series has volume collections."""
    safe_series_id = _bounded_positive_filter_int(series_id)
    if safe_series_id is None:
        return []

    collections = []
    page_count = _safe_page_parameter(max_pages, 4, 20)
    safe_limit = _safe_page_parameter(limit, 50, 100)
    for page in range(1, page_count + 1):
        payload = get_mangabaka_series_collections(safe_series_id, page=page, limit=safe_limit)
        records = _records(payload)
        collections.extend(records)
        if not records or not _pagination(payload).get("next"):
            break

    volume_collections = [
        item for item in collections
        if "volume" in str(item.get("type") or item.get("name") or "").lower()
    ]
    if not volume_collections:
        return []
    volume_collections.sort(key=lambda item: (
        0 if str(item.get("language") or "").lower() in {"en", "eng", "english"} else 1,
        -_safe_int(item.get("count") or item.get("works_count") or 0, 0),
    ))
    for collection in volume_collections:
        collection_id = _bounded_positive_filter_int(collection.get("id"))
        if collection_id is None:
            continue
        works = []
        for page in range(1, 5):
            payload = get_mangabaka_collection_works(collection_id, page=page, limit=50)
            records = _records(payload)
            works.extend(records)
            if not records or not _pagination(payload).get("next"):
                break
        if not works:
            continue
        normalized = []
        for index, work in enumerate(works, start=1):
            raw_number = (
                work.get("volume_number") or work.get("volume")
                or work.get("number") or work.get("position") or index
            )
            number = index
            number_match = re.search(r"\d+", str(raw_number))
            if number_match:
                digits = number_match.group(0)
                # Never convert an arbitrarily long provider-supplied numeral.
                if len(digits) <= 7:
                    try:
                        candidate_number = int(digits)
                    except (TypeError, ValueError, OverflowError):
                        candidate_number = index
                    if 1 <= candidate_number <= 1_000_000:
                        number = candidate_number
            title = _first_text(
                work.get("title"), work.get("name"), work.get("title_en"),
                work.get("title_english"), work.get("title_native"),
            )
            if not title or re.match(r"^(?:vol(?:ume)?\.?\s*)?\d+$", title, re.I):
                title = f"Volume {number}"
            normalized.append({
                "number": number, "title": title, "source_id": work.get("id"),
                "isbn": work.get("isbn") or work.get("isbn_10") or work.get("isbn_13"),
                "cover": work.get("cover"),
                "published": work.get("published") or work.get("release_date"),
                "raw": copy.deepcopy(work),
            })
        return sorted(normalized, key=lambda item: item["number"])
    return []
