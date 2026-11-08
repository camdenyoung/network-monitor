"""Role boundaries, stale-tab protection and deployment-scoped reads."""
import json
import time
import unittest
from unittest.mock import patch

import test_access_notifications as support
from app import access, server


class ScopedRoleTests(unittest.TestCase):
    # Reuse the HTTP fixture helpers without inheriting/discovering their suite.
    setUp = support.AccessAndNotificationTests.setUp
    tearDown = support.AccessAndNotificationTests.tearDown
    request = support.AccessAndNotificationTests.request
    create_host = support.AccessAndNotificationTests.create_host
    create_operator = support.AccessAndNotificationTests.create_operator

    def seed(self):
        self.create_host()
        server.mutate('service', {'assignment': 1, 'name': 'RSSI', 'kind': 'snmp',
                                  'target': '.1.2.3', 'direction': 'below', 'warning': '-70', 'critical': '-80'})
        server.mutate('activate', {'project': 1, 'description': 'Second run'})
        server.mutate('resume', {'project': 1})
        server.mutate('project', {'name': 'Other project'})
        server.mutate('device', {'name': 'Private device', 'model': '', 'address': '192.168.2.1'})
        server.mutate('assignment', {'project': 2, 'device': 2, 'alias': 'Private alias'})
        # Another project's deployment exists without changing global selection.
        with server.connect() as db:
            db.execute("INSERT INTO runs(id,project,started,description) VALUES(3,2,?,'Other run')", (time.time(),))
            for run, service in ((1, 1), (2, 1), (3, 3)):
                db.execute("INSERT INTO samples(run,service,timestamp,value,status,error) VALUES(?,?,?,1,'healthy','')",
                           (run, service, time.time()))
            db.execute("INSERT OR REPLACE INTO settings VALUES('private_setting','never expose')")
        self.operator_token, self.operator = self.create_operator()

    def state(self, token):
        return json.loads(self.request('/api/state', token=token)['content'])

    def operation(self, action, body, scope=2, csrf=True):
        return self.request('/api/' + action, {'expected_scope_run': scope, **body},
                            self.operator_token, self.operator['csrf'] if csrf else None)

    def test_state_filters_all_collections_and_follows_global_scope(self):
        self.seed()
        for token, expected_runs in ((self.viewer_token, [2]), (self.operator_token, [1, 2])):
            state = self.state(token)
            self.assertEqual(state['access_scope'], {'project': 1, 'run': 2})
            self.assertEqual([row['id'] for row in state['projects']], [1])
            self.assertEqual([row['id'] for row in state['runs']], expected_runs)
            self.assertEqual([row['id'] for row in state['devices']], [1])
            self.assertEqual([row['id'] for row in state['assignments']], [1])
            self.assertEqual({row['assignment'] for row in state['services']}, {1})
            self.assertEqual({row['run'] for row in state['latest']}, {2})
            for key in ('service_templates', 'device_service_defaults', 'legacy_addresses'):
                self.assertEqual(state[key], [])
            self.assertNotIn('private_setting', state['settings'])
            self.assertNotIn('Private alias', json.dumps(state))
        self.assertEqual(len(self.state(self.admin_token)['projects']), 2)
        server.mutate('pause', {})
        self.assertEqual(self.state(self.viewer_token)['access_scope']['run'], 2)
        server.mutate('resume-deployment', {'project': 2, 'run': 3, 'expected_active_run': 0})
        for token in (self.viewer_token, self.operator_token):
            state = self.state(token)
            self.assertEqual(state['access_scope'], {'project': 2, 'run': 3})
            self.assertEqual([row['id'] for row in state['projects']], [2])
        with server.connect() as db:
            db.execute("UPDATE settings SET value='0' WHERE key IN ('active_run','paused_run')")
        for token in (self.viewer_token, self.operator_token):
            state = self.state(token)
            self.assertEqual(state['access_scope'], {'project': None, 'run': None})
            for key in ('projects', 'devices', 'assignments', 'services', 'runs', 'latest', 'incidents'):
                self.assertEqual(state[key], [])
            self.assertTrue(all(not rows for rows in state['incident_lists'].values()))

    def test_operator_can_control_monitoring_notifications_services_and_resume(self):
        self.seed()
        self.assertEqual(self.operation('pause', {})['status'], 200)
        self.assertEqual(self.operation('resume', {'project': 1})['status'], 200)
        self.assertEqual(self.operation('notification-pause', {'paused': True})['status'], 200)
        self.assertEqual(self.operation('notification-pause', {'paused': False})['status'], 200)
        for monitoring in (False, True):
            self.assertEqual(self.operation('service-monitoring', {'service': 2, 'monitoring': monitoring})['status'], 200)
            with server.connect() as db:
                self.assertEqual(db.execute('SELECT monitoring FROM services WHERE id=2').fetchone()[0], monitoring)
        self.assertEqual(self.operation('resume-deployment', {'run': 1, 'project': 1, 'expected_active_run': 2})['status'], 200)
        state = self.state(self.viewer_token)
        self.assertEqual(state['access_scope']['run'], 1)
        self.assertEqual(state['settings']['active_run'], '0')
        self.assertEqual(state['settings']['notifications_paused'], '1')
        self.assertEqual(self.operation('resume', {'project': 1}, scope=1)['status'], 200)

    def test_operator_wrong_project_stale_context_managed_ping_and_configuration_denied(self):
        self.seed()
        for action, body in (
            ('resume-deployment', {'project': 2, 'run': 3, 'expected_active_run': 2}),
            ('resume', {'project': 2}),
            ('service-monitoring', {'service': 3, 'monitoring': False}),
            ('service-monitoring', {'service': 1, 'monitoring': False}),
            ('project-edit', {'project': 1, 'name': 'Forbidden'}),
            ('activate', {'project': 1, 'description': 'Forbidden'}),
            ('delete-deployment', {'project': 1, 'run': 1, 'expected_active_run': 2}),
        ):
            with self.subTest(action=action, body=body):
                self.assertEqual(self.operation(action, body)['status'], 403)
        self.assertEqual(self.operation('pause', {}, csrf=False)['status'], 403)
        self.assertEqual(self.operation('pause', {}, scope=1)['status'], 403)
        server.mutate('resume-deployment', {'project': 2, 'run': 3, 'expected_active_run': 2})
        self.assertEqual(self.operation('pause', {})['status'], 403)
        self.assertEqual(self.operation('notification-pause', {'paused': False})['status'], 403)
        self.assertEqual(self.operation('service-monitoring', {'service': 2, 'monitoring': False}, scope=3)['status'], 403)

    def test_viewer_denied_all_operational_writes(self):
        self.seed()
        for action in access.OPERATOR_ACTIONS:
            with self.subTest(action=action):
                self.assertEqual(self.request('/api/' + action, {'expected_scope_run': 2},
                                             self.viewer_token, self.viewer['csrf'])['status'], 403)

    def test_history_scope_for_legacy_graph_and_table_and_each_batch(self):
        self.seed()
        for mode in ('legacy', 'graph', 'table'):
            suffix = '' if mode == 'legacy' else f'&start=1&end=100&mode={mode}'
            for token, run, service, expected in (
                (self.viewer_token, 2, 1, 200), (self.viewer_token, 1, 1, 403),
                (self.operator_token, 1, 1, 200), (self.operator_token, 3, 3, 403),
                (self.viewer_token, 2, 3, 403), (self.admin_token, 3, 3, 200),
            ):
                with self.subTest(mode=mode, run=run, service=service):
                    self.assertEqual(self.request(f'/api/history?service={service}&run={run}' + suffix,
                                                 token=token)['status'], expected)
        # A global switch between definition and sample reads must reject the
        # request rather than continuing to reveal the previous project's rows.
        original = access.authorize_history
        calls = []
        def switch_after_definition(db, actor, service, run):
            calls.append(run)
            if len(calls) == 2:
                db.execute("UPDATE settings SET value='3' WHERE key='active_run'")
            return original(db, actor, service, run)
        with patch.object(access, 'authorize_history', side_effect=switch_after_definition):
            self.assertEqual(self.request('/api/history?service=1&run=2&start=1&end=100&mode=graph',
                                         token=self.viewer_token)['status'], 403)
        self.assertEqual(len(calls), 2)

    def test_project_logos_are_scoped_and_archived_services_cannot_be_controlled(self):
        self.seed()
        image = support.AccessAndNotificationTests.logo_image(self)
        with server.connect() as db:
            server.logos.save(db, 1, image)
            server.logos.save(db, 2, image)
        for token in (self.viewer_token, self.operator_token):
            self.assertEqual(self.request('/api/project-logo?project=1', token=token)['status'], 200)
            self.assertEqual(self.request('/api/project-logo?project=2', token=token)['status'], 404)
        self.assertEqual(self.request('/api/project-logo?project=2', token=self.admin_token)['status'], 200)
        with server.connect() as db:
            db.execute('UPDATE assignments SET removed=1 WHERE id=1')
        self.assertEqual(self.operation('service-monitoring', {'service': 2, 'monitoring': False})['status'], 403)
