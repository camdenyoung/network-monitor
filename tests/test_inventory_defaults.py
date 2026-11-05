"""Inventory defaults seed new assignments without changing existing event services."""
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from app import server


class InventoryDefaultsTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.previous_db = server.DB
        server.DB = Path(self.directory.name) / 'monitor.sqlite3'
        server.initialize()
        for name in ('Original', 'Next'):
            server.mutate('project', {'name': name})
        for name in ('SW1', 'SW2'):
            server.mutate('device', {'name': name, 'address': '192.0.2.1', 'model': 'Switch'})
        server.mutate('assignment', {'project': 1, 'device': 1, 'alias': 'Original host'})
        server.mutate('service', self.definition(assignment=1, name='Original RSSI'))

    def tearDown(self):
        server.DB = self.previous_db
        self.directory.cleanup()

    def definition(self, **overrides):
        return {'name': 'RSSI', 'kind': 'snmp', 'target': '.1.2.3',
                'community': 'private-test-community', 'scale': 1, 'units': 'dBm',
                'direction': 'below', 'warning': -65, 'critical': -75,
                'persistence': 3, **overrides}

    def defaults(self, device=1):
        with server.connect() as db:
            return [dict(row) for row in db.execute(
                'SELECT * FROM device_service_defaults WHERE device=? ORDER BY id', (device,))]

    def services(self, assignment):
        with server.connect() as db:
            return [dict(row) for row in db.execute(
                'SELECT * FROM services WHERE assignment=? ORDER BY id', (assignment,))]

    def assign_next(self):
        server.mutate('assignment', {'project': 2, 'device': 1, 'alias': 'Next host'})
        with server.connect() as db:
            return db.execute('SELECT id FROM assignments WHERE project=2 AND device=1').fetchone()[0]

    def test_new_assignments_receive_independent_defaults_with_secret_and_state_map(self):
        original = self.services(1)
        mapping = {'1': {'label': 'Up', 'status': 'healthy'}, '2': {'label': 'Down', 'status': 'critical'}}
        server.mutate('device-default-create', self.definition(
            device=1, value_type='state', state_map=mapping))
        assignment = self.assign_next()
        copies = self.services(assignment)
        self.assertEqual(sum(row['kind'] == 'ping' for row in copies), 1)
        copied = next(row for row in copies if row['kind'] != 'ping')
        self.assertEqual(copied['community'], 'private-test-community')
        self.assertEqual(json.loads(copied['state_map']), mapping)
        self.assertEqual(copied['monitoring'], 1)
        self.assertEqual(self.services(1), original)
        default = self.defaults()[0]
        server.mutate('device-default-edit', self.definition(
            device=1, default_service=default['id'], target='.1.9', community=''))
        self.assertEqual(self.defaults()[0]['community'], 'private-test-community')
        self.assertEqual(self.services(assignment), copies)
        server.mutate('service-edit', self.definition(service=copied['id'], target='.1.8'))
        self.assertEqual(self.defaults()[0]['target'], '.1.9')
        server.mutate('project', {'name': 'Third'})
        server.mutate('assignment', {'project': 3, 'device': 1, 'alias': 'Third host'})
        with server.connect() as db:
            target = db.execute('SELECT id FROM assignments WHERE project=3').fetchone()[0]
            self.assertEqual(db.execute("SELECT target FROM services WHERE assignment=? AND kind='snmp'", (target,)).fetchone()[0], '.1.9')
            self.assertEqual(db.execute('SELECT COUNT(*) FROM samples').fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM incidents').fetchone()[0], 0)
        public_state = server.snapshot()['device_service_defaults'][0]
        self.assertNotIn('community', public_state)
        self.assertNotIn('private-test-community', json.dumps(server.status_overview()))

    def test_reassignment_and_project_duplication_preserve_event_configuration(self):
        server.mutate('device-default-create', self.definition(device=1))
        assignment = self.assign_next()
        before = self.services(assignment)
        child = next(row for row in before if row['kind'] != 'ping')
        server.mutate('service-monitoring', {'service': child['id'], 'monitoring': False})
        server.mutate('assignment-remove', {'assignment': assignment})
        server.mutate('device-default-create', self.definition(device=1, name='New default'))
        self.assertEqual(self.assign_next(), assignment)
        restored = self.services(assignment)
        self.assertEqual([row['id'] for row in restored], [row['id'] for row in before])
        self.assertEqual(next(row for row in restored if row['id'] == child['id'])['monitoring'], 0)
        server.mutate('project-duplicate', {'project': 2, 'name': 'Duplicate'})
        with server.connect() as db:
            duplicate = db.execute('SELECT id FROM assignments WHERE project=3').fetchone()[0]
        duplicated = self.services(duplicate)
        self.assertEqual([row['name'] for row in duplicated], [row['name'] for row in restored])
        self.assertNotIn('New default', [row['name'] for row in duplicated])

    def test_adopting_a_project_is_explicit_and_does_not_modify_source(self):
        original = self.services(1)
        self.assertEqual(self.defaults(), [])
        server.mutate('device-defaults-from-assignment', {'device': 1, 'assignment': 1})
        adopted = self.defaults()[0]
        self.assertEqual(adopted['name'], 'Original RSSI')
        self.assertEqual(adopted['community'], 'private-test-community')
        self.assertEqual(self.services(1), original)
        with self.assertRaises(ValueError):
            server.mutate('device-defaults-from-assignment', {'device': 2, 'assignment': 1})
        self.assertEqual(self.defaults(), [adopted])
        # Duplicate names must be resolved explicitly rather than silently losing a definition.
        server.mutate('service', self.definition(assignment=1, name='Original RSSI'))
        with self.assertRaises(ValueError):
            server.mutate('device-defaults-from-assignment', {'device': 1, 'assignment': 1})
        self.assertEqual(self.defaults(), [adopted])

    def test_library_copies_and_default_removal_do_not_change_materialized_services(self):
        server.mutate('template-create', self.definition())
        template = server.snapshot()['service_templates'][0]
        server.mutate('device-default-from-template', {'device': 1, 'template': template['id']})
        before = self.defaults()
        server.mutate('template-delete', {'template': template['id']})
        self.assertEqual(self.defaults(), before)
        assignment = self.assign_next()
        copies = self.services(assignment)
        server.mutate('device-default-delete', {'device': 1, 'default_service': before[0]['id']})
        self.assertEqual(self.defaults(), [])
        self.assertEqual(self.services(assignment), copies)

    def test_library_copy_accepts_a_device_name_without_changing_source_or_existing_projects(self):
        server.mutate('template-create', self.definition(name='Siklu EH RSSI'))
        template = server.snapshot()['service_templates'][0]
        before = self.services(1)
        server.mutate('device-default-from-template', {'device':1,'template':template['id'],'name':' RSSI '})
        default = self.defaults()[0]
        self.assertEqual(default['name'], 'RSSI')
        self.assertEqual(default['community'], 'private-test-community')
        self.assertEqual(default['target'], template['target'])
        self.assertEqual(server.snapshot()['service_templates'][0]['name'], 'Siklu EH RSSI')
        self.assertEqual(self.services(1), before)
        assignment = self.assign_next()
        self.assertEqual([row['name'] for row in self.services(assignment) if row['kind'] != 'ping'], ['RSSI'])
        for name in ('', '   ', 'x' * 101, 123, None):
            with self.subTest(name=name), self.assertRaises(ValueError):
                server.mutate('device-default-from-template', {'device':1,'template':template['id'],'name':name})
        with self.assertRaises(sqlite3.IntegrityError):
            server.mutate('device-default-from-template', {'device':1,'template':template['id'],'name':'RSSI'})
        self.assertEqual(self.defaults(), [default])
        # Older clients that omit the override retain the library's original name.
        server.mutate('device-default-from-template', {'device':2,'template':template['id']})
        self.assertEqual(self.defaults(2)[0]['name'], 'Siklu EH RSSI')

    def test_validation_device_ownership_and_deletion(self):
        server.mutate('device-default-create', self.definition(device=1))
        default = self.defaults()[0]
        with self.assertRaises(sqlite3.IntegrityError):
            server.mutate('device-default-create', self.definition(device=1))
        for action in ('device-default-edit', 'device-default-delete'):
            with self.assertRaises(ValueError):
                server.mutate(action, self.definition(device=2, default_service=default['id']))
        with self.assertRaises(ValueError):
            server.mutate('device-default-create', self.definition(device=999))
        with self.assertRaises(ValueError):
            server.mutate('device-default-create', self.definition(device=1, kind='ping'))
        server.mutate('device-default-create', self.definition(device=2))
        other = self.defaults(2)
        server.mutate('delete-device', {'device': 1})
        self.assertEqual(self.defaults(), [])
        self.assertEqual(self.defaults(2), other)

    def test_legacy_upgrade_and_database_backup_preserve_defaults(self):
        with server.connect() as db:
            db.execute('DROP TABLE device_service_defaults')
        server.initialize()
        self.assertEqual(self.defaults(), [])
        server.mutate('device-default-create', self.definition(device=1))
        with server.connect() as db:
            backup = sqlite3.connect(':memory:')
            try:
                db.backup(backup)
                server.ensure_inventory_services(backup)
                self.assertEqual(backup.execute('SELECT community FROM device_service_defaults').fetchone()[0], 'private-test-community')
            finally:
                backup.close()
