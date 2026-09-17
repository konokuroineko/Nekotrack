import datetime
import requests
import time


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


def _media_fields(include_details=False):
    """Return GraphQL fields shared by search and detail queries."""
    base = """
        id
        type
        title { romaji english native }
        episodes
        averageScore
        startDate { year month day }
        coverImage { large }
        format
    """
    if not include_details:
        return base + """
        relations {
            edges {
                relationType
                node {
                    id
                    type
                    format
                    title { romaji english native }
                    coverImage { large }
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
        studios {
            edges {
                isMain
                node { id name }
            }
        }
        characters(perPage: 10, sort: ROLE) {
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
                    type
                    format
                    title { romaji english native }
                    coverImage { large }
                }
            }
        }
    """


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
                {_media_fields(include_details=False)}
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


def get_media_details(media_id):
    """Fetch the complete media record needed by detail/import workflows."""
    query = """
    query ($id: Int) {
        Media(id: $id) {
            %s
            airingSchedule(perPage: 50, notYetAired: false) {
                nodes {
                    airingAt
                    episode
                }
            }
        }
    }
    """ % _media_fields(include_details=True)
    data = anilist_request(query, {"id": media_id})
    return data["Media"]


def media_episodes(details):
    """Normalize a detail payload into the episode records `save_episodes` expects.

    AniList exposes two episode-ish sources: ``airingSchedule`` (numbered nodes
    with air times) and ``streamingEpisodes`` (titled clips without episode
    numbers or dates). Only the schedule carries enough information for the
    library's watched-state tracking, so episodes without a number are skipped.
    """
    episodes = []
    for node in (details.get("airingSchedule") or {}).get("nodes") or []:
        number = node.get("episode")
        if number is None:
            continue
        try:
            number = int(number)
        except (TypeError, ValueError):
            continue
        air_date = None
        airing_at = node.get("airingAt")
        if airing_at:
            try:
                air_date = datetime.datetime.fromtimestamp(airing_at).date().isoformat()
            except (OverflowError, OSError, TypeError, ValueError):
                air_date = None
        episodes.append(
            {"episodeNumber": number, "title": None, "description": None, "airdate": air_date}
        )
    episodes.sort(key=lambda episode: episode["episodeNumber"])
    return episodes
