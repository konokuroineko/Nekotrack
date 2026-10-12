"""Bounded, deduplicating scheduler for background Library metadata imports."""
from collections import deque


class LibraryImportQueue:
    """Reserve a bounded number of work IDs and keep the remainder in FIFO order.

    The GUI owns the workers and calls :meth:`complete` only when each worker's
    QThread has actually stopped.
    """

    def __init__(self, max_concurrent=2):
        if isinstance(max_concurrent, bool) or int(max_concurrent) < 1:
            raise ValueError("max_concurrent must be a positive integer")
        self.max_concurrent = int(max_concurrent)
        self._pending = deque()
        self._pending_ids = set()
        self._active_ids = set()
        self._closed = False

    def enqueue(self, work_ids):
        """Add valid unique IDs and return IDs that can start immediately."""
        if self._closed:
            return []
        try:
            values = iter(work_ids or ())
        except TypeError:
            return []
        for value in values:
            if isinstance(value, bool):
                continue
            try:
                work_id = int(value)
            except (TypeError, ValueError, OverflowError):
                continue
            if work_id == 0 or work_id in self._active_ids or work_id in self._pending_ids:
                continue
            self._pending.append(work_id)
            self._pending_ids.add(work_id)
        return self._reserve_available()

    def complete(self, work_id):
        """Release an active slot and reserve the next queued ID, if any."""
        try:
            work_id = int(work_id)
        except (TypeError, ValueError, OverflowError):
            return self._reserve_available()
        self._active_ids.discard(work_id)
        return self._reserve_available()

    def _reserve_available(self):
        started = []
        if self._closed:
            return started
        while self._pending and len(self._active_ids) < self.max_concurrent:
            work_id = self._pending.popleft()
            self._pending_ids.discard(work_id)
            if work_id in self._active_ids:
                continue
            self._active_ids.add(work_id)
            started.append(work_id)
        return started

    def close(self):
        """Stop accepting work and discard queued IDs without losing active IDs."""
        self._closed = True
        self._pending.clear()
        self._pending_ids.clear()
        return frozenset(self._active_ids)

    @property
    def active_ids(self):
        return frozenset(self._active_ids)

    @property
    def pending_ids(self):
        return tuple(self._pending)

    @property
    def is_closed(self):
        return self._closed
