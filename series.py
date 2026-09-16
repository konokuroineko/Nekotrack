from collections import defaultdict
import re

from api import get_media_details
from database import get_all_library, get_connection, save_anime

SERIES_RELATIONS = {"PREQUEL", "SEQUEL", "PARENT", "SIDE_STORY", "SUMMARY", "FULL_STORY", "SPIN_OFF"}
_relation_sync_checked_ids = set()


def _series_key(title):
    value = (title or "").lower().strip()
    value = re.sub(r"\s*[:\-–—]?\s*(the\s+)?final\s+season(?:\s+part\s+\d+)?\s*$", "", value)
    value = re.sub(r"\s*[:\-–—]?\s*(?:season|series)\s*(?:\d+|[ivx]+)(?:\s+part\s+\d+)?\s*$", "", value)
    value = re.sub(r"\s*[:\-–—]?\s*(?:part|cour)\s*\d+\s*$", "", value)
    value = re.sub(r"\s+(?:i|ii|iii|iv|v|vi|1st|2nd|3rd|4th|5th)\s*(?:season)?\s*$", "", value)
    value = re.sub(r"\s+\d+$", "", value)
    return re.sub(r"[^a-z0-9]+", " ", value).strip()


def _media_type(item):
    value = item.get("type") if hasattr(item, "get") else item["type"]
    return str(value or "UNKNOWN").upper()


def _media_family(item):
    """Keep Anime, Manga, Novel, and One Shot as separate grouping families."""
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


def _series_group_key(item):
    title = _title_text(item) if hasattr(item, "get") else item["title"]
    return _media_family(item), _series_key(title)


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
    return "season-1"


def _bundle_summary(members):
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
    return " · ".join(
        [f"{counts[key]} {key}" for key in order if counts[key]]
        + [f"{count} {key}" for key, count in counts.items() if key not in order]
    )


def _title_text(item):
    title = item.get("title") or {} if hasattr(item, "get") else item["title"] or {}
    return title.get("english") or title.get("romaji") or title.get("native") or "" if isinstance(title, dict) else str(title)


def _search_relation_edges(item):
    return (item.get("relations") or {}).get("edges", [])


def _related_placeholder(node):
    return {
        "id": int(node["id"]),
        "type": node.get("type"),
        "format": node.get("format"),
        "title": node.get("title") or {},
        "coverImage": node.get("coverImage") or {},
        "_related_only": True,
    }


def _discover_related(items, max_nodes=80):
    discovered = list(items)
    known_ids = {int(item["id"]) for item in discovered}
    queue = list(discovered)
    fetched_ids = set()
    while queue and len(discovered) < max_nodes:
        item = queue.pop(0)
        item_id = int(item["id"])
        if item_id not in fetched_ids:
            fetched_ids.add(item_id)
            try:
                details = get_media_details(item_id)
                if details:
                    item["relations"] = details.get("relations") or {}
                    item["type"] = details.get("type") or item.get("type")
                    item["format"] = details.get("format") or item.get("format")
                    item["title"] = details.get("title") or item.get("title") or {}
                    item["coverImage"] = details.get("coverImage") or item.get("coverImage") or {}
                    item["episodes"] = details.get("episodes") or item.get("episodes")
            except Exception:
                pass
        item_family = _media_family(item)
        for edge in _search_relation_edges(item):
            if edge.get("relationType") not in SERIES_RELATIONS:
                continue
            node = edge.get("node") or {}
            target_id = node.get("id")
            if not target_id:
                continue
            target_id = int(target_id)
            if target_id in known_ids or _media_family(node) != item_family:
                continue
            related = _related_placeholder(node)
            known_ids.add(target_id)
            discovered.append(related)
            queue.append(related)
    return discovered


def group_media_results(results):
    """Group search hits into separate media-family series bundles."""
    if not results:
        return []
    original_ids = {int(item["id"]) for item in results}
    members = _discover_related(results)
    ids = {int(item["id"]) for item in members}
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

    for item in members:
        item_id = int(item["id"])
        for edge in _search_relation_edges(item):
            if edge.get("relationType") not in SERIES_RELATIONS:
                continue
            target = edge.get("node") or {}
            target_id = target.get("id")
            if not target_id:
                continue
            target_id = int(target_id)
            if target_id in ids and _same_media_family(item, target):
                union(item_id, target_id)

    by_key = {}
    for item in members:
        key = _series_group_key(item)
        item_id = int(item["id"])
        if key[1]:
            if key in by_key:
                union(item_id, by_key[key])
            else:
                by_key[key] = item_id

    groups = defaultdict(list)
    for item in members:
        groups[find(int(item["id"]))].append(item)

    first_position = {int(item["id"]): i for i, item in enumerate(results)}
    grouped = []
    for group_members in groups.values():
        group_members.sort(key=lambda item: ((item.get("startDate") or {}).get("year") is None, (item.get("startDate") or {}).get("year") or 9999, int(item["id"])))
        visible = [item for item in group_members if int(item["id"]) in original_ids]
        representative = dict(visible[0] if visible else group_members[0])
        representative["_series_count"] = len(group_members)
        representative["_series_members"] = group_members
        representative["_bundle_summary"] = _bundle_summary(group_members)
        grouped.append((min(first_position.get(int(item["id"]), 10**9) for item in group_members), representative))
    grouped.sort(key=lambda pair: pair[0])
    return [item for _, item in grouped]


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

    for relation in _relation_data_for(ids):
        source_id, target_id = int(relation["source_id"]), int(relation["target_id"])
        if source_id in ids and target_id in ids:
            source = next((row for row in rows if int(row["id"]) == source_id), None)
            target = next((row for row in rows if int(row["id"]) == target_id), None)
            if source is not None and target is not None and _same_media_family(source, target):
                union(source_id, target_id)

    by_key = {}
    for row in rows:
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
