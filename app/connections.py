"""Bound live dashboard streams independently of short-lived HTTP requests."""
import threading
import time

DEFAULT_LIMIT = 20
MAX_LIMIT = 200
REQUEST_LIMIT = 32
REQUEST_TIMEOUT = 30
HANDOVER_TIMEOUT = 1


def ensure_settings(db):
    # Settings travel in both backup formats; older databases get the default.
    db.execute("INSERT OR IGNORE INTO settings VALUES ('dashboard_connection_limit',?)",
               (str(DEFAULT_LIMIT),))


def configured_limit(db):
    row = db.execute("SELECT value FROM settings WHERE key='dashboard_connection_limit'").fetchone()
    try:
        value = int(row[0]) if row else DEFAULT_LIMIT
        return value if 1 <= value <= MAX_LIMIT else DEFAULT_LIMIT
    except (ValueError, TypeError):
        return DEFAULT_LIMIT


class StreamLease:
    """One stream generation; its completion belongs only to this handle."""

    def __init__(self, key, cancel, thread):
        self.key = key
        self.cancel = cancel
        self.thread = thread
        self.stopped = threading.Event()
        self.finished = threading.Event()
        self.replacing = False

    def stop(self):
        self.stopped.set()
        if self.cancel:
            self.cancel()


class StreamConnections:
    def __init__(self):
        self._slots = {}
        self._lock = threading.Lock()

    def _prune_finished(self):
        # A worker signals completion in its finalizer. Keep counting it until
        # its thread has also exited, including a stalled handover finalizer.
        for key, lease in list(self._slots.items()):
            if (not lease.replacing and lease.finished.is_set()
                    and (lease.thread is None or not lease.thread.is_alive())):
                del self._slots[key]

    def acquire(self, maximum, key=None, cancel=None, thread=None):
        # Legacy clients without a tab ID still get independent bounded slots.
        key = key if key is not None else object()
        with self._lock:
            self._prune_finished()
            previous = self._slots.get(key)
            if previous is None:
                if len(self._slots) >= maximum:
                    return None
                lease = StreamLease(key, cancel, thread)
                self._slots[key] = lease
                return lease
            if previous.replacing:
                return None
            previous.replacing = True

        # Keep the slot reserved during handover. The incoming request remains
        # in the ordinary request pool until the old worker actually terminates.
        # Neither a refresh nor many concurrent replacements can bypass limits.
        deadline = time.monotonic() + HANDOVER_TIMEOUT
        replaced = False
        try:
            previous.stop()
            if not previous.finished.wait(max(0, deadline - time.monotonic())):
                return None
            if previous.thread is not None:
                previous.thread.join(max(0, deadline - time.monotonic()))
                if previous.thread.is_alive():
                    return None
            with self._lock:
                lease = StreamLease(key, cancel, thread)
                self._slots[key] = lease
                replaced = True
                return lease
        finally:
            if not replaced:
                with self._lock:
                    previous.replacing = False
                    self._prune_finished()

    def release(self, lease):
        with self._lock:
            lease.finished.set()
            self._prune_finished()

    def counts(self, maximum):
        with self._lock:
            self._prune_finished()
            return {'connections': len(self._slots), 'connection_limit': maximum}


streams = StreamConnections()
