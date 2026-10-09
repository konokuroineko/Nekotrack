"""MangaBaka public catalog integration.

AniList remains the anime catalog and relationship source. MangaBaka adds
multilingual manga/novel titles and catalog metadata.
"""
from __future__ import annotations

import math
import re
import time
import unicodedata
from urllib.parse import urljoin, urlparse

import requests

API_BASE = "https://api.mangabaka.org/v2/"
WEB_BASE = "https://mangabaka.org/"
REQUEST_TIMEOUT = 20
MAX_RETRIES = 3
CACHE_SECONDS = 300
MANGABAKA_ID_OFFSET = 1_000_000_000
_response_cache = {}


class MangaBakaError(RuntimeError):
    """A request to MangaBaka failed or returned an invalid response."""


def api_get(path, params=None, *, timeout=REQUEST_TIMEOUT, use_cache=True):
    """Cached, rate-limit-aware GET against any MangaBaka API endpoint."""
    clean_path = str(path or "").lstrip("/")
    if not clean_path or clean_path.startswith(("http:", "https:")):
        raise ValueError("Pass a relative MangaBaka API path.")
    try:
        import json
        key = (clean_path, json.dumps(params or {}, sort_keys=True, ensure_ascii=False, default=str))
    except (TypeError, ValueError):
        key = (clean_path, repr(params))
    now = time.monotonic()
    if use_cache and key in _response_cache:
        cached_at, payload = _response_cache[key]
        if now - cached_at < CACHE_SECONDS:
            return payload

    url = urljoin(API_BASE, clean_path)
    last_error = None
    for attempt in range(MAX_RETRIES):
        try:
            response = requests.get(
                url,
                params=params or {},
                headers={"Accept": "application/json", "User-Agent": "NekoTrack/1.0 (desktop catalog client)"},
                timeout=timeout,
            )
            if (response.status_code == 429 or response.status_code >= 500) and attempt + 1 < MAX_RETRIES:
                retry_after = response.headers.get("Retry-After")
                try:
                    wait = max(1.0, min(15.0, float(retry_after))) if retry_after else 1.5 * (2 ** attempt)
                except (TypeError, ValueError):
                    wait = 1.5 * (2 ** attempt)
                time.sleep(wait)
                continue
            try:
                payload = response.json()
            except ValueError as error:
                raise MangaBakaError("MangaBaka returned a non-JSON response.") from error
            if response.status_code >= 400:
                message = payload.get("message") if isinstance(payload, dict) else None
                raise MangaBakaError(
                    f"MangaBaka API returned HTTP {response.status_code}"
                    + (f": {message}" if message else ".")
                )
            if isinstance(payload, dict):
                api_status = payload.get("status")
                if isinstance(api_status, int) and api_status >= 400:
                    raise MangaBakaError(str(payload.get("message") or "MangaBaka request failed."))
            if use_cache:
                _response_cache[key] = (time.monotonic(), payload)
            return payload
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout,
                requests.exceptions.ChunkedEncodingError) as error:
            last_error = error
            if attempt + 1 < MAX_RETRIES:
                time.sleep(1.0 * (2 ** attempt))
                continue
        except requests.exceptions.RequestException as error:
            raise MangaBakaError(f"Could not reach MangaBaka: {error}") from error
    raise MangaBakaError(f"Could not reach MangaBaka after retries: {last_error}")


def _unwrap(payload):
    return payload.get("data") if isinstance(payload, dict) and "data" in payload else payload


def _items_and_pagination(payload):
    if not isinstance(payload, dict):
        return [], {}
    data = payload.get("data")
    if isinstance(data, list):
        return data, payload.get("pagination") or {}
    if isinstance(data, dict):
        return [data], payload.get("pagination") or {}
    return [], payload.get("pagination") or {}


def search_series(query="", *, page=1, limit=20, series_type=None,
                  publisher_id=None, tag_id=None, content_rating=None):
    """Search MangaBaka's catalog, explicitly keeping safe-rated records only."""
    params = {
        "page": max(1, int(page or 1)),
        "limit": max(1, min(50, int(limit or 20))),
        "content_rating": ["safe"],
    }
    if str(query or "").strip():
        params["q"] = str(query).strip()
    if series_type:
        params["type"] = list(series_type) if isinstance(series_type, (tuple, list, set)) else [series_type]
    if publisher_id is not None:
        params["publisher_id"] = publisher_id
    if tag_id is not None:
        params["tag_id"] = tag_id
    if content_rating:
        params["content_rating"] = ["safe"]
    payload = api_get("series/search", params)
    items, pagination = _items_and_pagination(payload)
    safe_items = [
        item for item in items
        if isinstance(item, dict) and str(item.get("content_rating") or "safe").lower() == "safe"
    ]
    return {"data": safe_items, "pagination": pagination, "raw": payload}


def get_series(series_id, *, schema="full", use_cache=True):
    """Fetch one full series record, including its multilingual titles and metadata."""
    if not str(series_id or "").isdigit():
        raise ValueError("MangaBaka series IDs must be numeric.")
    params = {"schema": schema} if schema else {}
    payload = api_get(f"series/{int(series_id)}", params, use_cache=use_cache)
    record = _unwrap(payload)
    if not isinstance(record, dict):
        raise MangaBakaError("MangaBaka returned no series record.")
    if str(record.get("content_rating") or "safe").lower() != "safe":
        raise MangaBakaError("This entry is not in NekoTrack's safe-rated catalog.")
    return record


def mix_series(*, page=1, limit=20, series_type=None, publisher_id=None, tag_id=None):
    """Browse the public catalog mix endpoint."""
    params = {"page": max(1, int(page or 1)), "limit": max(1, min(50, int(limit or 20))),
              "content_rating": ["safe"]}
    if series_type:
        params["type"] = list(series_type) if isinstance(series_type, (tuple, list, set)) else [series_type]
    if publisher_id is not None:
        params["publisher_id"] = publisher_id
    if tag_id is not None:
        params["tag_id"] = tag_id
    payload = api_get("series/mix", params)
    items, pagination = _items_and_pagination(payload)
    items = [
        item for item in items
        if isinstance(item, dict) and str(item.get("content_rating") or "safe").lower() == "safe"
    ]
    return {"data": items, "pagination": pagination, "raw": payload}


def random_series(**params):
    """Call the public random-series endpoint."""
    return api_get("series/random", params or None)


def discover_hidden_gems(*, page=1, limit=20, publisher_id=None, **filters):
    """Call the public hidden-gems discovery endpoint."""
    params = {"page": max(1, int(page or 1)), "limit": max(1, min(50, int(limit or 20))),
              "content_rating": ["safe"]}
    if publisher_id is not None:
        params["publisher_id"] = publisher_id
    params.update({key: value for key, value in filters.items() if value is not None})
    return api_get("series/discover/hidden-gems", params)


def get_tags(**params):
    """Return the catalog's tag/genre list."""
    return api_get("tags", params or None)


def get_tag(tag_id, **params):
    return api_get(f"tags/{int(tag_id)}", params or None)


def get_publishers(**params):
    return api_get("publishers", params or None)


def get_publisher(publisher_id, **params):
    return api_get(f"publishers/{int(publisher_id)}", params or None)


def get_publisher_similar(publisher_id, **params):
    return api_get(f"publishers/{int(publisher_id)}/similar", params or None)


def get_publisher_stats(publisher_id, **params):
    return api_get(f"publishers/{int(publisher_id)}/stats", params or None)


def _title_rank(title):
    traits = set(title.get("traits") or [])
    if title.get("is_primary"):
        return 0
    if "official" in traits:
        return 1
    if "native" in traits:
        return 2
    return 3


def _title_for_language(titles, language_prefix):
    candidates = [
        title for title in (titles or [])
        if isinstance(title, dict)
        and str(title.get("language") or "").lower().startswith(language_prefix.lower())
        and str(title.get("title") or "").strip()
    ]
    candidates.sort(key=_title_rank)
    return str(candidates[0]["title"]).strip() if candidates else None


def _parse_link_id(series, providers):
    provider_names = {str(value).lower() for value in providers}
    for link in series.get("links") or []:
        if not isinstance(link, dict):
            continue
        name = " ".join(str(link.get(key) or "") for key in ("name", "type")).lower()
        url = str(link.get("url") or "")
        host = (urlparse(url).hostname or "").lower()
        if not any(provider in name or provider in host for provider in provider_names):
            continue
        match = re.search(r"/(?:manga|anime)/(\d+)(?:/|$)", url)
        if match:
            return int(match.group(1))
    return None


def _parse_year(date_value):
    match = re.match(r"^\s*(\d{4})(?:-(\d{1,2}))?(?:-(\d{1,2}))?", str(date_value or ""))
    if not match:
        return {}
    return {
        "year": int(match.group(1)),
        "month": int(match.group(2)) if match.group(2) else None,
        "day": int(match.group(3)) if match.group(3) else None,
    }


def _mangabaka_web_url(series):
    for link in series.get("links") or []:
        if isinstance(link, dict):
            url = str(link.get("url") or "")
            host = (urlparse(url).hostname or "").lower()
            if host.endswith("mangabaka.org"):
                return url
    series_id = series.get("id")
    return f"{WEB_BASE}series/{int(series_id)}" if str(series_id or "").isdigit() else WEB_BASE


def normalize_series(series):
    """Normalize a MangaBaka record into NekoTrack's shared media shape."""
    if not isinstance(series, dict):
        raise ValueError("MangaBaka series must be an object.")
    if str(series.get("content_rating") or "safe").lower() != "safe":
        raise ValueError("Only safe-rated MangaBaka records can be imported.")

    titles = [title for title in (series.get("titles") or []) if isinstance(title, dict)]
    english = _title_for_language(titles, "en") or str(series.get("title") or "").strip() or None
    romaji = _title_for_language(titles, "ja-latn") or str(series.get("romanized_title") or "").strip() or None
    native = _title_for_language(titles, "ja") or str(series.get("native_title") or "").strip() or None
    title_data = {"english": english, "romaji": romaji, "native": native}

    try:
        mb_id = int(series["id"])
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("MangaBaka series is missing a numeric ID.") from error

    anilist_id = _parse_link_id(series, {"anilist.co", "anilist"})
    mal_id = _parse_link_id(series, {"myanimelist.net", "myanimelist", "mal"})
    work_id = anilist_id if anilist_id is not None else -(MANGABAKA_ID_OFFSET + abs(mb_id))
    record_type = str(series.get("type") or "manga").lower()
    media_format = "NOVEL" if record_type == "novel" else "MANGA"

    try:
        rating = float(series["rating"]) if series.get("rating") is not None else None
        score = max(0, min(100, round(rating * 10))) if rating is not None else None
    except (TypeError, ValueError):
        score = None

    published = series.get("published") or {}
    start_date = _parse_year(published.get("start_date"))
    end_date = _parse_year(published.get("end_date"))
    statuses = {
        "completed": "FINISHED", "finished": "FINISHED",
        "releasing": "RELEASING", "ongoing": "RELEASING",
        "upcoming": "NOT_YET_RELEASED", "hiatus": "HIATUS",
        "cancelled": "CANCELLED", "canceled": "CANCELLED",
    }
    cover = series.get("cover") or {}
    cover_url = cover.get("x350") or cover.get("x250") or cover.get("raw") or cover.get("x150")
    alternate_entries, synonyms, seen_titles = [], [], set()
    for title in titles:
        text_value = str(title.get("title") or "").strip()
        language = str(title.get("language") or "").strip() or None
        if not text_value:
            continue
        unique_key = (language, text_value.casefold())
        if unique_key in seen_titles:
            continue
        seen_titles.add(unique_key)
        alternate_entries.append({"title": text_value, "language": language})
        if text_value.casefold() not in {
            str(english or "").casefold(), str(romaji or "").casefold(), str(native or "").casefold()
        }:
            synonyms.append(text_value)
    for legacy_title in series.get("secondary_titles") or []:
        if isinstance(legacy_title, str) and legacy_title.strip():
            synonyms.append(legacy_title.strip())

    # MangaBaka records are never routed through anime/TMDB episode discovery.
    return {
        "id": work_id, "idMal": mal_id, "type": "MANGA", "format": media_format,
        "title": title_data, "description": series.get("description") or "",
        "episodes": None, "chapters": series.get("total_chapters"),
        "volumes": series.get("final_volume"), "averageScore": score,
        "startDate": start_date, "endDate": end_date,
        "coverImage": {"large": cover_url} if cover_url else {},
        "status": statuses.get(str(series.get("status") or "").lower()),
        "source": "MangaBaka", "synonyms": list(dict.fromkeys(synonyms)),
        "relations": {"edges": []}, "studios": {"edges": []},
        "_relations_loaded": True, "_provider": "MANGABAKA",
        "_provider_id": str(mb_id), "_provider_url": _mangabaka_web_url(series),
        "_provider_data": series, "_alternate_title_entries": alternate_entries,
        "_provider_only": anilist_id is None, "_provider_type": record_type,
    }


def enrich_anilist_media_from_mangabaka(anilist_media, series):
    """Add MangaBaka metadata to an AniList record without replacing its ID."""
    if not isinstance(anilist_media, dict):
        return anilist_media
    normalized = normalize_series(series)
    merged = dict(anilist_media)
    mb_title = normalized.get("title") or {}
    original_title = merged.get("title") or {}
    merged["title"] = {
        "english": original_title.get("english") or mb_title.get("english"),
        "romaji": original_title.get("romaji") or mb_title.get("romaji"),
        "native": original_title.get("native") or mb_title.get("native"),
    }
    for field in ("chapters", "volumes"):
        if merged.get(field) in (None, 0) and normalized.get(field) is not None:
            merged[field] = normalized[field]
    if not merged.get("description"):
        merged["description"] = normalized.get("description")
    if not (merged.get("coverImage") or {}).get("large") and (normalized.get("coverImage") or {}).get("large"):
        merged["coverImage"] = normalized["coverImage"]
    merged["synonyms"] = list(dict.fromkeys(
        [*(merged.get("synonyms") or []), *(normalized.get("synonyms") or [])]
    ))
    for field in ("_provider", "_provider_id", "_provider_url", "_provider_data", "_alternate_title_entries", "_provider_type"):
        merged[field] = normalized.get(field)
    merged["_provider_only"] = False
    merged["_relations_loaded"] = bool(merged.get("relations") is not None)
    return merged


def _normal_key(value):
    value = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return re.sub(r"[\W_]+", "", value, flags=re.UNICODE)


def _find_anilist_match(mb_item, candidates):
    # Exact linked IDs win. Title-only matches require a shared non-English
    # title/alias so two IF routes with the same English release title do not
    # get accidentally collapsed into one work.
    for candidate in candidates:
        if int(candidate.get("id") or 0) == int(mb_item.get("id") or 0):
            return candidate
    mb_title = mb_item.get("title") or {}
    mb_non_english = {
        _normal_key(mb_title.get(key)) for key in ("romaji", "native")
        if _normal_key(mb_title.get(key))
    }
    mb_non_english.update(
        _normal_key(entry.get("title"))
        for entry in mb_item.get("_alternate_title_entries") or []
        if entry.get("language") and not str(entry["language"]).lower().startswith("en")
        and _normal_key(entry.get("title"))
    )
    matches = []
    for candidate in candidates:
        title = candidate.get("title") or {}
        values = {
            _normal_key(title.get(key)) for key in ("romaji", "native")
            if _normal_key(title.get(key))
        }
        values.update(
            _normal_key(value) for value in (candidate.get("synonyms") or [])
            if _normal_key(value)
        )
        if mb_non_english & values:
            matches.append(candidate)
    return matches[0] if len(matches) == 1 else None


def _merge_catalog_records(mangabaka_items, anilist_items):
    unused_anilist = [dict(item) for item in (anilist_items or []) if isinstance(item, dict)]
    combined, seen_ids = [], set()
    for raw in mangabaka_items or []:
        try:
            mb_item = normalize_series(raw)
        except (TypeError, ValueError):
            continue
        matched = _find_anilist_match(mb_item, unused_anilist)
        if matched is not None:
            unused_anilist = [item for item in unused_anilist if item is not matched]
            record = dict(matched)
            record.update({
                "_provider": "MANGABAKA",
                "_provider_id": mb_item["_provider_id"],
                "_provider_url": mb_item["_provider_url"],
                "_provider_data": mb_item["_provider_data"],
                "_alternate_title_entries": mb_item["_alternate_title_entries"],
                "_provider_type": mb_item["_provider_type"],
                "_provider_only": False,
            })
            record["synonyms"] = list(dict.fromkeys(
                [*(record.get("synonyms") or []), *(mb_item.get("synonyms") or [])]
            ))
            for field in ("chapters", "volumes"):
                if record.get(field) in (None, 0) and mb_item.get(field) is not None:
                    record[field] = mb_item[field]
            if not record.get("description"):
                record["description"] = mb_item.get("description")
            if not (record.get("coverImage") or {}).get("large"):
                record["coverImage"] = mb_item.get("coverImage") or {}
            if not record.get("title"):
                record["title"] = mb_item.get("title") or {}
            if record.get("relations") is None:
                record["relations"] = {"edges": []}
            record["_relations_loaded"] = bool(record.get("relations") is not None)
        else:
            record = mb_item
        try:
            numeric_id = int(record["id"])
        except (KeyError, TypeError, ValueError):
            continue
        if numeric_id not in seen_ids:
            seen_ids.add(numeric_id)
            combined.append(record)
    for record in unused_anilist:
        try:
            numeric_id = int(record["id"])
        except (KeyError, TypeError, ValueError):
            continue
        if numeric_id not in seen_ids:
            seen_ids.add(numeric_id)
            combined.append(record)
    return _disambiguate_titles(combined)


def _disambiguate_titles(items):
    groups = {}
    for item in items:
        if str(item.get("_provider") or "").upper() != "MANGABAKA":
            continue
        title = item.get("title") or {}
        primary = title.get("english") or title.get("romaji") or title.get("native") or ""
        key = _normal_key(primary)
        if key:
            groups.setdefault(key, []).append(item)
    for duplicates in groups.values():
        if len(duplicates) < 2:
            continue
        for item in duplicates:
            title = item.get("title") or {}
            primary = title.get("english") or title.get("romaji") or title.get("native") or "Untitled"
            secondary = next(
                (value for value in (title.get("romaji"), title.get("native"))
                 if value and _normal_key(value) != _normal_key(primary)),
                None,
            )
            if not secondary:
                secondary = f"MangaBaka #{item.get('_provider_id')}"
            item["_display_title_override"] = f"{primary} ({secondary})"
    return items


def _matches_filters(item, media_format=None, filters=None):
    filters = filters or {}
    wanted_format = filters.get("format_filter") or media_format
    if wanted_format and str(item.get("format") or "").upper() != str(wanted_format).upper():
        return False
    status = str(filters.get("status") or "").upper()
    if status and str(item.get("status") or "").upper() != status:
        return False
    year = filters.get("year")
    if year:
        try:
            if int((item.get("startDate") or {}).get("year") or 0) != int(year):
                return False
        except (TypeError, ValueError):
            return False
    minimum_score = filters.get("min_score")
    if minimum_score is not None:
        try:
            if item.get("averageScore") is None or float(item["averageScore"]) < float(minimum_score):
                return False
        except (TypeError, ValueError):
            return False
    tag_names = {
        str(tag.get("name") or "").casefold()
        for tag in ((item.get("_provider_data") or {}).get("tags") or [])
        if isinstance(tag, dict)
    }
    genre = str(filters.get("genre") or "").strip().casefold()
    tag = str(filters.get("tag") or "").strip().casefold()
    if genre and not any(genre in name for name in tag_names):
        return False
    if tag and not any(tag in name for name in tag_names):
        return False
    return True


def search_reading_catalog(query, page=1, media_format=None, filters=None, include_relations=True):
    """Search/browse MangaBaka first, merging matching AniList records as a fallback."""
    from api import search_anime

    filters = filters or {}
    page = max(1, int(page or 1))
    effective_format = filters.get("format_filter") or media_format
    requested_type = ["novel"] if str(effective_format or "").upper() == "NOVEL" else [
        "manga", "manhwa", "manhua", "oel", "other"
    ]
    mb_error = None
    mb_response = None
    try:
        if str(query or "").strip():
            mb_response = search_series(query, page=page, limit=20, series_type=requested_type)
        else:
            mb_response = mix_series(page=page, limit=20, series_type=requested_type)
    except Exception as error:
        mb_error = error

    anilist_data = None
    ani_error = None
    try:
        ani_filters = {
            key: filters.get(key) for key in ("status", "year", "sort", "min_score", "genre", "tag")
            if filters.get(key) is not None
        }
        if filters.get("format_filter") or media_format:
            ani_filters["format_filter"] = filters.get("format_filter") or media_format
        anilist_data = search_anime(
            str(query or ""), page, media_type="MANGA",
            include_relations=include_relations, **ani_filters,
        )
    except Exception as error:
        ani_error = error

    mb_items = (mb_response or {}).get("data") or []
    anilist_items = (anilist_data or {}).get("media") or []
    normalized = _merge_catalog_records(mb_items, anilist_items)
    normalized = [
        item for item in normalized
        if str(item.get("type") or "").upper() == "MANGA"
        and _matches_filters(item, effective_format, filters)
    ]
    if not normalized and mb_error and ani_error:
        raise MangaBakaError(f"MangaBaka search failed ({mb_error}); AniList fallback failed ({ani_error}).")

    pagination = (mb_response or {}).get("pagination") or {}
    count = pagination.get("count")
    limit = int(pagination.get("limit") or 20)
    current_page = int(pagination.get("page") or page)
    try:
        last_page = max(1, int(math.ceil(float(count) / max(1, limit)))) if count is not None else current_page
    except (TypeError, ValueError):
        last_page = current_page
    has_next = bool(pagination.get("next")) or current_page < last_page
    if not mb_response and anilist_data:
        page_info = anilist_data.get("pageInfo") or {}
        current_page = int(page_info.get("currentPage") or page)
        last_page = int(page_info.get("lastPage") or current_page)
        has_next = bool(page_info.get("hasNextPage"))
    elif mb_response and anilist_data:
        has_next = has_next or bool((anilist_data.get("pageInfo") or {}).get("hasNextPage"))

    sort = str(filters.get("sort") or "").upper()
    if sort in {"SCORE_DESC", "SCORE"}:
        normalized.sort(key=lambda item: item.get("averageScore") or -1, reverse=True)
    elif sort in {"START_DATE_DESC", "NEWEST"}:
        normalized.sort(key=lambda item: (item.get("startDate") or {}).get("year") or 0, reverse=True)
    elif sort in {"START_DATE", "OLDEST"}:
        normalized.sort(key=lambda item: (item.get("startDate") or {}).get("year") or 9999)
    elif sort in {"TITLE_ROMAJI", "TITLE"}:
        normalized.sort(key=lambda item: _normal_key((item.get("title") or {}).get("romaji") or (item.get("title") or {}).get("english")))
    elif sort == "TITLE_ROMAJI_DESC":
        normalized.sort(key=lambda item: _normal_key((item.get("title") or {}).get("romaji") or (item.get("title") or {}).get("english")), reverse=True)

    return {"pageInfo": {"currentPage": current_page, "lastPage": last_page, "hasNextPage": has_next},
            "media": normalized}
