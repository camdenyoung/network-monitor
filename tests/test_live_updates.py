"""Live invalidations carry no private state and wake all dashboard listeners."""
import concurrent.futures
import io
import json
import unittest
from unittest.mock import patch

from app import live_updates, server


class LiveUpdateTests(unittest.TestCase):
    def test_all_waiters_observe_a_change_and_reconnect_gets_current_revision(self):
        original = live_updates.current_revision()
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            waiters = [pool.submit(live_updates.wait_for_change, original, 1) for _ in range(2)]
            live_updates.publish_acknowledgement_change()
            results = [waiter.result(timeout=2) for waiter in waiters]
        self.assertNotEqual(results[0], original)
        self.assertEqual(results[0], results[1])
        self.assertEqual(live_updates.current_revision(), results[0])
        self.assertEqual(live_updates.wait_for_change(results[0], timeout=0), results[0])

    def test_public_stream_flushes_revisions_and_heartbeats_without_private_data(self):
        handler = object.__new__(server.Handler)
        handler.path = '/api/ack-events'
        handler.wfile = io.BytesIO()
        headers = {}
        statuses = []
        handler.send_response = statuses.append
        handler.send_header = lambda key, value: headers.update({key: value})
        handler.end_headers = lambda: None
        with patch.object(live_updates, 'current_revision', return_value='first-revision'), \
                patch.object(live_updates, 'wait_for_change', side_effect=['first-revision', 'next-revision', OSError()]):
            handler.do_GET()
        text = handler.wfile.getvalue().decode()
        self.assertEqual(statuses, [200])
        self.assertEqual(headers['Content-Type'], 'text/event-stream')
        self.assertEqual(headers['X-Accel-Buffering'], 'no')
        self.assertEqual(headers['Cache-Control'], 'no-store')
        self.assertIn(': keepalive\n\n', text)
        events = [json.loads(line.removeprefix('data: ')) for line in text.splitlines() if line.startswith('data: ')]
        self.assertEqual(events, [{'revision': 'first-revision'}, {'revision': 'next-revision'}])
