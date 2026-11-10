"""Approximate dashboard presence, refreshed by each tab's normal polling.

This is operational information, never an authentication or authorization signal.
No browser identifiers or session credentials are exposed in the count response.
"""
import re
import threading
import time

CONNECTION_ID = re.compile(r'[A-Za-z0-9-]{16,80}')


class DashboardPresence:
    def __init__(self, timeout=60, capacity=4096):
        self.timeout = timeout
        self.capacity = capacity
        self._connections = {}
        self._lock = threading.Lock()

    def _prune(self, now):
        expired = [key for key, entry in self._connections.items()
                   if now - entry['seen'] >= self.timeout]
        for key in expired:
            del self._connections[key]

    def record(self, connection, user=None):
        # A random per-page ID distinguishes tabs without relying on NAT/IPs.
        # Legacy clients/probes without the header do not create phantom viewers.
        if not isinstance(connection, str) or not CONNECTION_ID.fullmatch(connection):
            return
        now = time.monotonic()
        with self._lock:
            self._prune(now)
            if connection not in self._connections and len(self._connections) >= self.capacity:
                oldest = min(self._connections, key=lambda key: self._connections[key]['seen'])
                del self._connections[oldest]
            self._connections[connection] = {
                'seen': now, 'csrf': user['csrf'] if user else None,
            }

    def _active_users(self, valid_sessions):
        # Caller holds the tracker lock; session validity comes from SQLite.
        return {valid_sessions[entry['csrf']] for entry in self._connections.values()
                if entry['csrf'] in valid_sessions}

    def online_users(self, valid_sessions):
        """Return recently active account IDs for the Admin user list only."""
        with self._lock:
            self._prune(time.monotonic())
            return self._active_users(valid_sessions)

    def counts(self, valid_sessions):
        """Deduplicate accounts and exclude logged-out, expired or revoked sessions."""
        with self._lock:
            self._prune(time.monotonic())
            users = self._active_users(valid_sessions)
            return {'logged_in_users': len(users), 'connections': len(self._connections),
                    'activity_window_seconds': self.timeout}


tracker = DashboardPresence()
