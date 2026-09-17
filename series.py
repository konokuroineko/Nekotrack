from collections import defaultdict
import re
import time

from api import get_media_details, get_media_relations_batch
from database import get_all_library, get_connection, save_anime


SERIES_RELATIONS = {
    "PREQUEL", "SEQUEL", "PARENT", "SIDE_STORY", "SUMMARY",
    "FULL_STORY", "SPIN_OFF", "ALTERNATIVE", "COMPILATION", "CONTAINS",
}
# These relations describe the actual season/continuation chain. Traversal is
# intentionally restricted to them so a TV-catalog search cannot spend its
# global discovery budget walking huge spin-off/alternative graphs first.
SEASON_CHAIN_RELATIONS = {"PREQUEL", "SEQUEL", "PARENT"}
ANIME_BUNDLE_FORMATS = {"TV", "TV_SHORT", "MOVIE", "OVA", "ONA", "SPECIAL"}
RELATION_BATCH_SIZE = 10
MAX_NODE_FETCH_RETRIES = 3

_relation_sync_checked_ids = set()
_relation_cache = {}


def _title_text(item):
    title = item.get("title") or {} if hasattr(item, "get") else item["title"] or {}
    if isinstance(title, dict):
        return title.get("english") or title.get("romaji") or title.get("native") or ""
    return str(title)


def _media_type(item):
    value = item.get("type") if hasattr(item, "get") else item["type"]
    return str(value or "UNKNOWN").upper()


def _media_family(item):
    media_type = _media_type(item)
    fmt = item.get("format") if hasattr(item, "get") else item["format"]
    fmt = str(fmt or "").upper()
    if media_type == "MANGA":
        if fmt == "NOVEL":
            return "NOVEL"
        if fmt == "ONE_SHOT":
            return "ONE_SHOT"
        return "MANGA"
    return media_type


def _same_media_family(left, right):
    return _media_family(left) == _media_family(right)


def _is_bundleable(item):
    family = _media_family(item)
    fmt = item.get("format") if hasattr(item, "get") else item["format"]
    fmt = str(fmt or "").upper()
    if family == "ANIME":
        return fmt in ANIME_BUNDLE_FORMATS
    if family == "MANGA":
        return fmt == "MANGA"
    if family in {"NOVEL", "ONE_SHOT"}:
        return True
    return False


def _series_key(title):
    value = (title or "").lower().strip()
    value = re.sub(
        r"\s*[:\-–—]?\s*(?:the\s+)?final\s+season(?:\s+part\s+\d+)?(?:\s+\([^)]*\))?\s*$",
        "",
        value,
    )
    value = re.sub(
        r"\s*[:\-–—]?\s*(?:\d+(?:st|nd|rd|th)|season\s*\d+|series\s*\d+|season\s*[ivx]+|series\s*[ivx]+)(?:\s+part\s+\d+)?\s*$",
        "",
        value,
    )
    value = re.sub(r"(?:^|\s)(?:ii|iii|iv|v|vi)\s*[:\-–—]\s*", " ", value)
    value = re.sub(
        r"\s+(?:i|ii|iii|iv|v|vi|1st|2nd|3rd|4th|5th)\s*(?:season)?\s*$",
        "",
        value,
    )
    value = re.sub(r"\s*[:\-–—]?\s*(?:part|cour)\s*\d+\s*$", "", value)
    value = re.sub(r"\s+\d+$", "", value)
    value = re.sub(r"\s+", " ", value).strip()
    return re.sub(r"[^a-z0-9]+", " ", value).strip()


def _series_group_key(item):
    return _media_family(item), _series_key(_title_text(item))


def _season_marker(title):
    """Return an explicit season identity, or None when the title does not say one."""
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

    # Some databases number follow-up seasons with a bare trailing number,
    # e.g. "Tokyo Ghoul:re 2" rather than "Season 2".
    bare_number = re.search(r"(?:^|[\s:])([2-9])\s*$", title)
    if bare_number:
        return f"season-{int(bare_number.group(1))}"

    return None


def _is_continuation_title(title):
    title = (title or "").lower()
    return bool(
        re.search(r"\b(?:part|cour)\s*(?:\d+|i|ii|iii|iv|v|vi)\b", title)
        or re.search(r"\bfinal\s+season\b", title)
    )


def _is_arc_title(title):
    """Return True for titles that represent named story arcs rather than numbered seasons."""
    return bool(re.search(r"\barc\b", (title or "").lower()))


def _member_start_year(member):
    start_date = member.get("startDate") if hasattr(member, "get") else None
    if isinstance(start_date, dict) and start_date.get("year") is not None:
        return start_date.get("year")
    return member.get("start_year") if hasattr(member, "get") else None


def _bundle_logical_season_count(members):
    """
    Count logical TV seasons rather than raw TV entries.

    AniList can represent one real season as several directly-related TV arc
    entries. For example, Demon Slayer Season 2 is split into the Mugen Train
    Arc and Entertainment District Arc. Numbered season/part markers remain
    authoritative; unnumbered arc entries can share a season when they are
    directly linked and aired in the same year.
    """
    tv_members = [
        member
        for member in members
        if str(member.get("format") or "").upper() in {"TV", "TV_SHORT"}
    ]
    if not tv_members:
        return 0

    ids = {int(member["id"]) for member in tv_members}
    parent = {media_id: media_id for media_id in ids}

    def find(media_id):
        while parent[media_id] != media_id:
            parent[media_id] = parent[parent[media_id]]
            media_id = parent[media_id]
        return media_id

    def union(left, right):
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    by_id = {int(member["id"]): member for member in tv_members}

    # Explicit season identities are the strongest signal. All parts/cours of
    # that same explicit season are counted as one logical season.
    by_explicit_marker = defaultdict(list)
    for member in tv_members:
        marker = _season_marker(_title_text(member))
        if marker:
            by_explicit_marker[marker].append(int(member["id"]))

    for ids_for_marker in by_explicit_marker.values():
        first = ids_for_marker[0]
        for media_id in ids_for_marker[1:]:
            union(first, media_id)

    # Explicit part/cour/final continuations inherit the logical season of
    # their directly-linked TV neighbor, but never cross two different explicit
    # season identities.
    for member in tv_members:
        member_id = int(member["id"])
        title = _title_text(member)
        if not _is_continuation_title(title):
            continue

        current_marker = _season_marker(title)
        for edge in _search_relation_edges(member):
            if edge.get("relationType") not in {"PREQUEL", "SEQUEL"}:
                continue
            node = edge.get("node") or {}
            target_id = node.get("id")
            if target_id is None:
                continue
            target_id = int(target_id)
            if target_id not in ids:
                continue

            target = by_id[target_id]
            target_title = _title_text(target)
            target_marker = _season_marker(target_title)

            if current_marker is not None and target_marker is not None:
                if current_marker == target_marker:
                    union(member_id, target_id)
                continue

            if current_marker is not None and target_marker is None:
                if _is_continuation_title(target_title):
                    union(member_id, target_id)
                continue

            if current_marker is None and target_marker is not None:
                if _is_continuation_title(title):
                    union(member_id, target_id)
                continue

            if _is_continuation_title(target_title):
                union(member_id, target_id)

    # Unnumbered named arcs are often multiple entries making up one season.
    # Merge only when they are directly linked in the season chain AND share a
    # start year. This avoids collapsing genuinely separate numbered seasons
    # that happen to air during the same calendar year.
    arc_ids = {
        int(member["id"])
        for member in tv_members
        if _is_arc_title(_title_text(member))
        and _season_marker(_title_text(member)) is None
        and not _is_continuation_title(_title_text(member))
    }

    for member_id in arc_ids:
        member = by_id[member_id]
        member_year = _member_start_year(member)
        for edge in _search_relation_edges(member):
            if edge.get("relationType") not in {"PREQUEL", "SEQUEL"}:
                continue
            node = edge.get("node") or {}
            target_id = node.get("id")
            if target_id is None:
                continue
            target_id = int(target_id)
            if target_id not in arc_ids:
                continue

            target = by_id[target_id]
            target_year = _member_start_year(target)
            if member_year is not None and member_year == target_year:
                union(member_id, target_id)

    return len({find(media_id) for media_id in ids})


def _bundle_summary(members):
    if len(members) <= 1:
        return ""

    counts = defaultdict(int)
    logical_seasons = _bundle_logical_season_count(members)
    for member in members:
        fmt = (
            str(member.get("format") or "").upper()
            if hasattr(member, "get")
            else str(member["format"] or "").upper()
        )
        if fmt in {"TV", "TV_SHORT"}:
            continue
        if fmt == "OVA":
            counts["OVAs"] += 1
        elif fmt == "ONA":
            counts["ONAs"] += 1
        elif fmt == "MOVIE":
            counts["movies"] += 1
        elif fmt == "SPECIAL":
            counts["specials"] += 1
        elif fmt == "MUSIC":
            counts["music"] += 1
        elif fmt:
            counts[fmt.lower()] += 1
        else:
            counts["entries"] += 1

    if logical_seasons:
        counts["seasons"] = logical_seasons

    order = ["seasons", "OVAs", "ONAs", "movies", "specials", "music"]
    parts = [f"{counts[key]} {key}" for key in order if counts[key]]
    parts.extend(
        f"{count} {key}"
        for key, count in counts.items()
        if key not in order
    )
    return " · ".join(parts)


def _search_relation_edges(item):
    return (item.get("relations") or {}).get("edges", [])


def _relation_edge_allowed(item, edge):
    if edge.get("relationType") not in SERIES_RELATIONS:
        return False
    node = edge.get("node") or {}
    return bool(node.get("id")) and _same_media_family(item, node)


def _bundle_edge_allowed(item, edge):
    if not _relation_edge_allowed(item, edge):
        return False
    return _is_bundleable(item) and _is_bundleable(edge.get("node") or {})


def _traversal_edge_allowed(item, edge):
    """Walk only the season/continuation chain during recursive discovery."""
    if edge.get("relationType") not in SEASON_CHAIN_RELATIONS:
        return False
    node = edge.get("node") or {}
    return bool(node.get("id")) and _same_media_family(item, node)


def _related_placeholder(node):
    return {
        "id": int(node["id"]),
        "type": node.get("type"),
        "format": node.get("format"),
        "title": node.get("title") or {},
        "coverImage": node.get("coverImage") or {},
        "episodes": node.get("episodes"),
        "startDate": node.get("startDate") or {},
        "_related_only": True,
        "_relations_loaded": False,
    }


def _apply_relation_details(item, details):
    if not details:
        return
    item["relations"] = details.get("relations") or {}
    item["type"] = details.get("type") or item.get("type")
    item["format"] = details.get("format") or item.get("format")
    item["title"] = details.get("title") or item.get("title") or {}
    item["coverImage"] = details.get("coverImage") or item.get("coverImage") or {}
    if details.get("episodes") is not None:
        item["episodes"] = details["episodes"]
    item["startDate"] = details.get("startDate") or item.get("startDate") or {}
    item["_relations_loaded"] = True


def _cache_relation_details_batch(media_ids):
    ids = sorted({int(media_id) for media_id in media_ids if media_id is not None})
    missing = [media_id for media_id in ids if media_id not in _relation_cache]
    if not missing:
        return {
            media_id: _relation_cache[media_id]
            for media_id in ids
            if media_id in _relation_cache
        }

    try:
        fetched = get_media_relations_batch(missing)
    except Exception:
        if len(missing) == 1:
            return {
                media_id: _relation_cache[media_id]
                for media_id in ids
                if media_id in _relation_cache
            }

        midpoint = max(1, len(missing) // 2)
        left = _cache_relation_details_batch(missing[:midpoint])
        right = _cache_relation_details_batch(missing[midpoint:])
        left.update(right)
        return {
            media_id: left[media_id]
            for media_id in ids
            if media_id in left
        }

    for media_id, details in fetched.items():
        if details is not None:
            _relation_cache[int(media_id)] = details

    missing_after_fetch = [
        media_id for media_id in missing if media_id not in _relation_cache
    ]
    if missing_after_fetch and len(missing_after_fetch) < len(missing):
        recovered = _cache_relation_details_batch(missing_after_fetch)
        for media_id, details in recovered.items():
            _relation_cache[media_id] = details

    return {
        media_id: _relation_cache[media_id]
        for media_id in ids
        if media_id in _relation_cache
    }


def _discover_related(items, max_nodes=2000, max_requests=0, delay=0.25, stop_event=None):
    """Finite breadth-first traversal of the season/continuation relation graph."""
    discovered = list(items)
    known_ids = {int(item["id"]) for item in discovered}
    frontier = list(discovered)
    processed_ids = set()
    fetch_failures = defaultdict(int)
    requests_used = 0
    hydrate_existing_nodes = max_requests != -1

    while frontier and len(discovered) < max_nodes:
        if stop_event is not None and stop_event.is_set():
            break

        unresolved = []
        for item in frontier:
            item_id = int(item["id"])
            if item_id in processed_ids:
                continue

            if item.get("_relations_loaded"):
                continue

            if not hydrate_existing_nodes and (
                _search_relation_edges(item) or item_id in _relation_cache
            ):
                continue

            unresolved.append(item)

        can_fetch = (
            max_requests == 0
            or (max_requests > 0 and requests_used < max_requests)
        )

        if unresolved and can_fetch:
            for start in range(0, len(unresolved), RELATION_BATCH_SIZE):
                if stop_event is not None and stop_event.is_set():
                    break
                if max_requests > 0 and requests_used >= max_requests:
                    break

                batch = unresolved[start:start + RELATION_BATCH_SIZE]
                fetched = _cache_relation_details_batch(
                    [item["id"] for item in batch]
                )
                requests_used += 1

                for item in batch:
                    details = fetched.get(int(item["id"]))
                    if details is not None:
                        _apply_relation_details(item, details)
                    else:
                        fetch_failures[int(item["id"])] += 1

                if delay > 0 and start + RELATION_BATCH_SIZE < len(unresolved):
                    time.sleep(delay)

        next_frontier = []
        unresolved_remaining = []

        for item in frontier:
            item_id = int(item["id"])
            if item_id in processed_ids:
                continue

            if not item.get("_relations_loaded"):
                cached = _relation_cache.get(item_id)
                if cached is not None:
                    _apply_relation_details(item, cached)

            if not item.get("_relations_loaded") and not _search_relation_edges(item):
                if fetch_failures[item_id] < MAX_NODE_FETCH_RETRIES and can_fetch:
                    unresolved_remaining.append(item)
                continue

            processed_ids.add(item_id)

            for edge in _search_relation_edges(item):
                if not _traversal_edge_allowed(item, edge):
                    continue

                node = edge.get("node") or {}
                target_id = int(node["id"])
                if target_id in known_ids:
                    continue

                related = _related_placeholder(node)
                known_ids.add(target_id)
                discovered.append(related)
                next_frontier.append(related)

                if len(discovered) >= max_nodes:
                    break

            if len(discovered) >= max_nodes:
                break

        if len(discovered) >= max_nodes:
            break

        if unresolved_remaining and can_fetch:
            next_frontier.extend(unresolved_remaining)

        if not next_frontier:
            break

        frontier = next_frontier

    return discovered, requests_used


def _group_discovered(results, discovered):
    original_ids = {int(item["id"]) for item in results}
    ids = {int(item["id"]) for item in discovered}
    parent = {item_id: item_id for item_id in ids}

    def find(item_id):
        while parent[item_id] != item_id:
            parent[item_id] = parent[parent[item_id]]
            item_id = parent[item_id]
        return item_id

    def union(left, right):
        left, right = find(left), find(right)
        if left != right:
            parent[right] = left

    for item in discovered:
        item_id = int(item["id"])
        for edge in _search_relation_edges(item):
            if not _relation_edge_allowed(item, edge):
                continue
            target_id = int((edge.get("node") or {})["id"])
            if target_id in ids:
                union(item_id, target_id)

    by_key = {}
    for item in discovered:
        if not _is_bundleable(item):
            continue
        key = _series_group_key(item)
        item_id = int(item["id"])
        if key[1]:
            if key in by_key:
                union(item_id, by_key[key])
            else:
                by_key[key] = item_id

    groups = defaultdict(list)
    for item in discovered:
        groups[find(int(item["id"]))].append(item)

    first_position = {int(item["id"]): i for i, item in enumerate(results)}
    grouped = []
    represented_original_ids = set()

    for group_members in groups.values():
        group_members.sort(
            key=lambda item: (
                (item.get("startDate") or {}).get("year") is None,
                (item.get("startDate") or {}).get("year") or 9999,
                int(item["id"]),
            )
        )

        bundle_members = [
            item for item in group_members if _is_bundleable(item)
        ]
        visible_bundle_members = [
            item for item in bundle_members
            if int(item["id"]) in original_ids
        ]

        if visible_bundle_members and bundle_members:
            representative = dict(visible_bundle_members[0])
            representative["_series_count"] = len(bundle_members)
            representative["_series_members"] = bundle_members
            representative["_bundle_summary"] = _bundle_summary(bundle_members)
            grouped.append(
                (
                    min(
                        first_position.get(int(item["id"]), 10**9)
                        for item in bundle_members
                    ),
                    representative,
                )
            )
            represented_original_ids.update(
                int(item["id"]) for item in visible_bundle_members
            )

    for item in results:
        item_id = int(item["id"])
        if item_id in represented_original_ids:
            continue
        grouped.append(
            (
                first_position[item_id],
                {
                    **item,
                    "_series_count": 1,
                    "_series_members": [item],
                    "_bundle_summary": "",
                },
            )
        )

    grouped.sort(key=lambda pair: pair[0])
    return [item for _, item in grouped]


def group_media_results(results, enrich=False, max_requests=0, delay=0.25, stop_event=None):
    if not results:
        return []

    discovered, _ = _discover_related(
        results,
        max_requests=max_requests if enrich else -1,
        delay=delay,
        stop_event=stop_event,
    )
    return _group_discovered(results, discovered)


def has_pending_relation_enrichment(results):
    seen = set()
    queue = list(results)

    while queue:
        item = queue.pop(0)
        item_id = int(item["id"])
        if item_id in seen:
            continue
        seen.add(item_id)

        if item.get("_relations_loaded"):
            edges = _search_relation_edges(item)
        else:
            cached = _relation_cache.get(item_id)
            if cached:
                edges = (cached.get("relations") or {}).get("edges", [])
            elif item.get("_related_only"):
                return True
            else:
                edges = _search_relation_edges(item)

        for edge in edges:
            if not _relation_edge_allowed(item, edge):
                continue

            node = edge.get("node") or {}
            target_id = node.get("id")
            if (
                target_id
                and int(target_id) not in seen
                and int(target_id) not in _relation_cache
            ):
                queue.append(_related_placeholder(node))

    return False


def _relation_data_for(ids):
    if not ids:
        return []

    placeholders = ",".join("?" for _ in ids)
    relation_types = ",".join(repr(value) for value in SERIES_RELATIONS)
    connection = get_connection()

    rows = connection.execute(
        f"SELECT source_id, target_id, relation_type "
        f"FROM work_relations "
        f"WHERE relation_type IN ({relation_types}) "
        f"AND (source_id IN ({placeholders}) OR target_id IN ({placeholders}))",
        [*ids, *ids],
    ).fetchall()

    connection.close()
    return rows


def sync_library_relations():
    rows = list(get_all_library())
    if len(rows) < 2:
        return False

    ids = {int(row["id"]) for row in rows}
    existing_rows = _relation_data_for(ids)
    existing = (
        {int(row["source_id"]) for row in existing_rows}
        | {int(row["target_id"]) for row in existing_rows}
    )

    missing = ids - existing - _relation_sync_checked_ids
    changed = False

    for work_id in missing:
        try:
            details = get_media_details(work_id)
            _relation_sync_checked_ids.add(work_id)
            if details:
                save_anime(details)
                changed = True
        except Exception:
            continue

    return changed


def get_library_series():
    rows = list(get_all_library())
    if not rows:
        return []

    ids = {int(row["id"]) for row in rows}
    parent = {work_id: work_id for work_id in ids}

    def find(work_id):
        while parent[work_id] != work_id:
            parent[work_id] = parent[parent[work_id]]
            work_id = parent[work_id]
        return work_id

    def union(left, right):
        left, right = find(left), find(right)
        if left != right:
            parent[right] = left

    row_by_id = {int(row["id"]): row for row in rows}

    for relation in _relation_data_for(ids):
        source_id = int(relation["source_id"])
        target_id = int(relation["target_id"])
        source = row_by_id.get(source_id)
        target = row_by_id.get(target_id)

        if (
            source is not None
            and target is not None
            and _same_media_family(source, target)
            and _is_bundleable(source)
            and _is_bundleable(target)
        ):
            union(source_id, target_id)

    by_key = {}
    for row in rows:
        if not _is_bundleable(row):
            continue

        key = _series_group_key(row)
        if key[1]:
            work_id = int(row["id"])
            if key in by_key:
                union(work_id, by_key[key])
            else:
                by_key[key] = work_id

    groups = defaultdict(list)
    for row in rows:
        groups[find(int(row["id"]))].append(row)

    result = []
    for members in groups.values():
        members.sort(
            key=lambda row: (
                row["start_year"] is None,
                row["start_year"] or 9999,
                row["id"],
            )
        )

        group = dict(members[0])
        statuses = {row["status"] for row in members}
        group["status"] = (
            "Watching"
            if "Watching" in statuses
            else "Completed"
            if statuses and statuses == {"Completed"}
            else "Planning"
        )
        group["_series_count"] = len(members)
        group["_series_members"] = members
        group["_series_episode_total"] = sum(
            int(row["episodes"] or 0) for row in members
        )
        group["_series_progress"] = sum(
            int(row["progress_episodes"] or 0) for row in members
        )
        group["_bundle_summary"] = _bundle_summary(members)
        result.append(group)

    return result
