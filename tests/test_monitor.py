"""Behaviour checks for project isolation, threshold persistence and recovery."""
import io
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import server


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
        server.mutate('activate', {'project': 1})
        with server.connect() as db:
            self.service = dict(db.execute("SELECT s.*,d.address FROM services s JOIN assignments a ON a.id=s.assignment JOIN devices d ON d.id=a.device WHERE s.kind='snmp'").fetchone())

    def tearDown(self):
        server.DB = self.previous_db
        self.directory.cleanup()

    def poll(self, value, run=1):
        with patch.object(server, 'read_metric', return_value=value):
            server.poll_one(self.service, run)

    def test_persistence_acknowledgement_and_recovery(self):
        self.poll(-80)
        self.assertEqual(server.snapshot()['incidents'], [])
        self.poll(-80)
        incident = server.snapshot()['incidents'][0]
        server.mutate('ack', {'id': incident['id']})
        self.assertIsNotNone(server.snapshot()['incidents'][0]['acknowledged'])
        self.assertIsNone(server.snapshot()['incidents'][0]['closed'])
        self.poll(-50)
        self.poll(-50)
        self.assertIsNotNone(server.snapshot()['incidents'][0]['closed'])

    def test_previous_deployment_results_are_discarded(self):
        server.mutate('activate', {'project': 1})
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

    def test_acknowledged_incident_moves_lists_and_remains_acknowledged_after_recovery(self):
        self.poll(-80)
        self.poll(-80)
        incident = server.snapshot()['incident_lists']['active'][0]
        server.mutate('ack', {'id': incident['id']})
        lists = server.snapshot()['incident_lists']
        self.assertEqual(lists['active'], [])
        self.assertEqual(len(lists['acknowledged']), 1)
        self.assertIsNone(lists['acknowledged'][0]['closed'])
        timestamp = lists['acknowledged'][0]['acknowledged']
        server.mutate('ack', {'id': incident['id']})
        self.assertEqual(server.snapshot()['incident_lists']['acknowledged'][0]['acknowledged'], timestamp)
        self.poll(-50)
        self.poll(-50)
        lists = server.snapshot()['incident_lists']
        self.assertEqual(lists['resolved'], [])
        self.assertIsNotNone(lists['acknowledged'][0]['closed'])

    def test_unacknowledged_recovery_moves_to_resolved_list(self):
        self.poll(-80)
        self.poll(-80)
        self.poll(-50)
        self.poll(-50)
        lists = server.snapshot()['incident_lists']
        self.assertEqual(lists['active'], [])
        self.assertEqual(lists['acknowledged'], [])
        self.assertEqual(len(lists['resolved']), 1)
        server.mutate('activate', {'project': 1})
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
        server.mutate('ack', {'id': incident['id']})
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
        server.mutate('ack', {'id': critical['id']})
        self.assertEqual(server.status_overview()['devices'][0]['incident_status'], 'critical')
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
        public = server.status_overview()
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


if __name__ == '__main__':
    unittest.main()
