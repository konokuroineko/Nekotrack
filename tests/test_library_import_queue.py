"""Tests for bounded background Library import scheduling."""
import unittest

from library_import_queue import LibraryImportQueue


class LibraryImportQueueTests(unittest.TestCase):
    def test_queue_never_reserves_more_than_limit_and_deduplicates_ids(self):
        queue = LibraryImportQueue(max_concurrent=2)

        self.assertEqual(queue.enqueue([1, 2, 3, 4, 3, 2]), [1, 2])
        self.assertEqual(queue.active_ids, frozenset({1, 2}))
        self.assertEqual(queue.pending_ids, (3, 4))
        self.assertEqual(queue.enqueue([2, 4, 5]), [])
        self.assertEqual(queue.pending_ids, (3, 4, 5))

        self.assertEqual(queue.complete(1), [3])
        self.assertEqual(queue.active_ids, frozenset({2, 3}))
        self.assertEqual(queue.complete(2), [4])
        self.assertEqual(queue.complete(3), [5])
        self.assertEqual(queue.complete(4), [])
        self.assertEqual(queue.complete(5), [])
        self.assertEqual(queue.active_ids, frozenset())

    def test_negative_provider_ids_are_supported_and_invalid_ids_are_ignored(self):
        queue = LibraryImportQueue(max_concurrent=1)
        self.assertEqual(
            queue.enqueue([True, 0, "bad", -148237, -148237]), [-148237]
        )
        self.assertEqual(queue.pending_ids, ())
        self.assertEqual(queue.active_ids, frozenset({-148237}))

    def test_close_discards_pending_work_but_keeps_active_workers_tracked(self):
        queue = LibraryImportQueue(max_concurrent=2)
        self.assertEqual(queue.enqueue([1, 2, 3, 4]), [1, 2])

        self.assertEqual(queue.close(), frozenset({1, 2}))
        self.assertTrue(queue.is_closed)
        self.assertEqual(queue.pending_ids, ())
        self.assertEqual(queue.complete(1), [])
        self.assertEqual(queue.enqueue([5, 6]), [])
        self.assertEqual(queue.active_ids, frozenset({2}))
        self.assertEqual(queue.complete(2), [])
        self.assertEqual(queue.active_ids, frozenset())

    def test_invalid_concurrency_limit_is_rejected(self):
        for limit in (0, -1, True):
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                LibraryImportQueue(max_concurrent=limit)


if __name__ == "__main__":
    unittest.main()
