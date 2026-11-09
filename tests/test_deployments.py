"""Deployment names use disposable databases and never contact devices/providers."""
from contextlib import closing
import concurrent.futures
import copy
import json
import sqlite3
import unittest
from unittest.mock import patch

from app import live_updates, server
import test_access_notifications as support


class DeploymentNameTests(unittest.TestCase):
    def setUp(self):
        self.fixture = support.AccessAndNotificationTests()
        self.fixture.setUp()
        self.host = self.fixture.create_host()

    def tearDown(self):
        self.fixture.tearDown()

    def rename(self, name, previous='Test deployment', project=1, run=1):
        return self.fixture.request('/api/rename-deployment', {
            'project': project, 'run': run, 'description': name,
            'expected_description': previous,
        }, self.fixture.admin_token, self.fixture.admin['csrf'])

    def records(self):
        with server.connect() as db:
            tables = [row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")]
            return {name: [dict(row) for row in db.execute(f'SELECT * FROM "{name}" ORDER BY rowid')]
                    for name in tables}

    def test_rename_requires_admin_and_csrf(self):
        token, operator = self.fixture.create_operator()
        body = {'project': 1, 'run': 1, 'description': 'New name',
                'expected_description': 'Test deployment'}
        with patch.object(live_updates, 'publish_dashboard_change') as publish:
            for credentials, expected in (
                    ({}, 401),
                    ({'token': self.fixture.viewer_token, 'csrf': self.fixture.viewer['csrf']}, 403),
                    ({'token': token, 'csrf': operator['csrf']}, 403),
                    ({'token': self.fixture.admin_token}, 403)):
                self.assertEqual(self.fixture.request('/api/rename-deployment', body,
                                                     **credentials)['status'], expected)
            publish.assert_not_called()
        with server.connect() as db:
            self.assertEqual(db.execute('SELECT description FROM runs WHERE id=1').fetchone()[0], 'Test deployment')

    def test_creation_and_rename_enforce_forty_characters(self):
        for name in (None, '', '   ', 123, True, 'x' * 41):
            with self.subTest(name=name):
                self.assertEqual(self.rename(name)['status'], 400)
                self.assertEqual(self.fixture.request('/api/activate', {'project': 1, 'description': name},
                    self.fixture.admin_token, self.fixture.admin['csrf'])['status'], 400)
        self.assertEqual(self.rename('  ' + 'x' * 40 + '  ')['status'], 200)
        with server.connect() as db:
            self.assertEqual(db.execute('SELECT description FROM runs WHERE id=1').fetchone()[0], 'x' * 40)
        self.assertEqual(self.fixture.request('/api/activate', {'project': 1, 'description': 'y' * 40},
            self.fixture.admin_token, self.fixture.admin['csrf'])['status'], 200)

    def test_active_paused_and_historical_renames_only_change_the_name(self):
        with server.connect() as db:
            server.notifications.save_configuration(db, {'enabled': True, 'recoveries': True,
                'bot_token': '12345:deployment_test_token', 'chat_id': '-1001'})
        with patch.object(server, 'read_metric', side_effect=TimeoutError):
            server.poll_one(self.host, 1)
            server.poll_one(self.host, 1)
        issue = server.snapshot()['incident_lists']['active'][0]
        server.mutate('ack', {'id': issue['id']}, actor=self.fixture.admin)
        previous = 'Test deployment'
        for mode in ('active', 'paused', 'historical'):
            if mode == 'paused':
                server.mutate('pause', {})
            elif mode == 'historical':
                server.mutate('activate', {'project': 1, 'description': 'Another deployment'})
            before = self.records()
            expected = copy.deepcopy(before)
            name = mode + ' renamed'
            next(row for row in expected['runs'] if row['id'] == 1)['description'] = name
            with patch.object(server.notifications, 'enqueue_incident') as notify:
                self.assertEqual(self.rename(name, previous)['status'], 200)
                notify.assert_not_called()
            self.assertEqual(self.records(), expected)
            previous = name
        self.assertTrue(before['samples'])
        self.assertTrue(before['incidents'])
        self.assertTrue(before['incident_acknowledgement_events'])
        self.assertTrue(before['notification_outbox'])

    def test_stale_wrong_project_and_deleted_targets_are_rejected(self):
        server.mutate('project', {'name': 'Other project'})
        self.assertEqual(self.rename('Wrong project', project=2)['status'], 404)
        self.assertEqual(self.rename('Stale editor', previous='Outdated name')['status'], 409)
        for run in (True, 1.5, '1', -1):
            self.assertEqual(self.rename('Invalid target', run=run)['status'], 400)
        server.mutate('pause', {})
        server.mutate('delete-deployment', {'project': 1, 'run': 1, 'expected_active_run': 0})
        self.assertEqual(self.rename('Deleted deployment')['status'], 404)
        server.mutate('activate', {'project': 1, 'description': 'New identity'})
        with server.connect() as db:
            self.assertGreater(db.execute('SELECT MAX(id) FROM runs').fetchone()[0], 1)

    def test_concurrent_renames_publish_one_committed_change_and_noop_is_quiet(self):
        committed = []

        def observe():
            with server.connect() as db:
                committed.append(db.execute('SELECT description FROM runs WHERE id=1').fetchone()[0])

        with patch.object(live_updates, 'publish_dashboard_change', side_effect=observe):
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(self.rename, ('First name', 'Second name')))
            self.assertEqual(sorted(result['status'] for result in results), [200, 409])
            self.assertEqual(len(committed), 1)
            self.assertEqual(self.rename(committed[0], committed[0])['status'], 200)
            self.assertEqual(len(committed), 1)
        public = json.loads(self.fixture.request('/api/status')['content'])
        self.assertNotIn(committed[0], json.dumps(public))

    def test_failed_database_write_rolls_back_without_publishing(self):
        with server.connect() as db:
            db.execute("""CREATE TRIGGER reject_run_rename BEFORE UPDATE OF description ON runs
                BEGIN SELECT RAISE(ABORT, 'Reject test rename'); END""")
        before = self.records()
        with patch.object(live_updates, 'publish_dashboard_change') as publish:
            self.assertEqual(self.rename('Should roll back')['status'], 400)
            publish.assert_not_called()
        self.assertEqual(self.records(), before)

    def test_legacy_names_survive_startup_and_restore_until_explicitly_renamed(self):
        legacy = 'Legacy description ' * 20
        with server.connect() as db:
            db.execute('UPDATE runs SET description=? WHERE id=1', (legacy,))
        server.initialize()
        payload = self.fixture.request('/api/backup', token=self.fixture.admin_token)['content']
        with closing(sqlite3.connect(':memory:')) as candidate:
            candidate.deserialize(payload)
            server.prepare_restored_database(candidate)
            self.assertEqual(candidate.execute('SELECT description FROM runs WHERE id=1').fetchone()[0], legacy)
        self.assertEqual(self.rename('Short legacy name', legacy)['status'], 200)
        payload = self.fixture.request('/api/backup', token=self.fixture.admin_token)['content']
        with closing(sqlite3.connect(':memory:')) as candidate:
            candidate.deserialize(payload)
            server.prepare_restored_database(candidate)
            self.assertEqual(candidate.execute('SELECT description FROM runs WHERE id=1').fetchone()[0], 'Short legacy name')
        with server.connect() as db:
            db.execute("UPDATE runs SET description='' WHERE id=1")
        self.assertEqual(self.rename('Previously unnamed', '')['status'], 200)
