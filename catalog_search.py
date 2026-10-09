"""Search AniList and MangaBaka together and normalize their results."""
from __future__ import annotations

from datetime import date

from api import search_anime
from mangabaka_api import enrich_anilist_results, search_media as search_mangabaka_media

ANIME_FORMATS = {"TV", "TV_SHORT", "MOVIE", "OVA", "ONA", "SPECIAL", "MUSIC"}
PROVIDER_ONLY_FILTERS = ("publisher_id", "is_licensed")
PAGE_SIZE = 20


def _provider_id(item):
    value = item.get("_mangabaka_id")
    if value is None:
        value = (item.get("_mangabaka") or {}).get("id")
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _media_id(item):
    try:
        return int(item.get("id"))
    except (AttributeError, TypeError, ValueError):
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
        return int(value.get("year")), int(value.get("month") or 1), int(value.get("day") or 1)
    except (TypeError, ValueError):
        return None


def _score(item):
    try:
        value = float(item.get("averageScore"))
        return value if 0 <= value <= 100 else -1.0
    except (TypeError, ValueError):
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
        last_page = max(1, int(info.get("lastPage") or 1))
    except (TypeError, ValueError):
        last_page = 1
    return {
        "currentPage": int(page),
        "lastPage": last_page,
        "hasNextPage": bool(info.get("hasNextPage")),
    }


def search_combined_media(search_text, page, media_type, media_format, filters,
                          include_relations=True):
    """Return a single de-duplicated page shaped for the existing result UI."""
    query = str(search_text or "").strip()
    page = max(1, int(page or 1))
    filters = dict(filters or {})
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
        raw_anilist_items = [
            item for item in (data.get("media") or []) if isinstance(item, dict)
        ]
        # Defend against duplicate records from partial or inconsistent provider responses.
        anilist_items = []
        seen_anilist_ids = set()
        for item in raw_anilist_items:
            media_id = _media_id(item)
            if media_id is not None:
                if media_id in seen_anilist_ids:
                    continue
                seen_anilist_ids.add(media_id)
            anilist_items.append(item)
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

    candidates = [
        item["_mangabaka"] for item in mangabaka_items
        if isinstance(item.get("_mangabaka"), dict)
    ]
    if anilist_items and candidates:
        enrich_anilist_results(anilist_items, query, candidates=candidates)

    provider_filter_active = any(filters.get(key) is not None for key in PROVIDER_ONLY_FILTERS)
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
        if provider_id is not None:
            if provider_id in seen_mb:
                continue
            seen_mb.add(provider_id)
        if media_id is not None:
            if media_id in seen_mb_media_ids:
                continue
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
