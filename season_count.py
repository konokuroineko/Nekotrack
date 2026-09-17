import re
from collections import defaultdict


LOGIC_VERSION = 2


def _get(item, key, default=None):
    """Read a member attribute from dicts and sqlite3.Row-like objects alike."""
    if hasattr(item, "get"):
        return item.get(key, default)
    try:
        return item[key]
    except (KeyError, IndexError, TypeError):
        return default


def _title_text(item):
    title = _get(item, "title") or {}
    if isinstance(title, dict):
        return title.get("english") or title.get("romaji") or title.get("native") or ""
    return str(title)


def _season_marker(title):
    """Return only an explicit season identity, never a bare Part/Cour number."""
    title = (title or "").lower()

    if re.search(r"\bfinal\s+season\b", title):
        return "final"

    ordinal = re.search(r"\b(\d+)(?:st|nd|rd|th)\s+season\b", title)
    if ordinal:
        return f"season-{int(ordinal.group(1))}"

    word_ordinal = re.search(
        r"\b(first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth)\s+season\b",
        title,
    )
    if word_ordinal:
        values = {
            "first": 1, "second": 2, "third": 3, "fourth": 4,
            "fifth": 5, "sixth": 6, "seventh": 7, "eighth": 8,
            "ninth": 9, "tenth": 10,
        }
        return f"season-{values[word_ordinal.group(1)]}"

    numbered = re.search(r"\bseason\s*(\d+)\b", title)
    if numbered:
        return f"season-{int(numbered.group(1))}"

    roman = re.search(r"\b(?:season|series)\s+(i|ii|iii|iv|v|vi)\b", title)
    if roman:
        values = {"i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5, "vi": 6}
        return f"season-{values[roman.group(1)]}"

    roman_prefix = re.search(r"(?:^|\s)(ii|iii|iv|v|vi)\s*[:\-–—]\s*", title)
    if roman_prefix:
        values = {"ii": 2, "iii": 3, "iv": 4, "v": 5, "vi": 6}
        return f"season-{values[roman_prefix.group(1)]}"

    roman_suffix = re.search(r"(?:^|\s)(ii|iii|iv|v|vi)\s*$", title)
    if roman_suffix:
        values = {"ii": 2, "iii": 3, "iv": 4, "v": 5, "vi": 6}
        return f"season-{values[roman_suffix.group(1)]}"

    # Bare trailing numbers are valid season markers only when they are not
    # part of a Part/Cour suffix. This covers titles such as "Tokyo Ghoul:re 2"
    # without turning "Boruto ... Part 2" into Season 2.
    if not re.search(r"\b(?:part|cour)\s*[0-9]+\s*$", title):
        bare_number = re.search(r"(?:^|[\s:])([2-9])\s*$", title)
        if bare_number:
            return f"season-{int(bare_number.group(1))}"

    return None


def _is_continuation(title):
    title = (title or "").lower()
    return bool(
        re.search(r"\b(?:part|cour)\s*(?:\d+|i|ii|iii|iv|v|vi)\b", title)
        or re.search(r"\bfinal\s+season\b", title)
    )


def _is_arc(title):
    return bool(re.search(r"\barc\b", (title or "").lower()))


def _air_period(member):
    start = _get(member, "startDate") or {}
    year = start.get("year")
    month = start.get("month")
    if year is None:
        year = _get(member, "start_year")
    if month is None and year is None:
        return None
    if month is None:
        return (year, None)

    # Anime seasons are conventionally Winter/Spring/Summer/Fall. Using the
    # airing season instead of calendar year prevents unrelated same-year arcs
    # from being merged while still combining consecutive arcs in one season.
    airing_season = (int(month) - 1) // 3
    return (year, airing_season)


def logical_season_count(members, series_module=None):
    tv_members = [
        member
        for member in members
        if str(_get(member, "format") or "").upper() in {"TV", "TV_SHORT"}
    ]
    if not tv_members:
        return 0

    ids = {int(_get(member, "id")) for member in tv_members}
    parent = {media_id: media_id for media_id in ids}
    by_id = {int(_get(member, "id")): member for member in tv_members}

    def find(media_id):
        while parent[media_id] != media_id:
            parent[media_id] = parent[parent[media_id]]
            media_id = parent[media_id]
        return media_id

    def union(left, right):
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    # 1. Explicit season labels are authoritative.
    by_marker = defaultdict(list)
    for member in tv_members:
        marker = _season_marker(_title_text(member))
        if marker:
            by_marker[marker].append(int(member["id"]))

    for ids_for_marker in by_marker.values():
        first = ids_for_marker[0]
        for media_id in ids_for_marker[1:]:
            union(first, media_id)

    # 2. Explicit Part/Cour/Final continuations inherit their direct TV
    #    neighbor, but never cross two different explicit season markers.
    for member in tv_members:
        title = _title_text(member)
        if not _is_continuation(title):
            continue

        member_id = int(member["id"])
        current_marker = _season_marker(title)

        for edge in (_get(member, "relations") or {}).get("edges", []):
            if edge.get("relationType") not in {"PREQUEL", "SEQUEL"}:
                continue

            node = edge.get("node") or {}
            target_id = node.get("id")
            if target_id is None:
                continue

            target_id = int(target_id)
            if target_id not in by_id:
                continue

            target_title = _title_text(by_id[target_id])
            target_marker = _season_marker(target_title)

            if current_marker is not None and target_marker is not None:
                if current_marker == target_marker:
                    union(member_id, target_id)
            elif current_marker is None and target_marker is None:
                union(member_id, target_id)

    # 3. Unnumbered named arcs can form a single season. Merge only directly
    #    linked arc entries that began in the same airing season.
    arc_ids = {
        int(member["id"])
        for member in tv_members
        if _is_arc(_title_text(member))
        and _season_marker(_title_text(member)) is None
        and not _is_continuation(_title_text(member))
    }

    for member_id in arc_ids:
        member = by_id[member_id]
        member_period = _air_period(member)

        for edge in (_get(member, "relations") or {}).get("edges", []):
            if edge.get("relationType") not in {"PREQUEL", "SEQUEL"}:
                continue

            node = edge.get("node") or {}
            target_id = node.get("id")
            if target_id is None:
                continue

            target_id = int(target_id)
            if target_id not in arc_ids:
                continue

            target_period = _air_period(by_id[target_id])
            if member_period == target_period:
                union(member_id, target_id)

    return len({find(media_id) for media_id in ids})


def patch_series(series_module):
    """Install the shared production season-count implementation."""
    series_module._bundle_logical_season_count = lambda members: logical_season_count(
        members, series_module
    )
