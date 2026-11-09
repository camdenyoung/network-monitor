"""Behaviour checks for project isolation, threshold persistence and recovery."""
import io
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import server, history


class MonitorTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.previous_db = server.DB
        server.DB = Path(self.directory.name) / 'test.sqlite3'
        server.initialize()
        # Most tests isolate service behaviour from the host dependency.
        self.host_dependency = patch.object(server, 'host_is_up', return_value=True)
        self.host_dependency.start()
        self.addCleanup(self.host_dependency.stop)
        server.mutate('project', {'name': 'Festival'})
        server.mutate('device', {'name': 'MW-014', 'model': 'Siklu', 'address': '127.0.0.1'})
        server.mutate('assignment', {
            'project': 1, 'device': 1, 'alias': 'Stage link',
        })
        server.mutate('service', {
            'assignment': 1, 'name': 'RSSI', 'kind': 'snmp', 'target': '.1.2.3',
            'direction': 'below', 'warning': '-65', 'critical': '-75',
        })
        self.start_deployment({'project': 1, 'description': 'Test deployment'})
        with server.connect() as db:
            self.service = dict(db.execute("SELECT s.*,d.address FROM services s JOIN assignments a ON a.id=s.assignment JOIN devices d ON d.id=a.device WHERE s.kind='snmp'").fetchone())

    def start_deployment(self, details):
        server.mutate('activate', details)
        server.mutate('resume', {'project': details['project']})
        if hasattr(self, 'service'):
            with server.connect() as db:
                self.service.update(dict(db.execute('SELECT * FROM services WHERE id=?',
                                                    (self.service['id'],)).fetchone()))

    def tearDown(self):
        server.DB = self.previous_db
        self.directory.cleanup()

    def poll(self, value, run=1):
        with patch.object(server, 'read_metric', return_value=value):
            server.poll_one(self.service, run)

    def test_new_project_allows_status_acknowledgements_without_changing_existing_projects_or_deployment(self):
        server.mutate('project-status-settings', {'project':1, 'enabled':False})
        before = server.snapshot()['settings']['active_run']
        created = server.mutate('project', {'name':'New event'})
        server.initialize()
        projects = {row['id']:row for row in server.snapshot()['projects']}
        self.assertEqual(projects[1]['status_ack_enabled'], 0)
        self.assertEqual(projects[created['project']]['status_ack_enabled'], 1)
        self.assertEqual(server.snapshot()['settings']['active_run'], before)

    def test_new_deployment_waits_for_explicit_monitoring_and_notification_resume(self):
        server.mutate('notification-pause', {'paused': False})
        self.poll(-55)
        with server.connect() as db:
            before = db.execute('SELECT COUNT(*) FROM samples').fetchone()[0]
        server.mutate('activate', {'project': 1, 'description': 'Prepare without polling'})
        settings = server.snapshot()['settings']
        self.assertEqual(settings['active_run'], '0')
        self.assertEqual(settings['paused_run'], '2')
        self.assertEqual(settings['notifications_paused'], '1')
        self.poll(-80, run=2)
        with server.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM samples').fetchone()[0], before)
        server.initialize()
        self.assertEqual(server.snapshot()['settings']['paused_run'], '2')
        server.mutate('resume', {'project': 1})
        settings = server.snapshot()['settings']
        self.assertEqual(settings['active_run'], '2')
        self.assertEqual(settings['paused_run'], '0')
        self.assertEqual(settings['notifications_paused'], '1')

    def test_large_history_snapshot_uses_bounded_current_reading_lookups(self):
        # A VM instruction budget catches full-history scans without depending on
        # the speed of the machine running the test. Seed before applying it.
        with server.connect() as db:
            db.executemany("""INSERT INTO samples
                (run,service,timestamp,value,status,revision) VALUES(1,?,1,-55,'healthy',1)""",
                ((self.service['id'],) for _ in range(30000)))
        self.poll(-56)
        original_connect = server.connect

        def bounded_connect():
            db = original_connect()
            calls = 0

            def progress():
                nonlocal calls
                calls += 1
                return int(calls > 200)

            db.set_progress_handler(progress, 1000)
            return db

        with patch.object(server, 'connect', side_effect=bounded_connect):
            state = server.snapshot()
        reading = next(row for row in state['latest'] if row['service'] == self.service['id'])
        self.assertEqual(reading['value'], -56)
        self.assertEqual(state['projects'][0]['name'], 'Festival')

    def test_latest_reading_excludes_other_runs_revisions_and_pre_resume_samples(self):
        with server.connect() as db:
            db.execute('UPDATE services SET revision=2,monitoring_since=100 WHERE id=?',
                       (self.service['id'],))
            for run, revision, timestamp, value in (
                    (1, 2, 101, -56), (1, 2, 99, -57), (2, 2, 102, -58), (1, 1, 103, -59)):
                db.execute("""INSERT INTO samples(run,service,timestamp,value,status,revision)
                    VALUES(?,?,?,?,'healthy',?)""",
                    (run, self.service['id'], timestamp, value, revision))
        latest = server.snapshot()['latest']
        self.assertEqual(next(row['value'] for row in latest
                              if row['service'] == self.service['id']), -56)

    def test_resume_with_zero_or_one_fresh_reading_does_not_scan_old_history(self):
        with server.connect() as db:
            db.executemany("""INSERT INTO samples
                (run,service,timestamp,value,status,revision) VALUES(1,?,1,-55,'healthy',1)""",
                ((self.service['id'],) for _ in range(30000)))
            db.execute('UPDATE services SET monitoring_since=100 WHERE id=?', (self.service['id'],))
            calls = 0

            def progress():
                nonlocal calls
                calls += 1
                return int(calls > 100)

            db.set_progress_handler(progress, 1000)
            self.assertEqual(server.current_samples(db, self.service['id'], 1, 1, 100), [])
            db.execute("""INSERT INTO samples(run,service,timestamp,value,status,revision)
                VALUES(1,?,101,-56,'healthy',1)""", (self.service['id'],))
            rows = server.current_samples(db, self.service['id'], 1, 1, 100, limit=2)
            self.assertEqual([row['value'] for row in rows], [-56])
            db.set_progress_handler(None, 0)

    def test_current_samples_keep_id_order_with_out_of_order_timestamps(self):
        with server.connect() as db:
            for timestamp, value in ((105, -55), (103, -56), (99, -57)):
                db.execute("""INSERT INTO samples(run,service,timestamp,value,status,revision)
                    VALUES(1,?, ?,?,'healthy',1)""", (self.service['id'], timestamp, value))
            rows = server.current_samples(db, self.service['id'], 1, 1, 100, limit=2)
            self.assertEqual([row['value'] for row in rows], [-56, -55])

    def test_retention_is_bounded_and_keeps_boundary_and_current_readings(self):
        with server.connect() as db:
            db.executemany("""INSERT INTO samples(run,service,timestamp,status)
                VALUES(1,?,?,'healthy')""",
                ((self.service['id'], timestamp) for timestamp in range(12)))
            self.assertEqual(server.prune_samples(db, 10, batch_size=3), 3)
            self.assertEqual(db.execute('SELECT MIN(timestamp) FROM samples').fetchone()[0], 3)
            self.assertEqual(server.prune_samples(db, 10), 7)
            self.assertEqual([row[0] for row in db.execute('SELECT timestamp FROM samples ORDER BY timestamp')],
                             [10, 11])
            self.assertEqual(server.prune_samples(db, 10), 0)

    def test_history_index_upgrade_preserves_data_and_is_repeatable(self):
        self.poll(-55)
        with server.connect() as db:
            before = [tuple(row) for row in db.execute('SELECT * FROM samples')]
            db.execute('DROP INDEX sample_current')
            db.execute('DROP INDEX sample_expiry')
        server.initialize()
        server.initialize()
        with server.connect() as db:
            self.assertEqual([tuple(row) for row in db.execute('SELECT * FROM samples')], before)
            indexes = {row[1] for row in db.execute('PRAGMA index_list(samples)')}
            self.assertTrue({'sample_current', 'sample_expiry'} <= indexes)

    def test_issue_labels_restart_for_each_deployment_but_ack_uses_internal_id(self):
        self.poll(-80)
        self.poll(-80)
        self.poll(-70)
        self.poll(-70)
        first = sorted(server.snapshot()['incidents'], key=lambda row: row['id'])
        self.assertEqual([row['number'] for row in first], [1, 2])
        self.start_deployment({'project': 1, 'description': 'Second event'})
        self.poll(-80, run=2)
        self.poll(-80, run=2)
        issue = server.snapshot()['incident_lists']['active'][0]
        self.assertEqual(issue['number'], 1)
        self.assertNotEqual(issue['id'], 1)
        server.mutate('ack', {'id': issue['id']}, actor={'id': 1})
        acknowledged = server.snapshot()['incident_lists']['acknowledged'][0]
        self.assertEqual(acknowledged['number'], 1)
        self.assertEqual(acknowledged['id'], issue['id'])
        with server.connect() as db:
            self.assertEqual([row[0] for row in db.execute('SELECT number FROM incidents WHERE run=1 ORDER BY id')], [1, 2])

    def test_issue_counter_is_not_reused_after_deletion_or_restart(self):
        self.poll(-80)
        self.poll(-80)
        with server.connect() as db:
            db.execute('DELETE FROM incidents WHERE run=1')
        server.initialize()
        self.poll(-80)
        self.assertEqual(server.snapshot()['incident_lists']['active'][0]['number'], 2)

    def test_legacy_issue_numbering_is_stable_per_run(self):
        self.poll(-80)
        self.poll(-80)
        self.poll(-70)
        self.poll(-70)
        self.start_deployment({'project': 1, 'description': 'Second event'})
        self.poll(-80, run=2)
        self.poll(-80, run=2)
        with server.connect() as db:
            ids = [row[0] for row in db.execute('SELECT id FROM incidents ORDER BY id')]
            db.execute('UPDATE incidents SET number=NULL')
            db.execute('UPDATE runs SET issue_counter=0')
            server.migrate_issue_numbers(db)
            server.migrate_issue_numbers(db)
            self.assertEqual([row[0] for row in db.execute('SELECT id FROM incidents ORDER BY id')], ids)
            self.assertEqual([row[0] for row in db.execute('SELECT number FROM incidents ORDER BY id')], [1, 2, 1])

    def test_deployment_description_is_required_and_survives_resume(self):
        for value in (None, '', '   ', 123, 'x' * 41):
            with self.subTest(value=value), self.assertRaises(ValueError):
                server.mutate('activate', {'project': 1, 'description': value})
        with self.assertRaises(ValueError):
            server.mutate('activate', {'project': 1})
        self.start_deployment({'project': 1, 'description': '  Reopening stage network  '})
        before = server.snapshot()['runs'][-1]
        self.assertEqual(before['description'], 'Reopening stage network')
        server.mutate('pause', {})
        server.mutate('resume', {'project': 1})
        self.assertEqual(server.snapshot()['runs'][-1], before)

    def test_deleting_deployment_purges_only_its_history_and_notification_records(self):
        self.poll(-80)
        self.poll(-80)
        issue1 = server.snapshot()['incident_lists']['active'][0]['id']
        server.mutate('ack', {'id': issue1}, actor={'id': 1})
        self.start_deployment({'project': 1, 'description': 'Keep this deployment'})
        self.poll(-70, run=2)
        self.poll(-70, run=2)
        issue2 = server.snapshot()['incident_lists']['active'][0]['id']
        with server.connect() as db:
            for issue in (issue1, issue2):
                db.execute("""INSERT INTO notification_outbox
                    (incident,event,channel,text,config_revision,next_attempt,created)
                    VALUES(?,'opened','telegram','Test notification',1,0,0)""", (issue,))
            configs = {table: [tuple(row) for row in db.execute('SELECT * FROM ' + table)]
                       for table in ('devices', 'projects', 'assignments', 'services')}
            other_samples = [tuple(row) for row in db.execute('SELECT * FROM samples WHERE run=2')]
            other_issue = tuple(db.execute('SELECT * FROM incidents WHERE id=?', (issue2,)).fetchone())
            other_notification = tuple(db.execute('SELECT * FROM notification_outbox WHERE incident=?', (issue2,)).fetchone())
        server.mutate('delete-deployment', {'project': 1, 'run': 1, 'expected_active_run': 2})
        with server.connect() as db:
            for table in ('runs', 'samples', 'incidents'):
                key = 'id' if table == 'runs' else 'run'
                self.assertEqual(db.execute(f'SELECT COUNT(*) FROM {table} WHERE {key}=1').fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM notification_outbox WHERE incident=?', (issue1,)).fetchone()[0], 0)
            self.assertEqual([tuple(row) for row in db.execute('SELECT * FROM samples WHERE run=2')], other_samples)
            self.assertEqual(tuple(db.execute('SELECT * FROM incidents WHERE id=?', (issue2,)).fetchone()), other_issue)
            self.assertEqual(tuple(db.execute('SELECT * FROM notification_outbox WHERE incident=?', (issue2,)).fetchone()), other_notification)
            for table, before in configs.items():
                self.assertEqual([tuple(row) for row in db.execute('SELECT * FROM ' + table)], before)
        self.assertEqual(server.snapshot()['settings']['active_run'], '2')

    def test_deleting_paused_deployment_clears_resume_pointer_and_never_reuses_ids(self):
        self.poll(-80)
        self.poll(-80)
        self.start_deployment({'project': 1, 'description': 'Delete latest deployment'})
        self.poll(-80, run=2)
        self.poll(-80, run=2)
        highest_issue = max(row['id'] for row in server.snapshot()['incidents'])
        server.mutate('pause', {})
        server.mutate('delete-deployment', {'project': 1, 'run': 2, 'expected_active_run': 0})
        self.assertEqual(server.snapshot()['settings']['paused_run'], '0')
        server.initialize()
        self.start_deployment({'project': 1, 'description': 'New unique deployment'})
        self.assertEqual(server.snapshot()['settings']['active_run'], '3')
        self.poll(-80, run=3)
        self.poll(-80, run=3)
        current = server.snapshot()['incident_lists']['active'][0]
        self.assertGreater(current['id'], highest_issue)
        self.assertEqual(current['number'], 1)
        self.assertIn(1, [row['id'] for row in server.snapshot()['runs']])

    def test_deployment_delete_rejects_active_stale_and_wrong_project_selections(self):
        self.start_deployment({'project': 1, 'description': 'Active second run'})
        server.mutate('project', {'name': 'Other project'})
        before = server.snapshot()
        for body in (
                {'project': 1, 'run': 2, 'expected_active_run': 2},
                {'project': 1, 'run': 1, 'expected_active_run': 0},
                {'project': 2, 'run': 1, 'expected_active_run': 2},
                {'project': 1, 'run': 999, 'expected_active_run': 2}):
            with self.subTest(body=body), self.assertRaises(ValueError):
                server.mutate('delete-deployment', body)
            self.assertEqual(server.snapshot(), before)

    def test_deployment_delete_rolls_back_if_database_rejects_run_removal(self):
        self.poll(-80)
        self.poll(-80)
        self.start_deployment({'project': 1, 'description': 'Keep active run'})
        before = server.snapshot()
        with server.connect() as db:
            db.execute("""CREATE TRIGGER reject_run_delete BEFORE DELETE ON runs
                WHEN OLD.id=1 BEGIN SELECT RAISE(ABORT,'test failure'); END""")
        with self.assertRaises(sqlite3.IntegrityError):
            server.mutate('delete-deployment', {'project': 1, 'run': 1, 'expected_active_run': 2})
        self.assertEqual(server.snapshot(), before)

    def test_selecting_old_deployment_preserves_history_metadata_and_issue_sequence(self):
        self.poll(-80)
        self.poll(-80)
        self.start_deployment({'project': 1, 'description': 'Second deployment'})
        server.mutate('notification-pause', {'paused': False})
        self.poll(-70, run=2)
        self.poll(-70, run=2)
        with server.connect() as db:
            before_runs = [tuple(row) for row in db.execute('SELECT * FROM runs ORDER BY id')]
            before_issues = [tuple(row) for row in db.execute('SELECT * FROM incidents ORDER BY id')]
            before_samples = [tuple(row) for row in db.execute('SELECT * FROM samples ORDER BY id')]
            issue_id = db.execute('SELECT id FROM incidents WHERE run=2').fetchone()[0]
            db.execute("""INSERT INTO notification_outbox
                (incident,event,channel,text,config_revision,next_attempt,created)
                VALUES(?,'opened','telegram','Pending old notification',1,0,0)""", (issue_id,))
        server.mutate('resume-deployment', {'project': 1, 'run': 1, 'expected_active_run': 2})
        state = server.snapshot()
        self.assertEqual(state['settings']['active_run'], '0')
        self.assertEqual(state['settings']['paused_run'], '1')
        server.mutate('resume', {'project': 1})
        state = server.snapshot()
        self.assertEqual(state['settings']['notifications_paused'], '1')
        self.assertEqual(state['latest'], [])
        retained = state['incident_lists']['active'] + state['incident_lists']['suppressed']
        self.assertEqual(retained[0]['number'], 1)
        with server.connect() as db:
            self.assertEqual([tuple(row) for row in db.execute('SELECT * FROM runs ORDER BY id')], before_runs)
            self.assertEqual([tuple(row) for row in db.execute('SELECT * FROM incidents ORDER BY id')], before_issues)
            self.assertEqual([tuple(row) for row in db.execute('SELECT * FROM samples ORDER BY id')], before_samples)
            self.assertEqual(db.execute('SELECT state FROM notification_outbox').fetchone()[0], 'cancelled')
        # Previously captured service objects must not append stale data after switching back.
        self.poll(-80)
        with server.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM samples').fetchone()[0], len(before_samples))
            self.service = dict(db.execute("""SELECT s.*,d.address FROM services s
                JOIN assignments a ON a.id=s.assignment JOIN devices d ON d.id=a.device
                WHERE s.id=?""", (self.service['id'],)).fetchone())
        self.poll(-70)
        self.poll(-70)
        self.assertEqual(server.snapshot()['incident_lists']['active'][0]['number'], 2)
        self.assertEqual(len(server.snapshot()['runs']), 2)

    def test_selected_deployment_resume_validates_project_and_expected_active_run(self):
        server.mutate('project', {'name': 'Other project'})
        before = server.snapshot()
        for body in (
                {'project': 1, 'run': 999, 'expected_active_run': 1},
                {'project': 2, 'run': 1, 'expected_active_run': 1},
                {'project': 1, 'run': 1, 'expected_active_run': 0},
                {'project': 1, 'run': 1, 'expected_active_run': 1}):
            with self.subTest(body=body), self.assertRaises(ValueError):
                server.mutate('resume-deployment', body)
            self.assertEqual(server.snapshot(), before)

    def test_old_deployment_resume_discards_read_that_spans_switch_away_and_back(self):
        def read_during_switch(service):
            self.start_deployment({'project': 1, 'description': 'Temporary second run'})
            server.mutate('resume-deployment', {'project': 1, 'run': 1, 'expected_active_run': 2})
            return -80
        with patch.object(server, 'read_metric', side_effect=read_during_switch):
            server.poll_one(self.service, 1)
        self.assertEqual(server.snapshot()['latest'], [])
        with server.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM samples').fetchone()[0], 0)

    def test_selected_resume_from_pause_preserves_service_flags_and_other_projects(self):
        server.mutate('service-monitoring', {'service': self.service['id'], 'monitoring': False})
        server.mutate('project', {'name': 'Other project'})
        server.mutate('assignment', {'project': 2, 'device': 1, 'alias': 'Other event'})
        self.start_deployment({'project': 2, 'description': 'Other run'})
        server.mutate('pause', {})
        with server.connect() as db:
            other_services = [tuple(row) for row in db.execute('SELECT * FROM services WHERE assignment=2')]
        server.mutate('resume-deployment', {'project': 1, 'run': 1, 'expected_active_run': 0})
        self.assertEqual(server.snapshot()['settings']['active_run'], '0')
        self.assertEqual(server.snapshot()['settings']['paused_run'], '1')
        with server.connect() as db:
            self.assertEqual(db.execute('SELECT monitoring FROM services WHERE id=?', (self.service['id'],)).fetchone()[0], 0)
            self.assertEqual([tuple(row) for row in db.execute('SELECT * FROM services WHERE assignment=2')], other_services)

    def test_pause_resume_keeps_deployment_history_and_issues(self):
        self.poll(-80)
        self.poll(-80)
        before = server.snapshot()
        server.mutate('pause', {})
        server.mutate('pause', {})
        server.initialize()
        with server.connect() as db:
            db.execute("DELETE FROM settings WHERE key='paused_run'")
        server.initialize()
        self.assertEqual(server.snapshot()['settings']['paused_run'], '1')
        server.mutate('resume', {'project': 1})
        after = server.snapshot()
        self.assertEqual(after['settings']['active_run'], '1')
        self.assertEqual(after['settings']['paused_run'], '0')
        self.assertEqual(after['runs'], before['runs'])
        self.assertEqual(after['incidents'], before['incidents'])
        with server.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM samples').fetchone()[0], 2)
        with self.assertRaises(ValueError):
            server.mutate('resume', {'project': 1})
        server.mutate('pause', {})
        with self.assertRaises(ValueError):
            server.mutate('resume', {'project': 999})
        self.start_deployment({'project': 1, 'description': 'Test deployment'})
        self.assertEqual(server.snapshot()['settings']['paused_run'], '0')
        self.assertEqual(len(server.snapshot()['runs']), 2)

    def test_pause_resume_discards_inflight_reads(self):
        def delayed_read(service):
            server.mutate('pause', {})
            server.mutate('resume', {'project': 1})
            return -80
        with patch.object(server, 'read_metric', side_effect=delayed_read):
            server.poll_one(self.service, 1)
        with server.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM samples').fetchone()[0], 0)

    def test_persistence_acknowledgement_and_recovery(self):
        self.poll(-80)
        self.assertEqual(server.snapshot()['incidents'], [])
        self.poll(-80)
        incident = server.snapshot()['incidents'][0]
        server.mutate('ack', {'id': incident['id']}, actor={'id': 1})
        self.assertIsNotNone(server.snapshot()['incidents'][0]['acknowledged'])
        self.assertIsNone(server.snapshot()['incidents'][0]['closed'])
        self.poll(-50)
        self.poll(-50)
        self.assertIsNotNone(server.snapshot()['incidents'][0]['closed'])

    def test_previous_deployment_results_are_discarded(self):
        self.start_deployment({'project': 1, 'description': 'Test deployment'})
        self.poll(-80, run=1)
        self.assertEqual(server.snapshot()['latest'], [])
        self.poll(-50, run=2)
        self.assertEqual(len(server.snapshot()['latest']), 1)

    def test_community_is_not_exposed(self):
        self.assertNotIn('community', server.snapshot()['services'][0])

    def test_non_numeric_oid_is_rejected(self):
        with self.assertRaises(ValueError):
            server.mutate('service', {
                'assignment': 1, 'name': 'Bad', 'kind': 'snmp',
                'target': '-bad', 'direction': 'above',
            })

    def test_database_backup_preserves_configuration_and_history(self):
        self.poll(-55)
        with server.connect() as source:
            destination = sqlite3.connect(':memory:')
            source.backup(destination)
            restored = sqlite3.connect(':memory:')
            restored.deserialize(destination.serialize())
            self.assertEqual(restored.execute('SELECT name FROM devices').fetchone()[0], 'MW-014')
            self.assertEqual(restored.execute('SELECT COUNT(*) FROM samples').fetchone()[0], 1)
            destination.close()
            restored.close()

    def test_restore_endpoint_pauses_monitoring_and_retains_data(self):
        self.poll(-55)
        with server.connect() as source:
            backup = sqlite3.connect(':memory:')
            source.backup(backup)
            payload = backup.serialize()
            backup.close()
        server.mutate('project', {'name': 'Added after backup'})

        # Exercise the handler without binding a network socket.
        handler = object.__new__(server.Handler)
        handler.path = '/api/restore'
        handler.headers = {
            'X-CSRF-Token': 'test',
            'Content-Length': str(len(payload)),
            'Content-Type': 'application/octet-stream',
        }
        handler.require_user = lambda **kwargs: {'id': 1, 'role': 'admin', 'csrf': 'test'}
        handler.rfile = io.BytesIO(payload)
        responses = []
        handler.send = lambda content, **kwargs: responses.append((content, kwargs))
        handler.do_POST()

        self.assertEqual(responses[0][0], '{"ok":true}')
        state = server.snapshot()
        self.assertEqual(state['settings']['active_run'], '0')
        self.assertEqual(len(state['projects']), 1)
        with server.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM samples').fetchone()[0], 1)

    def host_service(self):
        with server.connect() as db:
            return dict(db.execute("""
                SELECT s.*, d.address FROM services s
                JOIN assignments a ON a.id=s.assignment
                JOIN devices d ON d.id=a.device WHERE s.kind='ping'
            """).fetchone())

    def test_host_ping_is_automatic_and_not_removable(self):
        host = self.host_service()
        server.mutate('remove-service', {'id': host['id']})
        server.initialize()
        checks = [row for row in server.snapshot()['services'] if row['kind'] == 'ping']
        self.assertEqual(len(checks), 1)
        self.assertEqual(checks[0]['assignment'], 1)

    def test_existing_assignment_gets_ping_on_upgrade(self):
        with server.connect() as db:
            db.execute("DELETE FROM services WHERE kind='ping'")
        server.initialize()
        self.assertEqual(self.host_service()['assignment'], 1)

    def test_ping_success_and_failure_create_host_history_and_incident(self):
        host = self.host_service()
        with patch.object(server.subprocess, 'run') as run:
            self.assertEqual(server.read_metric(host), 1)
            self.assertEqual(run.call_args.args[0][-1], '127.0.0.1')
        with patch.object(server, 'read_metric', side_effect=TimeoutError):
            server.poll_one(host, 1)
            server.poll_one(host, 1)
        incident = server.snapshot()['incidents'][0]
        self.assertEqual(incident['service'], host['id'])
        self.assertEqual(incident['status'], 'unreachable')
        with patch.object(server, 'read_metric', return_value=1):
            server.poll_one(host, 1)
            server.poll_one(host, 1)
        self.assertIsNotNone(server.snapshot()['incidents'][0]['closed'])

    def test_option_like_ping_address_is_rejected(self):
        host = self.host_service()
        host['address'] = '-bad'
        with patch.object(server.subprocess, 'run') as run:
            with self.assertRaises(ValueError):
                server.read_metric(host)
            run.assert_not_called()

    def test_inventory_address_applies_to_all_projects(self):
        server.mutate('project', {'name': 'Motorsport'})
        server.mutate('assignment', {'project': 2, 'device': 1, 'alias': 'Timing link'})
        server.mutate('device-address', {'device': 1, 'address': '192.168.1.25'})
        state = server.snapshot()
        self.assertEqual(state['devices'][0]['address'], '192.168.1.25')
        self.assertEqual(len(state['assignments']), 2)
        self.assertTrue(all('address' not in row for row in state['assignments']))
        self.assertEqual(self.host_service()['address'], '192.168.1.25')

    def test_in_flight_reading_from_previous_inventory_ip_is_discarded(self):
        server.mutate('device-address', {'device': 1, 'address': '192.168.1.25'})
        self.poll(-50)
        self.assertEqual(server.snapshot()['latest'], [])

    def test_inventory_requires_valid_ip(self):
        with self.assertRaises(ValueError):
            server.mutate('device', {'name': 'Bad IP', 'address': '-invalid'})

    def legacy_database(self, addresses):
        """Create the old schema shape to exercise upgrade and restored backups."""
        db = sqlite3.connect(':memory:')
        db.executescript("""
            CREATE TABLE devices (id INTEGER PRIMARY KEY, name TEXT, model TEXT);
            CREATE TABLE assignments (
                id INTEGER PRIMARY KEY, device INTEGER, address TEXT NOT NULL
            );
            INSERT INTO devices VALUES(1, 'Radio', 'Siklu');
        """)
        db.executemany('INSERT INTO assignments(device,address) VALUES(1,?)',
                       [(address,) for address in addresses])
        return db

    def test_legacy_addresses_migrate_idempotently(self):
        db = self.legacy_database(['192.168.1.10', '192.168.1.10'])
        try:
            server.migrate_inventory_addresses(db)
            server.migrate_inventory_addresses(db)
            self.assertEqual(db.execute('SELECT address FROM devices').fetchone()[0],
                             '192.168.1.10')
            self.assertEqual(db.execute('SELECT COUNT(*) FROM legacy_assignment_addresses').fetchone()[0], 2)
            self.assertNotIn('address', [row[1] for row in db.execute('PRAGMA table_info(assignments)')])
        finally:
            db.close()

    def test_conflicting_legacy_addresses_are_preserved_for_review(self):
        db = self.legacy_database(['192.168.1.10', '192.168.2.10'])
        try:
            server.migrate_inventory_addresses(db)
            self.assertEqual(db.execute('SELECT address FROM devices').fetchone()[0], '')
            self.assertEqual(db.execute('SELECT COUNT(*) FROM legacy_assignment_addresses').fetchone()[0], 2)
        finally:
            db.close()

    def test_full_inventory_edit_preserves_identity_aliases_and_history(self):
        self.poll(-55)
        server.mutate('device-edit', {
            'device': 1, 'name': 'MW-RENAMED', 'model': 'EH710',
            'address': '192.168.1.70',
        })
        state = server.snapshot()
        self.assertEqual(state['devices'][0], {
            'id': 1, 'name': 'MW-RENAMED', 'model': 'EH710', 'address': '192.168.1.70',
        })
        self.assertEqual(state['assignments'][0]['alias'], 'Stage link')
        self.assertEqual(len(state['services']), 2)
        self.assertEqual(len(state['latest']), 1)

    def test_invalid_or_duplicate_inventory_edit_is_atomic(self):
        server.mutate('device', {'name': 'Other', 'address': '127.0.0.2'})
        for name, address, error in [
            ('Other', '192.168.1.70', sqlite3.IntegrityError),
            ('Changed', 'invalid-ip', ValueError),
            ('   ', '192.168.1.70', ValueError),
        ]:
            with self.assertRaises(error):
                server.mutate('device-edit', {
                    'device': 1, 'name': name, 'model': 'Changed', 'address': address,
                })
            device = server.snapshot()['devices'][0]
            self.assertEqual(device['name'], 'MW-014')
            self.assertEqual(device['address'], '127.0.0.1')

    def test_device_deletion_purges_all_projects_but_preserves_other_equipment(self):
        self.poll(-80)
        self.poll(-80)
        # Removing a service retains history until its owning device is deleted.
        server.mutate('remove-service', {'id': self.service['id']})
        server.mutate('project', {'name': 'Second project'})
        server.mutate('assignment', {'project': 2, 'device': 1, 'alias': 'Other use'})
        server.mutate('device', {'name': 'Keep me', 'address': '127.0.0.2'})
        server.mutate('assignment', {'project': 1, 'device': 2, 'alias': 'Keep host'})
        with server.connect() as db:
            db.execute("INSERT INTO legacy_assignment_addresses VALUES(1,1,'127.0.0.1')")
        server.mutate('delete-device', {'device': 1})
        state = server.snapshot()
        self.assertEqual([row['name'] for row in state['devices']], ['Keep me'])
        self.assertEqual(len(state['assignments']), 1)
        self.assertEqual(state['assignments'][0]['device'], 2)
        self.assertEqual(len(state['services']), 1)
        self.assertEqual(state['latest'], [])
        self.assertEqual(state['incidents'], [])
        self.assertEqual(state['legacy_addresses'], [])
        self.assertEqual(len(state['projects']), 2)
        self.assertEqual(len(state['runs']), 1)
        with server.connect() as db:
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])
            self.assertEqual(db.execute('SELECT COUNT(*) FROM samples').fetchone()[0], 0)

    def test_deleted_device_ids_are_not_reused_by_new_equipment(self):
        old_host = self.host_service()
        server.mutate('delete-device', {'device': 1})
        server.mutate('device', {'name': 'Replacement', 'address': '127.0.0.1'})
        replacement = server.snapshot()['devices'][0]
        self.assertGreater(replacement['id'], 1)
        server.mutate('assignment', {
            'project': 1, 'device': replacement['id'], 'alias': 'Replacement host',
        })
        self.assertGreater(self.host_service()['id'], old_host['id'])
        with patch.object(server, 'read_metric', return_value=1):
            server.poll_one(old_host, 1)
        self.assertEqual(server.snapshot()['latest'], [])

    def test_edit_and_delete_unknown_device_are_rejected(self):
        with self.assertRaises(ValueError):
            server.mutate('delete-device', {'device': 999})
        with self.assertRaises(ValueError):
            server.mutate('device-edit', {
                'device': 999, 'name': 'Missing', 'model': '', 'address': '127.0.0.1',
            })
        self.assertEqual(len(server.snapshot()['devices']), 1)

    def edited_service_body(self, **overrides):
        body = {
            'service': self.service['id'], 'name': 'Edited RSSI', 'kind': 'snmp',
            'target': '.1.2.4', 'community': '', 'unit': '1', 'scale': '0.1',
            'units': 'dBm', 'direction': 'below', 'warning': '-60', 'critical': '-70',
            'persistence': '3',
        }
        body.update(overrides)
        return body

    def test_alarm_edit_preserves_graph_measurement_and_recorded_statuses(self):
        self.poll(-70)
        server.mutate('service-edit', {**self.service, 'service': self.service['id'],
                                      'warning': -80, 'critical': -90, 'persistence': 3,
                                      'flap_changes': 6, 'community': 'new-secret'})
        with server.connect() as db:
            edited = dict(db.execute('SELECT * FROM services WHERE id=?', (self.service['id'],)).fetchone())
        self.assertEqual(edited['revision'], 2)
        self.assertEqual(edited['measurement_revision'], 1)
        self.service.update(edited)
        self.poll(-70)
        with server.connect() as db:
            db.execute('UPDATE samples SET timestamp=100+id WHERE service=?', (self.service['id'],))
        graph = history.read(server.connect, dict(service=[str(self.service['id'])],run=['1'],
                                                  start=['100'],end=['200'],mode=['graph']))
        self.assertEqual(graph['total'], 2)
        self.assertEqual({row['revision'] for row in graph['rows']}, {1, 2})
        self.assertEqual({row['status'] for row in graph['rows']}, {'warning', 'healthy'})
        self.assertFalse(any(row['gap_before'] for row in graph['rows']))
        self.assertEqual(graph['measurement']['warning'], -80)

    def test_measurement_edit_retains_separate_selectable_history_and_metadata(self):
        self.poll(-55)
        source_id = self.service['id']
        server.mutate('service-edit', {**self.service, 'service': source_id,
                                      'target': '.1.2.99', 'units': 'V', 'scale': 0.1})
        with server.connect() as db:
            self.service.update(dict(db.execute('SELECT * FROM services WHERE id=?', (source_id,)).fetchone()))
        self.assertEqual(self.service['measurement_revision'], 2)
        self.poll(24)
        with server.connect() as db:
            db.execute('UPDATE samples SET timestamp=100+id WHERE service=?', (source_id,))
        query = dict(service=[str(source_id)],run=['1'],start=['100'],end=['200'],mode=['graph'])
        current = history.read(server.connect, query)
        old = history.read(server.connect, {**query, 'measurement':['1']})
        self.assertEqual([row['value'] for row in current['rows']], [24])
        self.assertEqual([row['value'] for row in old['rows']], [-55])
        self.assertEqual(old['measurement']['target'], '.1.2.3')
        self.assertEqual(old['measurement']['units'], '')
        self.assertIsNone(old['measurement']['warning'])
        self.assertNotIn('community', old['measurement'])
        self.assertEqual(len(current['measurements']), 2)
        self.assertEqual(len(history.read(server.connect, {**query,'mode':['table']})['rows']), 2)
        server.initialize()
        self.assertEqual(history.read(server.connect, {**query,'measurement':['1']})['total'], 1)
        with self.assertRaises(history.HistoryError):
            history.read(server.connect, {**query,'measurement':['99']})
        with server.connect() as db:
            db.execute('DELETE FROM services WHERE id=?', (source_id,))
            self.assertEqual(db.execute('SELECT COUNT(*) FROM service_measurements').fetchone()[0], 0)

    def test_alarm_edit_still_discards_inflight_reads_using_old_rules(self):
        def read_and_edit(service):
            server.mutate('service-edit', {**self.service, 'service': service['id'],
                                          'warning': -80, 'critical': -90})
            return -70
        with patch.object(server, 'read_metric', side_effect=read_and_edit):
            server.poll_one(self.service, 1)
        with server.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM samples').fetchone()[0], 0)

    def test_state_label_metadata_survives_measurement_changes(self):
        first = {'1': {'label':'Running', 'status':'healthy'}}
        server.mutate('service-edit', {**self.service, 'service':self.service['id'],
                                      'value_type':'state', 'state_map':first})
        with server.connect() as db:
            state_service = dict(db.execute('SELECT * FROM services WHERE id=?', (self.service['id'],)).fetchone())
        # Changing severity keeps the same measurement; renaming the label starts another.
        second = {'1': {'label':'Running', 'status':'warning'}}
        server.mutate('service-edit', {**state_service, 'service':state_service['id'], 'state_map':second})
        with server.connect() as db:
            self.assertEqual(db.execute('SELECT measurement_revision FROM services WHERE id=?',
                                        (self.service['id'],)).fetchone()[0], 2)
        server.mutate('service-edit', {**state_service, 'service':state_service['id'],
                                      'state_map':{'1': {'label':'Enabled','status':'healthy'}}})
        query = dict(service=[str(self.service['id'])],run=['1'],start=['100'],end=['200'],
                     mode=['graph'],measurement=['2'])
        graph = history.read(server.connect, query)
        self.assertEqual(graph['measurement']['state_map']['1']['label'], 'Running')
        self.assertNotIn('community', graph['measurement'])

    def test_measurement_migration_preserves_legacy_samples_without_rewriting_them(self):
        self.poll(-55)
        with server.connect() as db:
            db.execute('ALTER TABLE services DROP COLUMN measurement_revision')
            db.execute('ALTER TABLE samples DROP COLUMN measurement_revision')
        server.initialize()
        server.initialize()
        with server.connect() as db:
            row = db.execute('SELECT * FROM samples WHERE service=?', (self.service['id'],)).fetchone()
            self.assertEqual((row['value'], row['measurement_revision'], row['revision']), (-55, 1, 1))

    def test_measurement_field_detection_ignores_irrelevant_modbus_fields(self):
        base = dict(self.service)
        updated = {**base, 'unit': 5, 'modbus_function': 4}
        self.assertFalse(history.measurement_changed(base, updated))
        for field, value in (('kind', 'modbus'), ('target', '.1.2.9'), ('scale', 0.1),
                             ('units', 'dBm'), ('value_type', 'state')):
            with self.subTest(field=field):
                self.assertTrue(history.measurement_changed(base, {**base, field:value}))
        modbus = {**base,'kind':'modbus'}
        for field, value in (('unit', 7), ('modbus_function', 4)):
            self.assertTrue(history.measurement_changed(modbus, {**modbus,field:value}))

    def test_service_edit_preserves_identity_secret_and_history(self):
        self.poll(-55)
        with server.connect() as db:
            db.execute('UPDATE services SET community=? WHERE id=?',
                       ('private-secret', self.service['id']))
        server.mutate('service-edit', self.edited_service_body())
        with server.connect() as db:
            edited = db.execute('SELECT * FROM services WHERE id=?', (self.service['id'],)).fetchone()
            self.assertEqual(edited['name'], 'Edited RSSI')
            self.assertEqual(edited['assignment'], self.service['assignment'])
            self.assertEqual(edited['community'], 'private-secret')
            self.assertEqual(edited['scale'], 0.1)
            self.assertEqual(edited['persistence'], 3)
            self.assertEqual(edited['revision'], 2)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM samples').fetchone()[0], 1)
        self.assertEqual(server.snapshot()['latest'], [])
        self.assertNotIn('community', server.snapshot()['services'][1])

    def test_service_edit_rejects_invalid_values_atomically(self):
        for change in ({'target': 'not-an-oid'}, {'scale': 'nan'},
                       {'persistence': '0'}, {'unit': '248'},
                       {'warning': '-80', 'critical': '-60'}):
            with self.assertRaises(ValueError):
                server.mutate('service-edit', self.edited_service_body(**change))
        with server.connect() as db:
            row = db.execute('SELECT * FROM services WHERE id=?', (self.service['id'],)).fetchone()
            self.assertEqual(row['name'], 'RSSI')
            self.assertEqual(row['revision'], 1)

    def test_service_edit_can_replace_credentials_and_change_protocol(self):
        server.mutate('service-edit', self.edited_service_body(
            community='replacement', kind='modbus', target='100', unit='7',
        ))
        with server.connect() as db:
            row = db.execute('SELECT * FROM services WHERE id=?', (self.service['id'],)).fetchone()
            self.assertEqual((row['kind'], row['target'], row['unit']), ('modbus', '100', 7))
            self.assertEqual(row['community'], 'replacement')

    def test_managed_or_removed_services_cannot_be_edited(self):
        with self.assertRaises(ValueError):
            server.mutate('service-edit', self.edited_service_body(service=self.host_service()['id']))
        server.mutate('remove-service', {'id': self.service['id']})
        with self.assertRaises(ValueError):
            server.mutate('service-edit', self.edited_service_body())

    def test_service_edit_discards_old_poll_and_restarts_persistence(self):
        self.poll(-80)
        server.mutate('service-edit', self.edited_service_body(persistence='2'))
        self.poll(-80)  # An in-flight read for revision 1 must be discarded.
        with server.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM samples').fetchone()[0], 1)
            self.service = dict(db.execute("""
                SELECT s.*, d.address FROM services s
                JOIN assignments a ON a.id=s.assignment JOIN devices d ON d.id=a.device
                WHERE s.id=?
            """, (self.service['id'],)).fetchone())
        self.poll(-80)
        self.assertEqual(server.snapshot()['incident_lists']['active'], [])
        self.poll(-80)
        self.assertEqual(len(server.snapshot()['incident_lists']['active']), 1)

    def test_acknowledged_incident_moves_to_resolved_with_attribution_after_recovery(self):
        self.poll(-80)
        self.poll(-80)
        incident = server.snapshot()['incident_lists']['active'][0]
        with server.connect() as db:
            db.execute("UPDATE users SET full_name='Test Administrator' WHERE id=1")
        server.mutate('ack', {'id': incident['id']}, actor={'id': 1})
        lists = server.snapshot()['incident_lists']
        self.assertEqual(lists['active'], [])
        self.assertEqual(len(lists['acknowledged']), 1)
        self.assertIsNone(lists['acknowledged'][0]['closed'])
        timestamp = lists['acknowledged'][0]['acknowledged']
        server.mutate('ack', {'id': incident['id']}, actor={'id': 1})
        self.assertEqual(server.snapshot()['incident_lists']['acknowledged'][0]['acknowledged'], timestamp)
        self.poll(-50)
        self.assertIsNone(server.snapshot()['incident_lists']['acknowledged'][0]['closed'])
        self.assertEqual(server.snapshot()['incident_lists']['resolved'], [])
        self.poll(-50)
        lists = server.snapshot()['incident_lists']
        self.assertEqual(lists['acknowledged'], [])
        self.assertEqual(lists['active'], [])
        resolved = lists['resolved'][0]
        self.assertIsNotNone(resolved['closed'])
        self.assertEqual(resolved['id'], incident['id'])
        self.assertEqual(resolved['acknowledged'], timestamp)
        self.assertEqual(resolved['acknowledged_by_username'], 'admin')
        self.assertEqual(resolved['acknowledged_by_full_name'], 'Test Administrator')
        self.assertEqual(resolved['acknowledgement_history'][-1]['action'], 'acknowledged')
        server.initialize()
        self.assertEqual(server.snapshot()['incident_lists']['resolved'][0]['id'], incident['id'])

    def test_unacknowledged_recovery_moves_to_resolved_list(self):
        self.poll(-80)
        self.poll(-80)
        self.poll(-50)
        self.poll(-50)
        lists = server.snapshot()['incident_lists']
        self.assertEqual(lists['active'], [])
        self.assertEqual(lists['acknowledged'], [])
        self.assertEqual(len(lists['resolved']), 1)
        self.start_deployment({'project': 1, 'description': 'Test deployment'})
        self.assertEqual(server.snapshot()['incident_lists']['resolved'], [])

    def add_copy_target(self):
        server.mutate('device', {'name': 'Target radio', 'address': '127.0.0.2'})
        server.mutate('assignment', {'project': 1, 'device': 2, 'alias': 'Target link'})
        return server.snapshot()['assignments'][-1]['id']

    def create_template_from_service(self):
        server.mutate('template-create', self.edited_service_body(
            source=self.service['id'], name='Library RSSI', community='',
        ))
        return server.snapshot()['service_templates'][0]['id']

    def test_service_copy_has_independent_identity_settings_and_history(self):
        target = self.add_copy_target()
        self.poll(-80)
        self.poll(-80)
        with server.connect() as db:
            db.execute('UPDATE services SET community=? WHERE id=?',
                       ('source-secret', self.service['id']))
        server.mutate('service-copy', {
            'service': self.service['id'], 'assignment': target, 'name': 'Copied RSSI',
        })
        with server.connect() as db:
            copied = db.execute("SELECT * FROM services WHERE name='Copied RSSI'").fetchone()
            self.assertNotEqual(copied['id'], self.service['id'])
            self.assertEqual(copied['assignment'], target)
            self.assertEqual(copied['community'], 'source-secret')
            self.assertEqual(copied['warning'], -65)
            self.assertEqual(copied['critical'], -75)
            self.assertEqual(copied['revision'], 1)
            for table in ('samples', 'incidents'):
                self.assertEqual(db.execute(f'SELECT COUNT(*) FROM {table} WHERE service=?',
                                            (copied['id'],)).fetchone()[0], 0)
        server.mutate('service-edit', self.edited_service_body())
        copied = next(row for row in server.snapshot()['services'] if row['name'] == 'Copied RSSI')
        self.assertEqual(copied['target'], '.1.2.3')

    def test_copy_rejects_same_host_unknown_target_and_managed_ping(self):
        for source, target in ((self.service['id'], 1), (self.service['id'], 999),
                               (self.host_service()['id'], self.add_copy_target())):
            with self.assertRaises(ValueError):
                server.mutate('service-copy', {'service': source, 'assignment': target})
        self.assertEqual(len(server.snapshot()['services']), 3)

    def test_library_apply_edit_and_delete_do_not_change_materialized_services(self):
        template = self.create_template_from_service()
        target = self.add_copy_target()
        server.mutate('template-apply', {
            'template': template, 'assignment': target, 'community': 'target-secret',
        })
        server.mutate('template-edit', self.edited_service_body(
            template=template, name='Changed template', target='.1.2.99',
        ))
        with server.connect() as db:
            copied = db.execute("SELECT * FROM services WHERE assignment=? AND kind='snmp'", (target,)).fetchone()
            self.assertEqual(copied['name'], 'Library RSSI')
            self.assertEqual(copied['target'], '.1.2.4')
            self.assertEqual(copied['community'], 'target-secret')
        server.mutate('template-delete', {'template': template})
        self.assertEqual(server.snapshot()['service_templates'], [])
        self.assertTrue(any(row['name'] == 'Library RSSI' for row in server.snapshot()['services']))

    def test_library_survives_source_device_deletion_and_is_redacted(self):
        with server.connect() as db:
            db.execute('UPDATE services SET community=? WHERE id=?',
                       ('source-secret', self.service['id']))
        template = self.create_template_from_service()
        self.assertNotIn('community', server.snapshot()['service_templates'][0])
        server.mutate('delete-device', {'device': 1})
        self.assertEqual(len(server.snapshot()['service_templates']), 1)
        with server.connect() as db:
            row = db.execute('SELECT community FROM service_templates WHERE id=?', (template,)).fetchone()
            self.assertEqual(row[0], 'source-secret')

    def test_library_can_be_created_without_a_source_and_duplicate_names_are_rejected(self):
        body = self.edited_service_body(name='Reusable voltage', kind='modbus', target='100')
        server.mutate('template-create', body)
        with self.assertRaises(sqlite3.IntegrityError):
            server.mutate('template-create', body)
        self.assertEqual(len(server.snapshot()['service_templates']), 1)
        with self.assertRaises(ValueError):
            server.mutate('template-apply', {'template': 999, 'assignment': 1})

    def test_templates_are_restored_with_the_database(self):
        self.create_template_from_service()
        with server.connect() as source:
            backup = sqlite3.connect(':memory:')
            source.backup(backup)
            payload = backup.serialize()
            backup.close()
        server.mutate('template-delete', {'template': 1})
        handler = object.__new__(server.Handler)
        handler.path = '/api/restore'
        handler.headers = {'X-CSRF-Token': 'test', 'Content-Length': str(len(payload)),
                           'Content-Type': 'application/octet-stream'}
        handler.require_user = lambda **kwargs: {'id': 1, 'role': 'admin', 'csrf': 'test'}
        handler.rfile = io.BytesIO(payload)
        responses = []
        handler.send = lambda content, **kwargs: responses.append(content)
        handler.do_POST()
        self.assertEqual(responses, ['{"ok":true}'])
        self.assertEqual(len(server.snapshot()['service_templates']), 1)
        self.assertEqual(server.snapshot()['settings']['active_run'], '0')

    def test_legacy_database_gets_empty_service_library(self):
        with server.connect() as db:
            db.execute('DROP TABLE service_templates')
        server.initialize()
        self.assertEqual(server.snapshot()['service_templates'], [])

    def reload_service(self):
        with server.connect() as db:
            self.service = dict(db.execute("""
                SELECT s.*, d.address FROM services s
                JOIN assignments a ON a.id=s.assignment JOIN devices d ON d.id=a.device
                WHERE s.id=?
            """, (self.service['id'],)).fetchone())

    def poll_ping(self, up):
        host = self.host_service()
        if up:
            with patch.object(server, 'read_metric', return_value=1):
                server.poll_one(host, 1)
        else:
            with patch.object(server, 'read_metric', side_effect=TimeoutError):
                server.poll_one(host, 1)

    def test_host_down_suppresses_children_without_network_reads_or_child_incidents(self):
        self.host_dependency.stop()
        self.poll_ping(False)
        with patch.object(server, 'read_metric') as read:
            server.poll_one(self.service, 1)
            server.poll_one(self.service, 1)
            read.assert_not_called()
        latest = next(row for row in server.snapshot()['latest'] if row['service'] == self.service['id'])
        self.assertEqual(latest['status'], 'blocked')
        self.assertIsNone(latest['value'])
        self.assertEqual(server.snapshot()['incidents'], [])
        self.poll_ping(False)
        active = server.snapshot()['incident_lists']['active']
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0]['service'], self.host_service()['id'])

    def test_missing_or_stale_ping_does_not_report_service_failure(self):
        self.host_dependency.stop()
        with patch.object(server, 'read_metric') as read:
            server.poll_one(self.service, 1)
            read.assert_not_called()
        self.poll_ping(True)
        with server.connect() as db:
            db.execute("UPDATE samples SET timestamp=0 WHERE service=?", (self.host_service()['id'],))
        with patch.object(server, 'read_metric') as read:
            server.poll_one(self.service, 1)
            read.assert_not_called()
        self.assertEqual(server.snapshot()['incident_lists']['active'], [])

    def test_services_can_fail_when_host_is_online(self):
        self.host_dependency.stop()
        self.poll_ping(True)
        with patch.object(server, 'read_metric', side_effect=TimeoutError):
            server.poll_one(self.service, 1)
            server.poll_one(self.service, 1)
        active = server.snapshot()['incident_lists']['active']
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0]['service'], self.service['id'])

    def test_existing_service_incident_is_suppressed_and_not_falsely_recovered(self):
        self.host_dependency.stop()
        self.poll_ping(True)
        self.poll(-80)
        self.poll(-80)
        self.poll_ping(False)
        self.poll(-80)  # Blocked rather than collected when ping is down.
        lists = server.snapshot()['incident_lists']
        self.assertEqual(lists['active'], [])
        self.assertEqual(len(lists['suppressed']), 1)
        self.assertIsNone(lists['suppressed'][0]['closed'])
        self.poll_ping(True)
        self.assertEqual(len(server.snapshot()['incident_lists']['suppressed']), 1)
        self.poll(-50)
        self.poll(-50)
        lists = server.snapshot()['incident_lists']
        self.assertEqual(lists['suppressed'], [])
        self.assertEqual(len(lists['resolved']), 1)

    def test_poll_host_checks_ping_before_children(self):
        self.host_dependency.stop()
        calls = []
        def read(service):
            calls.append(service['kind'])
            if service['kind'] == 'ping':
                raise TimeoutError()
            return -80
        with patch.object(server, 'read_metric', side_effect=read):
            server.poll_host([self.service, self.host_service()], 1)
        self.assertEqual(calls, ['ping'])

    def configure_state_service(self):
        mapping = {'1': {'label': 'Up', 'status': 'healthy'},
                   '2': {'label': 'Down', 'status': 'critical'}}
        server.mutate('service-edit', self.edited_service_body(
            name='Port state', value_type='state', state_map=mapping,
            scale='1', warning='', critical='',
        ))
        self.reload_service()
        return mapping

    def test_state_values_display_labels_and_control_severity(self):
        self.configure_state_service()
        self.assertEqual(server.classify(1, self.service), 'healthy')
        self.assertEqual(server.classify(2, self.service), 'critical')
        self.assertEqual(server.display_value(self.service, 1), 'Up')
        self.assertEqual(server.display_value(self.service, 2), 'Down')
        self.poll(2)
        reading = next(row for row in server.snapshot()['latest'] if row['service'] == self.service['id'])
        self.assertEqual(reading['display_value'], 'Down')
        self.assertEqual(reading['value'], 2)
        self.assertEqual(reading['status'], 'critical')
        self.poll(2)
        self.poll(2)
        self.assertEqual(len(server.snapshot()['incident_lists']['active']), 1)
        self.poll(1)
        self.poll(1)
        self.poll(1)
        self.assertEqual(len(server.snapshot()['incident_lists']['resolved']), 1)

    def test_unmapped_state_warns_instead_of_showing_healthy(self):
        self.configure_state_service()
        self.assertEqual(server.classify(99, self.service), 'warning')
        self.assertEqual(server.display_value(self.service, 99), 'Unmapped state (99)')

    def test_state_mapping_survives_copy_and_library_apply(self):
        mapping = self.configure_state_service()
        target = self.add_copy_target()
        server.mutate('service-copy', {'service': self.service['id'], 'assignment': target})
        server.mutate('template-create', {**dict(self.service), 'source': self.service['id']})
        template = server.snapshot()['service_templates'][0]
        self.assertEqual(template['state_map'], mapping)
        server.mutate('template-apply', {'template': template['id'], 'assignment': target})
        copies = [row for row in server.snapshot()['services'] if row['assignment'] == target and row['kind'] == 'snmp']
        self.assertEqual(len(copies), 2)
        self.assertTrue(all(row['state_map'] == mapping and row['value_type'] == 'state' for row in copies))

    def test_invalid_state_mappings_are_rejected(self):
        for mapping in ({}, {'x': {'label': 'Up', 'status': 'healthy'}},
                        {'1': {'label': '', 'status': 'healthy'}},
                        {'1': {'label': 'Up', 'status': 'invalid'}},
                        {'1': {'label': 'Up', 'status': 'healthy'},
                         '1.0': {'label': 'Duplicate', 'status': 'critical'}}):
            with self.assertRaises(ValueError):
                server.mutate('service-edit', self.edited_service_body(
                    value_type='state', state_map=mapping,
                ))

    def test_host_failure_during_service_read_suppresses_result(self):
        self.host_dependency.stop()
        self.poll_ping(True)
        def read(service):
            self.poll_ping(False)
            return -80
        with patch.object(server, 'read_metric', side_effect=read):
            server.poll_one(self.service, 1)
        reading = next(row for row in server.snapshot()['latest'] if row['service'] == self.service['id'])
        self.assertEqual(reading['status'], 'blocked')
        self.assertEqual(server.snapshot()['incident_lists']['active'], [])

    def test_numeric_metric_scaling_and_snmp_enum_output(self):
        self.service['scale'] = 0.1
        result = type('Result', (), {'stdout': '32\n'})()
        with patch.object(server.subprocess, 'run', return_value=result) as run:
            self.assertAlmostEqual(server.read_metric(self.service), 3.2)
            self.assertIn('-Oeqv', run.call_args.args[0])
        self.assertEqual(server.display_value(self.service, 3.2), '3.2')

    def test_scaled_metric_display_removes_float_residue_without_rounding_samples(self):
        for value, expected in ((231 * 0.1, '23.1'), (321 * 0.1, '32.1'),
                                (2301 * 0.1, '230.1'), (4099 * 0.1, '409.9'),
                                (-321 * 0.1, '-32.1'), (0.000000123456, '1.23456e-07')):
            with self.subTest(value=value):
                self.assertEqual(server.display_value(self.service, value), expected)
        original = 231 * 0.1
        self.poll(original)
        with server.connect() as db:
            reading = db.execute('SELECT value,display_value FROM samples WHERE service=?',
                                 (self.service['id'],)).fetchone()
        self.assertEqual(reading['value'], original)
        self.assertEqual(reading['display_value'], '23.1')

    def test_blocked_samples_break_service_persistence_streaks(self):
        self.host_dependency.stop()
        self.poll_ping(True)
        self.poll(-80)
        self.poll_ping(False)
        self.poll(-80)
        self.poll_ping(True)
        self.poll(-80)
        self.assertEqual(server.snapshot()['incident_lists']['active'], [])
        self.poll(-80)
        self.assertEqual(len(server.snapshot()['incident_lists']['active']), 1)

    def test_project_alias_edit_preserves_history_and_other_project_aliases(self):
        self.poll(-55)
        server.mutate('project', {'name': 'Other project'})
        server.mutate('assignment', {'project': 2, 'device': 1, 'alias': 'Other alias'})
        server.mutate('assignment-edit', {'assignment': 1, 'alias': 'New stage alias'})
        state = server.snapshot()
        self.assertEqual([row['alias'] for row in state['assignments']],
                         ['New stage alias', 'Other alias'])
        self.assertEqual(state['devices'][0]['name'], 'MW-014')
        self.assertEqual(len(state['latest']), 1)
        self.assertEqual(len(state['services']), 3)

    def test_alias_edit_rejects_empty_alias_or_unknown_assignment(self):
        with self.assertRaises(ValueError):
            server.mutate('assignment-edit', {'assignment': 1, 'alias': '   '})
        with self.assertRaises(ValueError):
            server.mutate('assignment-edit', {'assignment': 999, 'alias': 'New alias'})
        self.assertEqual(server.snapshot()['assignments'][0]['alias'], 'Stage link')

    def test_acknowledged_service_stays_acknowledged_when_host_goes_down(self):
        self.host_dependency.stop()
        self.poll_ping(True)
        self.poll(-80)
        self.poll(-80)
        incident = server.snapshot()['incident_lists']['active'][0]
        server.mutate('ack', {'id': incident['id']}, actor={'id': 1})
        self.poll_ping(False)
        lists = server.snapshot()['incident_lists']
        self.assertEqual(lists['active'], [])
        self.assertEqual(len(lists['acknowledged']), 1)
        self.assertTrue(lists['acknowledged'][0]['suppressed'])
        self.assertEqual(lists['suppressed'], [])

    def test_host_card_uses_highest_open_service_severity_until_recovery(self):
        self.poll_ping(True)
        self.poll(-70)
        self.poll(-70)
        self.assertEqual(server.snapshot()['assignments'][0]['incident_status'], 'warning')
        server.mutate('service', {'assignment': 1, 'name': 'Temperature', 'kind': 'snmp',
            'target': '.1.2.5', 'direction': 'above', 'warning': '70', 'critical': '80'})
        with server.connect() as db:
            temperature = dict(db.execute("""SELECT s.*, d.address FROM services s
                JOIN assignments a ON a.id=s.assignment JOIN devices d ON d.id=a.device
                WHERE s.name='Temperature'""").fetchone())
        with patch.object(server, 'read_metric', return_value=90):
            server.poll_one(temperature, 1)
            server.poll_one(temperature, 1)
        state = server.snapshot()
        self.assertEqual(state['assignments'][0]['incident_status'], 'critical')
        critical = next(row for row in state['incident_lists']['active'] if row['status'] == 'critical')
        server.mutate('ack', {'id': critical['id']}, actor={'id': 1})
        self.assertEqual(server.status_overview(include_hosts=True)['devices'][0]['incident_status'], 'critical')
        with patch.object(server, 'read_metric', return_value=50):
            server.poll_one(temperature, 1)
            server.poll_one(temperature, 1)
        self.assertEqual(server.snapshot()['assignments'][0]['incident_status'], 'warning')
        self.poll(-50)
        self.poll(-50)
        self.assertIsNone(server.snapshot()['assignments'][0]['incident_status'])

    def test_host_card_ignores_unconfirmed_faults_and_paused_monitoring(self):
        self.poll_ping(True)
        self.poll(-80)
        self.assertIsNone(server.snapshot()['assignments'][0]['incident_status'])
        self.poll(-80)
        self.assertEqual(server.snapshot()['assignments'][0]['incident_status'], 'critical')
        server.mutate('toggle', {'id': 1, 'field': 'monitoring'})
        self.assertIsNone(server.snapshot()['assignments'][0]['incident_status'])

    def test_capitalised_state_severities_are_normalised_for_storage(self):
        server.mutate('service-edit', self.edited_service_body(value_type='state', state_map={
            '1': {'label': 'Up', 'status': 'Healthy'},
            '2': {'label': 'Down', 'status': 'Critical'},
        }))
        self.reload_service()
        self.assertEqual(server.classify(1, self.service), 'healthy')
        self.assertEqual(server.classify(2, self.service), 'critical')

    def test_service_pause_preserves_configuration_history_and_suppresses_incidents(self):
        self.poll_ping(True)
        self.poll(-80)
        self.poll(-80)
        server.mutate('service-monitoring', {'service': self.service['id'], 'monitoring': False})
        state = server.snapshot()
        paused = next(row for row in state['services'] if row['id'] == self.service['id'])
        self.assertEqual(paused['monitoring'], 0)
        self.assertEqual(paused['enabled'], 1)
        self.assertEqual(paused['target'], '.1.2.3')
        self.assertEqual(state['incident_lists']['active'], [])
        self.assertEqual(state['incident_lists']['suppressed'][0]['suppressed_reason'], 'Service monitoring paused')
        self.assertIsNone(state['assignments'][0]['incident_status'])
        with patch.object(server, 'read_metric') as read:
            server.poll_one(self.service, 1)
            read.assert_not_called()
        public = server.status_overview(include_hosts=True)
        self.assertEqual(public['devices'][0]['services'][0]['status'], 'paused')
        with server.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM samples WHERE service=?', (self.service['id'],)).fetchone()[0], 3)

    def test_service_resume_restarts_persistence_without_changing_configuration_revision(self):
        self.poll_ping(True)
        self.poll(-80)
        server.mutate('service-monitoring', {'service': self.service['id'], 'monitoring': False})
        server.mutate('service-monitoring', {'service': self.service['id'], 'monitoring': True})
        old = dict(self.service)
        self.reload_service()
        self.assertEqual(self.service['revision'], old['revision'])
        with patch.object(server, 'read_metric') as read:
            server.poll_one(old, 1)
            read.assert_not_called()
        self.poll(-80)
        self.assertEqual(server.snapshot()['incident_lists']['active'], [])
        self.poll(-80)
        self.assertEqual(len(server.snapshot()['incident_lists']['active']), 1)
        with self.assertRaises(ValueError):
            server.mutate('service-monitoring', {'service': self.host_service()['id'], 'monitoring': False})

    def test_remove_from_project_preserves_inventory_other_projects_and_history(self):
        self.poll(-55)
        server.mutate('project', {'name': 'Other event'})
        server.mutate('assignment', {'project': 2, 'device': 1, 'alias': 'Other alias'})
        server.mutate('assignment-remove', {'assignment': 1})
        state = server.snapshot()
        self.assertEqual(len(state['devices']), 1)
        self.assertEqual(state['assignments'][0]['removed'], 1)
        self.assertEqual(state['assignments'][1]['removed'], 0)
        self.assertEqual(state['assignments'][1]['alias'], 'Other alias')
        self.assertEqual(server.status_overview()['devices'], [])
        self.assertEqual(state['incident_lists']['active'], [])
        with patch.object(server, 'read_metric') as read:
            server.poll_one(self.service, 1)
            read.assert_not_called()
        with server.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM samples').fetchone()[0], 1)
        server.mutate('assignment', {'project': 1, 'device': 1, 'alias': 'Restored alias'})
        restored = server.snapshot()
        self.assertEqual(len(restored['assignments']), 2)
        self.assertEqual(restored['assignments'][0]['removed'], 0)
        self.assertEqual(restored['assignments'][0]['alias'], 'Restored alias')
        self.assertTrue(any(row['id'] == self.service['id'] for row in restored['services']))

    def test_poll_failure_does_not_log_credential(self):
        with patch.object(server, 'read_metric', side_effect=RuntimeError('secret community')):
            server.poll_one(self.service, 1)
        self.assertEqual(server.snapshot()['latest'][0]['error'], 'RuntimeError')

    def test_opening_evidence_survives_readings_edits_and_retention(self):
        self.poll(-80)
        self.poll(-81)
        issue = server.snapshot()['incidents'][0]
        self.assertEqual(issue['trigger_value'], -81)
        self.assertEqual(issue['trigger_display'], '-81')
        self.poll(-60)
        self.poll(-60)
        with server.connect() as db:
            db.execute('DELETE FROM samples')
            db.execute("UPDATE services SET units='changed',name='Renamed' WHERE id=?", (self.service['id'],))
        saved = server.snapshot()['incidents'][0]
        self.assertEqual(saved['trigger_value'], -81)
        self.assertEqual(saved['trigger_units'], '')
        self.assertIsNotNone(saved['closed'])

    def test_state_and_unreachable_opening_evidence(self):
        with server.connect() as db:
            db.execute("""UPDATE services SET value_type='state',state_map=? WHERE id=?""",
                       ('{"1":{"label":"Port Up","status":"healthy"},"2":{"label":"Port Down","status":"critical"}}', self.service['id']))
            self.service = dict(db.execute('SELECT s.*,? address FROM services s WHERE id=?',
                                          (self.service['address'], self.service['id'])).fetchone())
        self.poll(2)
        self.poll(2)
        self.assertEqual(server.snapshot()['incidents'][0]['trigger_display'], 'Port Down')
        with patch.object(server, 'read_metric', side_effect=TimeoutError('private credential')):
            server.poll_one(self.service, 1)
            server.poll_one(self.service, 1)
        issue = server.snapshot()['incidents'][0]
        self.assertEqual(issue['trigger_error'], 'TimeoutError')
        self.assertIsNone(issue['trigger_value'])

    def test_negative_metric_recovery_hysteresis_and_escalation(self):
        service = {**self.service, 'hysteresis': 3}
        self.assertEqual(server.classify(-64, service, 'warning'), 'warning')
        self.assertEqual(server.classify(-62, service, 'warning'), 'healthy')
        self.assertEqual(server.classify(-74, service, 'critical'), 'critical')
        self.assertEqual(server.classify(-72, service, 'critical'), 'warning')
        self.assertEqual(server.classify(-80, service, 'healthy'), 'critical')
        self.assertEqual(server.classify(-64, {**service, 'hysteresis': 0}, 'warning'), 'healthy')
        service.update(direction='above', warning=50, critical=70)
        self.assertEqual(server.classify(49, service, 'warning'), 'warning')
        self.assertEqual(server.classify(47, service, 'warning'), 'healthy')

    def test_flap_episodes_are_persistent_and_require_continuous_stability(self):
        from app import stability
        service = {**self.service, 'flap_stable': 1}
        with server.connect() as db:
            events = [stability.observe(db, service, 1, status, True, 1000 + index * 15)
                      for index, status in enumerate(('healthy', 'critical', 'healthy', 'critical', 'healthy'))]
        self.assertEqual(events[-1], 'flap-start:1')
        with server.connect() as db:
            # Reopening the DB must retain the episode, and gaps cannot clear it.
            self.assertEqual(stability.observe(db, service, 1, 'healthy', True, 1200), None)
            for stamp in (1215, 1230, 1245):
                self.assertIsNone(stability.observe(db, service, 1, 'healthy', True, stamp))
            self.assertEqual(stability.observe(db, service, 1, 'healthy', True, 1260), 'flap-stable:1')
            runtime = stability.state_for(db, 1, service['id'], service['revision'], service['monitoring_since'])
            self.assertFalse(runtime['flapping'])
            self.assertTrue(stability.event_is_current(runtime, 'flap-stable:1', 1260))
            self.assertFalse(stability.event_is_current(runtime, 'flap-start:1', 1260))
            self.assertFalse(stability.event_is_current(runtime, 'flap-stable:1', 1400))

    def test_flapping_suppresses_ordinary_notifications_but_keeps_issues(self):
        from app import notifications
        server.mutate('notification-pause', {'paused': False})
        with server.connect() as db:
            notifications.save_configuration(db, {'enabled': True, 'bot_token': '123:test', 'chat_id': '-123',
                                                  'recoveries': True})
        self.service['persistence'] = 1
        with server.connect() as db:
            db.execute('UPDATE services SET persistence=1 WHERE id=?', (self.service['id'],))
        clock = self.service['monitoring_since'] + 1
        for index, value in enumerate((-60, -80, -60, -80, -60, -80, -60)):
            with patch('time.time', return_value=clock + index * 15):
                self.poll(value)
        with server.connect() as db:
            outbox = [dict(row) for row in db.execute('SELECT * FROM notification_outbox')]
            self.assertEqual(len([row for row in outbox if row['event'] == 'flap-start:1']), 1)
            flap_message = next(row['text'] for row in outbox if row['event'] == 'flap-start:1')
            self.assertEqual(flap_message.splitlines(), [
                '⚠️ FLAPPING - Festival', 'MW-014 - Stage link', 'RSSI: -60', 'Issue #2 - Deployment #1',
                'Notifications for this check are suppressed until it stabilises.'])

            self.assertFalse(any(row['state'] == 'pending' and row['event'] in ('opened', 'recovery') for row in outbox))
            self.assertEqual(db.execute('SELECT COUNT(*) FROM samples WHERE service=?', (self.service['id'],)).fetchone()[0], 7)
        self.assertTrue(next(row for row in server.snapshot()['services'] if row['id'] == self.service['id'])['flapping'])
        for index in range(7, 27):
            with patch('time.time', return_value=clock + index * 15):
                self.poll(-60)
        with server.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM notification_outbox WHERE event='flap-stable:1'").fetchone()[0], 1)
        with patch('time.time', return_value=clock + 390), patch.object(notifications, 'send_message', return_value='test-id') as send:
            while notifications.deliver_once(server.connect, server.LOCK, server.host_is_up):
                pass
            self.assertEqual(send.call_count, 1)
            self.assertTrue(send.call_args.args[1].startswith('✅ STABLE - Festival\n'))
            self.assertNotIn('HEALTHY', send.call_args.args[1])
            self.assertEqual(len(send.call_args.args[1].splitlines()), 4)
        self.assertFalse(next(row for row in server.snapshot()['services'] if row['id'] == self.service['id'])['flapping'])

    def test_notification_opening_uses_saved_cause_after_later_reading(self):
        from app import notifications
        self.poll(-80)
        self.poll(-81)
        issue = server.snapshot()['incidents'][0]
        self.poll(-60)
        server.mutate('notification-pause', {'paused': False})
        with server.connect() as db:
            notifications.save_configuration(db, {'enabled': True, 'bot_token': '123:test', 'chat_id': '-123'})
            notifications.enqueue_incident(db, issue['id'], 'opened')
            message = db.execute('SELECT text FROM notification_outbox').fetchone()[0]
            self.assertIn('RSSI: -81', message)
            self.assertNotIn('RSSI: -60', message)
            notifications.enqueue_incident(db, issue['id'], 'reminder:1')
            message = db.execute("SELECT text FROM notification_outbox WHERE event='reminder:1'").fetchone()[0]
            self.assertIn('\n-81', message)
            self.assertNotIn('Triggered by', message)
            notifications.enqueue_incident(db, issue['id'], 'recovery')
            recovered = db.execute("SELECT text FROM notification_outbox WHERE event='recovery'").fetchone()[0]
            self.assertIn('RSSI: -60', recovered)
            self.assertNotIn('-81', recovered)


    def test_policy_export_roundtrip_and_disabled_detector(self):
        from app import stability, service_library
        definition = {**self.service, 'name': 'Reusable RSSI', 'flap_enabled': False,
                      'flap_changes': 6, 'flap_window': 7, 'flap_stable': 8, 'hysteresis': 3}
        server.mutate('template-create', definition)
        with server.connect() as db:
            exported = service_library.export_document(db)
            self.assertEqual(exported['version'], 3)
            self.assertEqual(exported['services'][0]['hysteresis'], 3)
            service_library.import_document(db, exported, 'replace', server.service_details)
            template = db.execute('SELECT * FROM service_templates').fetchone()
            self.assertEqual(template['flap_changes'], 6)
            self.assertEqual(template['flap_enabled'], 0)
            for index in range(20):
                self.assertIsNone(stability.observe(db, definition, 1,
                    'healthy' if index % 2 else 'critical', True, 1000 + index * 15))


    def test_legacy_evidence_backfill_uses_opening_sample_not_recovery(self):
        self.poll(-80)
        self.poll(-81)
        self.poll(-60)
        self.poll(-60)
        with server.connect() as db:
            for field in ('trigger_value', 'trigger_display', 'trigger_units', 'trigger_timestamp', 'trigger_error'):
                db.execute(f'ALTER TABLE incidents DROP COLUMN {field}')
        server.initialize()
        issue = server.snapshot()['incidents'][0]
        self.assertEqual(issue['trigger_value'], -81)
        self.assertEqual(issue['trigger_display'], '-81')


    def test_disabled_protocol_fields_preserve_saved_values_on_edit(self):
        with server.connect() as db:
            db.execute('UPDATE services SET unit=17,community=? WHERE id=?', ('saved-secret', self.service['id']))
        body = {**self.service, 'service': self.service['id']}
        body.pop('unit')
        body.pop('community')
        server.mutate('service-edit', body)
        with server.connect() as db:
            saved = db.execute('SELECT unit,community FROM services WHERE id=?', (self.service['id'],)).fetchone()
            self.assertEqual(tuple(saved), (17, 'saved-secret'))
        server.mutate('service-edit', {**body, 'kind': 'modbus', 'target': '10', 'unit': 23})
        server.mutate('service-edit', {**body, 'kind': 'tcp', 'target': '443'})
        with server.connect() as db:
            saved = db.execute('SELECT kind,unit,community FROM services WHERE id=?', (self.service['id'],)).fetchone()
            self.assertEqual(tuple(saved), ('tcp', 23, 'saved-secret'))

    def test_unacknowledgement_returns_blocked_service_to_suppressed(self):
        self.poll(-80)
        self.poll(-80)
        issue = server.snapshot()['incident_lists']['active'][0]
        server.mutate('ack', {'id': issue['id']}, actor={'id': 1})
        acknowledged = server.snapshot()['incident_lists']['acknowledged'][0]
        with patch.object(server, 'host_is_up', return_value=False):
            server.mutate('unack', {'id': issue['id'], 'expected_revision': acknowledged['ack_revision']}, actor={'id': 1})
            data = server.snapshot()['incident_lists']
            self.assertEqual(data['active'], [])
            self.assertEqual(data['acknowledged'], [])
            self.assertEqual(data['suppressed'][0]['id'], issue['id'])
            self.assertIsNone(data['suppressed'][0]['closed'])
        self.assertEqual(server.snapshot()['incident_lists']['active'][0]['id'], issue['id'])

    def test_unacknowledgement_rejects_inactive_and_removed_sources(self):
        self.poll(-80)
        self.poll(-80)
        issue = server.snapshot()['incident_lists']['active'][0]
        server.mutate('ack', {'id': issue['id']}, actor={'id': 1})
        issue = server.snapshot()['incident_lists']['acknowledged'][0]
        body = {'id': issue['id'], 'expected_revision': issue['ack_revision']}
        self.start_deployment({'project': 1, 'description': 'Another run'})
        with self.assertRaises(ValueError):
            server.mutate('unack', body, actor={'id': 1})
        with server.connect() as db:
            db.execute("UPDATE settings SET value='1' WHERE key='active_run'")
            db.execute('UPDATE services SET enabled=0 WHERE id=?', (self.service['id'],))
        with self.assertRaises(ValueError):
            server.mutate('unack', body, actor={'id': 1})

    def test_status_unacknowledgement_rechecks_service_dependency(self):
        self.poll(-80)
        self.poll(-80)
        issue = server.snapshot()['incident_lists']['active'][0]
        server.mutate('ack', {'id': issue['id']}, actor={'id': 1})
        issue = server.snapshot()['incident_lists']['acknowledged'][0]
        server.mutate('project-status-settings', {'project': 1, 'enabled': True})
        body = {'id': issue['id'], 'expected_revision': issue['ack_revision']}
        with patch.object(server, 'host_is_up', return_value=False):
            with self.assertRaises(ValueError):
                server.mutate('status-unack', body, actor={'id': 1})
        self.assertEqual(server.snapshot()['incident_lists']['acknowledged'][0]['id'], issue['id'])
        server.mutate('status-unack', body, actor={'id': 1})
        self.assertEqual(server.snapshot()['incident_lists']['active'][0]['id'], issue['id'])


if __name__ == '__main__':
    unittest.main()
