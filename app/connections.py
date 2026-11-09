"""Bound live dashboard streams independently of short-lived HTTP requests."""
import threading

DEFAULT_LIMIT = 20
MAX_LIMIT = 200
REQUEST_LIMIT = 32
REQUEST_TIMEOUT = 30


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


class StreamConnections:
    def __init__(self):
        self._current = 0
        self._lock = threading.Lock()

    def acquire(self, maximum):
        with self._lock:
            if self._current >= maximum:
                return False
            self._current += 1
            return True

    def release(self):
        with self._lock:
            self._current -= 1

    def counts(self, maximum):
        with self._lock:
            return {'connections': self._current, 'connection_limit': maximum}


streams = StreamConnections()
