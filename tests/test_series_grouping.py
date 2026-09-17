"""Offline tests for series discovery and grouping (fetch mocked, no network)."""

from threading import Event


import series


def item(media_id, title, media_format="TV", media_type="ANIME", year=2020, relations=None):
    return {
        "id": media_id,
        "type": media_type,
        "format": media_format,
        "title": {"romaji": title, "english": None, "native": None},
        "episodes": None,
        "coverImage": {"large": None},
        "startDate": {"year": year, "month": 1, "day": 1},
        "relations": {"edges": relations or []},
    }


def node(media_id, title, media_format="TV", media_type="ANIME", year=2021):
    return {
        "id": media_id,
        "type": media_type,
        "format": media_format,
        "title": {"romaji": title, "english": None, "native": None},
        "coverImage": {"large": None},
        "episodes": None,
        "startDate": {"year": year, "month": 1, "day": 1},
    }


def edge(target_id, relation_type="SEQUEL", title=None, **node_kwargs):
    return {"relationType": relation_type, "node": node(target_id, title or f"Related {target_id}", **node_kwargs)}


def fake_details(by_id):
    """Return a fetch function serving canned detail payloads into the cache."""

    def fetch(media_ids):
        return {int(i): by_id[int(i)] for i in media_ids if int(i) in by_id}

    return fetch


class TestDiscoverRelated:
    def test_traverses_only_chain_relations(self, monkeypatch):
        root = item(
            1,
            "Root",
            relations=[edge(2), edge(3, "SIDE_STORY"), edge(4, "PARENT")],
        )
        details = {
            1: {"relations": {"edges": [edge(2), edge(3, "SIDE_STORY"), edge(4, "PARENT")]}},
            2: {"relations": {"edges": []}},
            4: {"relations": {"edges": []}},
        }
        monkeypatch.setattr(series, "_cache_relation_details_batch", fake_details(details))
        discovered, requests = series._discover_related([root], max_nodes=50)
        ids = {int(d["id"]) for d in discovered}
        assert ids == {1, 2, 4}  # SIDE_STORY (3) is not part of the chain
        assert requests == 2  # one batch for the root, one for {2, 4}

    def test_respects_request_budget(self, monkeypatch):
        members = [item(i, f"Title {i}") for i in range(11)]
        details = {}
        monkeypatch.setattr(series, "_cache_relation_details_batch", fake_details(details))
        discovered, requests = series._discover_related(members, max_requests=3)
        assert requests <= 3
        assert len(discovered) == len(members)

    def test_stop_event_aborts(self, monkeypatch):
        root = item(1, "Root", relations=[edge(2)])
        details = {
            1: {"relations": {"edges": [edge(2)]}},
            2: {"relations": {"edges": [edge(3)]}},
            3: {"relations": {"edges": []}},
        }
        monkeypatch.setattr(series, "_cache_relation_details_batch", fake_details(details))
        stop = Event()
        stop.set()
        discovered, _ = series._discover_related([root], max_nodes=100, stop_event=stop)
        # The stop event is checked before any fetch; nothing beyond the root resolves.
        assert len(discovered) == 1

    def test_cache_avoids_fetches_without_enrichment(self, monkeypatch):
        """Non-enriched grouping must not re-fetch nodes already in the cache."""
        root = item(1, "Root", relations=[edge(2), edge(3, "SEQUEL")])
        series._relation_cache[1] = {"relations": {"edges": [edge(2), edge(3, "SEQUEL")]}}
        calls = []

        def counting_fetch(media_ids):
            calls.extend(media_ids)
            return {}

        monkeypatch.setattr(series, "_cache_relation_details_batch", counting_fetch)
        discovered, _ = series._discover_related([root], max_nodes=50, max_requests=-1)
        ids = {int(d["id"]) for d in discovered}
        assert ids == {1, 2, 3}
        assert calls == []  # everything came from the module cache


class TestGroupMediaResults:
    def test_same_key_results_bundle(self, monkeypatch):
        results = [
            item(1, "Attack on Titan"),
            item(2, "Attack on Titan Season 2", year=2017),
        ]
        monkeypatch.setattr(series, "_cache_relation_details_batch", lambda ids: {})
        grouped = series.group_media_results(results)
        assert len(grouped) == 1
        representative = grouped[0]
        assert representative["_series_count"] == 2
        assert representative["_bundle_summary"] == "2 seasons"
        assert len(representative["_series_members"]) == 2

    def test_distinct_titles_stay_separate(self, monkeypatch):
        results = [item(1, "Cowboy Bebop"), item(2, "Trigun")]
        monkeypatch.setattr(series, "_cache_relation_details_batch", lambda ids: {})
        grouped = series.group_media_results(results)
        assert len(grouped) == 2

    def test_relation_union_across_different_keys(self, monkeypatch):
        results = [
            item(1, "Franchise A"),
            item(2, "-Franchise A: The Movie-", media_format="MOVIE", relations=[edge(1, title="Franchise A")]),
        ]
        monkeypatch.setattr(series, "_cache_relation_details_batch", lambda ids: {})
        grouped = series.group_media_results(results)
        assert len(grouped) == 1
        assert grouped[0]["_series_count"] == 2

    def test_empty_results(self):
        assert series.group_media_results([]) == []

    def test_mixed_bundle_summary(self, monkeypatch):
        results = [
            item(1, "Franchise"),
            item(2, "Franchise OVA", media_format="OVA", year=2001, relations=[edge(1, title="Franchise")]),
            item(3, "Franchise Part 2", year=2002),
        ]
        monkeypatch.setattr(series, "_cache_relation_details_batch", lambda ids: {})
        grouped = series.group_media_results(results)
        assert len(grouped) == 1
        assert "1 OVA" in grouped[0]["_bundle_summary"]


class TestSeriesKey:
    def test_value_error_geometry(self):
        assert series._series_group_key(item(1, "Psycho-Pass 2")) == series._series_group_key(item(2, "Psycho Pass"))

    def test_manga_family_kept_separate_from_anime(self):
        anime = item(1, "Monster", media_type="ANIME")
        manga = item(2, "Monster", media_type="MANGA", media_format="MANGA")
        assert series._series_group_key(anime) != series._series_group_key(manga)