"""MangaBaka API client and NekoTrack media normalizer."""
from __future__ import annotations

import copy
import datetime as _dt
import re
import threading
import time
from difflib import SequenceMatcher
from urllib.parse import urljoin

import requests


MANGABAKA_BASE_URL = "https://api.mangabaka.org/v2/"
REQUEST_TIMEOUT = 18
MAX_RETRIES = 3
_CACHE_TTL = 300
_CACHE_LIMIT = 160
_cache = {}
_cache_lock = threading.RLock()


class MangaBakaAPIError(RuntimeError):
    """An API response failed or could not be decoded."""


def _cache_key(path, params):
    stable = []
    for key, value in (params or {}).items():
        if isinstance(value, (list, tuple, set)):
            value = tuple(sorted(str(item) for item in value))
        stable.append((str(key), value))
    return path, tuple(sorted(stable))


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
    for attempt in range(MAX_RETRIES):
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
                if attempt < MAX_RETRIES - 1:
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
            if attempt < MAX_RETRIES - 1:
                time.sleep(0.5 * (2 ** attempt))
        except requests.exceptions.RequestException as error:
            raise MangaBakaAPIError(str(error)) from error
    raise MangaBakaAPIError(f"Could not reach MangaBaka: {last_error}")


def get_public_data(endpoint, params=None, use_cache=True):
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
    if not isinstance(payload, dict):
        return {}
    value = payload.get("pagination")
    return value if isinstance(value, dict) else {}


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
    if isinstance(value, (int, str)):
        try:
            return {int(value)}
        except (TypeError, ValueError):
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
            if rating < float(min_score):
                return False
        except (TypeError, ValueError):
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
        actual_license = None
        for key in ("is_licensed", "isLicensed", "licensed"):
            if record.get(key) is not None:
                actual_license = _as_bool(record.get(key))
                break
        if actual_license is None or actual_license is not bool(expected_license):
            return False

    return True




def search_series(query="", page=1, limit=20, **filters):
    """Search series with filters. Basic title search survives filter-schema changes."""
    params = {
        "q": (query or "").strip(),
        "page": max(1, int(page)),
        "limit": min(50, max(1, int(limit))),
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
            "page": max(1, int(page)),
            "limit": min(50, max(1, int(limit))),
            "content_rating": ["safe", "suggestive"],
        }
        return _request("series/search", params=basic)


def get_series(series_id, full=False):
    series_id = int(series_id)
    if series_id <= 0:
        raise ValueError("MangaBaka series IDs must be positive.")
    # MangaBaka selects the expanded schema with ?schema=full; /full is not
    # a separate endpoint. The fallback keeps the core record usable if this
    # optional query parameter changes in a future API revision.
    if full:
        try:
            return _request(f"series/{series_id}", params={"schema": "full"})
        except MangaBakaAPIError:
            return _request(f"series/{series_id}")
    return _request(f"series/{series_id}")


def get_series_collections(series_id, page=1, limit=50):
    return _request(f"series/{int(series_id)}/collections",
                    params={"page": max(1, int(page)), "limit": min(100, max(1, int(limit)))})


def get_collection_works(collection_id, page=1, limit=50):
    return _request(f"collections/{int(collection_id)}/works",
                    params={"page": max(1, int(page)), "limit": min(100, max(1, int(limit)))})


def get_work(work_id):
    return _request(f"works/{int(work_id)}")


def get_related_series(series_id):
    return _request(f"series/{int(series_id)}/related")


def get_series_news(series_id, page=1, limit=20):
    return _request(f"series/{int(series_id)}/news",
                    params={"page": max(1, int(page)), "limit": min(50, max(1, int(limit)))})


def get_series_mix(page=1, limit=20, **filters):
    params = {"page": max(1, int(page)), "limit": min(50, max(1, int(limit))),
              "content_rating": ["safe", "suggestive"]}
    params.update({key: value for key, value in filters.items() if value not in (None, "")})
    return _request("series/mix", params=params)


def get_hidden_gems(page=1, limit=20, **filters):
    params = {"page": max(1, int(page)), "limit": min(50, max(1, int(limit))),
              "content_rating": ["safe", "suggestive"]}
    params.update({key: value for key, value in filters.items() if value not in (None, "")})
    return _request("series/discover/hidden-gems", params=params)


def get_publishers(page=1, limit=20, **filters):
    params = {"page": max(1, int(page)), "limit": min(100, max(1, int(limit)))}
    params.update({key: value for key, value in filters.items() if value not in (None, "")})
    return _request("publishers", params=params)


def get_publisher(publisher_id):
    return _request(f"publishers/{int(publisher_id)}")


def get_similar_publishers(publisher_id, page=1, limit=20):
    return _request(f"publishers/{int(publisher_id)}/similar",
                    params={"page": max(1, int(page)), "limit": min(50, max(1, int(limit)))})


def get_publisher_stats(publisher_id):
    return _request(f"publishers/{int(publisher_id)}/stats")


def extract_external_id(series, provider):
    """Find an upstream provider ID in MangaBaka source/response structures."""
    provider_key = str(provider or "").lower().replace("-", "").replace("_", "")
    candidates = []

    def walk(value, path=""):
        if isinstance(value, dict):
            for key, child in value.items():
                key_text = str(key)
                new_path = f"{path}.{key_text}".lower()
                normalized_path = new_path.replace("-", "").replace("_", "")
                if provider_key in normalized_path and "id" in key_text.lower():
                    if isinstance(child, (str, int)) and str(child).isdigit():
                        candidates.append(int(child))
                # Upstream source objects often use a plain ID field.
                if provider_key in normalized_path and key_text.lower() in {
                    "id", "idmal", "media_id", "series_id", "mal_id"
                } and isinstance(child, (str, int)) and str(child).isdigit():
                    candidates.append(int(child))
                walk(child, new_path)
        elif isinstance(value, list):
            for item in value:
                walk(item, path)

    walk(series)
    return next((candidate for candidate in candidates if candidate > 0), None)


def _title_records(series):
    records = series.get("titles")
    if isinstance(records, list):
        return [item for item in records if isinstance(item, dict) and item.get("title")]
    return []


def _pick_title(records, language):
    language = language.lower()
    localized = [item for item in records
                 if str(item.get("language") or "").lower() == language]
    for item in localized:
        if item.get("is_primary"):
            return str(item["title"])
    for trait in ("official", "native", "alternative"):
        for item in localized:
            if trait in (item.get("traits") or []):
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


def _valid_date_parts(year, month=None, day=None):
    """Return validated date components, or None for malformed provider data."""
    try:
        year_value = int(year)
        month_value = 1 if month in (None, "") else int(month)
        day_value = 1 if day in (None, "") else int(day)
        _dt.date(year_value, month_value, day_value)
    except (TypeError, ValueError, OverflowError):
        return None
    if isinstance(year, float) and not year.is_integer():
        return None
    if isinstance(month, float) and not month.is_integer():
        return None
    if isinstance(day, float) and not day.is_integer():
        return None
    return {"year": year_value, "month": month_value, "day": day_value}


def _valid_date_parts(year, month=None, day=None):
    """Return validated date components, or None for malformed provider data."""
    try:
        year_value = int(year)
        month_value = 1 if month in (None, "") else int(month)
        day_value = 1 if day in (None, "") else int(day)
        _dt.date(year_value, month_value, day_value)
    except (TypeError, ValueError, OverflowError):
        return None
    if isinstance(year, float) and not year.is_integer():
        return None
    if isinstance(month, float) and not month.is_integer():
        return None
    if isinstance(day, float) and not day.is_integer():
        return None
    return {"year": year_value, "month": month_value, "day": day_value}


def _date_parts(series):
    published = series.get("published") or {}
    candidates = []
    if isinstance(published, dict):
        candidates.extend([published.get("start"), published.get("from"),
                           published.get("start_date"), published.get("date")])
    candidates.extend([series.get("published_start"), series.get("start_date"),
                       series.get("published_at"), series.get("created_at")])
    for value in candidates:
        if isinstance(value, dict):
            parts = _valid_date_parts(
                value.get("year"), value.get("month"), value.get("day")
            )
            if parts:
                return parts
        if isinstance(value, str) and value.strip():
            match = re.search(r"(\d{4})(?:-(\d{1,2}))?(?:-(\d{1,2}))?", value)
            if match:
                parts = _valid_date_parts(
                    match.group(1), match.group(2), match.group(3)
                )
                if parts:
                    return parts
    return {"year": None, "month": None, "day": None}


def _count_or_none(value):
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool) and value < 0:
        return None
    text = str(value).strip()
    # Do not turn a negative count such as "-5 chapters" into a positive 5.
    if re.match(r"^-\s*\d", text):
        return None
    match = re.search(r"\d+", text)
    if not match:
        return None
    try:
        number = int(match.group(0))
    except (TypeError, ValueError, OverflowError):
        return None
    return number if number > 0 else None


def normalize_series(series, preferred_id=None):
    """Convert a MangaBaka series record to NekoTrack's AniList-like media shape."""
    if not isinstance(series, dict):
        raise TypeError("A MangaBaka series record must be an object.")
    try:
        mb_id = int(series.get("id"))
    except (TypeError, ValueError):
        raise ValueError("MangaBaka response did not include a numeric series ID.")

    titles = _title_records(series)
    english = _first_text(_pick_title(titles, "en"), series.get("title"), series.get("english_title"))
    romanized = _first_text(_pick_title(titles, "ja-Latn"), series.get("romanized_title"),
                            _pick_title(titles, "ja-ro"))
    native = _first_text(_pick_title(titles, "ja"), series.get("native_title"))
    primary = english or romanized or native or f"Untitled MangaBaka series {mb_id}"
    anilist_id = int(preferred_id) if preferred_id else extract_external_id(series, "anilist")
    local_id = anilist_id if anilist_id else -mb_id
    mal_id = extract_external_id(series, "myanimelist") or extract_external_id(series, "mal")

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


def _normalize_title(value):
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
            if extract_external_id(candidate, "anilist") == anilist_id:
                return candidate

    title_data = anilist_media.get("title") or {}
    aliases = [title_data.get("english"), title_data.get("romaji"),
               title_data.get("native"), *(anilist_media.get("synonyms") or [])]
    normalized_aliases = {_normalize_title(value) for value in aliases if value}
    normalized_aliases.discard("")
    if not normalized_aliases:
        return None
    scored = []
    for candidate in candidates:
        candidate_titles = {_normalize_title(value) for value in _series_title_candidates(candidate)}
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
            candidates = _records(search_series(query, page=1, limit=50))
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
        candidates = _records(search_series(query, page=1, limit=10))
        matched = match_series_for_anilist(media, candidates)
        if matched:
            chosen = matched
            if fetch_full and matched.get("id") is not None:
                try:
                    full_record = _response_record(get_series(matched["id"], full=True))
                    if full_record and int(full_record.get("id") or 0) == int(matched["id"]):
                        chosen = full_record
                except Exception as error:
                    print(f"MangaBaka full-detail lookup skipped: {error}")
            _attach_mangabaka_record(media, chosen)
    except Exception as error:
        print(f"MangaBaka enrichment skipped: {error}")
    return media


def search_media(query="", page=1, media_type=None, media_format=None, filters=None,
                limit=20, browse_mode="search"):
    """Return MangaBaka search results in the envelope expected by SearchPage."""
    filters = dict(filters or {})
    if str(media_type or "").upper() == "ANIME" or (filters.get("format_filter") or media_format) == "ONE_SHOT":
        return {"pageInfo": {"currentPage": int(page), "lastPage": 1, "hasNextPage": False},
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
        query_filters["rating_lower"] = int(filters["min_score"])
    year = filters.get("year")
    if year and str(year).isdigit():
        query_filters["start_year"] = int(year)
        query_filters["end_year"] = int(year)
    for key in ("genre", "tag"):
        value = filters.get(key)
        if value:
            query_filters[key] = [part.strip() for part in str(value).split(",") if part.strip()]
    publisher_id = filters.get("publisher_id")
    if publisher_id and str(publisher_id).isdigit():
        query_filters["publisher_id"] = int(publisher_id)
    if filters.get("is_licensed") is not None:
        query_filters["is_licensed"] = bool(filters.get("is_licensed"))
    sort_map = {"SEARCH_MATCH": "relevance", "POPULARITY_DESC": "popular_desc",
                "SCORE_DESC": "rating_desc", "START_DATE_DESC": "newest",
                "START_DATE": "oldest", "TITLE_ROMAJI": "title_asc",
                "TITLE_ROMAJI_DESC": "title_desc"}
    if filters.get("sort") in sort_map:
        query_filters["sort_by"] = sort_map[filters["sort"]]

    mode = str(browse_mode or "search").lower()
    if mode == "hidden_gems" and not str(query or "").strip():
        # This endpoint is a discovery feed, not a title search.
        payload = get_hidden_gems(page=page, limit=limit, **query_filters)
    elif mode == "popular" and not str(query or "").strip():
        query_filters.setdefault("sort_by", "popular_desc")
        payload = get_series_mix(page=page, limit=limit, **query_filters)
    elif str(query or "").strip():
        if mode == "popular":
            query_filters.setdefault("sort_by", "popular_desc")
        payload = search_series(query, page=page, limit=limit, **query_filters)
    else:
        payload = get_series_mix(page=page, limit=limit, **query_filters)

    pagination = _pagination(payload)
    normalized = []
    for item in _records(payload):
        # The query filter is sent upstream, but also enforce it locally in
        # case a future API revision ignores or changes that filter.
        if str(item.get("content_rating") or "").lower() not in {"safe", "suggestive"}:
            continue
        if not _matches_local_filters(item, picked_format, filters):
            continue
        normalized.append(normalize_series(item))
    def safe_int(value, fallback):
        try:
            return int(value)
        except (TypeError, ValueError, OverflowError):
            return int(fallback)

    current_page = max(1, safe_int(pagination.get("page") or page, page))
    limit_value = max(1, safe_int(pagination.get("limit") or limit, limit))
    total = max(0, safe_int(pagination.get("count") or len(normalized), len(normalized)))
    last_page = max(current_page, (total + limit_value - 1) // limit_value)
    return {
        "pageInfo": {
            "currentPage": current_page,
            "lastPage": last_page,
            "hasNextPage": bool(pagination.get("next") or (total and current_page < last_page)),
        },
        "media": normalized,
        "_catalog": "MangaBaka",
    }


def get_volume_records(series_id, max_pages=4, limit=50):
    """Resolve published volume records when a MangaBaka series has volume collections."""
    collections = []
    for page in range(1, max(1, int(max_pages)) + 1):
        payload = get_series_collections(series_id, page=page, limit=limit)
        records = _records(payload)
        collections.extend(records)
        if not records or not _pagination(payload).get("next"):
            break

    volume_collections = [item for item in collections
                          if "volume" in str(item.get("type") or item.get("name") or "").lower()]
    if not volume_collections:
        return []
    volume_collections.sort(key=lambda item: (
        0 if str(item.get("language") or "").lower() in {"en", "eng", "english"} else 1,
        -int(item.get("count") or item.get("works_count") or 0),
    ))
    for collection in volume_collections:
        collection_id = collection.get("id")
        if not collection_id:
            continue
        works = []
        for page in range(1, 5):
            payload = get_collection_works(collection_id, page=page, limit=50)
            records = _records(payload)
            works.extend(records)
            if not records or not _pagination(payload).get("next"):
                break
        if not works:
            continue
        normalized = []
        for index, work in enumerate(works, start=1):
            raw_number = (work.get("volume_number") or work.get("volume") or
                          work.get("number") or work.get("position") or index)
            match = re.search(r"\d+", str(raw_number))
            number = int(match.group(0)) if match else index
            title = _first_text(work.get("title"), work.get("name"), work.get("title_en"),
                                work.get("title_english"), work.get("title_native"))
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
