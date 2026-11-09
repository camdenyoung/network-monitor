"""Live invalidations carry no private state and wake all dashboard listeners."""
import concurrent.futures
import io
import json
import threading
import unittest
from unittest.mock import patch

from app import live_updates, server
import test_access_notifications as support


class LiveUpdateTests(unittest.TestCase):
    def test_next_burst_cannot_postpone_an_existing_listener(self):
        clock = [100.0]

        def wait(seconds):
            clock[0] += seconds
            live_updates.publish_monitoring_change()

        with patch.object(live_updates, '_monitoring_due', 0), \
                patch.object(live_updates.time, 'monotonic', side_effect=lambda: clock[0]), \
                patch.object(live_updates._CHANGED, 'wait', side_effect=wait) as waiting:
            before = live_updates.current_revision()
            live_updates.publish_monitoring_change()
            self.assertNotEqual(live_updates.wait_for_change(before), before)
            self.assertEqual(waiting.call_count, 1)
            self.assertEqual(clock[0], 101.0)

    def test_monitoring_burst_uses_a_fixed_deadline_and_one_latest_revision(self):
        clock = [100.0]
        waits = []

        def wait(seconds):
            waits.append(seconds)
            clock[0] += seconds

        with patch.object(live_updates, '_monitoring_due', 0), \
                patch.object(live_updates.time, 'monotonic', side_effect=lambda: clock[0]), \
                patch.object(live_updates._CHANGED, 'wait', side_effect=wait):
            before = live_updates.current_revision()
            live_updates.publish_monitoring_change()
            clock[0] = 100.6
            live_updates.publish_monitoring_change()
            latest = live_updates.current_revision()
            self.assertEqual(live_updates._monitoring_due, 101.0)
            self.assertEqual(live_updates.wait_for_change(before), latest)
            self.assertEqual(len(waits), 1)
            self.assertAlmostEqual(waits[0], 0.4)
            # After the deadline, the next burst gets its own bounded window.
            live_updates.publish_monitoring_change()
            self.assertEqual(live_updates._monitoring_due, 102.0)

    def test_interactive_change_and_stream_cancellation_interrupt_coalescing(self):
        with patch.object(live_updates, '_monitoring_due', 0):
            before = live_updates.current_revision()
            live_updates.publish_monitoring_change()
            with patch.object(live_updates._CHANGED, 'wait', side_effect=lambda _: live_updates.publish_dashboard_change()) as wait:
                self.assertNotEqual(live_updates.wait_for_change(before), before)
                self.assertEqual(wait.call_count, 1)
                self.assertEqual(live_updates._monitoring_due, 0)
            before = live_updates.current_revision()
            live_updates.publish_monitoring_change()
            stopped = threading.Event()
            with patch.object(live_updates._CHANGED, 'wait', side_effect=lambda _: stopped.set()) as wait:
                live_updates.wait_for_change(before, stopped=stopped)
                self.assertEqual(wait.call_count, 1)

    def test_cancel_wakes_stream_without_a_data_revision_change(self):
        import threading
        stopped = threading.Event()
        revision = live_updates.current_revision()
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            waiting = pool.submit(live_updates.wait_for_change, revision, 15, stopped)
            stopped.set()
            live_updates.wake_waiters()
            self.assertEqual(waiting.result(timeout=1), revision)
        self.assertEqual(live_updates.current_revision(), revision)

    def test_all_waiters_observe_a_change_and_reconnect_gets_current_revision(self):
        original = live_updates.current_revision()
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            waiters = [pool.submit(live_updates.wait_for_change, original, 1) for _ in range(2)]
            live_updates.publish_dashboard_change()
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
        with patch.object(server, 'connect') as connect, \
                patch.object(live_updates, 'current_revision', return_value='first-revision'), \
                patch.object(live_updates, 'wait_for_change', side_effect=['first-revision', 'next-revision', OSError()]):
            connect.return_value.__enter__.return_value.execute.return_value.fetchone.return_value = ('20',)
            handler.do_GET()
        text = handler.wfile.getvalue().decode()
        self.assertEqual(statuses, [200])
        self.assertEqual(headers['Content-Type'], 'text/event-stream')
        self.assertEqual(headers['X-Accel-Buffering'], 'no')
        self.assertEqual(headers['Cache-Control'], 'no-store')
        self.assertIn(': keepalive\n\n', text)
        events = [json.loads(line.removeprefix('data: ')) for line in text.splitlines() if line.startswith('data: ')]
        self.assertEqual(events, [{'revision': 'first-revision'}, {'revision': 'next-revision'}])


class ControlLiveUpdateTests(unittest.TestCase):
    # Share disposable database/HTTP helpers without inheriting their tests.
    setUp = support.AccessAndNotificationTests.setUp
    tearDown = support.AccessAndNotificationTests.tearDown
    create_host = support.AccessAndNotificationTests.create_host
    create_operator = support.AccessAndNotificationTests.create_operator
    request = support.AccessAndNotificationTests.request

    def test_operational_controls_publish_only_after_their_state_commits(self):
        self.create_host()
        server.mutate('service', {'assignment': 1, 'name': 'RSSI', 'kind': 'snmp',
                                  'target': '.1.2.3', 'direction': 'below', 'warning': '', 'critical': ''})
        server.mutate('project', {'name': 'Other project'})
        observed = []

        def observe_commit():
            # A separate connection cannot see uncommitted writes. Inspect all
            # controls affected by deployment changes, not just the revision.
            with server.connect() as db:
                settings = dict(db.execute('SELECT key,value FROM settings'))
                observed.append((settings['active_run'], settings['paused_run'],
                                 settings['notifications_paused'],
                                 db.execute('SELECT monitoring FROM services WHERE id=2').fetchone()[0],
                                 tuple(db.execute('SELECT monitoring,visible,notifications FROM assignments WHERE id=1').fetchone())))

        actions = [
            ('pause', {}, ('0', '1', '0', 1, (1, 1, 1))),
            ('resume', {'project': 1}, ('1', '0', '0', 1, (1, 1, 1))),
            ('notification-pause', {'paused': True}, ('1', '0', '1', 1, (1, 1, 1))),
            ('notification-pause', {'paused': False}, ('1', '0', '0', 1, (1, 1, 1))),
            ('service-monitoring', {'service': 2, 'monitoring': False}, ('1', '0', '0', 0, (1, 1, 1))),
            ('service-monitoring', {'service': 2, 'monitoring': True}, ('1', '0', '0', 1, (1, 1, 1))),
            ('toggle', {'id': 1, 'field': 'monitoring'}, ('1', '0', '0', 1, (0, 1, 1))),
            ('toggle', {'id': 1, 'field': 'visible'}, ('1', '0', '0', 1, (0, 0, 1))),
            ('toggle', {'id': 1, 'field': 'notifications'}, ('1', '0', '0', 1, (0, 0, 0))),
            ('activate', {'project': 1, 'description': 'New run'}, ('0', '2', '1', 1, (0, 0, 0))),
            ('activate', {'project': 2, 'description': 'Switch project'}, ('0', '3', '1', 1, (0, 0, 0))),
            ('resume-deployment', {'project': 1, 'run': 1, 'expected_active_run': 0}, ('0', '1', '1', 1, (0, 0, 0))),
            ('delete-deployment', {'project': 1, 'run': 1, 'expected_active_run': 0}, ('0', '0', '1', 1, (0, 0, 0))),
        ]
        with patch.object(live_updates, 'publish_dashboard_change', side_effect=observe_commit):
            for index, (action, body, expected) in enumerate(actions, 1):
                with self.subTest(action=action, body=body):
                    server.mutate(action, body, actor=self.admin)
                    self.assertEqual(len(observed), index)
                    self.assertEqual(observed[-1], expected)

    def test_noop_rejected_and_rolled_back_controls_do_not_publish(self):
        self.create_host()
        server.mutate('service', {'assignment': 1, 'name': 'Port', 'kind': 'snmp',
                                  'target': '.1.2.3', 'direction': 'above', 'warning': '', 'critical': ''})
        server.mutate('pause', {})
        before = server.snapshot()
        with patch.object(live_updates, 'publish_dashboard_change') as publish:
            server.mutate('pause', {})
            server.mutate('notification-pause', {'paused': False})
            server.mutate('service-monitoring', {'service': 2, 'monitoring': True})
            server.mutate('toggle', {'id': 999, 'field': 'monitoring'})
            with self.assertRaises(ValueError):
                server.mutate('resume', {'project': 999})
            with self.assertRaises(PermissionError):
                server.mutate('resume', {'project': 1}, actor=self.viewer)
            with self.assertRaises(ValueError):
                server.mutate('notification-pause', {'paused': 'true'})
            original = server.notifications.set_paused

            def fail_after_writing(db, value):
                original(db, value)
                raise RuntimeError('Simulated transaction failure')

            with patch.object(server.notifications, 'set_paused', side_effect=fail_after_writing):
                with self.assertRaises(RuntimeError):
                    server.mutate('activate', {'project': 1, 'description': 'Roll back this run'})
            publish.assert_not_called()
        self.assertEqual(server.snapshot()['runs'], before['runs'])
        self.assertEqual(server.snapshot()['settings'], before['settings'])

    def test_operator_change_wakes_other_authenticated_dashboards(self):
        self.create_host()
        token, operator = self.create_operator()
        revision = live_updates.current_revision()

        def other_dashboard(token):
            next_revision = live_updates.wait_for_change(revision, timeout=2)
            response = self.request('/api/state', token=token)
            return next_revision, json.loads(response['content'])

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            dashboards = [pool.submit(other_dashboard, token) for token in (self.admin_token, self.viewer_token)]
            response = self.request('/api/pause', {'expected_scope_run': 1}, token, operator['csrf'])
            self.assertEqual(response['status'], 200)
            results = [dashboard.result(timeout=3) for dashboard in dashboards]
        for updated_revision, state in results:
            self.assertNotEqual(updated_revision, revision)
            self.assertEqual(state['settings']['active_run'], '0')
            self.assertEqual(state['settings']['paused_run'], '1')
        self.assertEqual(results[0][0], results[1][0])
        self.assertNotIn('access_scope', results[0][1])
        self.assertEqual(results[1][1]['access_scope'], {'project': 1, 'run': 1})


class PollingLiveUpdateTests(unittest.TestCase):
    tearDown = support.AccessAndNotificationTests.tearDown
    create_host = support.AccessAndNotificationTests.create_host
    request = support.AccessAndNotificationTests.request

    def setUp(self):
        support.AccessAndNotificationTests.setUp(self)
        host = self.create_host()
        with patch.object(server, 'read_metric', return_value=1):
            server.poll_one(host, 1)
            server.poll_one(host, 1)
        server.mutate('service', {'assignment': 1, 'name': 'RSSI', 'kind': 'snmp',
                                  'target': '.1.2.3', 'direction': 'below', 'warning': '-65', 'critical': '-75'})
        with server.connect() as db:
            self.service = dict(db.execute('''SELECT s.*, d.address FROM services s
                JOIN assignments a ON a.id=s.assignment JOIN devices d ON d.id=a.device
                WHERE s.kind='snmp' ''').fetchone())

    def poll(self, value):
        with patch.object(server, 'read_metric', return_value=value):
            server.poll_one(self.service, 1)

    def test_issue_open_severity_and_recovery_signal_only_after_commit(self):
        committed = []

        def observe():
            # Use a second DB connection: no event may precede committed issue,
            # evidence, samples, severity replacement or recovery records.
            with server.connect() as db:
                committed.append([(row['number'], row['status'], bool(row['closed']), row['trigger_value'])
                    for row in db.execute('SELECT * FROM incidents ORDER BY id')])

        with patch.object(live_updates, 'publish_monitoring_change', side_effect=observe):
            self.poll(-55); self.poll(-55)
            self.poll(-70)
            self.assertEqual(committed, [])  # Persistence is still required.
            self.poll(-70)
            self.assertEqual(committed[-1], [(1, 'warning', False, -70)])
            self.poll(-71)
            self.assertEqual(len(committed), 1)  # Same issue, new numeric reading.
            self.poll(-80); self.poll(-80)
            self.assertEqual(committed[-1], [(1, 'warning', True, -70), (2, 'critical', False, -80)])
            self.poll(-55); self.poll(-55)
            self.assertEqual(committed[-1], [(1, 'warning', True, -70), (2, 'critical', True, -80)])
            self.assertEqual(len(committed), 3)

    def test_no_signal_on_rollback_blocked_reads_or_invalidated_results(self):
        self.poll(-80)
        with server.connect() as db:
            samples = db.execute('SELECT COUNT(*) FROM samples').fetchone()[0]
        with patch.object(live_updates, 'publish_monitoring_change') as publish:
            with patch.object(server.notifications, 'enqueue_incident', side_effect=RuntimeError('Rollback')):
                with self.assertRaises(RuntimeError):
                    self.poll(-80)
            with server.connect() as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM samples').fetchone()[0], samples)
                self.assertEqual(db.execute('SELECT COUNT(*) FROM incidents').fetchone()[0], 0)
            with patch.object(server, 'host_is_up', return_value=False):
                self.poll(-80)
            with patch.object(server, 'read_metric', side_effect=lambda _: server.mutate('pause', {}) or -80):
                server.poll_one(self.service, 1)
            publish.assert_not_called()

    def test_committed_issue_wakes_admin_viewer_and_public_views_with_notifications_muted(self):
        server.mutate('notification-pause', {'paused': True})
        revision = live_updates.current_revision()

        def dashboard(path, token=None):
            updated = live_updates.wait_for_change(revision, timeout=3)
            return updated, json.loads(self.request(path, token=token)['content'])

        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            clients = [pool.submit(dashboard, '/api/state', self.admin_token),
                       pool.submit(dashboard, '/api/state', self.viewer_token),
                       pool.submit(dashboard, '/api/status')]
            self.poll(-80); self.poll(-80)
            results = [client.result(timeout=4) for client in clients]
        self.assertTrue(all(updated != revision for updated, _ in results))
        self.assertEqual(len({updated for updated, _ in results}), 1)
        self.assertEqual(len(results[0][1]['incident_lists']['active']), 1)
        self.assertEqual(len(results[1][1]['incident_lists']['active']), 1)
        public = results[2][1]
        self.assertEqual(len(public['incidents']), 1)
        self.assertNotIn('address', json.dumps(public))
        self.assertEqual(results[1][1]['service_templates'], [])

    def test_flap_stabilization_signals_without_a_new_or_resolved_issue(self):
        with server.connect() as db:
            db.execute('UPDATE services SET persistence=1,flap_changes=2,flap_stable=1 WHERE id=?',
                       (self.service['id'],))
        self.service.update(persistence=1, flap_changes=2, flap_stable=1)
        self.poll(-55); self.poll(-80); self.poll(-55)
        with server.connect() as db:
            self.assertEqual(db.execute('SELECT flapping FROM check_stability WHERE service=?',
                                        (self.service['id'],)).fetchone()[0], 1)
            db.execute('UPDATE check_stability SET stable_since=? WHERE service=?',
                       (server.time.time() - 61, self.service['id']))
            issues_before = [tuple(row) for row in db.execute('SELECT id,closed FROM incidents')]
        with patch.object(live_updates, 'publish_monitoring_change') as publish:
            self.poll(-55)
            publish.assert_called_once_with()
        with server.connect() as db:
            self.assertEqual(db.execute('SELECT flapping FROM check_stability WHERE service=?',
                                        (self.service['id'],)).fetchone()[0], 0)
            self.assertEqual([tuple(row) for row in db.execute('SELECT id,closed FROM incidents')], issues_before)
