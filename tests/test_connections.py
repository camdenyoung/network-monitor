"""Admission, durable Admin settings, and real HTTP disconnect/timeout behaviour."""
import concurrent.futures
from contextlib import closing
import http.client
import json
import socket
import sqlite3
import threading
import time
import unittest
from unittest.mock import Mock, patch

from app import connections, server
import test_access_notifications as support


class ConnectionCounterTests(unittest.TestCase):
    def test_handover_reserves_slot_and_old_cleanup_cannot_remove_replacement(self):
        streams = connections.StreamConnections()
        counts = []

        def cancel():
            counts.append(streams.counts(1)['connections'])
            streams.release(first)
            counts.append(streams.counts(1)['connections'])

        first = streams.acquire(1, 'same-tab', cancel)
        replacement = streams.acquire(1, 'same-tab')
        self.assertIsNotNone(replacement)
        self.assertTrue(first.stopped.is_set())
        self.assertEqual(counts, [1, 1])
        streams.release(first)
        self.assertEqual(streams.counts(1)['connections'], 1)
        streams.release(replacement)
        self.assertEqual(streams.counts(1)['connections'], 0)

    def test_stalled_handover_retains_real_capacity_and_eventual_cleanup(self):
        streams = connections.StreamConnections()
        first = streams.acquire(1, 'same-tab')
        with patch.object(connections, 'HANDOVER_TIMEOUT', 0.01):
            self.assertIsNone(streams.acquire(1, 'same-tab'))
        self.assertTrue(first.stopped.is_set())
        self.assertIsNone(streams.acquire(1, 'other-tab'))
        streams.release(first)
        self.assertIsNotNone(streams.acquire(1, 'same-tab'))

    def test_a_stalled_thread_after_cleanup_still_occupies_its_slot(self):
        streams = connections.StreamConnections()
        thread = Mock()
        thread.is_alive.return_value = True
        first = streams.acquire(1, 'same-tab', thread=thread)
        streams.release(first)
        with patch.object(connections, 'HANDOVER_TIMEOUT', 0.01):
            self.assertIsNone(streams.acquire(1, 'same-tab'))
        self.assertEqual(streams.counts(1)['connections'], 1)
        self.assertIsNone(streams.acquire(1, 'other-tab'))
        thread.is_alive.return_value = False
        self.assertIsNotNone(streams.acquire(1, 'other-tab'))

    def test_concurrent_admission_never_exceeds_limit_and_lowering_keeps_connections(self):
        streams = connections.StreamConnections()
        with concurrent.futures.ThreadPoolExecutor(max_workers=32) as pool:
            accepted = list(pool.map(lambda _: streams.acquire(20), range(100)))
        self.assertEqual(sum(lease is not None for lease in accepted), 20)
        self.assertEqual(streams.counts(10), {'connections': 20, 'connection_limit': 10})
        self.assertFalse(streams.acquire(10))
        for lease in [lease for lease in accepted if lease is not None][:11]:
            streams.release(lease)
        self.assertTrue(streams.acquire(10))
        self.assertFalse(streams.acquire(10))
        self.assertTrue(streams.acquire(30))

    def test_missing_or_invalid_legacy_setting_falls_back_to_default(self):
        with closing(sqlite3.connect(':memory:')) as db:
            db.execute('CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT)')
            self.assertEqual(connections.configured_limit(db), 20)
            connections.ensure_settings(db)
            for value in ('bad', '-1', '0', '201', None):
                db.execute("UPDATE settings SET value=?", (value,))
                self.assertEqual(connections.configured_limit(db), 20)
            db.execute("UPDATE settings SET value='80'")
            connections.ensure_settings(db)
            self.assertEqual(connections.configured_limit(db), 80)


class ConnectionSettingsTests(unittest.TestCase):
    setUp = support.AccessAndNotificationTests.setUp
    tearDown = support.AccessAndNotificationTests.tearDown
    request = support.AccessAndNotificationTests.request
    create_operator = support.AccessAndNotificationTests.create_operator

    def test_malformed_stream_identity_is_rejected_before_admission(self):
        for query in ('connection=', 'connection=short', 'connection=%3Cscript%3E',
                      'connection=' + 'x' * 81,
                      'connection=valid-dashboard-id&connection=second-dashboard-id'):
            self.assertEqual(self.request('/api/ack-events?' + query)['status'], 400)

    def test_rapid_refresh_at_twenty_stream_capacity_stops_real_old_workers(self):
        # Keep all old client/upstream sockets open deliberately, as a proxy
        # may do. Use the real 15s heartbeat: replacement must wake it immediately.
        streams = connections.StreamConnections()
        clients, responses, retired = [], [], []
        with patch.object(connections, 'streams', streams), patch.object(server.Handler, 'log_message'):
            with server.MonitorHTTPServer(('127.0.0.1', 0), server.Handler) as httpd:
                worker = threading.Thread(target=httpd.serve_forever, daemon=True)
                worker.start()

                def connect(key):
                    client = http.client.HTTPConnection(*httpd.server_address, timeout=3)
                    clients.append(client)
                    client.request('GET', '/api/ack-events?connection=' + key)
                    response = client.getresponse()
                    responses.append(response)
                    return response

                try:
                    for index in range(20):
                        self.assertEqual(connect(f'dashboard-refresh-{index:02}').status, 200)
                    self.assertEqual(streams.counts(20)['connections'], 20)
                    self.assertEqual(connect('dashboard-different-tab').status, 503)
                    responses[-1].read()
                    for _ in range(15):
                        with streams._lock:
                            old = streams._slots['dashboard-refresh-00']
                        started = time.monotonic()
                        self.assertEqual(connect('dashboard-refresh-00').status, 200)
                        self.assertLess(time.monotonic() - started, 2)
                        self.assertFalse(old.thread.is_alive())
                        retired.append(old.thread)
                        self.assertEqual(streams.counts(20)['connections'], 20)
                        with httpd._request_lock:
                            self.assertEqual(len(httpd._stream_requests), 20)
                    self.assertTrue(all(not thread.is_alive() for thread in retired))
                finally:
                    with streams._lock:
                        leases = list(streams._slots.values())
                    for lease in leases:
                        lease.stop()
                    for lease in leases:
                        lease.thread.join(timeout=2)
                        self.assertFalse(lease.thread.is_alive())
                    for response in responses:
                        response.close()
                    for client in clients:
                        client.close()
                    httpd.shutdown()
                    worker.join(timeout=2)
                    self.assertEqual(streams.counts(20)['connections'], 0)


    def test_admin_csrf_bounded_values_and_committed_live_setting(self):
        token, operator = self.create_operator()
        self.assertEqual(self.request('/api/connection-settings', {'maximum': 40})['status'], 401)
        for token, user in ((self.viewer_token, self.viewer), (token, operator)):
            self.assertEqual(self.request('/api/connection-settings', {'maximum': 40}, token, user['csrf'])['status'], 403)
        self.assertEqual(self.request('/api/connection-settings', {'maximum': 40}, self.admin_token)['status'], 403)
        for value in (0, 201, 1.5, True, '20', None):
            self.assertEqual(self.request('/api/connection-settings', {'maximum': value},
                                         self.admin_token, self.admin['csrf'])['status'], 400)
        committed = []

        def observe():
            with server.connect() as db:
                committed.append(connections.configured_limit(db))

        with patch.object(server.live_updates, 'publish_dashboard_change', side_effect=observe):
            for value in (1, 200, 40, 40):
                self.assertEqual(self.request('/api/connection-settings', {'maximum': value},
                                             self.admin_token, self.admin['csrf'])['status'], 200)
        self.assertEqual(committed, [1, 200, 40])
        server.initialize()
        with server.connect() as db:
            self.assertEqual(connections.configured_limit(db), 40)
        for kind in ('complete', 'configuration'):
            payload = self.request('/api/backup?kind=' + kind, token=self.admin_token)['content']
            with closing(sqlite3.connect(':memory:')) as candidate:
                candidate.deserialize(payload)
                server.prepare_restored_database(candidate)
                self.assertEqual(connections.configured_limit(candidate), 40)
                candidate.execute("DELETE FROM settings WHERE key='dashboard_connection_limit'")
                server.prepare_restored_database(candidate)
                self.assertEqual(connections.configured_limit(candidate), 20)

    def test_admin_count_uses_admitted_streams_not_polling_and_is_private(self):
        streams = connections.StreamConnections()
        with patch.object(connections, 'streams', streams):
            for _ in range(3):
                streams.acquire(20)
            state = json.loads(self.request('/api/state', token=self.admin_token)['content'])
            self.assertEqual(state['dashboard_presence']['connections'], 3)
            self.assertEqual(state['dashboard_presence']['connection_limit'], 20)
            for path, token in (('/api/state', self.viewer_token), ('/api/status', None)):
                self.assertNotIn('dashboard_presence', json.loads(self.request(path, token=token)['content']))

    def test_slot_released_even_if_response_headers_or_stream_body_fail(self):
        for failure in ('headers', 'write', 'flush', 'wait'):
            with self.subTest(failure=failure):
                handler = object.__new__(server.Handler)
                handler.wfile = Mock()
                handler.send_response = Mock()
                handler.send_header = Mock()
                handler.end_headers = Mock()
                if failure == 'headers':
                    handler.send_response.side_effect = BrokenPipeError
                elif failure in ('write', 'flush'):
                    getattr(handler.wfile, failure).side_effect = BrokenPipeError
                streams = connections.StreamConnections()
                with patch.object(connections, 'streams', streams), \
                        patch.object(server.live_updates, 'wait_for_change', side_effect=ConnectionResetError):
                    handler.stream_acknowledgement_changes()
                    self.assertEqual(streams.counts(20)['connections'], 0)

    def test_real_http_full_streams_leave_login_and_health_available_then_disconnect_reopens_slot(self):
        streams = connections.StreamConnections()
        with server.connect() as db:
            db.execute("UPDATE settings SET value='1' WHERE key='dashboard_connection_limit'")
        clients = []
        responses = []

        def wait_for_count(expected):
            deadline = time.monotonic() + 2
            while streams.counts(1)['connections'] != expected and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertEqual(streams.counts(1)['connections'], expected)

        # Fast heartbeats detect real socket closure without a 15-second test wait.
        def heartbeat(previous, stopped=None):
            time.sleep(0.02)
            return previous

        with patch.object(connections, 'streams', streams), \
                patch.object(server.live_updates, 'wait_for_change', side_effect=heartbeat):
            with server.MonitorHTTPServer(('127.0.0.1', 0), server.Handler) as httpd:
                worker = threading.Thread(target=httpd.serve_forever, daemon=True)
                worker.start()

                def get(path):
                    client = http.client.HTTPConnection(*httpd.server_address, timeout=2)
                    clients.append(client)
                    client.request('GET', path)
                    response = client.getresponse()
                    responses.append(response)
                    return response

                try:
                    live = get('/api/ack-events')
                    self.assertEqual(live.status, 200)
                    wait_for_count(1)
                    refused = get('/api/ack-events')
                    self.assertEqual(refused.status, 503)
                    self.assertEqual(refused.getheader('Retry-After'), '30')
                    refused.read()
                    self.assertEqual(get('/api/health').status, 200)
                    login = http.client.HTTPConnection(*httpd.server_address, timeout=2)
                    clients.append(login)
                    login.request('POST', '/api/login', json.dumps({'username': 'admin', 'password': 'Temporary-test-123'}),
                                  {'Content-Type': 'application/json'})
                    result = login.getresponse()
                    responses.append(result)
                    self.assertEqual(result.status, 200)
                    result.read()
                    live.close()
                    wait_for_count(0)
                    replacement = get('/api/ack-events')
                    self.assertEqual(replacement.status, 200)
                    wait_for_count(1)
                    # The admitted stream no longer occupies the request pool.
                    deadline = time.monotonic() + 2
                    while httpd._requests and time.monotonic() < deadline:
                        time.sleep(0.01)
                    self.assertEqual(len(httpd._requests), 0)
                    self.assertEqual(self.request('/api/connection-settings', {'maximum': 2},
                                                  self.admin_token, self.admin['csrf'])['status'], 200)
                    expanded = get('/api/ack-events')
                    self.assertEqual(expanded.status, 200)
                    wait_for_count(2)
                    self.assertEqual(self.request('/api/connection-settings', {'maximum': 1},
                                                  self.admin_token, self.admin['csrf'])['status'], 200)
                    # Lowering preserves both streams but refuses any new ones.
                    wait_for_count(2)
                    refused_again = get('/api/ack-events')
                    self.assertEqual(refused_again.status, 503)
                    refused_again.read()
                finally:
                    for response in responses:
                        response.close()
                    for client in clients:
                        client.close()
                    wait_for_count(0)
                    httpd.shutdown()
                    worker.join(timeout=2)

    def test_slow_headers_timeout_releases_request_capacity(self):
        with patch.object(server.Handler, 'timeout', 0.1):
            with server.MonitorHTTPServer(('127.0.0.1', 0), server.Handler) as httpd:
                worker = threading.Thread(target=httpd.serve_forever, daemon=True)
                worker.start()
                try:
                    with socket.create_connection(httpd.server_address, timeout=2) as client:
                        client.sendall(b'GET /api/health HTTP/1.1\r\nHost: localhost\r\n')
                        self.assertEqual(client.recv(1024), b'')
                    deadline = time.monotonic() + 2
                    while httpd._requests and time.monotonic() < deadline:
                        time.sleep(0.01)
                    self.assertEqual(len(httpd._requests), 0)
                finally:
                    httpd.shutdown()
                    worker.join(timeout=2)

    def test_request_pool_rejects_before_thread_creation_and_cleans_up_thread_errors(self):
        # No network is needed to prove an overflow cannot spawn another thread.
        httpd = object.__new__(server.MonitorHTTPServer)
        httpd._request_lock = threading.Lock()
        httpd._requests = set(range(connections.REQUEST_LIMIT))
        httpd._stream_requests = {}
        httpd.shutdown_request = Mock()
        request = Mock()
        with patch.object(server.ThreadingHTTPServer, 'process_request') as spawn:
            httpd.process_request(request, ('127.0.0.1', 1))
            spawn.assert_not_called()
        self.assertIn(b'503 Service Unavailable', request.sendall.call_args.args[0])
        httpd.shutdown_request.assert_called_once_with(request)
        httpd._requests.clear()
        with patch.object(server.ThreadingHTTPServer, 'process_request', side_effect=RuntimeError):
            with self.assertRaises(RuntimeError):
                httpd.process_request(request, ('127.0.0.1', 1))
        self.assertEqual(httpd._requests, set())
        httpd._requests.add(request)
        with patch.object(server.ThreadingHTTPServer, 'process_request_thread', side_effect=RuntimeError):
            with self.assertRaises(RuntimeError):
                httpd.process_request_thread(request, ('127.0.0.1', 1))
        self.assertEqual(httpd._requests, set())
