import requests
import time


ANILIST_URL = "https://graphql.anilist.co"

MAX_RETRIES = 3
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
            data = response.json()

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
):
    """Search AniList for anime, manga, or novel media with optional filters."""
    if media_type not in {None, "ANIME", "MANGA"}:
        raise ValueError("media_type must be None, ANIME, or MANGA")

    if media_type == "MANGA" and media_format not in {None, "MANGA", "NOVEL", "ONE_SHOT"}:
        raise ValueError("Invalid manga media_format")

    if media_type == "ANIME" and media_format is not None:
        if media_format not in {"TV", "TV_SHORT", "MOVIE", "SPECIAL", "OVA", "ONA", "MUSIC"}:
            raise ValueError("Invalid anime media_format")

    valid_formats = {"TV", "TV_SHORT", "MOVIE", "SPECIAL", "OVA", "ONA", "MUSIC", "MANGA", "NOVEL", "ONE_SHOT"}
    if format_filter and format_filter not in valid_formats:
        raise ValueError("Invalid format_filter")

    if status and status not in {"FINISHED", "RELEASING", "NOT_YET_RELEASED", "CANCELLED", "HIATUS"}:
        raise ValueError("Invalid status")

    if season and season not in {"WINTER", "SPRING", "SUMMER", "FALL"}:
        raise ValueError("Invalid season")

    if sort and sort not in {
        "SEARCH_MATCH",
        "POPULARITY_DESC",
        "POPULARITY",
        "SCORE_DESC",
        "SCORE",
        "START_DATE_DESC",
        "START_DATE",
        "END_DATE_DESC",
        "END_DATE",
        "TITLE_ROMAJI",
        "TITLE_ROMAJI_DESC",
        "UPDATED_AT_DESC",
        "ID_DESC",
    }:
        raise ValueError("Invalid sort")

    if min_score is not None and not 0 <= int(min_score) <= 100:
        raise ValueError("min_score must be between 0 and 100")

    # AniList treats format_in as the multi-format filter. Do not send
    # format and format_in together: some combinations are rejected with
    # "illegal operator and value combinations".
    effective_formats = None
    if format_filter:
        effective_formats = [format_filter]
    elif media_format:
        effective_formats = [media_format]

    # Relevance sorting requires an actual text search. Browsing with
    # filters uses popularity when no explicit sort was requested.
    clean_search = search.strip() if search else None
    effective_sort = sort
    if not clean_search and effective_sort == "SEARCH_MATCH":
        effective_sort = "POPULARITY_DESC"

    query = """
    query (
        $search: String,
        $page: Int,
        $perPage: Int,
        $type: MediaType,
        $formatFilter: [MediaFormat],
        $status: MediaStatus,
        $season: MediaSeason,
        $seasonYear: Int,
        $year: String,
        $sort: [MediaSort],
        $minScore: Int,
        $genres: [String]
    ) {
        Page(page: $page, perPage: $perPage) {
            pageInfo {
                currentPage
                lastPage
                hasNextPage
            }
            media(
                search: $search,
                type: $type,
                format_in: $formatFilter,
                status: $status,
                season: $season,
                seasonYear: $seasonYear,
                startDate_like: $year,
                sort: $sort,
                averageScore_greater: $minScore,
                genre_in: $genres
            ) {
                %s
            }
        }
    }
    """ % _media_fields(include_details=False)

    variables = {
        "search": clean_search,
        "page": page,
        "perPage": per_page,
        "type": media_type,
        "formatFilter": effective_formats,
        "status": status,
        "season": season,
        "seasonYear": int(year) if season and year else None,
        "year": str(year) if year and not season else None,
        "sort": [effective_sort] if effective_sort else None,
        "minScore": int(min_score) if min_score is not None else None,
        "genres": [genre.strip()] if genre and genre.strip() else None,
    }

    data = anilist_request(query, variables)
    return data["Page"]


def get_media_details(media_id):
    """Fetch the complete media record needed by detail/import workflows."""
    query = """
    query ($id: Int) {
        Media(id: $id) {
            %s
            airingSchedule(perPage: 50) {
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
