"""Deletion ownership/batch safety and exact/bounded history range behaviour."""
import tempfile
import unittest
import threading
from unittest.mock import patch
from pathlib import Path

from app import server, project_deletion, history, stability


class ProjectHistoryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.previous = server.DB
        server.DB = Path(self.directory.name) / 'monitor.sqlite3'
        server.initialize()
        self.definition = {'name': 'RSSI', 'kind': 'snmp', 'target': '.1.2.3',
                           'direction': 'below', 'warning': '-65', 'critical': '-75'}
        server.mutate('device', {'name': 'Shared radio', 'address': '127.0.0.1'})
        for project in (1, 2):
            server.mutate('project', {'name': f'Project {project}'})
            server.mutate('assignment', {'project': project, 'device': 1, 'alias': f'Alias {project}'})
            server.mutate('service', dict(self.definition, assignment=project))
            server.mutate('activate', {'project': project, 'description': 'Test deployment'})
        server.mutate('template-create', self.definition)
        server.mutate('device-default-create', dict(self.definition, device=1))
        with server.connect() as db:
            self.services = {row['assignment']: dict(row) for row in db.execute("SELECT * FROM services WHERE kind='snmp'")}
            for project, service in self.services.items():
                db.executemany("""INSERT INTO samples(run,service,timestamp,value,status,revision,display_value)
                    VALUES(?,?,?,?,'healthy',1,?)""",
                    ((project, service['id'], 100 + index, -50-index, str(-50-index)) for index in range(10)))
                db.execute("INSERT INTO incidents(id,run,service,opened,status,number) VALUES(?,?,?,100,'critical',1)",
                           (project, project, service['id']))
                server.record_acknowledgement(db, project, {'id': 1})
                db.execute("""INSERT INTO notification_outbox(incident,event,text,config_revision,next_attempt,created)
                    VALUES(?,'opened','Saved message',1,0,0)""", (project,))
                stability.observe(db, service, project, 'critical', True, 100)
                db.execute("INSERT INTO project_logos(project,image,mime,digest) VALUES(?,?,'image/png',?)",
                           (project, b'test-logo', f'logo-{project}'))
                db.execute('INSERT INTO legacy_assignment_addresses VALUES(?,?,?)', (project, 1, '127.0.0.1'))

    def tearDown(self):
        server.DB = self.previous
        self.directory.cleanup()

    def range(self, **values):
        query = {'service': [str(self.services[1]['id'])], 'run': ['1'],
                 'start': ['100'], 'end': ['109'], 'mode': ['graph']}
        query.update({key: [str(value)] for key, value in values.items()})
        return history.read(server.connect, query)

    def drain(self):
        for _ in range(100):
            with server.connect() as db:
                if not project_deletion.step(db, batch_size=2):
                    return
        self.fail('Deletion did not finish')

    def test_deletion_is_bounded_resumable_and_preserves_shared_records(self):
        result = server.mutate('project-delete', {'project': 1, 'expected_name': 'Project 1'})
        self.assertIn('job', result)
        with server.connect() as db:
            before = db.execute('SELECT COUNT(*) FROM samples WHERE run=1').fetchone()[0]
            project_deletion.step(db, batch_size=2)
            after = db.execute('SELECT COUNT(*) FROM samples WHERE run=1').fetchone()[0]
            self.assertLessEqual(before-after, 2)
            self.assertEqual(db.execute('SELECT monitoring FROM assignments WHERE id=1').fetchone()[0], 0)
        # Restart the app between batches: missing managed ping must not be recreated.
        server.initialize()
        self.drain()
        with server.connect() as db:
            self.assertEqual(db.execute('SELECT id FROM projects').fetchall()[0][0], 2)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM samples WHERE run=1').fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM samples WHERE run=2').fetchone()[0], 10)
            for table in ('incidents', 'notification_outbox', 'incident_acknowledgement_events',
                          'check_stability', 'assignments', 'runs', 'project_logos', 'legacy_assignment_addresses'):
                self.assertEqual(db.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0], 1, table)
            for table in ('devices', 'device_service_defaults', 'service_templates'):
                self.assertEqual(db.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0], 1, table)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM services WHERE assignment=1').fetchone()[0], 0)
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])
            job = db.execute('SELECT * FROM project_deletions').fetchone()
            self.assertEqual(job['state'], 'completed')
            self.assertEqual(job['deleted_samples'], 10)
        server.mutate('project', {'name': 'New project'})
        with server.connect() as db:
            self.assertEqual(db.execute("SELECT id FROM projects WHERE name='New project'").fetchone()[0], 3)

    def test_deletion_cleans_legacy_orphan_samples_by_run_without_touching_other_runs(self):
        with server.connect() as db:
            db.execute("INSERT INTO samples(run,service,timestamp,value,status) VALUES(1,999,100,1,'healthy')")
            db.execute("INSERT INTO samples(run,service,timestamp,value,status) VALUES(2,999,100,2,'healthy')")
        server.mutate('project-delete', {'project': 1, 'expected_name': 'Project 1'})
        self.drain()
        with server.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM samples WHERE run=1').fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM samples WHERE run=2 AND service=999').fetchone()[0], 1)
            self.assertEqual(db.execute('SELECT deleted_samples FROM project_deletions').fetchone()[0], 11)

    def test_active_project_rejected_but_other_project_can_keep_monitoring(self):
        server.mutate('resume', {'project': 2})
        with self.assertRaises(project_deletion.DeletionError):
            server.mutate('project-delete', {'project': 2, 'expected_name': 'Project 2'})
        with self.assertRaises(project_deletion.DeletionError):
            server.mutate('project-delete', {'project': 1, 'expected_name': 'Renamed project'})
        server.mutate('project-delete', {'project': 1, 'expected_name': 'Project 1'})
        self.assertEqual(server.snapshot()['settings']['active_run'], '2')
        with self.assertRaises(project_deletion.DeletionError):
            server.mutate('project-edit', {'project': 2, 'name': 'Concurrent change'})
        server.mutate('ack', {'id': 2}, actor={'id': 1})
        self.drain()
        self.assertEqual(server.snapshot()['settings']['active_run'], '2')

    def test_paused_project_pointer_and_failed_job_retry(self):
        result = server.mutate('project-delete', {'project': 2, 'expected_name': 'Project 2'})
        self.assertEqual(server.snapshot()['settings']['paused_run'], '0')
        self.assertEqual(server.mutate('project-delete', {'project': 2, 'expected_name': 'Project 2'}), result)
        with server.connect() as db:
            db.execute("UPDATE project_deletions SET state='failed',error='Test failure'")
        self.assertEqual(server.mutate('project-delete', {'project': 2, 'expected_name': 'Project 2'}), result)
        self.drain()
        with server.connect() as db:
            self.assertEqual(db.execute('SELECT state,error FROM project_deletions').fetchone()[0], 'completed')
        server.mutate('project', {'name': 'Replacement'})
        with server.connect() as db:
            self.assertEqual(db.execute("SELECT id FROM projects WHERE name='Replacement'").fetchone()[0], 3)

    def test_range_boundaries_negative_values_and_deployment_isolation(self):
        data = self.range(start=102, end=105)
        self.assertEqual(data['total'], 4)
        self.assertEqual([row['value'] for row in data['rows']], [-55, -54, -53, -52])
        self.assertFalse(data['aggregated'])
        self.assertEqual(self.range(start=200, end=210)['rows'], [])
        with self.assertRaises(ValueError):
            self.range(run=2)
        for values in ({'start': 'nan'}, {'end': 'inf'}, {'start': 110, 'end': 100},
                       {'start': -1}, {'start': 0, 'end': 32*86400}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                self.range(**values)

    def test_small_history_range_does_not_scan_other_projects_history(self):
        other = self.services[2]['id']
        with server.connect() as db:
            db.executemany("INSERT INTO samples(run,service,timestamp,value,status) VALUES(2,?,100,1,'healthy')",
                           ((other,) for _ in range(30000)))
        original_connect = server.connect

        def bounded_connect():
            db = original_connect()
            calls = 0

            def progress():
                nonlocal calls
                calls += 1
                return int(calls > 100)

            db.set_progress_handler(progress, 1000)
            return db

        with patch.object(server, 'connect', side_effect=bounded_connect):
            self.assertEqual(self.range()['total'], 10)
            self.assertEqual(len(self.range(mode='table')['rows']), 10)

    def test_history_concurrency_and_work_budget_are_bounded(self):
        with patch.object(history, '_HISTORY_SLOTS', threading.BoundedSemaphore(0)):
            with self.assertRaisesRegex(history.HistoryError, 'History is busy'):
                self.range()
        with patch.object(history.time, 'monotonic', side_effect=[0, 21]):
            with self.assertRaisesRegex(history.HistoryError, 'shorter time range'):
                self.range()

    def test_exact_table_pagination_handles_equal_timestamps_without_duplicates(self):
        service = self.services[1]['id']
        with server.connect() as db:
            db.executemany("INSERT INTO samples(run,service,timestamp,value,status) VALUES(1,?,200,?,'healthy')",
                           ((service, value) for value in range(450)))
        first = self.range(start=190, end=210, mode='table')
        self.assertEqual(len(first['rows']), 200)
        second = self.range(start=190, end=210, mode='table', **first['next'])
        third = self.range(start=190, end=210, mode='table', **second['next'])
        ids = [row['id'] for data in (first, second, third) for row in data['rows']]
        self.assertEqual(len(ids), 450)
        self.assertEqual(len(set(ids)), 450)
        self.assertIsNone(third['next'])

    def test_large_graph_retains_extremes_and_real_gaps_with_bounded_points(self):
        service = self.services[1]['id']
        with server.connect() as db:
            db.execute('DELETE FROM samples WHERE service=?', (service,))
            db.executemany("""INSERT INTO samples(run,service,timestamp,value,status,revision)
                VALUES(1,?,?,?,'healthy',1)""",
                ((service, index+1000, -95 if index == 1234 else -35 if index == 1235 else -55)
                 for index in range(6000)))
            db.execute("UPDATE samples SET value=NULL,status='blocked' WHERE service=? AND timestamp=4000", (service,))
        data = self.range(start=1000, end=7000)
        self.assertTrue(data['aggregated'])
        self.assertEqual(data['total'], 6000)
        self.assertLessEqual(len(data['rows']), 2000)
        self.assertIn(-95, [row['value'] for row in data['rows']])
        self.assertIn(-35, [row['value'] for row in data['rows']])
        self.assertTrue(any(row['gap_before'] for row in data['rows']))

    def test_state_graph_keeps_transitions_and_flags_excessive_flapping(self):
        service = self.services[1]['id']
        with server.connect() as db:
            db.execute("UPDATE services SET value_type='state' WHERE id=?", (service,))
            db.execute('DELETE FROM samples WHERE service=?', (service,))
            db.executemany("INSERT INTO samples(run,service,timestamp,value,status) VALUES(1,?,?,?,'healthy')",
                           ((service, index+1000, 1 if index < 3000 else 2) for index in range(6000)))
        data = self.range(start=1000, end=7000)
        self.assertFalse(data['state_overflow'])
        self.assertEqual({row['value'] for row in data['rows']}, {1, 2})
        self.assertIn(3999, [row['timestamp'] for row in data['rows']])
        self.assertIn(4000, [row['timestamp'] for row in data['rows']])
        with server.connect() as db:
            db.execute('UPDATE samples SET value=id%2 WHERE service=?', (service,))
        data = self.range(start=1000, end=7000)
        self.assertTrue(data['state_overflow'])
        self.assertLessEqual(len(data['rows']), 2000)
