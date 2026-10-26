import random
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import database
import series


def media(media_id, title, fmt="TV", media_type="ANIME", relations=None):
    return {
        "id": media_id, "type": media_type, "format": fmt,
        "title": {"english": title, "romaji": title, "native": None},
        "startDate": {"year": 2020, "month": 1, "day": 1},
        "coverImage": {"large": None}, "relations": {"edges": relations or []},
    }


def edge(relation_type, node):
    return {"relationType": relation_type, "node": node}


class SeriesKeyCacheTests(unittest.TestCase):
    def tearDown(self):
        series._cached_series_key.cache_clear()

    def test_cached_key_preserves_normalization_and_input_coercion(self):
        series._cached_series_key.cache_clear()
        cases = [
            (None, ""),
            ("Example Series Season 2", "example series"),
            ("Example Series - Final Season", "example series"),
            ("Sword Art Online: Alicization - War of Underworld",
             "sword art online alicization war of underworld"),
            (["Odd Title"], "odd title"),
        ]
        for title, expected in cases:
            with self.subTest(title=title):
                self.assertEqual(series._series_key(title), expected)

        series._cached_series_key.cache_clear()
        title = "Repeatable Series Season 2"
        first = series._series_key(title)
        first_info = series._cached_series_key.cache_info()
        second = series._series_key(title)
        second_info = series._cached_series_key.cache_info()
        self.assertEqual(first, second)
        self.assertEqual(second_info.hits, first_info.hits + 1)

    def test_title_key_cache_has_a_fixed_memory_bound(self):
        series._cached_series_key.cache_clear()
        for index in range(16392):
            series._series_key(f"Synthetic Cache Bound {index} Season 2")
        info = series._cached_series_key.cache_info()
        self.assertEqual(info.maxsize, 16384)
        self.assertLessEqual(info.currsize, info.maxsize)


class SeriesPrefixIndexTests(unittest.TestCase):
    @staticmethod
    def _reference_indices(keys):
        token_lists = [tuple(str(key or "").split()) for key in keys]
        result = []
        for index, tokens in enumerate(token_lists):
            matches = []
            if len(tokens) >= 2:
                for other_index, other_tokens in enumerate(token_lists):
                    if other_index == index or len(other_tokens) < 2:
                        continue
                    shorter, longer = (
                        (tokens, other_tokens)
                        if len(tokens) <= len(other_tokens)
                        else (other_tokens, tokens)
                    )
                    if longer[:len(shorter)] == shorter:
                        matches.append(other_index)
            result.append(matches)
        return token_lists, result

    def test_index_matches_original_all_pairs_logic_and_order(self):
        keys = [
            "", "solo", "echo series", "echo series season 2",
            "echo series season 2 part 2", "echo series ova",
            "unrelated title", "unrelated title", "東京 物語",
        ]
        rng = random.Random(20261023)
        roots = ["north wind", "blue archive", "one piece", "monogatari", "neko track"]
        suffixes = ["", "season two", "season two part three", "ova", "arc zero"]
        for index in range(250):
            root = rng.choice(roots)
            suffix = rng.choice(suffixes)
            keys.append(" ".join(part for part in (root, suffix, f"variant{index}") if part))
            if index % 6 == 0:
                keys.append(root + " " + suffix if suffix else root)

        expected_tokens, expected_indices = self._reference_indices(keys)
        actual_tokens, actual_indices = series._prefix_related_tv_candidate_indices(keys)

        self.assertEqual(actual_tokens, expected_tokens)
        self.assertEqual(actual_indices, expected_indices)

    def test_short_or_empty_titles_have_no_prefix_candidates(self):
        keys = ["", "solo", "another", "solo season 2", "solo season 3"]
        tokens, matches = series._prefix_related_tv_candidate_indices(keys)
        self.assertEqual(tokens[0:3], [(), ("solo",), ("another",)])
        self.assertEqual(matches[0:3], [[], [], []])
        self.assertEqual(matches[3], [])
        self.assertEqual(matches[4], [])


class SeriesExclusionIndexTests(unittest.TestCase):
    def test_neighbor_lookup_matches_original_cross_product_check(self):
        rng = random.Random(20261024)
        for _ in range(500):
            universe = list(range(1, rng.randint(5, 60)))
            rng.shuffle(universe)
            split = rng.randrange(1, len(universe))
            left_members = set(universe[:split])
            right_members = set(universe[split:])
            if rng.randrange(5) == 0:
                left_members.clear()
            if rng.randrange(5) == 0:
                right_members.clear()

            excluded_links = set()
            for _ in range(rng.randrange(0, 25)):
                a = rng.choice(universe)
                b = rng.choice(universe)
                if a != b:
                    excluded_links.add(tuple(sorted((a, b))))

            expected = any(
                tuple(sorted((left_id, right_id))) in excluded_links
                for left_id in left_members
                for right_id in right_members
            )
            neighbors = series._build_exclusion_neighbors(excluded_links)
            actual = series._components_have_excluded_pair(
                left_members, right_members, neighbors
            )
            with self.subTest(
                left_size=len(left_members),
                right_size=len(right_members),
                exclusion_count=len(excluded_links),
            ):
                self.assertEqual(actual, expected)

    def test_exclusion_neighbor_index_is_undirected(self):
        neighbors = series._build_exclusion_neighbors({(12, 99), (13, 98)})
        self.assertEqual(neighbors[12], {99})
        self.assertEqual(neighbors[99], {12})
        self.assertTrue(series._components_have_excluded_pair({12}, {99}, neighbors))
        self.assertFalse(series._components_have_excluded_pair({12}, {98}, neighbors))
        self.assertFalse(series._components_have_excluded_pair({12}, {98}, {}))

    def test_missing_or_empty_neighbor_sets_do_not_create_false_exclusions(self):
        self.assertFalse(
            series._components_have_excluded_pair(
                {1, 2}, {3, 4}, {1: set(), 2: set()}
            )
        )
        self.assertTrue(
            series._components_have_excluded_pair(
                {1, 2}, {3, 4}, {1: {4}}
            )
        )


class BundleOverrideBatchingTests(unittest.TestCase):
    def test_search_grouping_applies_override_from_one_bulk_read(self):
        first = media(1, "Same Series", "TV")
        second = media(2, "Same Series", "TV")
        override = {
            "bundle_anchor_id": 1,
            "custom_title": "My Custom Series",
            "cover_work_id": 2,
            "custom_cover_path": None,
        }
        with (
            patch("series.get_manual_bundle_links", return_value=[]),
            patch("series.get_bundle_exclusions", return_value=[]),
            patch("series.get_bundle_overrides", return_value=[override]) as bulk,
            patch("series.get_bundle_override") as single,
            patch("series.get", return_value=False),
        ):
            groups = series.group_media_results([first, second], enrich=False)

        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["title"], "My Custom Series")
        self.assertEqual(groups[0]["_bundle_cover_work_id"], 2)
        bulk.assert_called_once_with([1, 2])
        single.assert_not_called()



class LargeLibraryRelationQueryTests(unittest.TestCase):
    def test_relation_lookup_chunks_large_id_sets_and_deduplicates_cross_chunk_edges(self):
        with tempfile.TemporaryDirectory(prefix="nekotrack-relations-") as temporary:
            with patch.object(database, "DATABASE_NAME", str(Path(temporary) / "relations.sqlite3")):
                connection = database.get_connection()
                try:
                    connection.execute("""
                        CREATE TABLE work_relations (
                            source_id INTEGER NOT NULL,
                            target_id INTEGER NOT NULL,
                            relation_type TEXT NOT NULL,
                            PRIMARY KEY (source_id, target_id, relation_type)
                        )
                    """)
                    connection.executemany(
                        "INSERT INTO work_relations VALUES (?, ?, ?)",
                        [
                            (10, 900, "SEQUEL"),
                            (1200, 1100, "PREQUEL"),
                            (1500, 10, "SIDE_STORY"),
                            (10, 1500, "SPIN_OFF"),
                            (5, 6, "OTHER"),
                        ],
                    )
                    connection.commit()
                finally:
                    connection.close()

                rows = series._relation_data_for(set(range(1, 1201)))

        actual = [
            (int(row["source_id"]), int(row["target_id"]), str(row["relation_type"]))
            for row in rows
        ]
        self.assertEqual(len(actual), 4)
        self.assertCountEqual(actual, [
            (10, 900, "SEQUEL"),
            (1200, 1100, "PREQUEL"),
            (1500, 10, "SIDE_STORY"),
            (10, 1500, "SPIN_OFF"),
        ])


    def test_relation_lookup_reuses_a_supplied_connection_without_closing_it(self):
        with tempfile.TemporaryDirectory(prefix="nekotrack-relations-shared-") as temporary:
            with patch.object(database, "DATABASE_NAME", str(Path(temporary) / "relations.sqlite3")):
                connection = database.get_connection()
                try:
                    connection.execute("""
                        CREATE TABLE work_relations (
                            source_id INTEGER NOT NULL,
                            target_id INTEGER NOT NULL,
                            relation_type TEXT NOT NULL,
                            PRIMARY KEY (source_id, target_id, relation_type)
                        )
                    """)
                    connection.executemany(
                        "INSERT INTO work_relations VALUES (?, ?, ?)",
                        [
                            (10, 900, "SEQUEL"),
                            (400, 401, "PREQUEL"),
                            (1200, 1100, "PREQUEL"),
                            (1500, 10, "SIDE_STORY"),
                        ],
                    )
                    connection.commit()
                finally:
                    connection.close()

                ids = set(range(1, 1201))
                expected = [
                    dict(row) for row in series._relation_data_for(ids)
                ]
                connection = database.get_connection()
                try:
                    with patch.object(
                        series,
                        "get_connection",
                        wraps=database.get_connection,
                    ) as connection_factory:
                        actual = [
                            dict(row)
                            for row in series._relation_data_for(ids, connection=connection)
                        ]
                    connection_factory.assert_not_called()
                    self.assertEqual(actual, expected)
                    self.assertEqual(connection.execute("SELECT 1").fetchone()[0], 1)
                finally:
                    connection.close()




class ComponentUnionBySizeTests(unittest.TestCase):
    @staticmethod
    def _find(parent, item_id):
        while parent[item_id] != item_id:
            parent[item_id] = parent[parent[item_id]]
            item_id = parent[item_id]
        return item_id

    def test_small_to_large_merge_preserves_members_and_avoids_repeated_large_copies(self):
        count = 4096
        balanced_parent = {item_id: item_id for item_id in range(count)}
        balanced_members = {item_id: {item_id} for item_id in range(count)}
        balanced_moves = 0

        reference_parent = {item_id: item_id for item_id in range(count)}
        reference_members = {item_id: {item_id} for item_id in range(count)}
        reference_moves = 0

        # The descending chain is hostile to the former "always attach right
        # to left" rule: each merge would copy the entire growing component.
        for left_id in range(count - 2, -1, -1):
            balanced_left = self._find(balanced_parent, left_id)
            balanced_right = self._find(balanced_parent, left_id + 1)
            if balanced_left != balanced_right:
                _root, moved = series._merge_component_roots(
                    balanced_parent, balanced_members, balanced_left, balanced_right
                )
                balanced_moves += moved

            reference_left = self._find(reference_parent, left_id)
            reference_right = self._find(reference_parent, left_id + 1)
            if reference_left != reference_right:
                reference_moves += len(reference_members[reference_right])
                reference_parent[reference_right] = reference_left
                reference_members[reference_left].update(
                    reference_members.pop(reference_right)
                )

        balanced_components = {}
        reference_components = {}
        for item_id in range(count):
            balanced_components.setdefault(
                self._find(balanced_parent, item_id), set()
            ).add(item_id)
            reference_components.setdefault(
                self._find(reference_parent, item_id), set()
            ).add(item_id)

        self.assertEqual(
            {frozenset(members) for members in balanced_components.values()},
            {frozenset(members) for members in reference_components.values()},
        )
        self.assertEqual(len(balanced_components), 1)
        self.assertEqual(next(iter(balanced_components.values())), set(range(count)))
        self.assertLessEqual(balanced_moves, count)
        self.assertGreater(reference_moves, count * count // 4)

    def test_snapshot_sets_follow_the_selected_root(self):
        parent = {1: 1, 2: 2, 3: 3}
        members = {1: {1}, 2: {2, 3}, 3: set()}
        snapshots = {1: {100}, 2: {200}, 3: set()}
        # Use consistent disjoint-set keys and validate that the larger root,
        # along with its snapshot IDs, survives the small-to-large merge.
        parent = {1: 1, 2: 2}
        members = {1: {1}, 2: {2, 3}}
        snapshots = {1: {100}, 2: {200}}
        root, moved = series._merge_component_roots(
            parent, members, 1, 2, snapshots
        )
        self.assertEqual(root, 2)
        self.assertEqual(moved, 1)
        self.assertEqual(parent, {1: 2, 2: 2})
        self.assertEqual(members, {2: {1, 2, 3}})
        self.assertEqual(snapshots, {2: {100, 200}})



class BundleOptionTests(unittest.TestCase):
    def test_tv_and_tv_short_are_always_bundleable(self):
        with patch("series.get", return_value=False):
            self.assertTrue(series._auto_bundleable(media(1, "Series", "TV")))
            self.assertTrue(series._auto_bundleable(media(2, "Series Short", "TV_SHORT")))

    def test_extra_formats_follow_preferences(self):
        settings = {
            "bundle_include_movies": False, "bundle_include_ovas": True,
            "bundle_include_onas": False, "bundle_include_specials": True,
            "bundle_include_manga": False, "bundle_include_novels": True,
            "bundle_include_one_shots": False,
        }
        with patch("series.get", side_effect=lambda key: settings.get(key, False)):
            self.assertFalse(series._auto_bundleable(media(1, "Movie", "MOVIE")))
            self.assertTrue(series._auto_bundleable(media(2, "OVA", "OVA")))
            self.assertFalse(series._auto_bundleable(media(3, "ONA", "ONA")))
            self.assertTrue(series._auto_bundleable(media(4, "Special", "SPECIAL")))
            self.assertFalse(series._auto_bundleable(media(5, "Manga", "MANGA", "MANGA")))
            self.assertTrue(series._auto_bundleable(media(6, "Novel", "NOVEL", "MANGA")))
            self.assertFalse(series._auto_bundleable(media(7, "One shot", "ONE_SHOT", "MANGA")))

    def test_ova_only_joins_tv_bundle_when_enabled(self):
        tv = media(1, "Example Series", "TV", relations=[
            edge("SIDE_STORY", {
                "id": 2, "type": "ANIME", "format": "OVA",
                "title": {"english": "Example Series OVA", "romaji": "Example Series OVA"},
                "coverImage": {"large": None},
                "startDate": {"year": 2021, "month": 1, "day": 1},
            })
        ])
        ova = media(2, "Example Series OVA", "OVA")
        with patch("series.get_manual_bundle_links", return_value=[]), patch("series.get_bundle_exclusions", return_value=[]), patch("series.get", return_value=False):
            default_groups = series.group_media_results([tv, ova], enrich=False)
        with patch("series.get_manual_bundle_links", return_value=[]), patch("series.get_bundle_exclusions", return_value=[]), patch("series.get", side_effect=lambda key: key == "bundle_include_ovas"):
            enabled_groups = series.group_media_results([tv, ova], enrich=False)
        self.assertEqual(len(default_groups), 2)
        self.assertEqual(len(enabled_groups), 1)
        self.assertEqual(enabled_groups[0]["_series_count"], 2)

    def test_manual_links_override_auto_bundle_rules(self):
        tv = media(1, "Main Series", "TV")
        music = media(2, "Unbundleable Theme Song", "MUSIC")
        with patch("series.get_manual_bundle_links", return_value=[{"work_a": 1, "work_b": 2}]), patch("series.get_bundle_exclusions", return_value=[]), patch("series.get", return_value=False):
            groups = series.group_media_results([tv, music], enrich=False)
        self.assertEqual(len(groups), 1)
        self.assertEqual({item["id"] for item in groups[0]["_series_members"]}, {1, 2})

    def test_exclusion_prevents_same_title_auto_grouping(self):
        first = media(1, "Same Series", "TV")
        second = media(2, "Same Series", "TV")
        with patch("series.get_manual_bundle_links", return_value=[]), patch("series.get_bundle_exclusions", return_value=[{"work_a": 1, "work_b": 2}]), patch("series.get", return_value=False):
            groups = series.group_media_results([first, second], enrich=False)
        self.assertEqual(len(groups), 2)

    def test_exclusion_cannot_be_bypassed_through_a_transitive_relation(self):
        first = media(11, "Echo Series", "TV", relations=[
            edge("SEQUEL", {
                "id": 12, "type": "ANIME", "format": "TV",
                "title": {"english": "Echo Series Season 2", "romaji": "Echo Series Season 2"},
                "coverImage": {"large": None},
                "startDate": {"year": 2021, "month": 1, "day": 1},
            }),
            edge("SEQUEL", {
                "id": 13, "type": "ANIME", "format": "TV",
                "title": {"english": "Echo Series Season 3", "romaji": "Echo Series Season 3"},
                "coverImage": {"large": None},
                "startDate": {"year": 2022, "month": 1, "day": 1},
            }),
        ])
        second = media(12, "Echo Series Season 2", "TV", relations=[
            edge("PREQUEL", {
                "id": 11, "type": "ANIME", "format": "TV",
                "title": {"english": "Echo Series", "romaji": "Echo Series"},
                "coverImage": {"large": None},
                "startDate": {"year": 2020, "month": 1, "day": 1},
            }),
            edge("SEQUEL", {
                "id": 13, "type": "ANIME", "format": "TV",
                "title": {"english": "Echo Series Season 3", "romaji": "Echo Series Season 3"},
                "coverImage": {"large": None},
                "startDate": {"year": 2022, "month": 1, "day": 1},
            }),
        ])
        third = media(13, "Echo Series Season 3", "TV", relations=[
            edge("PREQUEL", {
                "id": 12, "type": "ANIME", "format": "TV",
                "title": {"english": "Echo Series Season 2", "romaji": "Echo Series Season 2"},
                "coverImage": {"large": None},
                "startDate": {"year": 2021, "month": 1, "day": 1},
            }),
        ])

        with patch("series.get_manual_bundle_links", return_value=[]), \
             patch("series.get_bundle_exclusions", return_value=[{"work_a": 11, "work_b": 12}]), \
             patch("series.get", return_value=False):
            groups = series.group_media_results([first, second, third], enrich=False)

        memberships = [
            {member["id"] for member in group["_series_members"]}
            for group in groups
        ]
        self.assertTrue(any(11 in members for members in memberships))
        self.assertTrue(any(12 in members for members in memberships))
        self.assertFalse(any({11, 12} <= members for members in memberships))

    def test_unrelated_spin_off_is_not_traversed(self):
        root = media(1, "One Piece", "TV", relations=[
            edge("SPIN_OFF", {
                "id": 2, "type": "ANIME", "format": "TV",
                "title": {"english": "MONSTERS", "romaji": "MONSTERS"},
                "coverImage": {"large": None},
                "startDate": {"year": 2024, "month": 1, "day": 1},
            })
        ])
        with patch("series.get_manual_bundle_links", return_value=[]), patch("series.get_bundle_exclusions", return_value=[]), patch("series.get", return_value=False):
            groups = series.group_media_results([root], enrich=False)
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["_series_count"], 1)



class RelationPendingQueueTests(unittest.TestCase):
    @staticmethod
    def _reference_has_pending(results):
        seen = set()
        queue = list(results)
        while queue:
            item = queue.pop(0)
            item_id = int(item["id"])
            if item_id in seen:
                continue
            seen.add(item_id)
            if series._get(item, "_relations_loaded"):
                edges = series._search_relation_edges(item)
            else:
                cached = series._relation_cache.get(item_id)
                if cached:
                    edges = (cached.get("relations") or {}).get("edges", [])
                elif series._get(item, "_related_only"):
                    return True
                else:
                    edges = series._search_relation_edges(item)
            for relation in edges:
                if not series._relation_edge_allowed(item, relation):
                    continue
                node = relation.get("node") or {}
                target_id = node.get("id")
                if (
                    target_id
                    and int(target_id) not in seen
                    and int(target_id) not in series._relation_cache
                ):
                    queue.append(series._related_placeholder(node))
        return False

    def test_deque_fifo_matches_reference_on_a_large_loaded_frontier(self):
        frontier = []
        for work_id in range(1, 2501):
            item = media(work_id, f"Synthetic Series {work_id}", "TV")
            item["_relations_loaded"] = True
            frontier.append(item)

        with patch.object(series, "_relation_cache", series._BoundedRelationCache()):
            expected = self._reference_has_pending(frontier)
            actual = series.has_pending_relation_enrichment(frontier)

        self.assertFalse(expected)
        self.assertEqual(actual, expected)

    def test_deque_traversal_still_detects_an_uncached_related_placeholder(self):
        root = media(1, "Example Series", "TV", relations=[
            edge("SEQUEL", {
                "id": 2,
                "type": "ANIME",
                "format": "TV",
                "title": {"english": "Example Series Season 2", "romaji": "Example Series Season 2"},
                "coverImage": {"large": None},
                "episodes": 12,
                "startDate": {"year": 2021, "month": 1, "day": 1},
            })
        ])
        root["_relations_loaded"] = True

        with patch.object(series, "_relation_cache", series._BoundedRelationCache()):
            expected = self._reference_has_pending([root])
            actual = series.has_pending_relation_enrichment([root])

        self.assertTrue(expected)
        self.assertEqual(actual, expected)



class RelationBatchFailureIsolationTests(unittest.TestCase):
    def test_anilist_batch_failure_does_not_fan_out_to_single_item_requests(self):
        ids = [910001, 910002, 910003, 910004, 910005]
        calls = []

        def fail_batch(request_ids):
            calls.append(list(request_ids))
            raise RuntimeError("AniList temporarily unavailable")

        with (
            patch.object(series, "_relation_cache", series._BoundedRelationCache()),
            patch("series.get_media_relations_batch", side_effect=fail_batch),
        ):
            result = series._cache_relation_details_batch(ids)

        self.assertEqual(result, {})
        self.assertEqual(calls, [ids])

    def test_anilist_failure_does_not_block_negative_mangabaka_ids(self):
        positive_id = 920001
        local_id = -920001
        local_details = {
            "id": local_id, "type": "MANGA", "format": "MANGA",
            "title": {"english": "Local title"}, "relations": {"edges": []},
        }
        calls = []

        def split_provider_fetch(request_ids):
            calls.append(list(request_ids))
            if request_ids == [positive_id]:
                raise RuntimeError("AniList temporarily unavailable")
            return {local_id: local_details}

        with (
            patch.object(series, "_relation_cache", series._BoundedRelationCache()),
            patch("series.get_media_relations_batch", side_effect=split_provider_fetch),
        ):
            result = series._cache_relation_details_batch([positive_id, local_id])

        self.assertEqual(calls, [[positive_id], [local_id]])
        self.assertEqual(result, {local_id: local_details})





class BoundedRelationCacheTests(unittest.TestCase):
    def test_cache_promotes_reads_and_evicts_least_recently_used(self):
        cache = series._BoundedRelationCache(max_entries=2)
        cache[1] = {"id": 1}
        cache[2] = {"id": 2}
        self.assertEqual(cache.get(1), {"id": 1})
        cache[3] = {"id": 3}

        self.assertEqual(list(cache), [1, 3])
        self.assertNotIn(2, cache)

    def test_cache_operations_are_safe_while_worker_threads_mutate_it(self):
        cache = series._BoundedRelationCache(max_entries=64)
        failures = []
        start = threading.Barrier(4)

        def writer(offset):
            try:
                start.wait()
                for index in range(1500):
                    key = offset * 10000 + index
                    cache[key] = {"id": key}
                    cache.get(key)
                    if index % 7 == 0:
                        cache.pop(key - 1, None)
            except Exception as error:
                failures.append(error)

        def reader():
            try:
                start.wait()
                for _ in range(1500):
                    keys = list(cache)
                    for key in keys[:8]:
                        cache.get(key)
                    if len(cache) > cache.max_entries:
                        failures.append(AssertionError("LRU cache exceeded its configured limit"))
            except Exception as error:
                failures.append(error)

        threads = [
            threading.Thread(target=writer, args=(1,)),
            threading.Thread(target=writer, args=(2,)),
            threading.Thread(target=reader),
            threading.Thread(target=reader),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(failures, [])
        self.assertLessEqual(len(cache), cache.max_entries)

    def test_batch_returns_all_results_even_when_cache_limit_is_exceeded(self):
        cache = series._BoundedRelationCache(max_entries=2)
        details = {
            work_id: {
                "id": work_id,
                "relations": {"edges": []},
            }
            for work_id in (1, 2, 3)
        }
        with (
            patch.object(series, "_relation_cache", cache),
            patch("series.get_media_relations_batch", return_value=details),
        ):
            result = series._cache_relation_details_batch([1, 2, 3])

        self.assertEqual(result, details)
        self.assertEqual(list(cache), [2, 3])
        self.assertLessEqual(len(cache), cache.max_entries)




class AutoBundleActionTests(unittest.TestCase):
    def test_auto_bundle_reuses_library_grouping_and_persists_its_member_snapshot(self):
        import sqlite3

        connection = sqlite3.connect(":memory:")
        self.addCleanup(connection.close)
        connection.row_factory = sqlite3.Row
        current = connection.execute("SELECT 501 AS id").fetchone()
        related = connection.execute("SELECT 502 AS id").fetchone()
        group = {
            "id": 501,
            "title": {"english": "Current"},
            "_series_count": 2,
            "_series_members": [current, related],
        }
        with (
            patch("series.get_all_library", return_value=[current, related]),
            patch("series.sync_library_relations", return_value=True) as sync,
            patch("series.get_library_series", side_effect=[[group], [group]]),
            patch("series.save_automatic_bundle_membership", return_value=True) as save,
        ):
            result = series.auto_bundle_library_work(501)

        sync.assert_called_once_with(force_ids={501})
        save.assert_called_once_with(501, [501, 502])
        self.assertEqual(result["count"], 2)
        self.assertTrue(result["relations_refreshed"])
        self.assertEqual(result["group"], group)

    def test_auto_bundle_refuses_non_library_work_before_touching_relations(self):
        with patch("series.get_all_library", return_value=[]), patch(
            "series.sync_library_relations"
        ) as sync:
            with self.assertRaisesRegex(ValueError, "Library"):
                series.auto_bundle_library_work(501)
        sync.assert_not_called()

    def test_auto_bundle_refuses_non_anilist_ids(self):
        with patch("series.get_all_library") as get_library:
            with self.assertRaisesRegex(ValueError, "AniList"):
                series.auto_bundle_library_work(-501)
        get_library.assert_not_called()


if __name__ == "__main__":
    unittest.main()
