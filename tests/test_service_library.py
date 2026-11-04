"""Portable library imports are validated atomically and isolated from live services."""
import copy
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from app import server, service_library


class ServiceLibraryTransferTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.previous_db = server.DB
        server.DB = Path(self.directory.name) / 'library.sqlite3'
        server.initialize()

    def tearDown(self):
        server.DB = self.previous_db
        self.directory.cleanup()

    def definition(self, name='RSSI', **overrides):
        return {'name': name, 'kind': 'snmp', 'target': '.1.2.3',
                'community': 'TEST_LIBRARY_SECRET', 'unit': 1, 'scale': 1,
                'units': 'dBm', 'direction': 'below', 'warning': -65,
                'critical': -75, 'persistence': 2, 'value_type': 'metric',
                'state_map': {}, **overrides}

    def document(self, services):
        return {'format': service_library.FORMAT, 'version': 1, 'services': services}

    def rows(self):
        with server.connect() as db:
            return [dict(row) for row in db.execute('SELECT * FROM service_templates ORDER BY id')]

    def import_file(self, document, mode='merge'):
        return server.mutate('library-import', {'mode': mode, 'library': document})

    def test_export_roundtrip_to_fresh_install_preserves_all_protocols_and_credentials(self):
        entries = [self.definition(), self.definition('Port state', value_type='state',
            warning=None, critical=None, state_map={'1': {'label': 'Up', 'status': 'healthy'},
                                                   '2': {'label': 'Down', 'status': 'critical'}}),
            self.definition('Voltage', kind='modbus', target='100', unit=5, scale=0.1, units='V'),
            self.definition('Web port', kind='tcp', target='443', warning=None, critical=None)]
        for entry in entries:
            server.mutate('template-create', entry)
        with server.connect() as db:
            exported = service_library.export_document(db)
        self.assertTrue(exported['exported_at'])
        for entry in exported['services']:
            self.assertEqual(set(entry), set(service_library.FIELDS))
            self.assertNotIn('id', entry)
            self.assertEqual(entry['community'], 'TEST_LIBRARY_SECRET')
        source_db = server.DB
        server.DB = Path(self.directory.name) / 'fresh.sqlite3'
        try:
            server.initialize()
            result = self.import_file(json.loads(json.dumps(exported)))
            self.assertEqual(result, {'added': 4, 'skipped': 0, 'replaced': 0, 'total': 4})
            with server.connect() as db:
                imported = service_library.export_document(db)
            self.assertEqual(imported['services'], exported['services'])
        finally:
            server.DB = source_db

    def test_merge_keeps_existing_named_entries_and_adds_new_names(self):
        server.mutate('template-create', self.definition())
        original = self.rows()[0]
        result = self.import_file(self.document([
            self.definition(target='.9.9', community='REPLACEMENT_SECRET'),
            self.definition('Temperature', units='°C'),
        ]))
        self.assertEqual(result, {'added': 1, 'skipped': 1, 'replaced': 0, 'total': 2})
        self.assertEqual(self.rows()[0], original)
        self.assertEqual(self.rows()[1]['name'], 'Temperature')

    def test_replace_only_changes_library_and_never_reuses_template_ids(self):
        server.mutate('template-create', self.definition())
        template_id = self.rows()[0]['id']
        server.mutate('project', {'name': 'Existing event'})
        server.mutate('device', {'name': 'Radio', 'model': 'Microwave', 'address': '192.0.2.10'})
        server.mutate('assignment', {'device': 1, 'project': 1, 'alias': 'Stage'})
        server.mutate('template-apply', {'assignment': 1, 'template': template_id})
        server.mutate('device-default-from-template', {'device': 1, 'template': template_id})
        server.mutate('activate', {'project': 1, 'description': 'Keep existing history'})
        server.mutate('resume', {'project': 1})
        with server.connect() as db:
            service = db.execute("SELECT id FROM services WHERE kind='snmp'").fetchone()[0]
            db.execute("INSERT INTO samples(run,service,timestamp,value,status) VALUES(1,?,1,-80,'critical')", (service,))
            db.execute("INSERT INTO incidents(run,service,opened,status,number) VALUES(1,?,1,'critical',1)", (service,))
        tables = ('devices', 'projects', 'assignments', 'services', 'device_service_defaults',
                  'runs', 'samples', 'incidents', 'settings', 'users')
        with server.connect() as db:
            before = {table: [tuple(row) for row in db.execute('SELECT * FROM ' + table)] for table in tables}
        result = self.import_file(self.document([self.definition('New definition')]), 'replace')
        self.assertEqual(result, {'added': 1, 'skipped': 0, 'replaced': 1, 'total': 1})
        self.assertGreater(self.rows()[0]['id'], template_id)
        with server.connect() as db:
            after = {table: [tuple(row) for row in db.execute('SELECT * FROM ' + table)] for table in tables}
        self.assertEqual(after, before)
        self.assertEqual(self.import_file(self.document([]), 'replace')['total'], 0)

    def test_invalid_files_never_partially_change_the_library(self):
        server.mutate('template-create', self.definition('Keep me'))
        original = self.rows()
        valid = self.document([self.definition('Good first row')])
        cases = [None, [], {**valid, 'format': 'other'}, {**valid, 'version': 3},
                 {**valid, 'version': True}, {**valid, 'services': {}},
                 {**valid, 'services': [self.definition()] * 5001},
                 self.document([self.definition('Repeated'), self.definition(' Repeated ')])]
        for override in ({'id': 99}, {'kind': 'ping'}, {'target': 'bad-oid'},
                         {'community': {'secret': 'not-text'}}, {'unit': 1.5},
                         {'persistence': True}, {'scale': float('nan')},
                         {'warning': -80, 'critical': -65}, {'state_map': []},
                         {'value_type': 'state', 'state_map': {}}):
            invalid = self.definition('Bad row', **override)
            cases.append(self.document([self.definition('Good first row'), invalid]))
        for document in cases:
            with self.subTest(document_type=type(document).__name__):
                with self.assertRaises(service_library.LibraryImportError):
                    self.import_file(copy.deepcopy(document), 'replace')
                self.assertEqual(self.rows(), original)
        with self.assertRaises(service_library.LibraryImportError):
            self.import_file(valid, 'unknown')
        self.assertEqual(self.rows(), original)

    def test_database_failure_rolls_back_replace_after_validated_rows_begin_inserting(self):
        server.mutate('template-create', self.definition('Keep me'))
        original = self.rows()
        with server.connect() as db:
            db.execute("""CREATE TRIGGER reject_import BEFORE INSERT ON service_templates
                WHEN NEW.name='Reject' BEGIN SELECT RAISE(ABORT,'test import failure'); END""")
        with self.assertRaises(sqlite3.IntegrityError):
            self.import_file(self.document([self.definition('First'), self.definition('Reject')]), 'replace')
        self.assertEqual(self.rows(), original)
