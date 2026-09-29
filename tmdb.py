import datetime as _dt
import re
import time

import requests

from ui.preferences import get


TMDB_BASE_URL = "https://api.themoviedb.org/3"
TMDB_IMAGE_BASE_URL = "https://image.tmdb.org/t/p/w780"


def _tmdb_token():
    return str(get("tmdb_api_token") or "").strip()


def _tmdb_get(path, params=None):
    token = _tmdb_token()
    if not token:
        raise RuntimeError(
            "TMDB API token is not configured. Open Settings and enter your TMDB API Read Access Token."
        )

    response = requests.get(
        f"{TMDB_BASE_URL}/{str(path).lstrip('/')}",
        params=params or {},
        headers={
            "Authorization": f"Bearer {token}",
            "accept": "application/json",
        },
        timeout=20,
    )
    response.raise_for_status()
    time.sleep(0.15)
    return response.json() or {}


def _parse_date(value):
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return _dt.date.fromisoformat(text[:10])
    except ValueError:
        return None


def _normalize_title(value):
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def _candidate_score(candidate, title_variants, target_date):
    names = {
        _normalize_title(candidate.get("name")),
        _normalize_title(candidate.get("original_name")),
    }
    queries = {
        _normalize_title(value)
        for value in (title_variants or [])
        if str(value or "").strip()
    }

    score = 0
    if names & queries:
        score += 1000

    candidate_date = _parse_date(candidate.get("first_air_date"))
    if candidate_date and target_date:
        score -= abs((candidate_date - target_date).days) / 10

    if "JP" in {str(value).upper() for value in (candidate.get("origin_country") or [])}:
        score += 20

    score += min(float(candidate.get("popularity") or 0), 20)
    return score


def _find_tmdb_series(title_variants, target_date):
    variants = [
        str(value).strip()
        for value in (title_variants or [])
        if str(value or "").strip()
    ]
    if not variants:
        raise RuntimeError("No title is available for TMDB series search.")

    candidates = {}
    year = target_date.year if target_date else None

    for query in variants[:6]:
        params = {
            "query": query,
            "include_adult": "false",
        }
        if year:
            params["first_air_date_year"] = year

        payload = _tmdb_get("/search/tv", params)
        for candidate in payload.get("results") or []:
            if candidate.get("id") is not None:
                candidates[int(candidate["id"])] = candidate

    if not candidates:
        for query in variants[:3]:
            payload = _tmdb_get(
                "/search/tv",
                {
                    "query": query,
                    "include_adult": "false",
                },
            )
            for candidate in payload.get("results") or []:
                if candidate.get("id") is not None:
                    candidates[int(candidate["id"])] = candidate

    if not candidates:
        raise RuntimeError("TMDB could not find a matching TV series.")

    return max(
        candidates.values(),
        key=lambda candidate: _candidate_score(
            candidate,
            variants,
            target_date,
        ),
    )


def _find_tmdb_season(series_details, target_date):
    seasons = [
        season
        for season in (series_details.get("seasons") or [])
        if int(season.get("season_number") or -1) >= 0
    ]
    if not seasons:
        raise RuntimeError("TMDB series has no usable seasons.")

    def score(season):
        season_date = _parse_date(season.get("air_date"))
        if season_date is None or target_date is None:
            return (1, 999999, int(season.get("season_number") or 0))
        return (
            0,
            abs((season_date - target_date).days),
            int(season.get("season_number") or 0),
        )

    return min(seasons, key=score)


def _episode_still_url(path):
    if not path:
        return None
    return f"{TMDB_IMAGE_BASE_URL}{path}"


def _pick_best_episode_still(series_id, season_number, episode):
    primary = _episode_still_url(episode.get("still_path"))
    if primary:
        return primary, 1

    try:
        payload = _tmdb_get(
            f"/tv/{int(series_id)}/season/{int(season_number)}/episode/{int(episode['episode_number'])}/images",
            {
                "include_image_language": "en,null",
            },
        )
    except requests.RequestException:
        return None, 0

    stills = payload.get("stills") or []
    if not stills:
        return None, 0

    stills.sort(
        key=lambda item: (
            float(item.get("vote_average") or 0),
            int(item.get("vote_count") or 0),
            int(item.get("width") or 0),
        ),
        reverse=True,
    )
    return _episode_still_url(stills[0].get("file_path")), len(stills)


def get_tmdb_episode_data(
    title_variants,
    start_date,
    end_date=None,
    expected_episodes=None,
    tmdb_id=None,
    tmdb_season_number=None,
):
    """Resolve one NekoTrack season and fetch its TMDB episode data."""
    target_start = _parse_date(start_date)
    target_end = _parse_date(end_date)

    if target_start is None:
        raise RuntimeError("NekoTrack needs a valid start date to match TMDB.")

    if tmdb_id is None:
        candidate = _find_tmdb_series(title_variants, target_start)
        tmdb_id = int(candidate["id"])

    series_details = _tmdb_get(f"/tv/{int(tmdb_id)}")
    if tmdb_season_number is None:
        selected_season = _find_tmdb_season(series_details, target_start)
        tmdb_season_number = int(selected_season["season_number"])

    season = _tmdb_get(
        f"/tv/{int(tmdb_id)}/season/{int(tmdb_season_number)}",
        {"language": "en-US"},
    )

    selected = []
    for episode in season.get("episodes") or []:
        air_date = _parse_date(episode.get("air_date"))
        if air_date is None or air_date < target_start:
            continue
        if target_end is not None and air_date >= target_end:
            continue

        thumbnail, image_variants = _pick_best_episode_still(
            tmdb_id,
            tmdb_season_number,
            episode,
        )

        selected.append({
            "episodeNumber": int(episode["episode_number"]),
            "title": episode.get("name") or f"Episode {episode['episode_number']}",
            "description": episode.get("overview") or None,
            "airdate": air_date.isoformat(),
            "thumbnail": thumbnail,
            "episode_type": episode.get("episode_type"),
            "tmdb_episode_id": episode.get("id"),
            "tmdb_image_count": image_variants,
        })

    selected.sort(key=lambda item: item["episodeNumber"])

    if expected_episodes:
        try:
            expected = int(expected_episodes)
        except (TypeError, ValueError):
            expected = 0
        if expected > 0 and len(selected) > expected:
            selected = selected[:expected]

    return {
        "tmdb_id": int(tmdb_id),
        "tmdb_season_number": int(tmdb_season_number),
        "episodes": selected,
        "tmdb_count": len(selected),
    }


def get_tmdb_episode_sample(
    title_variants,
    start_date,
    end_date=None,
    expected_episodes=None,
    tmdb_id=None,
    tmdb_season_number=None,
):
    """Fetch one lightweight TMDB season sample for in-app testing."""
    data = get_tmdb_episode_data(
        title_variants,
        start_date,
        end_date,
        expected_episodes,
        tmdb_id,
        tmdb_season_number,
    )

    episode = next(
        (row for row in data["episodes"] if int(row["episodeNumber"]) == 1),
        None,
    )

    return {
        **data,
        "sample_episode_1": episode or {},
    }
