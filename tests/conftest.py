"""Shared fixtures: isolated SQLite database and clean module state per test."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import database
import series


@pytest.fixture(autouse=True)
def clean_series_state():
    """Module-level caches on series.py survive app lifetime; reset them per test."""
    series._relation_cache.clear()
    series._relation_sync_checked_ids.clear()
    yield
    series._relation_cache.clear()
    series._relation_sync_checked_ids.clear()


@pytest.fixture()
def db_path(tmp_path, monkeypatch):
    """Point database.py at a throwaway file and initialize the schema."""
    path = tmp_path / "test_tracker.db"
    monkeypatch.setattr(database, "DATABASE_NAME", str(path))
    database.initialize_database()
    return path


def media(
    media_id,
    title,
    media_format="TV",
    media_type="ANIME",
    year=None,
    episodes=None,
    relations=None,
    synonyms=None,
):
    """Build an AniList-style media payload with just the fields save_anime uses."""
    return {
        "id": media_id,
        "title": {"romaji": title, "english": None, "native": None},
        "type": media_type,
        "format": media_format,
        "description": f"Description of {title}",
        "episodes": episodes,
        "chapters": None,
        "volumes": None,
        "source": None,
        "duration": None,
        "averageScore": 80,
        "startDate": {"year": year, "month": 1, "day": 1},
        "endDate": {"year": None, "month": None, "day": None},
        "coverImage": {"large": None},
        "synonyms": synonyms or [],
        "studios": {"edges": []},
        "relations": {"edges": relations or []},
    }


def relation(target_id, relation_type="SEQUEL", title=None):
    return {
        "relationType": relation_type,
        "node": media(target_id, title or f"Work {target_id}"),
    }