from collections import defaultdict
import re


def _count_marker(title, series_module):
    """Use explicit season markers, but do not treat a bare trailing number as one."""
    title = title or ""
    marker_title = re.sub(r"(?:^|[\s:])([2-9])\s*$", "", title)
    return series_module._season_marker(marker_title)


def logical_season_count(members, series_module):
    """Count TV seasons without collapsing unrelated named arcs."""
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

    # Explicit season labels are authoritative. Parts/cours of the same
    # labeled season therefore remain one logical season.
    by_marker = defaultdict(list)
    for member in tv_members:
        marker = _count_marker(series_module._title_text(member), series_module)
        if marker:
            by_marker[marker].append(int(member["id"]))

    for ids_for_marker in by_marker.values():
        first = ids_for_marker[0]
        for media_id in ids_for_marker[1:]:
            union(first, media_id)

    # Only explicit continuations can inherit a neighboring season identity.
    # Never merge two different explicit markers. Unnumbered Part/Cour entries
    # may merge with an unnumbered neighboring base entry, e.g. Boruto Part 2.
    for member in tv_members:
        member_id = int(member["id"])
        title = series_module._title_text(member)
        if not series_module._is_continuation_title(title):
            continue

        current_marker = _count_marker(title, series_module)
        for edge in series_module._search_relation_edges(member):
            if edge.get("relationType") not in {"PREQUEL", "SEQUEL"}:
                continue

            target = edge.get("node") or {}
            target_id = target.get("id")
            if target_id is None:
                continue
            target_id = int(target_id)
            if target_id not in by_id:
                continue

            target_title = series_module._title_text(by_id[target_id])
            target_marker = _count_marker(target_title, series_module)

            if current_marker == target_marker:
                union(member_id, target_id)
            elif current_marker is None and target_marker is None:
                union(member_id, target_id)

    return len({find(media_id) for media_id in ids})


def patch_series(series_module):
    series_module._bundle_logical_season_count = lambda members: logical_season_count(
        members, series_module
    )
