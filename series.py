from collections import defaultdict
import re
import time

from api import get_media_details, get_media_relations_batch
from database import get_all_library, get_connection, save_anime

SERIES_RELATIONS = {
    "PREQUEL", "SEQUEL", "PARENT", "SIDE_STORY", "SUMMARY",
    "FULL_STORY", "SPIN_OFF", "ALTERNATIVE",
}
ANIME_BUNDLE_FORMATS = {"TV", "TV_SHORT", "MOVIE", "OVA", "ONA", "SPECIAL"}
RELATION_BATCH_SIZE = 25
_relation_sync_checked_ids = set()
_relation_cache = {}
_relation_cache_failures = set()


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
    value = re.sub(r"\s*[:\-–—]?\s*(the\s+)?final\s+season(?:\s+part\s+\d+)?\s*$", "", value)
    value = re.sub(r"\s*[:\-–—]?\s*(?:season|series)\s*(?:\d+|[ivx]+)(?:\s+part\s+\d+)?\s*$", "", value)
    value = re.sub(r"\s*[:\-–—]?\s*(?:part|cour)\s*\d+\s*$", "", value)
    value = re.sub(r"\s+(?:i|ii|iii|iv|v|vi|1st|2nd|3rd|4th|5th)\s*(?:season)?\s*$", "", value)
    value = re.sub(r"\s+\d+$", "", value)
    return re.sub(r"[^a-z0-9]+", " ", value).strip()


def _series_group_key(item):
    return _media_family(item), _series_key(_title_text(item))


def _season_group_key(item):
    title = _title_text(item).lower()
    if re.search(r"\bfinal\s+season\b", title):
        return "final"

    ordinal = re.search(r"\b(\d+)(?:st|nd|rd|th)\s+season\b", title)
    if ordinal:
        return f"season-{int(ordinal.group(1))}"

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

    return "season-1"


def _bundle_summary(members):
    if len(members) <= 1:
        return ""

    counts = defaultdict(int)
    logical_seasons = set()
    for member in members:
        fmt = str(member.get("format") or "").upper() if hasattr(member, "get") else str(member["format"] or "").upper()
        if fmt in {"TV", "TV_SHORT"}:
            logical_seasons.add(_season_group_key(member))
        elif fmt == "OVA":
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
        counts["seasons"] = len(logical_seasons)
    order = ["seasons", "OVAs", "ONAs", "movies", "specials", "music"]
    parts = [f"{counts[key]} {key}" for key in order if counts[key]]
    parts.extend(f"{count} {key}" for key, count in counts.items() if key not in order)
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
    """Only traverse through entries that can actually participate in a bundle."""
    return _bundle_edge_allowed(item, edge)


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
    missing = [media_id for media_id in ids if media_id not in _relation_cache and media_id not in _relation_cache_failures]
    if not missing:
        return {media_id: _relation_cache[media_id] for media_id in ids if media_id in _relation_cache}

    try:
        fetched = get_media_relations_batch(missing)
    except Exception:
        return {media_id: _relation_cache[media_id] for media_id in ids if media_id in _relation_cache}

    for media_id in missing:
        details = fetched.get(media_id)
        if details is None:
            _relation_cache_failures.add(media_id)
        else:
            _relation_cache[media_id] = details

    return {media_id: _relation_cache[media_id] for media_id in ids if media_id in _relation_cache}


def _discover_related(items, max_nodes=1000, max_requests=0, delay=0.25, stop_event=None):
    """Finite breadth-first traversal of the bundleable relation graph.

    max_requests meanings:
      -1: never perform network relation fetches (fast UI grouping)
       0: unlimited fetches (background enrichment)
      >0: cap fetches at that number
    """
    discovered = list(items)
    known_ids = {int(item["id"]) for item in discovered}
    frontier = list(discovered)
    processed_ids = set()
    requests_used = 0

    while frontier and len(discovered) < max_nodes:
        if stop_event is not None and stop_event.is_set():
            break

        unresolved = []
        for item in frontier:
            item_id = int(item["id"])
            if item_id in processed_ids:
                continue
            if item.get("_relations_loaded") or _search_relation_edges(item) or item_id in _relation_cache:
                continue
            if item_id in _relation_cache_failures:
                continue
            unresolved.append(item)

        can_fetch = max_requests == 0 or (max_requests > 0 and requests_used < max_requests)
        loaded_this_round = 0
        if unresolved and can_fetch:
            for start in range(0, len(unresolved), RELATION_BATCH_SIZE):
                if stop_event is not None and stop_event.is_set():
                    break
                if max_requests > 0 and requests_used >= max_requests:
                    break

                batch = unresolved[start:start + RELATION_BATCH_SIZE]
                fetched = _cache_relation_details_batch([item["id"] for item in batch])
                requests_used += 1

                for item in batch:
                    details = fetched.get(int(item["id"]))
                    if details is not None:
                        _apply_relation_details(item, details)
                        loaded_this_round += 1

                if delay > 0 and start + RELATION_BATCH_SIZE < len(unresolved):
                    time.sleep(delay)

        next_frontier = []
        unresolved_remaining = 0
        for item in frontier:
            item_id = int(item["id"])
            if item_id in processed_ids:
                continue

            if not item.get("_relations_loaded") and not _search_relation_edges(item):
                cached = _relation_cache.get(item_id)
                if cached is not None:
                    _apply_relation_details(item, cached)

            if not item.get("_relations_loaded") and not _search_relation_edges(item):
                unresolved_remaining += 1
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

        if not next_frontier:
            break

        # In capped mode an unresolved node stays unresolved instead of being
        # treated as completed; a later enrichment pass can retry it.
        if unresolved_remaining and loaded_this_round == 0 and max_requests != 0:
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
            if not _bundle_edge_allowed(item, edge):
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
    for group_members in groups.values():
        group_members.sort(
            key=lambda item: (
                (item.get("startDate") or {}).get("year") is None,
                (item.get("startDate") or {}).get("year") or 9999,
                int(item["id"]),
            )
        )
        visible = [item for item in group_members if int(item["id"]) in original_ids]
        if not visible:
            continue
        representative = dict(visible[0])
        representative["_series_count"] = len(group_members)
        representative["_series_members"] = group_members
        representative["_bundle_summary"] = _bundle_summary(group_members)
        grouped.append((min(first_position.get(int(item["id"]), 10**9) for item in group_members), representative))
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
            if target_id and int(target_id) not in seen and int(target_id) not in _relation_cache:
                queue.append(_related_placeholder(node))
    return False


def _relation_data_for(ids):
    if not ids:
        return []
    placeholders = ",".join("?" for _ in ids)
    relation_types = ",".join(repr(value) for value in SERIES_RELATIONS)
    connection = get_connection()
    rows = connection.execute(
        f"SELECT source_id, target_id, relation_type FROM work_relations WHERE relation_type IN ({relation_types}) AND (source_id IN ({placeholders}) OR target_id IN ({placeholders}))",
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
    existing = {int(row["source_id"]) for row in existing_rows} | {int(row["target_id"]) for row in existing_rows}
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
        source_id, target_id = int(relation["source_id"]), int(relation["target_id"])
        source = row_by_id.get(source_id)
        target = row_by_id.get(target_id)
        if source is not None and target is not None and _same_media_family(source, target) and _is_bundleable(source) and _is_bundleable(target):
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
        members.sort(key=lambda row: (row["start_year"] is None, row["start_year"] or 9999, row["id"]))
        group = dict(members[0])
        statuses = {row["status"] for row in members}
        group["status"] = "Watching" if "Watching" in statuses else "Completed" if statuses and statuses == {"Completed"} else "Planning"
        group["_series_count"] = len(members)
        group["_series_members"] = members
        group["_series_episode_total"] = sum(int(row["episodes"] or 0) for row in members)
        group["_series_progress"] = sum(int(row["progress_episodes"] or 0) for row in members)
        group["_bundle_summary"] = _bundle_summary(members)
        result.append(group)
    return result
