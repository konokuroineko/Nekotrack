from collections import OrderedDict, defaultdict, deque
from threading import RLock
import re
import time

from api import get_media_relations_batch
from diagnostics import diagnostic_context, log_event, log_exception
from database import (
    get_all_library,
    get_bundle_override,
    get_bundle_overrides,
    get_bundle_exclusions,
    get_library_bundle_grouping_state,
    get_connection,
    get_manual_bundle_links,
    save_anime,
    save_automatic_bundle_membership,
)
from ui.preferences import get


SERIES_RELATIONS = {
    "PREQUEL", "SEQUEL", "PARENT", "SIDE_STORY", "SUMMARY",
    "FULL_STORY", "SPIN_OFF", "ALTERNATIVE", "COMPILATION", "CONTAINS",
}
# These relations describe the actual season/continuation chain. Traversal is
# intentionally restricted to them so a TV-catalog search cannot spend its
# global discovery budget walking huge spin-off/alternative graphs first.
SEASON_CHAIN_RELATIONS = {"PREQUEL", "SEQUEL", "PARENT", "SUMMARY", "SIDE_STORY"}
# These relation types can contain legitimate franchise entries that are not
# part of the main season chain. Traverse them only when the titles identify
# the same series family, preventing unrelated spin-offs from being absorbed.
RELATED_TRAVERSAL_RELATIONS = {
    "SPIN_OFF", "ALTERNATIVE", "COMPILATION", "FULL_STORY", "CONTAINS",
}


def _build_exclusion_neighbors(excluded_links):
    """Build an undirected lookup for user-defined bundle exclusions."""
    neighbors = defaultdict(set)
    for left_id, right_id in excluded_links or ():
        neighbors[left_id].add(right_id)
        neighbors[right_id].add(left_id)
    return neighbors


def _components_have_excluded_pair(left_members, right_members, excluded_neighbors):
    """Check cross-component exclusions without scanning every member pair."""
    if not excluded_neighbors:
        return False
    if len(left_members) > len(right_members):
        left_members, right_members = right_members, left_members
    return any(
        not excluded_neighbors.get(member_id, set()).isdisjoint(right_members)
        for member_id in left_members
    )
ANIME_BUNDLE_FORMATS = {"TV", "TV_SHORT", "MOVIE", "OVA", "ONA", "SPECIAL"}
RELATION_BATCH_SIZE = 10
MAX_NODE_FETCH_RETRIES = 3

_relation_sync_checked_ids = set()
RELATION_CACHE_MAX_ENTRIES = 5000


class _BoundedRelationCache(OrderedDict):
    """Small LRU cache so relation graphs from old Search sessions are released."""

    def __init__(self, max_entries=RELATION_CACHE_MAX_ENTRIES):
        super().__init__()
        self.max_entries = max(1, int(max_entries))
        self._lock = RLock()

    def __contains__(self, key):
        with self._lock:
            return super().__contains__(key)

    def __getitem__(self, key):
        with self._lock:
            value = super().__getitem__(key)
            super().move_to_end(key)
            return value

    def get(self, key, default=None):
        # Membership, lookup and LRU promotion must be atomic: concurrent
        # relation-enrichment workers can otherwise evict a key between them.
        with self._lock:
            try:
                value = super().__getitem__(key)
            except KeyError:
                return default
            super().move_to_end(key)
            return value

    def __setitem__(self, key, value):
        with self._lock:
            super().__setitem__(key, value)
            super().move_to_end(key)
            while len(self) > self.max_entries:
                super().popitem(last=False)

    def __delitem__(self, key):
        with self._lock:
            super().__delitem__(key)

    def __iter__(self):
        # Iterating a live OrderedDict while a worker updates it raises
        # RuntimeError. Iterate a stable key snapshot under the same lock.
        with self._lock:
            keys = tuple(super().__iter__())
        return iter(keys)

    def __len__(self):
        with self._lock:
            return super().__len__()

    def clear(self):
        with self._lock:
            super().clear()

    def pop(self, key, *default):
        with self._lock:
            return super().pop(key, *default)

    def popitem(self, last=True):
        with self._lock:
            return super().popitem(last=last)

    def move_to_end(self, key, last=True):
        with self._lock:
            return super().move_to_end(key, last=last)

    def copy(self):
        with self._lock:
            duplicate = type(self)(self.max_entries)
            for key, value in super().items():
                duplicate[key] = value
            return duplicate


_relation_cache = _BoundedRelationCache()



def _merge_component_roots(
    parent, component_members, left_root, right_root, component_snapshot_ids=None
):
    """Merge disjoint-set roots small-to-large to bound repeated set copying."""
    left_members = component_members[left_root]
    right_members = component_members[right_root]
    if len(left_members) < len(right_members):
        left_root, right_root = right_root, left_root
        left_members, right_members = right_members, left_members

    moved_member_count = len(right_members)
    parent[right_root] = left_root
    left_members.update(component_members.pop(right_root))
    if component_snapshot_ids is not None:
        component_snapshot_ids[left_root].update(
            component_snapshot_ids.pop(right_root)
        )
    return left_root, moved_member_count



def _get(item, key, default=None):
    """Read a field from either an AniList dict or a sqlite3.Row."""
    if hasattr(item, "get"):
        try:
            return item.get(key, default)
        except (TypeError, ValueError, AttributeError):
            return default
    try:
        return item[key]
    except (KeyError, IndexError, TypeError):
        return default


def _valid_relation_id(value):
    """Return a provider/local ID in range, or None for malformed IDs."""
    if isinstance(value, bool):
        return None
    if isinstance(value, float):
        if not value.is_integer():
            return None
    if isinstance(value, str) and (
        len(value.strip()) > 20
        or not value.strip().isascii()
        or not re.fullmatch(r"[+-]?[0-9]+", value.strip())
    ):
        return None
    try:
        media_id = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if media_id == 0 or media_id > (1 << 31) - 1 or media_id < -((1 << 63) - 1):
        return None
    return media_id


def _title_text(item):
    title = _get(item, "title") or {}
    if isinstance(title, dict):
        value = title.get("english") or title.get("romaji") or title.get("native") or ""
        return str(value or "")
    return str(title or "")


def _media_type(item):
    value = _get(item, "type")
    return str(value or "UNKNOWN").upper()


def _media_family(item):
    media_type = _media_type(item)
    fmt = str(_get(item, "format") or "").upper()
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
    fmt = str(_get(item, "format") or "").upper()
    if family == "ANIME":
        return fmt in ANIME_BUNDLE_FORMATS
    if family == "MANGA":
        return fmt == "MANGA"
    if family in {"NOVEL", "ONE_SHOT"}:
        return True
    return False

def _auto_bundleable(item):
    """Return whether an entry is eligible for automatic series bundling.

    TV seasons and TV shorts are always part of the main series chain.
    Related formats outside that chain are opt-in individually so users can,
    for example, include OVAs without pulling every movie, special, or manga
    entry into the same automatic bundle.
    """
    if not _is_bundleable(item):
        return False

    media_family = _media_family(item)
    media_format = str(_get(item, "format") or "").upper()

    if media_family == "ANIME":
        if media_format in {"TV", "TV_SHORT"}:
            return True
        option_by_format = {
            "MOVIE": "bundle_include_movies",
            "OVA": "bundle_include_ovas",
            "ONA": "bundle_include_onas",
            "SPECIAL": "bundle_include_specials",
        }
        option = option_by_format.get(media_format)
        return bool(get(option)) if option else False

    option_by_family = {
        "MANGA": "bundle_include_manga",
        "NOVEL": "bundle_include_novels",
        "ONE_SHOT": "bundle_include_one_shots",
    }
    option = option_by_family.get(media_family)
    return bool(get(option)) if option else False


def _series_key(title):
    value = str(title or "").lower().strip()
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


def _prefix_related_tv_candidate_indices(keys):
    """Index title-prefix candidates without comparing every pair of TV titles.

    Return tokenized keys and, for each original position, sorted original
    indices whose two-or-more tokens are a prefix of each other. Sorting each
    candidate list preserves the old nested loop's comparison order, which
    matters because bundle exclusions can make union order observable.
    """
    tokens_by_index = [
        tuple(str(key or "").split())
        for key in (keys or [])
    ]
    exact_by_tokens = defaultdict(list)
    by_prefix = defaultdict(list)

    for index, tokens in enumerate(tokens_by_index):
        if len(tokens) < 2:
            continue
        exact_by_tokens[tokens].append(index)
        for prefix_length in range(2, len(tokens) + 1):
            by_prefix[tokens[:prefix_length]].append(index)

    candidates_by_index = []
    for index, tokens in enumerate(tokens_by_index):
        if len(tokens) < 2:
            candidates_by_index.append([])
            continue

        matching_indices = set()
        # Titles that are the same as, or shorter prefixes of, this title.
        for prefix_length in range(2, len(tokens) + 1):
            matching_indices.update(exact_by_tokens.get(tokens[:prefix_length], ()))
        # Titles for which this title is itself a prefix.
        matching_indices.update(by_prefix.get(tokens, ()))
        matching_indices.discard(index)
        candidates_by_index.append(sorted(matching_indices))

    return tokens_by_index, candidates_by_index


def _series_group_key(item):
    return _media_family(item), _series_key(_title_text(item))


def _title_family_compatible(left, right):
    """Return whether two anime titles identify the same named series family."""
    left_key = _series_key(_title_text(left))
    right_key = _series_key(_title_text(right))
    if not left_key or not right_key:
        return False

    if left_key == right_key:
        return True

    left_tokens = left_key.split()
    right_tokens = right_key.split()

    left_token_set = set(left_tokens)
    right_token_set = set(right_tokens)
    if left_token_set and right_token_set and (
        left_token_set <= right_token_set or right_token_set <= left_token_set
    ):
        return True

    shorter, longer = (
        (left_tokens, right_tokens)
        if len(left_tokens) <= len(right_tokens)
        else (right_tokens, left_tokens)
    )
    if len(shorter) >= 2 and longer[:len(shorter)] == shorter:
        return True

    common_prefix = 0
    for left, right in zip(left_tokens, right_tokens):
        if left != right:
            break
        common_prefix += 1
    return common_prefix >= 2


# Season counting belongs to the series bundling system. Keeping it here
# avoids a second module for logic that is only used to summarize bundles.


def _season_marker(title):
    """Return only an explicit season identity, never a bare Part/Cour number."""
    title = str(title or "").lower()

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
        values = {"i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5, "vi": 6}
        return f"season-{values[roman_suffix.group(1)]}"

    if not re.search(r"\b(?:part|cour)\s*[0-9]+\s*$", title):
        bare_number = re.search(r"(?:^|[\s:])([2-9])\s*$", title)
        if bare_number:
            return f"season-{int(bare_number.group(1))}"

    return None


def _is_continuation(title):
    title = str(title or "").lower()
    return bool(
        re.search(r"\b(?:part|cour)\s*(?:\d+|i|ii|iii|iv|v|vi)\b", title)
        or re.search(r"\bfinal\s+season\b", title)
    )


def _is_arc(title):
    return bool(re.search(r"\barc\b", str(title or "").lower()))


def _air_period(member):
    start = _get(member, "startDate")
    if not isinstance(start, dict):
        start = {}
    year = start.get("year")
    month = start.get("month")
    if year is None:
        year = _get(member, "start_year")
    if isinstance(year, bool) or isinstance(month, bool):
        return None
    try:
        year = int(year)
        month = int(month)
    except (TypeError, ValueError, OverflowError):
        return None
    if not (1 <= year <= 9999 and 1 <= month <= 12):
        return None
    return (year, (month - 1) // 3)


def logical_season_count(members):
    """Count logical TV seasons while tolerating malformed optional relation data."""
    tv_members = [
        member for member in members
        if str(_get(member, "format") or "").upper() in {"TV", "TV_SHORT"}
        and _valid_relation_id(_get(member, "id")) is not None
    ]
    if not tv_members:
        return 0

    by_id = {_valid_relation_id(_get(member, "id")): member for member in tv_members}
    ids = set(by_id)
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

    # 1. Explicit season labels are authoritative.
    by_marker = defaultdict(list)
    for media_id, member in by_id.items():
        marker = _season_marker(_title_text(member))
        if marker:
            by_marker[marker].append(media_id)
    for members_for_marker in by_marker.values():
        for media_id in members_for_marker[1:]:
            union(members_for_marker[0], media_id)

    # 2. Part/Cour/final continuations inherit directly connected neighbors,
    #    but never cross two explicit, conflicting season markers.
    for member_id, member in by_id.items():
        title = _title_text(member)
        if not _is_continuation(title):
            continue
        current_marker = _season_marker(title)
        for edge in _search_relation_edges(member):
            if edge.get("relationType") not in {"PREQUEL", "SEQUEL"}:
                continue
            node = edge.get("node")
            if not isinstance(node, dict):
                continue
            target_id = _valid_relation_id(node.get("id"))
            if target_id is None or target_id not in by_id:
                continue
            target_marker = _season_marker(_title_text(by_id[target_id]))
            if current_marker is not None and target_marker is not None:
                if current_marker == target_marker:
                    union(member_id, target_id)
            elif current_marker is None and target_marker is None:
                union(member_id, target_id)

    # 3. Named unnumbered arcs only combine when both have a valid, matching
    #    airing season. Unknown dates are not evidence that two arcs are equal.
    arc_ids = {
        media_id for media_id, member in by_id.items()
        if _is_arc(_title_text(member))
        and _season_marker(_title_text(member)) is None
        and not _is_continuation(_title_text(member))
    }
    for member_id in arc_ids:
        member_period = _air_period(by_id[member_id])
        if member_period is None:
            continue
        for edge in _search_relation_edges(by_id[member_id]):
            if edge.get("relationType") not in {"PREQUEL", "SEQUEL"}:
                continue
            node = edge.get("node")
            if not isinstance(node, dict):
                continue
            target_id = _valid_relation_id(node.get("id"))
            if target_id is None or target_id not in arc_ids:
                continue
            target_period = _air_period(by_id[target_id])
            if target_period is not None and member_period == target_period:
                union(member_id, target_id)

    return len({find(media_id) for media_id in ids})

def _bundle_logical_season_count(members):
    return logical_season_count(members)


def _bundle_summary(members):
    if len(members) <= 1:
        return ""

    counts = defaultdict(int)
    logical_seasons = _bundle_logical_season_count(members)
    for member in members:
        fmt = str(_get(member, "format") or "").upper()
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
    relations = _get(item, "relations")
    if not isinstance(relations, dict):
        return []
    edges = relations.get("edges")
    if not isinstance(edges, (list, tuple)):
        return []
    return [edge for edge in edges if isinstance(edge, dict)]


def _relation_edge_allowed(item, edge):
    if not isinstance(edge, dict) or edge.get("relationType") not in SERIES_RELATIONS:
        return False
    node = edge.get("node")
    if not isinstance(node, dict):
        return False
    if _valid_relation_id(node.get("id")) is None:
        return False
    return _same_media_family(item, node)


def _bundle_edge_allowed(item, edge):
    if not _relation_edge_allowed(item, edge):
        return False
    return _is_bundleable(item) and _is_bundleable(edge.get("node") or {})


def _relation_group_compatible(item, edge, target):
    """Avoid pulling unrelated cross-format works into a series bundle.

    AniList can use PREQUEL/SEQUEL/SIDE_STORY for franchise-level connections
    that are not actually part of the same display bundle. Same-format
    continuations remain trusted; cross-format entries must also share the
    meaningful title identity (for example "Attack on Titan" -> "... No
    Regrets"), which blocks unrelated entries such as ONE PIECE -> MONSTERS.
    """
    if not _relation_edge_allowed(item, edge):
        return False
    if not _auto_bundleable(item) or not _auto_bundleable(target):
        return False

    source_format = str(_get(item, "format") or "").upper()
    target_format = str(_get(target, "format") or "").upper()
    relation_type = edge.get("relationType")

    if relation_type in RELATED_TRAVERSAL_RELATIONS:
        return _title_family_compatible(item, target)

    if source_format == target_format:
        return True

    # AniList's SIDE_STORY, SUMMARY, and PARENT relations are explicit
    # franchise-membership signals. Keep them across anime formats
    # (TV/OVA/movie/special/ONA) instead of requiring title-token overlap.
    # This is needed for entries whose proper subtitle does not repeat the
    # main title. PREQUEL/SEQUEL still use title compatibility to avoid
    # unrelated franchise-level links such as ONE PIECE -> MONSTERS.
    if relation_type in {"SIDE_STORY", "SUMMARY", "PARENT"}:
        return True

    source_key = _series_key(_title_text(item))
    target_key = _series_key(_title_text(target))
    if not source_key or not target_key:
        return False

    if source_key == target_key:
        return True

    source_tokens = set(source_key.split())
    target_tokens = set(target_key.split())
    if source_tokens and target_tokens and (
        source_tokens <= target_tokens or target_tokens <= source_tokens
    ):
        return True

    # Some legitimate sequels change the subtitle completely when moving
    # from a TV season to a movie trilogy (for example Demon Slayer's
    # Hashira Training Arc -> Infinity Castle). Treat a shared ordered title
    # prefix of at least two meaningful tokens as the same series identity.
    source_words = source_key.split()
    target_words = target_key.split()
    common_prefix = 0
    for left, right in zip(source_words, target_words):
        if left != right:
            break
        common_prefix += 1
    return common_prefix >= 2


def _traversal_edge_allowed(item, edge):
    """Walk season chains and carefully include named series extras."""
    if not isinstance(edge, dict):
        return False
    relation_type = edge.get("relationType")
    node = edge.get("node")
    if not isinstance(node, dict) or _valid_relation_id(node.get("id")) is None:
        return False
    if not _same_media_family(item, node):
        return False
    if not _auto_bundleable(item) or not _auto_bundleable(node):
        return False

    if relation_type in SEASON_CHAIN_RELATIONS:
        return True

    if relation_type not in RELATED_TRAVERSAL_RELATIONS:
        return False

    # Extra relations such as Spin Off and Alternative can point outside the
    # actual series. Only traverse them when the names still identify the same
    # series family. This catches entries such as Re:Zero -> Break Time while
    # avoiding unrelated franchise spin-offs.
    return _title_family_compatible(item, node)


def _related_placeholder(node):
    return {
        "id": int(node["id"]),
        "idMal": node.get("idMal"),
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
    item["type"] = details.get("type") or _get(item, "type")
    item["format"] = details.get("format") or _get(item, "format")
    item["title"] = details.get("title") or _get(item, "title") or {}
    item["coverImage"] = details.get("coverImage") or _get(item, "coverImage") or {}
    if details.get("idMal") is not None:
        item["idMal"] = details["idMal"]
    if details.get("episodes") is not None:
        item["episodes"] = details["episodes"]
    item["startDate"] = details.get("startDate") or _get(item, "startDate") or {}
    item["_relations_loaded"] = True


def _cache_relation_details_batch(media_ids):
    """Fetch uncached relation graphs without fanning out failed provider batches."""
    ids = sorted({int(media_id) for media_id in media_ids if media_id is not None})
    result_for_call = {}
    for media_id in ids:
        cached = _relation_cache.get(media_id)
        if cached is not None:
            result_for_call[media_id] = cached
    missing = [media_id for media_id in ids if media_id not in result_for_call]
    if not missing:
        return result_for_call

    # Keep the AniList request and local MangaBaka resolutions independent.
    # A transient AniList failure must not prevent negative-ID entries from
    # loading, and must not recursively turn one failed request into N requests.
    provider_groups = (
        ("anilist", [media_id for media_id in missing if media_id > 0]),
        ("mangabaka", [media_id for media_id in missing if media_id < 0]),
    )
    for provider, group_ids in provider_groups:
        if not group_ids:
            continue
        requested = set(group_ids)
        try:
            fetched = get_media_relations_batch(group_ids)
        except Exception as error:
            # _discover_related already retries unresolved IDs a bounded number
            # of times. Keep the batch intact here rather than recursively
            # issuing one request per member during a shared outage.
            log_event(
                "bundling.relation_batch_failed",
                provider=provider,
                error_type=type(error).__name__,
                error=str(error)[:300],
                requested_count=len(group_ids),
                requested_ids=group_ids[:50],
            )
            continue
        if not isinstance(fetched, dict):
            log_event(
                "bundling.relation_batch_malformed",
                provider=provider,
                returned_type=type(fetched).__name__,
                requested_count=len(group_ids),
            )
            continue

        for raw_id, details in fetched.items():
            try:
                media_id = int(raw_id)
            except (TypeError, ValueError, OverflowError):
                continue
            if media_id in requested and details is not None:
                # Keep all results in this call even if inserting later entries
                # evicts an earlier graph from the bounded cross-search cache.
                _relation_cache[media_id] = details
                result_for_call[media_id] = details

    return {
        media_id: result_for_call[media_id]
        for media_id in ids
        if media_id in result_for_call
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

            if _get(item, "_relations_loaded"):
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

            if not _get(item, "_relations_loaded"):
                cached = _relation_cache.get(item_id)
                if cached is not None:
                    _apply_relation_details(item, cached)

            if not _get(item, "_relations_loaded") and not _search_relation_edges(item):
                if fetch_failures[item_id] < MAX_NODE_FETCH_RETRIES and can_fetch:
                    unresolved_remaining.append(item)
                continue

            processed_ids.add(item_id)

            for edge in _search_relation_edges(item):
                if not _traversal_edge_allowed(item, edge):
                    continue

                node = edge.get("node") or {}
                target_id = int(_get(node, "id"))
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

    log_event(
        "bundling.relation_discovery",
        seed_count=len(items),
        discovered_count=len(discovered),
        request_batches=requests_used,
        processed_nodes=len(processed_ids),
        failed_node_ids=sorted(fetch_failures)[:100],
        failed_node_count=len(fetch_failures),
        stopped_by_event=bool(stop_event is not None and stop_event.is_set()),
        hit_node_limit=len(discovered) >= max_nodes,
        request_limit=max_requests,
    )
    return discovered, requests_used


def _apply_bundle_override(group, members, overrides_by_anchor=None):
    """Apply the persisted title and cover choice shared by all bundle cards."""
    safe_members = [
        member for member in (members or [])
        if _valid_relation_id(_get(member, "id")) is not None
    ]
    if len(safe_members) <= 1:
        return group
    member_ids = [int(_get(member, "id")) for member in safe_members]
    try:
        if overrides_by_anchor is None:
            override = get_bundle_override(member_ids)
        else:
            # The old helper sorted IDs before selecting an anchor, regardless
            # of visual/release ordering among bundle members.
            override = next(
                (overrides_by_anchor[work_id] for work_id in sorted(set(member_ids))
                 if work_id in overrides_by_anchor),
                None,
            )
    except Exception as error:
        if "no such table: bundle_overrides" not in str(error).casefold():
            log_exception(
                "bundling.presentation_override_unavailable",
                error,
                work_ids=member_ids,
            )
        return group
    if not override:
        return group

    custom_title = _get(override, "custom_title")
    if isinstance(custom_title, str) and custom_title.strip():
        group["title"] = custom_title.strip()

    custom_cover_path = _get(override, "custom_cover_path")
    cover_work_id = _get(override, "cover_work_id")
    if custom_cover_path:
        group["cover_path"] = custom_cover_path
        group["cover_url"] = None
        group.pop("_bundle_cover_work_id", None)
    elif cover_work_id is not None:
        try:
            selected_id = int(cover_work_id)
        except (TypeError, ValueError, OverflowError):
            selected_id = None
        cover_member = next(
            (member for member in safe_members if int(_get(member, "id")) == selected_id),
            None,
        )
        if cover_member is not None:
            group["cover_path"] = _get(cover_member, "cover_path")
            group["cover_url"] = _get(cover_member, "cover_url")
            group["_bundle_cover_work_id"] = selected_id
    return group


def _apply_bundle_overrides(groups):
    """Apply all bundle appearance overrides with one batched database read."""
    entries = []
    work_ids = set()
    for group in groups or []:
        members = _get(group, "_series_members") or [group]
        safe_members = [
            member for member in members
            if _valid_relation_id(_get(member, "id")) is not None
        ]
        if len(safe_members) <= 1:
            continue
        member_ids = [int(_get(member, "id")) for member in safe_members]
        entries.append((group, safe_members))
        work_ids.update(member_ids)

    if not entries:
        return groups

    try:
        override_rows = get_bundle_overrides(sorted(work_ids))
    except Exception as error:
        if "no such table: bundle_overrides" not in str(error).casefold():
            log_exception(
                "bundling.presentation_override_unavailable",
                error,
                work_ids=sorted(work_ids),
            )
        return groups

    overrides_by_anchor = {
        int(_get(row, "bundle_anchor_id")): row
        for row in override_rows
        if _get(row, "bundle_anchor_id") is not None
    }
    for group, members in entries:
        _apply_bundle_override(group, members, overrides_by_anchor)
    return groups


def _group_discovered(results, discovered):
    original_ids = {int(item["id"]) for item in results}
    ids = {int(item["id"]) for item in discovered}
    parent = {item_id: item_id for item_id in ids}
    component_members = {item_id: {item_id} for item_id in ids}

    def find(item_id):
        while parent[item_id] != item_id:
            parent[item_id] = parent[parent[item_id]]
            item_id = parent[item_id]
        return item_id

    def union(left, right):
        left_root, right_root = find(left), find(right)
        if left_root == right_root:
            return True

        # A pair exclusion must survive indirect paths through other works.
        # Checking only the edge currently being joined allowed A and B to be
        # regrouped as A -> C -> B after the user explicitly split A from B.
        left_members = component_members[left_root]
        right_members = component_members[right_root]
        if _components_have_excluded_pair(
            left_members, right_members, excluded_neighbors
        ):
            return False

        # Keep the larger component as the root. Component exclusions were
        # checked above and are symmetric, so this only changes merge cost.
        _merge_component_roots(parent, component_members, left_root, right_root)
        return True

    # Explicit manual links are an override: when the user links two works,
    # they belong to the same display bundle regardless of AniList relation type
    # or whether one entry has a missing/unrecognized format.
    manual_links = get_manual_bundle_links(ids)
    excluded_links = {
        tuple(sorted((int(link["work_a"]), int(link["work_b"]))))
        for link in get_bundle_exclusions(ids)
    }
    excluded_neighbors = _build_exclusion_neighbors(excluded_links)
    manual_ids = set()
    for link in manual_links:
        left_id = int(link["work_a"])
        right_id = int(link["work_b"])
        if left_id in ids and right_id in ids:
            union(left_id, right_id)
            manual_ids.update((left_id, right_id))

    for item in discovered:
        item_id = int(item["id"])
        for edge in _search_relation_edges(item):
            target = edge.get("node")
            if not isinstance(target, dict):
                continue
            target_id = _valid_relation_id(target.get("id"))
            if target_id is None or target_id not in ids:
                continue
            if tuple(sorted((item_id, target_id))) in excluded_links:
                continue
            if not _relation_group_compatible(item, edge, target):
                continue
            union(item_id, target_id)

    by_key = {}
    for item in discovered:
        if not _auto_bundleable(item):
            continue
        key = _series_group_key(item)
        item_id = int(item["id"])
        if key[1]:
            if key in by_key:
                partner_id = by_key[key]
                if tuple(sorted((item_id, partner_id))) not in excluded_links:
                    union(item_id, partner_id)
            else:
                by_key[key] = item_id

    # TV continuations often carry a named production subtitle instead of a
    # numeric Season marker (for example "Sword Art Online: Alicization" and
    # "Sword Art Online: Alicization - War of Underworld"). AniList still links
    # them through the normal season chain, but keep a title-family fallback so
    # discovered TV entries are not stranded in groups with no original seed.
    tv_members = [
        item
        for item in discovered
        if str(_get(item, "format") or "").upper() in {"TV", "TV_SHORT"}
    ]
    tv_keys = [
        (item, _series_key(_title_text(item)))
        for item in tv_members
    ]
    tv_tokens, tv_candidate_indices = _prefix_related_tv_candidate_indices(
        [key for _, key in tv_keys]
    )
    # Keep candidates in their original order so exclusion-aware union behavior
    # remains the same while unrelated titles no longer trigger O(n^2) compares.
    for item_index, (item, key) in enumerate(tv_keys):
        item_tokens = tv_tokens[item_index]
        if not key or len(item_tokens) < 2:
            continue
        item_id = int(_get(item, "id"))
        for other_index in tv_candidate_indices[item_index]:
            other, other_key = tv_keys[other_index]
            if item_id == int(_get(other, "id")) or not other_key:
                continue
            other_tokens = tv_tokens[other_index]
            if len(other_tokens) < 2:
                continue
            shorter, longer = (
                (item_tokens, other_tokens)
                if len(item_tokens) <= len(other_tokens)
                else (other_tokens, item_tokens)
            )
            if longer[:len(shorter)] == shorter:
                other_id = int(_get(other, "id"))
                if tuple(sorted((item_id, other_id))) not in excluded_links:
                    union(item_id, other_id)

    groups = defaultdict(list)
    for item in discovered:
        groups[find(int(item["id"]))].append(item)

    first_position = {int(item["id"]): i for i, item in enumerate(results)}
    grouped = []
    represented_original_ids = set()

    for group_members in groups.values():
        def start_year(item):
            start = _get(item, "startDate")
            if not isinstance(start, dict):
                return 9999
            year = start.get("year") or _get(item, "start_year")
            if isinstance(year, bool):
                return 9999
            try:
                year = int(year)
            except (TypeError, ValueError, OverflowError):
                return 9999
            return year if 1 <= year <= 9999 else 9999

        group_members.sort(
            key=lambda item: (
                not isinstance(_get(item, "startDate"), dict),
                start_year(item),
                int(_get(item, "id")),
            )
        )

        bundle_members = [
            item
            for item in group_members
            if _auto_bundleable(item) or int(_get(item, "id")) in manual_ids
        ]
        visible_bundle_members = [
            item for item in bundle_members
            if int(_get(item, "id")) in original_ids
        ]

        if visible_bundle_members and bundle_members:
            # Keep the originally matched work as the search result identity,
            # but use the earliest bundle member for the default presentation.
            representative = dict(visible_bundle_members[0])
            default_member = bundle_members[0]
            representative["title"] = _get(default_member, "title") or representative.get("title")
            if _get(default_member, "cover_path"):
                representative["cover_path"] = _get(default_member, "cover_path")
            if _get(default_member, "cover_url"):
                representative["cover_url"] = _get(default_member, "cover_url")
            if _get(default_member, "coverImage"):
                representative["coverImage"] = _get(default_member, "coverImage")
            representative["_series_count"] = len(bundle_members)
            representative["_series_members"] = bundle_members
            representative["_bundle_summary"] = _bundle_summary(bundle_members)
            representative["_bundle_default_member_id"] = int(_get(default_member, "id"))
            # Overrides are applied in one batch after every group is assembled.
            grouped.append(
                (
                    min(
                        first_position.get(int(_get(item, "id")), 10**9)
                        for item in bundle_members
                    ),
                    representative,
                )
            )
            represented_original_ids.update(
                int(_get(item, "id")) for item in visible_bundle_members
            )

    for item in results:
        item_id = int(_get(item, "id"))
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
    return _apply_bundle_overrides([item for _, item in grouped])


def _diagnostic_media_summary(item, include_relations=False):
    try:
        edges = _search_relation_edges(item)
    except Exception:
        edges = []
    summary = {
        "id": _get(item, "id"),
        "title": _title_text(item),
        "type": _media_type(item),
        "format": str(_get(item, "format") or "").upper(),
        "relations_loaded": bool(_get(item, "_relations_loaded")),
        "relation_count": len(edges),
    }
    if include_relations:
        summary["relations"] = [
            {
                "relation_type": edge.get("relationType"),
                "target_id": _get(edge.get("node") or {}, "id"),
                "target_title": _title_text(edge.get("node") or {}),
                "target_type": _media_type(edge.get("node") or {}),
                "target_format": str(_get(edge.get("node") or {}, "format") or "").upper(),
            }
            for edge in edges[:20]
        ]
    return summary


def group_media_results(results, enrich=False, max_requests=0, delay=0.25, stop_event=None):
    if not results:
        log_event("bundling.empty_input")
        return []

    seed_ids = [_get(item, "id") for item in results[:100]]
    seed_summary = [
        _diagnostic_media_summary(item, include_relations=True)
        for item in results[:50]
    ]
    settings = {}
    for key in (
        "bundle_include_movies", "bundle_include_ovas", "bundle_include_onas",
        "bundle_include_specials", "bundle_include_manga", "bundle_include_novels",
        "bundle_include_one_shots",
    ):
        try:
            settings[key] = bool(get(key))
        except Exception:
            settings[key] = None

    with diagnostic_context(workflow="bundling", seed_ids=seed_ids):
        log_event(
            "bundling.started",
            seed_count=len(results),
            enrich=bool(enrich),
            max_requests=max_requests,
            delay=delay,
            options=settings,
            seed_items=seed_summary,
        )
        try:
            discovered, requests_used = _discover_related(
                results,
                max_requests=max_requests if enrich else -1,
                delay=delay,
                stop_event=stop_event,
            )
            groups = _group_discovered(results, discovered)
        except Exception as error:
            log_exception(
                "bundling.failed",
                error,
                seed_count=len(results),
                enrich=bool(enrich),
                max_requests=max_requests,
            )
            raise

        group_summary = []
        for group in groups[:50]:
            members = group.get("_series_members") or [group]
            group_summary.append({
                "representative_id": _get(group, "id"),
                "representative_title": _title_text(group),
                "member_count": len(members),
                "members": [
                    _diagnostic_media_summary(member)
                    for member in members[:50]
                ],
            })
        log_event(
            "bundling.completed",
            seed_count=len(results),
            discovered_count=len(discovered),
            request_batches=requests_used,
            output_group_count=len(groups),
            discovered_items=[
                _diagnostic_media_summary(item, include_relations=True)
                for item in discovered[:50]
            ],
            groups=group_summary,
        )
        return groups

def has_pending_relation_enrichment(results):
    seen = set()
    queue = deque(results)

    while queue:
        item = queue.popleft()
        item_id = int(item["id"])
        if item_id in seen:
            continue
        seen.add(item_id)

        if _get(item, "_relations_loaded"):
            edges = _search_relation_edges(item)
        else:
            cached = _relation_cache.get(item_id)
            if cached:
                edges = (cached.get("relations") or {}).get("edges", [])
            elif _get(item, "_related_only"):
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

    member_ids = sorted({int(work_id) for work_id in ids})
    if not member_ids:
        return []
    relation_types = ",".join(repr(value) for value in SERIES_RELATIONS)
    connection = get_connection()
    try:
        # Keep the single-query path unchanged for typical library sizes. Large
        # libraries are chunked because this predicate binds every ID twice.
        if len(member_ids) <= 400:
            placeholders = ",".join("?" for _ in member_ids)
            return connection.execute(
                f"SELECT source_id, target_id, relation_type "
                f"FROM work_relations "
                f"WHERE relation_type IN ({relation_types}) "
                f"AND (source_id IN ({placeholders}) OR target_id IN ({placeholders}))",
                [*member_ids, *member_ids],
            ).fetchall()

        rows_by_identity = {}
        for start in range(0, len(member_ids), 400):
            chunk = member_ids[start:start + 400]
            placeholders = ",".join("?" for _ in chunk)
            rows = connection.execute(
                f"SELECT rowid AS _relation_rowid, source_id, target_id, relation_type "
                f"FROM work_relations "
                f"WHERE relation_type IN ({relation_types}) "
                f"AND (source_id IN ({placeholders}) OR target_id IN ({placeholders}))",
                [*chunk, *chunk],
            ).fetchall()
            for row in rows:
                identity = (
                    int(row["source_id"]), int(row["target_id"]), str(row["relation_type"])
                )
                rows_by_identity[identity] = (
                    int(row["_relation_rowid"]),
                    {
                        "source_id": identity[0],
                        "target_id": identity[1],
                        "relation_type": identity[2],
                    },
                )
        return [
            row for _rowid, row in sorted(
                rows_by_identity.values(), key=lambda item: item[0]
            )
        ]
    finally:
        connection.close()


def sync_library_relations(force_ids=None):
    """Persist complete relation snapshots, optionally refreshing chosen works.

    A forced refresh is used by the explicit Auto-bundle action. Existing
    background startup sync remains incremental, and failed or partial provider
    responses are never treated as authoritative empty relation snapshots.
    """
    rows = list(get_all_library())
    if not rows:
        return False

    ids = {int(row["id"]) for row in rows}
    if force_ids is None:
        pending = ids - _relation_sync_checked_ids
    else:
        requested = set()
        for raw_id in force_ids:
            try:
                work_id = int(raw_id)
            except (TypeError, ValueError, OverflowError):
                continue
            if work_id > 0:
                requested.add(work_id)
        pending = ids.intersection(requested)
    if not pending:
        return False

    details_by_id = {}
    try:
        fetched = get_media_relations_batch(sorted(pending))
        if isinstance(fetched, dict):
            details_by_id = fetched
    except Exception as error:
        log_exception(
            "library.relation_sync.batch_failed",
            error,
            requested_count=len(pending),
        )

    changed = False
    for work_id in sorted(pending):
        details = details_by_id.get(work_id)
        if details is None:
            try:
                individual = get_media_relations_batch([work_id])
                details = (
                    individual.get(work_id)
                    if isinstance(individual, dict)
                    else None
                )
            except Exception as error:
                log_exception(
                    "library.relation_sync.item_failed",
                    error,
                    work_id=work_id,
                )
                continue

        if not isinstance(details, dict) or details.get("id") != work_id:
            log_event(
                "library.relation_sync.item_missing_details",
                work_id=work_id,
            )
            continue
        relation_data = details.get("relations")
        if (
            not isinstance(relation_data, dict)
            or not isinstance(relation_data.get("edges"), list)
        ):
            log_event(
                "library.relation_sync.item_missing_relation_snapshot",
                work_id=work_id,
            )
            continue

        try:
            save_anime(details)
        except Exception as error:
            log_exception(
                "library.relation_sync.item_failed",
                error,
                work_id=work_id,
            )
            continue

        _relation_sync_checked_ids.add(work_id)
        changed = True

    return changed


def auto_bundle_library_work(work_id):
    """Refresh provider relations and persist the existing Library grouping for one work.

    This deliberately reuses get_library_series() and the same grouping rules as
    Search/Library, including user preferences, manual links, and exclusions.
    """
    try:
        numeric_id = int(work_id)
    except (TypeError, ValueError, OverflowError):
        raise ValueError("A valid AniList work ID is required.")
    if numeric_id <= 0:
        raise ValueError("Automatic provider bundling requires an AniList work ID.")

    rows = list(get_all_library())
    if not any(int(row["id"]) == numeric_id for row in rows):
        raise ValueError("Add this title to the Library before automatic bundling.")

    changed = sync_library_relations(force_ids={numeric_id})
    def contains_work(item, target_id):
        for member in item.get("_series_members") or []:
            try:
                if int(member["id"]) == target_id:
                    return True
            except (KeyError, TypeError, ValueError, OverflowError):
                continue
        return False

    groups = get_library_series()
    group = next(
        (item for item in groups if contains_work(item, numeric_id)),
        None,
    )
    if group is None:
        raise RuntimeError("The updated Library grouping could not be rebuilt.")

    members = []
    for member in group.get("_series_members") or []:
        try:
            member_id = int(member["id"])
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
        if member_id > 0 and member_id not in members:
            members.append(member_id)

    if len(members) > 1:
        # Existing exclusions are enforced by get_library_series() before this
        # snapshot is persisted. Never create a separate grouping algorithm.
        try:
            bundle_id = int(group["id"])
        except (KeyError, TypeError, ValueError, OverflowError):
            bundle_id = min(members)
        if not save_automatic_bundle_membership(bundle_id, members):
            raise RuntimeError("NekoTrack could not save the automatic bundle.")
        # Re-read so the returned group reflects the persisted bundle snapshot
        # and any existing user appearance overrides.
        refreshed = get_library_series()
        group = next(
            (item for item in refreshed if contains_work(item, numeric_id)),
            group,
        )

    return {
        "group": group,
        "member_ids": members,
        "count": len(members),
        "relations_refreshed": bool(changed),
    }


def get_library_series(rows=None):
    """Return the Library's canonical grouped rows, optionally from a snapshot."""
    rows = list(get_all_library()) if rows is None else [dict(row) for row in rows]
    if not rows:
        return []

    ids = {int(row["id"]) for row in rows}
    parent = {work_id: work_id for work_id in ids}
    component_members = {work_id: {work_id} for work_id in ids}
    # Track the Search snapshots represented by each component. Automatic
    # relation/title joins may extend one snapshot, but must not collapse two
    # independently selected Search result groups.
    component_snapshot_ids = {work_id: set() for work_id in ids}

    def find(work_id):
        while parent[work_id] != work_id:
            parent[work_id] = parent[parent[work_id]]
            work_id = parent[work_id]
        return work_id

    def union(left, right, allow_snapshot_merge=False):
        left_root, right_root = find(left), find(right)
        if left_root == right_root:
            return True

        left_members = component_members[left_root]
        right_members = component_members[right_root]
        # Component-wide checks stop indirect relation chains from bypassing
        # an exclusion the user explicitly added.
        if _components_have_excluded_pair(
            left_members, right_members, excluded_neighbors
        ):
            return False

        left_snapshots = component_snapshot_ids[left_root]
        right_snapshots = component_snapshot_ids[right_root]
        if (
            not allow_snapshot_merge
            and left_snapshots
            and right_snapshots
            and left_snapshots.isdisjoint(right_snapshots)
        ):
            return False

        # Snapshot compatibility and exclusion checks are symmetric. Merge the
        # smaller component into the larger one to avoid quadratic set copying.
        _merge_component_roots(
            parent, component_members, left_root, right_root, component_snapshot_ids
        )
        return True

    row_by_id = {int(row["id"]): row for row in rows}
    grouping_state = get_library_bundle_grouping_state(ids, relation_types=SERIES_RELATIONS)
    excluded_links = {
        tuple(sorted((int(link["work_a"]), int(link["work_b"]))))
        for link in grouping_state["exclusions"]
    }
    excluded_neighbors = _build_exclusion_neighbors(excluded_links)

    # Search already computed these bundles using the full discovered relation
    # graph. Preserve that exact grouping in Library while honoring current
    # format preferences and explicit pair exclusions.
    saved_groups = defaultdict(set)
    for membership in grouping_state["automatic_memberships"]:
        bundle_id = int(membership["bundle_id"])
        work_id = int(membership["work_id"])
        if work_id in ids:
            saved_groups[bundle_id].add(work_id)
            component_snapshot_ids[work_id].add(bundle_id)

    for member_ids in saved_groups.values():
        bundleable_ids = sorted(
            work_id for work_id in member_ids
            if work_id in row_by_id and _auto_bundleable(row_by_id[work_id])
        )
        if len(bundleable_ids) > 1:
            anchor_id = bundleable_ids[0]
            for work_id in bundleable_ids[1:]:
                union(anchor_id, work_id)

    for relation in grouping_state["relations"]:
        source_id = int(relation["source_id"])
        target_id = int(relation["target_id"])
        source = row_by_id.get(source_id)
        target = row_by_id.get(target_id)

        if source is None or target is None:
            continue

        # Use the same conservative relation policy as Search. In particular,
        # don't let stored franchise-level relations bypass the cross-format
        # compatibility rules used during search enrichment.
        edge = {
            "relationType": relation["relation_type"],
            "node": target,
        }
        if tuple(sorted((source_id, target_id))) in excluded_links:
            continue
        if _relation_group_compatible(source, edge, target):
            union(source_id, target_id)

    # Manual bundle links are explicit user overrides and may join works
    # even when AniList relations or formats would not allow automatic bundling.
    for link in grouping_state["manual_links"]:
        source_id = int(link["work_a"])
        target_id = int(link["work_b"])
        if source_id in ids and target_id in ids:
            # Explicit user-created manual links may combine automatic
            # snapshots, but the exclusion check inside union remains active.
            union(source_id, target_id, allow_snapshot_merge=True)

    by_key = {}
    for row in rows:
        if not _auto_bundleable(row):
            continue

        key = _series_group_key(row)
        if key[1]:
            work_id = int(row["id"])
            if key in by_key:
                partner_id = by_key[key]
                if tuple(sorted((work_id, partner_id))) not in excluded_links:
                    union(work_id, partner_id)
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

        group["_bundle_default_member_id"] = int(members[0]["id"])
        result.append(group)

    return _apply_bundle_overrides(result)
