"""Small, explainable recommendation scoring helpers.

Pure functions live here so ranking behaviour can be tested without Qt or a live
AniList connection. Credit-role weights are centralized for shared use by the
profile UI and recommendation model as those relationship signals are loaded.
"""

import math
import re
from collections import Counter


CHARACTER_ROLE_WEIGHTS = {
    "MAIN": 1.0,
    "SUPPORTING": 0.58,
    "BACKGROUND": 0.18,
    "UNKNOWN": 0.30,
}
VOICE_ACTOR_ROLE_WEIGHTS = CHARACTER_ROLE_WEIGHTS

# More specific labels precede broad terms; the highest matching weight wins.
STAFF_ROLE_RULES = (
    ("principal director", 1.00),
    ("chief director", 0.98),
    ("original creator", 0.98),
    ("original work", 0.96),
    ("original story", 0.96),
    ("series director", 0.94),
    ("series composition", 0.94),
    ("series composer", 0.94),
    ("assistant director", 0.58),
    ("chief animation director", 0.86),
    ("character designer", 0.84),
    ("screenplay", 0.82),
    ("script", 0.80),
    ("episode director", 0.76),
    ("animation director", 0.76),
    ("music", 0.74),
    ("composer", 0.74),
    ("storyboard", 0.70),
    ("art director", 0.68),
    ("sound director", 0.66),
    ("director", 0.90),
    ("producer", 0.56),
    ("animation producer", 0.60),
    ("design", 0.48),
    ("editor", 0.43),
    ("production assistant", 0.22),
    ("assistant", 0.28),
    ("background", 0.25),
)
DEFAULT_STAFF_ROLE_WEIGHT = 0.30
EXPOSURE_MULTIPLIER_FLOOR = 0.18


def _safe_int(value, default=0):
    if isinstance(value, bool):
        return default
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return default


def character_role_weight(role):
    """Return a centralized influence weight for an AniList character role."""
    normalized = str(role or "").strip().upper().replace("-", "_").replace(" ", "_")
    if normalized in {"MAIN", "SUPPORTING", "BACKGROUND"}:
        return CHARACTER_ROLE_WEIGHTS[normalized]
    return CHARACTER_ROLE_WEIGHTS["UNKNOWN"]


def voice_actor_role_weight(role):
    """Voice credits inherit the importance of the character being voiced."""
    return character_role_weight(role)


def staff_role_weight(role):
    """Rank creative credits by normalized responsibility, not provider order."""
    normalized = re.sub(r"[^a-z0-9]+", " ", str(role or "").casefold()).strip()
    if not normalized:
        return DEFAULT_STAFF_ROLE_WEIGHT
    matches = [weight for phrase, weight in STAFF_ROLE_RULES if phrase in normalized]
    return max(matches, default=DEFAULT_STAFF_ROLE_WEIGHT)


def exposure_multiplier(impressions, floor=EXPOSURE_MULTIPLIER_FLOOR):
    """Apply a diminishing, strictly-positive exposure penalty."""
    count = max(0, _safe_int(impressions))
    try:
        safe_floor = float(floor)
    except (TypeError, ValueError, OverflowError):
        safe_floor = EXPOSURE_MULTIPLIER_FLOOR
    if not math.isfinite(safe_floor):
        safe_floor = EXPOSURE_MULTIPLIER_FLOOR
    safe_floor = min(1.0, max(0.01, safe_floor))
    return max(safe_floor, 1.0 / math.sqrt(1.0 + 0.35 * count))


def _work_id(work):
    if not isinstance(work, dict):
        return None
    value = _safe_int(work.get("id"), 0)
    return value if value > 0 else None


def _work_title(work):
    title = work.get("title") if isinstance(work, dict) else None
    if isinstance(title, dict):
        return str(title.get("english") or title.get("romaji") or title.get("native") or "Untitled")
    return str(title or "Untitled")


def _terms(work):
    if not isinstance(work, dict):
        return set()
    values = []
    genres = work.get("genres")
    if isinstance(genres, (list, tuple, set)):
        values.extend(genres)
    tags = work.get("tags")
    if isinstance(tags, (list, tuple, set)):
        values.extend(tags)
    terms = set()
    for value in values:
        if isinstance(value, dict):
            value = value.get("name") or value.get("name_path")
        normalized = " ".join(str(value or "").casefold().split())
        if normalized and len(normalized) <= 100:
            terms.add(normalized)
    return terms


def _history_metadata(entry):
    if not isinstance(entry, dict):
        return {}
    metadata = entry.get("metadata")
    return metadata if isinstance(metadata, dict) else {}


def _preference_profiles(history, favorite_works):
    positive = Counter()
    negative = Counter()
    for entry in (history or {}).values():
        if not isinstance(entry, dict):
            continue
        metadata = _history_metadata(entry)
        feedback = entry.get("feedback")
        weight = 2.2 if feedback == "like" else 3.0 if feedback == "dislike" else 0.0
        if not weight:
            continue
        target = negative if feedback == "dislike" else positive
        for term in _terms(metadata):
            target[term] += weight

    for work in favorite_works or []:
        if not isinstance(work, dict):
            continue
        weight = 1.0
        try:
            rating = float(work.get("rating") or 0)
            if math.isfinite(rating):
                weight += min(1.0, max(0.0, rating / 10.0))
        except (TypeError, ValueError, OverflowError):
            pass
        for term in _terms(work):
            positive[term] += weight
    return positive, negative


def recommendation_reason(work, positive_profile=None):
    """Explain the strongest available reason without inventing connections."""
    count = max(0, _safe_int(work.get("_recommendation_count")))
    source_titles = work.get("_recommendation_source_titles")
    if count > 1:
        return f"Related to {count} titles in your collection"
    if isinstance(source_titles, list) and source_titles:
        title = str(source_titles[0] or "").strip()
        if title:
            return f"Related to {title}"
    positive_profile = positive_profile or {}
    matches = sorted(_terms(work).intersection(positive_profile))
    if matches:
        shown = ", ".join(term.title() for term in matches[:2])
        return f"Matches interests you've liked: {shown}"
    if work.get("_recommendation_catalog_source"):
        return "Popular anime discovery"
    return "Discovered from AniList"


def _language_matches(actual, preference):
    normalized = str(actual or "").strip().casefold().replace("_", " ").replace("-", " ")
    if preference == "ALL":
        return True
    if preference == "JA":
        return normalized in {"japanese", "ja", "jpn", "jp"}
    if preference == "EN":
        return normalized in {"english", "en", "eng"}
    return True


def _edge_id(value):
    if isinstance(value, dict):
        value = value.get("id")
    parsed = _safe_int(value, 0)
    return parsed if parsed > 0 else None


def _candidate_credit_signal(work, credit_profile, favorite_entities, voice_language):
    source_weights = Counter()
    for payload in (credit_profile or {}).values():
        if not isinstance(payload, dict):
            continue
        try:
            source_weight = float(payload.get("_source_weight", 1.0) or 1.0)
        except (TypeError, ValueError, OverflowError):
            source_weight = 1.0
        source_weight = min(3.5, max(0.0, source_weight))
        for kind in ("characters", "voice_actors", "staff"):
            credits = payload.get(kind)
            if not isinstance(credits, list):
                continue
            for credit in credits:
                if not isinstance(credit, dict):
                    continue
                entity_id = _edge_id(credit.get("id"))
                if entity_id is None:
                    continue
                if kind == "characters":
                    weight = character_role_weight(credit.get("role"))
                    source_weights[("character", entity_id)] += source_weight * weight
                elif kind == "voice_actors":
                    if not _language_matches(credit.get("language"), voice_language):
                        continue
                    weight = voice_actor_role_weight(credit.get("character_role"))
                    source_weights[("voice_actor", entity_id)] += source_weight * weight
                else:
                    source_weights[("staff", entity_id)] += source_weight * staff_role_weight(credit.get("role"))

    favorites = set()
    for entry in favorite_entities or []:
        if not isinstance(entry, dict):
            continue
        kind = str(entry.get("entity_type") or "").strip().casefold()
        entity_id = _edge_id(entry.get("entity_id"))
        # A favorite is the performer identity, not one particular role. The
        # actual candidate edge below is filtered by voice language.
        if kind in {"character", "voice_actor", "staff"} and entity_id is not None:
            favorites.add((kind, entity_id))

    strongest_by_entity = {}
    reasons = []
    characters = work.get("characters")
    edges = characters.get("edges") if isinstance(characters, dict) else []
    if isinstance(edges, list):
        for edge in edges:
            if not isinstance(edge, dict):
                continue
            character = edge.get("node") if isinstance(edge.get("node"), dict) else {}
            character_id = _edge_id(character)
            if character_id is None:
                continue
            role_weight = character_role_weight(edge.get("role"))
            key = ("character", character_id)
            boost = 0.0
            if key in favorites:
                boost = 22.0 * role_weight
                reasons.append((boost, "Features a favorite character"))
            elif source_weights[key] > 0:
                boost = min(14.0, source_weights[key] * role_weight * 5.0)
                reasons.append((boost, "Shares a character with a title you enjoyed"))
            strongest_by_entity[key] = max(strongest_by_entity.get(key, 0.0), boost)

            voices = edge.get("voiceActors")
            if not isinstance(voices, list):
                continue
            for voice in voices:
                if not isinstance(voice, dict) or not _language_matches(voice.get("language"), voice_language):
                    continue
                voice_id = _edge_id(voice)
                if voice_id is None:
                    continue
                key = ("voice_actor", voice_id)
                voice_boost = 20.0 * role_weight if key in favorites else min(
                    16.0, source_weights[key] * role_weight * 5.5
                )
                if voice_boost:
                    reasons.append((
                        voice_boost,
                        "Features a favorite voice actor" if key in favorites
                        else "Shares a voice actor with a title you enjoyed",
                    ))
                strongest_by_entity[key] = max(strongest_by_entity.get(key, 0.0), voice_boost)

    staff_connection = work.get("staff")
    staff_edges = staff_connection.get("edges") if isinstance(staff_connection, dict) else []
    if isinstance(staff_edges, list):
        for edge in staff_edges:
            if not isinstance(edge, dict):
                continue
            person_id = _edge_id(edge.get("node"))
            if person_id is None:
                continue
            role_weight = staff_role_weight(edge.get("role"))
            key = ("staff", person_id)
            boost = 15.0 * role_weight if key in favorites else min(
                14.0, source_weights[key] * role_weight * 5.0
            )
            if boost:
                reasons.append((
                    boost,
                    "Features a favorite production contributor" if key in favorites
                    else "Shares important production staff with a title you enjoyed",
                ))
            strongest_by_entity[key] = max(strongest_by_entity.get(key, 0.0), boost)

    favorite_boost = sum(value for key, value in strongest_by_entity.items() if key in favorites)
    other_boost = sum(value for key, value in strongest_by_entity.items() if key not in favorites)
    return min(48.0, favorite_boost) + min(26.0, other_boost), max(reasons, default=(0.0, ""))[1]


def rank_candidates(
    candidates, history=None, favorite_works=None, rotation=0,
    credit_profile=None, favorite_entities=None, voice_language="ALL",
):
    """Score candidates with local feedback, weighted credits and exposure."""
    history = history or {}
    positive, negative = _preference_profiles(history, favorite_works)
    credit_profile = credit_profile or {}
    favorite_entities = favorite_entities or []
    voice_language = str(voice_language or "ALL").upper()
    scored = []
    for raw in candidates or []:
        if not isinstance(raw, dict):
            continue
        work_id = _work_id(raw)
        if work_id is None:
            continue
        item_history = history.get(work_id, history.get(str(work_id), {}))
        if not isinstance(item_history, dict):
            item_history = {}
        # An explicit dislike is a suppression rule, not an exploration hint.
        if item_history.get("feedback") == "dislike":
            continue

        terms = _terms(raw)
        positive_overlap = sum(min(2.5, positive[term]) for term in terms)
        negative_overlap = sum(min(3.0, negative[term]) for term in terms)
        repeat_count = max(0, _safe_int(raw.get("_recommendation_count")))
        community_score = max(0, min(100, _safe_int(raw.get("averageScore"))))
        recommendation_score = max(0, min(100, _safe_int(raw.get("_recommendation_rating"))))
        popularity = max(0, _safe_int(raw.get("popularity")))
        credit_boost, credit_reason = _candidate_credit_signal(
            raw, credit_profile, favorite_entities, voice_language
        )
        raw_score = (
            6.0
            + min(repeat_count, 5) * 11.0
            + recommendation_score * 0.14
            + community_score * 0.05
            + min(12.0, math.log1p(popularity)) * 0.25
            + min(35.0, positive_overlap * 8.5)
            + credit_boost
            - min(48.0, negative_overlap * 10.0)
        )
        impressions = max(0, _safe_int(item_history.get("impressions")))
        score = max(0.1, raw_score) * exposure_multiplier(impressions)
        item = dict(raw)
        item["_recommendation_score"] = round(score, 6)
        item["_recommendation_exposure_multiplier"] = exposure_multiplier(impressions)
        item["_recommendation_reason"] = credit_reason or recommendation_reason(item, positive)
        item["_recommendation_matching_terms"] = sorted(terms.intersection(positive))
        item["_recommendation_credit_boost"] = round(credit_boost, 6)
        # Rotation only changes deterministic tie-breaks; the main relevance score
        # remains intact and refreshes can expose a different slice of close ties.
        item["_recommendation_rotation_key"] = (_work_id(item) + _safe_int(rotation)) % 1000003
        scored.append(item)

    scored.sort(key=lambda item: (
        -item["_recommendation_score"],
        -_safe_int(item.get("_recommendation_count")),
        -_safe_int(item.get("averageScore")),
        item["_recommendation_rotation_key"],
        _work_title(item).casefold(),
    ))
    return scored


def inject_rare_exploration(ranked, rotation=0, fraction=0.04):
    """Move a few lower-ranked, non-disliked eligible titles into rare feed slots."""
    items = list(ranked or [])
    if len(items) < 25:
        return items
    try:
        probability = float(fraction)
    except (TypeError, ValueError, OverflowError):
        probability = 0.04
    if not math.isfinite(probability):
        probability = 0.04
    probability = min(0.05, max(0.0, probability))
    if probability <= 0:
        return items

    period = max(20, round(1.0 / probability))
    slot_positions = list(range(period - 1, len(items), period))
    used_ids = set()
    rotation_value = _safe_int(rotation)
    # Work from the bottom upward so inserting one exploration item does not
    # shift any slot that has not been handled yet.
    for slot in reversed(slot_positions):
        pool_start = min(len(items) - 1, max(slot + 1, int(len(items) * 0.72)))
        pool = [
            index for index in range(pool_start, len(items))
            if _work_id(items[index]) not in used_ids
        ]
        if not pool:
            continue
        chosen_index = pool[(rotation_value + slot // period) % len(pool)]
        chosen = items.pop(chosen_index)
        used_ids.add(_work_id(chosen))
        items.insert(min(slot, len(items)), chosen)
    return items


__all__ = [
    "CHARACTER_ROLE_WEIGHTS",
    "VOICE_ACTOR_ROLE_WEIGHTS",
    "STAFF_ROLE_RULES",
    "DEFAULT_STAFF_ROLE_WEIGHT",
    "EXPOSURE_MULTIPLIER_FLOOR",
    "character_role_weight",
    "voice_actor_role_weight",
    "staff_role_weight",
    "exposure_multiplier",
    "recommendation_reason",
    "rank_candidates",
    "inject_rare_exploration",
]
