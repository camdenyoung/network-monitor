"""Presence counts active tabs and accounts without changing authentication."""
import unittest
from unittest.mock import patch

from app.presence import DashboardPresence


class PresenceTests(unittest.TestCase):
    def test_tabs_are_separate_but_accounts_are_unique(self):
        tracker = DashboardPresence()
        tracker.record('first-dashboard-tab', {'csrf': 'alice-session-a'})
        tracker.record('second-dashboard-tab', {'csrf': 'alice-session-b'})
        tracker.record('third-dashboard-tab', {'csrf': 'bob-session'})
        tracker.record('anonymous-status-tab')
        sessions = {'alice-session-a': 1, 'alice-session-b': 1, 'bob-session': 2}
        self.assertEqual(tracker.counts(sessions), {
            'logged_in_users': 2, 'connections': 4, 'activity_window_seconds': 60})
        self.assertEqual(tracker.online_users(sessions), {1, 2})
        self.assertEqual(tracker.online_users({}), set())
        # Logging out or revoking a session removes attribution immediately.
        self.assertEqual(tracker.counts({})['logged_in_users'], 0)
        tracker.record('first-dashboard-tab')
        self.assertEqual(tracker.counts({'alice-session-a': 1})['logged_in_users'], 0)

    def test_stale_tabs_expire_but_polling_keeps_a_tab_active(self):
        tracker = DashboardPresence()
        with patch('app.presence.time.monotonic', return_value=100):
            tracker.record('first-dashboard-tab')
            tracker.record('second-dashboard-tab')
        with patch('app.presence.time.monotonic', return_value=150):
            tracker.record('first-dashboard-tab')
        with patch('app.presence.time.monotonic', return_value=160):
            self.assertEqual(tracker.counts({})['connections'], 1)
        with patch('app.presence.time.monotonic', return_value=210):
            self.assertEqual(tracker.counts({})['connections'], 0)

    def test_invalid_ids_and_capacity_are_bounded(self):
        tracker = DashboardPresence(capacity=2)
        for value in (None, '', 'short', 'x' * 81, '<script>bad-id-value</script>'):
            tracker.record(value)
        self.assertEqual(tracker.counts({})['connections'], 0)
        for index in range(3):
            tracker.record(f'dashboard-connection-{index}')
        self.assertEqual(tracker.counts({})['connections'], 2)
