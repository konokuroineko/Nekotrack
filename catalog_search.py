"""Search AniList and MangaBaka together and normalize their results."""
from __future__ import annotations

from datetime import date as _date
import re

from api import search_anime
from mangabaka_api import enrich_anilist_results, search_media as search_mangabaka_media

ANIME_FORMATS = {"TV", "TV_SHORT", "MOVIE", "OVA", "ONA", "SPECIAL", "MUSIC"}
PROVIDER_ONLY_FILTERS = ("publisher_id", "is_licensed")
PAGE_SIZE = 20
MAX_CATALOG_PAGES = 10000
MAX_PROVIDER_ID = (1 << 63) - 1


def _positive_provider_id(value):
    """Parse bounded positive publisher IDs without trusting provider/user input."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if 0 < value <= MAX_PROVIDER_ID else None
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    # Real provider IDs are small numeric identifiers; bound parsing work and
    # reject abusive digit strings before calling int() (which can raise for
    # extremely long values on modern Python).
    if not stripped or len(stripped) > 19 or not stripped.isascii() or not stripped.isdigit():
        return None
    try:
        number = int(stripped)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if 0 < number <= MAX_PROVIDER_ID else None


def _filter_bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().casefold()
        if normalized in {"true", "yes", "1", "licensed", "on"}:
            return True
        if normalized in {"false", "no", "0", "unlicensed", "off"}:
            return False
    return None


def _collect_publisher_ids(value):
    if value is None or isinstance(value, bool):
        return set()
    if isinstance(value, (int, str)):
        number = _positive_provider_id(value)
        return {number} if number is not None else set()
    if isinstance(value, (list, tuple, set)):
        result = set()
        for item in value:
            result.update(_collect_publisher_ids(item))
        return result
    if isinstance(value, dict):
        result = set()
        for key in ("id", "publisher_id", "publisherId"):
            if key in value:
                result.update(_collect_publisher_ids(value[key]))
        return result
    return set()


def _matches_provider_only_filters(item, filters):
    """Fail closed if provider-only filters cannot be verified from row metadata."""
    if not isinstance(item, dict):
        return False
    raw = item.get("_mangabaka")
    if not isinstance(raw, dict):
        return False

    wanted_publisher = filters.get("publisher_id")
    if wanted_publisher not in (None, ""):
        wanted_id = _positive_provider_id(wanted_publisher)
        if wanted_id is None:
            return False
        known_ids = set()
        for key in ("publisher_id", "publisherId", "publisher_ids", "publisher", "publishers"):
            known_ids.update(_collect_publisher_ids(raw.get(key)))
        if wanted_id <= 0 or wanted_id not in known_ids:
            return False

    wanted_license = filters.get("is_licensed")
    if wanted_license is not None:
        wanted_bool = _filter_bool(wanted_license)
        if wanted_bool is None:
            return False
        actual = None
        for key in ("is_licensed", "isLicensed", "licensed"):
            if raw.get(key) is not None:
                actual = _filter_bool(raw.get(key))
                break
        if actual is None or actual is not wanted_bool:
            return False

    return True


def _provider_id(item):
    if not isinstance(item, dict):
        return None
    value = item.get("_mangabaka_id")
    if value is None:
        raw = item.get("_mangabaka")
        value = raw.get("id") if isinstance(raw, dict) else None
    if isinstance(value, bool) or (isinstance(value, float) and not value.is_integer()):
        return None
    if isinstance(value, str) and not re.fullmatch(r"\s*[0-9]+\s*", value):
        return None
    try:
        provider_id = int(value) if value is not None else None
    except (TypeError, ValueError, OverflowError):
        return None
    return provider_id if provider_id is not None and provider_id > 0 else None


def _media_id(item):
    if not isinstance(item, dict):
        return None
    value = item.get("id")
    if isinstance(value, bool) or (isinstance(value, float) and not value.is_integer()):
        return None
    if isinstance(value, str) and not re.fullmatch(r"\s*-?[0-9]+\s*", value):
        return None
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return None


def _title(item):
    title = item.get("title") or {}
    if isinstance(title, dict):
        return str(title.get("english") or title.get("romaji") or title.get("native") or "").strip()
    return str(title or "").strip()


def _date_parts(item):
    value = item.get("startDate") or {}
    if not isinstance(value, dict):
        return None
    try:
        if any(isinstance(value.get(key), bool) for key in ("year", "month", "day")):
            return None
        year = int(value.get("year"))
        month = int(value.get("month") or 1)
        day = int(value.get("day") or 1)
        _date(year, month, day)
        return year, month, day
    except (TypeError, ValueError, OverflowError):
        return None


def _score(item):
    try:
        value = float(item.get("averageScore"))
        return value if 0 <= value <= 100 else -1.0
    except (TypeError, ValueError, OverflowError):
        return -1.0


def _interleave(left, right):
    """Keep each API's ranking without comparing incompatible popularity scales."""
    result = []
    for index in range(max(len(left), len(right))):
        if index < len(left):
            result.append(left[index])
        if index < len(right):
            result.append(right[index])
    return result


def _sort_combined(anilist_items, mangabaka_items, sort):
    rows = [*anilist_items, *mangabaka_items]
    if sort == "SCORE_DESC":
        return sorted(rows, key=_score, reverse=True)
    if sort in {"START_DATE_DESC", "START_DATE"}:
        dated = [item for item in rows if _date_parts(item) is not None]
        undated = [item for item in rows if _date_parts(item) is None]
        dated.sort(key=_date_parts, reverse=sort == "START_DATE_DESC")
        return dated + undated
    if sort in {"TITLE_ROMAJI", "TITLE_ROMAJI_DESC"}:
        return sorted(rows, key=lambda item: _title(item).casefold(),
                      reverse=sort == "TITLE_ROMAJI_DESC")
    return _interleave(anilist_items, mangabaka_items)


def _page_info(data, page):
    info = data.get("pageInfo") if isinstance(data, dict) else {}
    info = info if isinstance(info, dict) else {}
    try:
        current_page = min(MAX_CATALOG_PAGES, max(1, int(page or 1)))
    except (TypeError, ValueError, OverflowError):
        current_page = 1

    try:
        last_page = max(1, int(info.get("lastPage") or 1))
    except (TypeError, ValueError, OverflowError):
        last_page = 1
    # Guard against corrupt pagination values making infinite scrolling believe
    # the catalogue has millions of pages.
    last_page = min(last_page, MAX_CATALOG_PAGES)

    raw_next = info.get("hasNextPage", False)
    if isinstance(raw_next, str):
        normalized = raw_next.strip().casefold()
        has_next = normalized in {"1", "true", "yes", "on"}
    elif isinstance(raw_next, bool):
        has_next = raw_next
    elif isinstance(raw_next, (int, float)) and raw_next in (0, 1):
        has_next = bool(raw_next)
    else:
        has_next = False

    last_page = max(current_page, last_page)
    return {
        "currentPage": current_page,
        "lastPage": last_page,
        "hasNextPage": has_next and current_page < last_page,
    }


def search_combined_media(search_text, page, media_type, media_format, filters,
                          include_relations=True):
    """Return a single de-duplicated page shaped for the existing result UI."""
    query = str(search_text or "").strip()
    try:
        page = min(MAX_CATALOG_PAGES, max(1, int(page or 1)))
    except (TypeError, ValueError, OverflowError):
        page = 1
    try:
        filters = dict(filters or {})
    except (TypeError, ValueError):
        filters = {}
    requested_format = filters.get("format_filter") or media_format
    season = filters.get("season")

    anime_only = (
        str(media_type or "").upper() == "ANIME"
        or requested_format in ANIME_FORMATS
        or bool(season)
    )
    use_mangabaka = (
        str(media_type or "").upper() != "ANIME"
        and not anime_only
        and requested_format != "ONE_SHOT"
    )
    anilist_type = media_type
    if requested_format in ANIME_FORMATS or (season and not media_type):
        anilist_type = "ANIME"

    # Publisher/licensing are MangaBaka-only. Never send unsupported variables
    # to AniList, and later exclude entries that can't be matched to that data.
    anilist_filters = dict(filters)
    for key in PROVIDER_ONLY_FILTERS:
        anilist_filters.pop(key, None)

    anilist_error = None
    try:
        data = search_anime(
            query, page, per_page=PAGE_SIZE, media_type=anilist_type,
            media_format=media_format, include_relations=include_relations,
            **anilist_filters,
        )
        data = data if isinstance(data, dict) else {}
        anilist_items = [item for item in (data.get("media") or []) if isinstance(item, dict)]
        anilist_page = _page_info(data, page)
    except Exception as error:
        anilist_error = str(error)
        anilist_items = []
        anilist_page = {"currentPage": page, "lastPage": 1, "hasNextPage": False}

    mangabaka_error = None
    mangabaka_items = []
    mangabaka_page = {"currentPage": page, "lastPage": 1, "hasNextPage": False}
    if use_mangabaka:
        mb_filters = dict(filters)
        if not query and mb_filters.get("sort") == "SEARCH_MATCH":
            mb_filters["sort"] = "POPULARITY_DESC"
        try:
            data = search_mangabaka_media(
                query, page, media_type, media_format, mb_filters, limit=PAGE_SIZE
            )
            data = data if isinstance(data, dict) else {}
            mangabaka_items = [item for item in (data.get("media") or []) if isinstance(item, dict)]
            mangabaka_page = _page_info(data, page)
        except Exception as error:
            mangabaka_error = str(error)

    if anilist_error and (not use_mangabaka or mangabaka_error):
        detail = f"AniList: {anilist_error}"
        if use_mangabaka:
            detail += f" | MangaBaka: {mangabaka_error or 'search unavailable'}"
        raise RuntimeError("Combined search failed. " + detail)
    if anilist_error:
        anilist_items = []
    if mangabaka_error:
        mangabaka_items = []

    # Drop duplicate AniList rows before performing cross-catalog enrichment.
    seen_anilist_ids = set()
    unique_anilist_items = []
    for item in anilist_items:
        media_id = _media_id(item)
        if media_id is not None:
            if media_id in seen_anilist_ids:
                continue
            seen_anilist_ids.add(media_id)
        unique_anilist_items.append(item)
    anilist_items = unique_anilist_items

    provider_filter_active = any(filters.get(key) is not None for key in PROVIDER_ONLY_FILTERS)
    if provider_filter_active:
        # The provider may silently ignore/fallback from query filters. Recheck
        # its raw metadata at this boundary and fail closed when unprovable.
        mangabaka_items = [
            item for item in mangabaka_items
            if _matches_provider_only_filters(item, filters)
        ]

    candidates = [
        item["_mangabaka"] for item in mangabaka_items
        if isinstance(item.get("_mangabaka"), dict)
    ]
    if anilist_items and candidates:
        enrich_anilist_results(anilist_items, query, candidates=candidates)

    if provider_filter_active:
        matching_provider_ids = {
            _provider_id(item) for item in mangabaka_items if _provider_id(item) is not None
        }
        anilist_items = [
            item for item in anilist_items
            if _provider_id(item) in matching_provider_ids
        ]

    attached_provider_ids = {
        _provider_id(item) for item in anilist_items if _provider_id(item) is not None
    }
    anilist_ids = {_media_id(item) for item in anilist_items if _media_id(item) is not None}
    unique_mb = []
    seen_mb = set()
    seen_mb_media_ids = set()
    for item in mangabaka_items:
        provider_id = _provider_id(item)
        media_id = _media_id(item)
        if provider_id is not None and provider_id in attached_provider_ids:
            continue
        if media_id is not None and media_id > 0 and media_id in anilist_ids:
            continue
        if provider_id is not None and provider_id in seen_mb:
            continue
        if media_id is not None and media_id in seen_mb_media_ids:
            continue
        if provider_id is not None:
            seen_mb.add(provider_id)
        if media_id is not None:
            seen_mb_media_ids.add(media_id)
        # MangaBaka-only entries have no AniList relation graph to fetch.
        if media_id is not None and media_id < 0:
            item["_relations_loaded"] = True
        unique_mb.append(item)

    results = _sort_combined(anilist_items, unique_mb, filters.get("sort") or "SEARCH_MATCH")
    warnings = []
    if anilist_error:
        warnings.append("AniList is temporarily unavailable; showing MangaBaka results.")
    if mangabaka_error:
        warnings.append("MangaBaka is temporarily unavailable; showing AniList results.")
    return {
        "pageInfo": {
            "currentPage": page,
            "lastPage": max(anilist_page["lastPage"], mangabaka_page["lastPage"]),
            "hasNextPage": bool(anilist_page["hasNextPage"] or (
                use_mangabaka and mangabaka_page["hasNextPage"]
            )),
        },
        "media": results,
        "_warnings": warnings,
    }
