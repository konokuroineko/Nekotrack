"""Offline tests for api.py: validation, retry logic, and episode normalization."""

import datetime

import pytest

import api


class FakeResponse:
    def __init__(self, status_code, payload=None, reason="OK", headers=None):
        self.status_code = status_code
        self._payload = payload
        self.reason = reason
        self.headers = headers or {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise ValueError(f"HTTP {self.status_code}")


def patch_post(monkeypatch, responses):
    """Successively serve FakeResponse objects from a queue."""
    calls = []

    def fake_post(url, json=None, timeout=None):
        calls.append({"url": url, "json": json, "timeout": timeout})
        if not responses:
            raise AssertionError("fake_post called more times than canned responses")
        response = responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(api.requests, "post", fake_post)
    return calls


class TestAnilistRequest:
    def test_success(self, monkeypatch):
        calls = patch_post(
            monkeypatch,
            [FakeResponse(200, {"data": {"Page": {"media": []}}})],
        )
        result = api.anilist_request("query {}", {"page": 1})
        assert result == {"Page": {"media": []}}
        assert calls[0]["timeout"] == 30

    def test_retries_on_429_then_succeeds(self, monkeypatch):
        patch_post(
            monkeypatch,
            [
                FakeResponse(429, {"errors": [{"message": "rate limited"}]}, headers={"Retry-After": "0"}),
                FakeResponse(200, {"data": {"ok": True}}),
            ],
        )
        assert api.anilist_request("q") == {"ok": True}

    def test_429_exhausted_raises(self, monkeypatch):
        patch_post(
            monkeypatch,
            [FakeResponse(429, {"errors": [{"message": "rate limited"}]})] * api.MAX_RETRIES,
        )
        with pytest.raises(Exception, match="429"):
            api.anilist_request("q")

    def test_retries_on_5xx_then_succeeds(self, monkeypatch):
        patch_post(
            monkeypatch,
            [
                FakeResponse(500, {}, reason="boom"),
                FakeResponse(200, {"data": {"ok": True}}),
            ],
        )
        assert api.anilist_request("q") == {"ok": True}

    def test_5xx_exhausted_raises(self, monkeypatch):
        patch_post(
            monkeypatch,
            [FakeResponse(503, {}, reason="unavailable")] * api.MAX_RETRIES,
        )
        with pytest.raises(Exception, match="server error"):
            api.anilist_request("q")

    def test_network_error_then_succeeds(self, monkeypatch):
        patch_post(
            monkeypatch,
            [
                api.requests.exceptions.ConnectionError("dns failed"),
                FakeResponse(200, {"data": {"ok": True}}),
            ],
        )
        assert api.anilist_request("q") == {"ok": True}

    def test_network_error_exhausted_raises(self, monkeypatch):
        patch_post(
            monkeypatch,
            [api.requests.exceptions.Timeout("slow")] * api.MAX_RETRIES,
        )
        with pytest.raises(Exception, match="Network error after"):
            api.anilist_request("q")

    def test_graphql_error_raises_message(self, monkeypatch):
        patch_post(
            monkeypatch,
            [FakeResponse(200, {"errors": [{"message": "boom"}], "data": None})],
        )
        with pytest.raises(Exception, match="boom"):
            api.anilist_request("q")

    def test_other_request_exception_raises_immediately(self, monkeypatch):
        patch_post(monkeypatch, [api.requests.exceptions.InvalidURL("bad url")])
        with pytest.raises(api.requests.exceptions.InvalidURL):
            api.anilist_request("q")


class TestSearchAnimeValidation:
    def test_bad_media_type(self):
        with pytest.raises(ValueError, match="media_type"):
            api.search_anime("x", media_type="GAME")

    def test_bad_anime_format(self):
        with pytest.raises(ValueError, match="media_format"):
            api.search_anime("x", media_type="ANIME", media_format="UNICORN")

    def test_bad_manga_format(self):
        with pytest.raises(ValueError, match="media_format"):
            api.search_anime("x", media_type="MANGA", media_format="TV")

    def test_bad_status(self):
        with pytest.raises(ValueError, match="status"):
            api.search_anime("x", status="AIRING")

    def test_bad_season(self):
        with pytest.raises(ValueError, match="season"):
            api.search_anime("x", season="MONSOON")

    def test_bad_sort(self):
        with pytest.raises(ValueError, match="sort"):
            api.search_anime("x", sort="RANDOM")

    def test_bad_min_score(self):
        with pytest.raises(ValueError, match="min_score"):
            api.search_anime("x", min_score=150)

    def test_valid_arguments_build_query(self, monkeypatch):
        calls = patch_post(monkeypatch, [FakeResponse(200, {"data": {"Page": {"media": []}}})])
        api.search_anime(
            "Cowboy Bebop",
            media_type="ANIME",
            media_format="TV",
            min_score=60,
            status="FINISHED",
        )
        body = calls[0]["json"]
        variables = body["variables"]
        assert variables["search"] == "Cowboy Bebop"
        assert variables["type"] == "ANIME"
        assert variables["formatFilter"] == ["TV"]
        assert variables["minScore"] == 60
        assert variables["status"] == "FINISHED"
        assert variables["sort"] == ["SEARCH_MATCH"]
        assert "Page(page: $page, perPage: $perPage)" in body["query"]
        assert "averageScore_greater: $minScore" in body["query"]

    def test_browse_without_search_defaults_to_popularity(self, monkeypatch):
        calls = patch_post(monkeypatch, [FakeResponse(200, {"data": {"Page": {"media": []}}})])
        api.search_anime(None, sort="SEARCH_MATCH")
        variables = calls[0]["json"]["variables"]
        assert variables["sort"] == ["POPULARITY_DESC"]
        assert "search" not in variables


def _detail_payload(nodes):
    return {"airingSchedule": {"nodes": nodes}}


class TestMediaEpisodes:
    def test_maps_schedule_nodes(self):
        details = _detail_payload(
            [
                {"airingAt": 1700000000, "episode": 2},
                {"airingAt": 1690000000, "episode": 1},
            ]
        )
        episodes = api.media_episodes(details)
        assert [ep["episodeNumber"] for ep in episodes] == [1, 2]
        assert episodes[0]["airdate"] == datetime.datetime.fromtimestamp(1690000000).date().isoformat()
        assert episodes[0]["title"] is None
        assert episodes[0]["description"] is None

    def test_skips_episode_without_number(self):
        details = _detail_payload([{"airingAt": 1700000000, "episode": None}])
        assert api.media_episodes(details) == []

    def test_skips_non_numeric_episode(self):
        details = _detail_payload([{"airingAt": 1700000000, "episode": "N/A"}])
        assert api.media_episodes(details) == []

    def test_missing_airing_schedule(self):
        assert api.media_episodes({}) == []
        assert api.media_episodes({"airingSchedule": None}) == []

    def test_missing_airing_at(self):
        episodes = api.media_episodes(_detail_payload([{"episode": 3}]))
        assert episodes[0]["airdate"] is None

    def test_invalid_airing_at_does_not_raise(self):
        episodes = api.media_episodes(
            _detail_payload([{"episode": 1, "airingAt": "not-a-timestamp"}])
        )
        assert episodes[0]["airdate"] is None

    def test_sorted_by_episode_number(self):
        details = _detail_payload(
            [
                {"airingAt": 1700000000, "episode": 5},
                {"airingAt": 1690000000, "episode": 1},
                {"airingAt": 1695000000, "episode": 3},
            ]
        )
        assert [ep["episodeNumber"] for ep in api.media_episodes(details)] == [1, 3, 5]