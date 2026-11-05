"""Read-only TCP register functions and portable configuration compatibility."""
from contextlib import closing
import io
from pathlib import Path
import sqlite3
import struct
import tempfile
import unittest
from unittest.mock import patch

from app import server, service_library


class FragmentedSocket:
    """Return short reads to exercise TCP framing independently of packet boundaries."""

    def __init__(self, response):
        self.response = response
        self.request = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def settimeout(self, timeout):
        self.timeout = timeout

    def sendall(self, request):
        self.request = request

    def recv(self, length):
        count = min(length, 2)
        result, self.response = self.response[:count], self.response[count:]
        return result


class ModbusWireTests(unittest.TestCase):
    def service(self, **overrides):
        return dict(kind='modbus', address='192.0.2.20', target='98', unit=7,
                    scale=0.1, **overrides)

    def response(self, function=4, transaction=1, protocol=0, unit=7, length=5):
        return struct.pack('>HHHBBB H', transaction, protocol, length, unit, function, 2, 321)

    def test_holding_and_input_register_requests_and_fragmented_responses(self):
        for function in (3, 4):
            with self.subTest(function=function):
                sock = FragmentedSocket(self.response(function))
                with patch.object(server.socket, 'create_connection', return_value=sock) as connect:
                    self.assertAlmostEqual(server.read_metric(self.service(modbus_function=function)), 32.1)
                self.assertEqual(sock.request, struct.pack('>HHHBBHH', 1, 0, 6, 7, function, 98, 1))
                connect.assert_called_once_with(('192.0.2.20', 502), timeout=2)
                self.assertEqual(sock.timeout, 2)

    def test_legacy_config_uses_function_three(self):
        sock = FragmentedSocket(self.response(3))
        with patch.object(server.socket, 'create_connection', return_value=sock):
            self.assertAlmostEqual(server.read_metric(self.service()), 32.1)
        self.assertEqual(sock.request[7], 3)

    def test_mismatched_headers_functions_and_truncated_frames_are_rejected(self):
        responses = [self.response(3), self.response(transaction=2), self.response(protocol=1),
                     self.response(unit=8), self.response(length=500), self.response()[:-1],
                     self.response()[:4], self.response().replace(b'\x04\x02', b'\x04\x01')]
        for response in responses:
            with self.subTest(response=response):
                with patch.object(server.socket, 'create_connection', return_value=FragmentedSocket(response)):
                    with self.assertRaises(ValueError):
                        server.read_metric(self.service(modbus_function=4))

    def test_exception_response_is_not_a_reading(self):
        response = struct.pack('>HHHBBB', 1, 0, 3, 7, 0x84, 2)
        with patch.object(server.socket, 'create_connection', return_value=FragmentedSocket(response)):
            with self.assertRaisesRegex(ValueError, 'Modbus exception 2'):
                server.read_metric(self.service(modbus_function=4))


class ModbusConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.previous_db = server.DB
        server.DB = Path(self.directory.name) / 'test.sqlite3'
        server.initialize()
        server.mutate('project', {'name': 'Event'})
        server.mutate('device', {'name': 'PSU', 'address': '192.0.2.20'})
        self.details = dict(name='Temperature', kind='modbus', target='98', unit=7,
                            modbus_function=4, scale=0.1, units='°C', direction='above',
                            warning=50, critical=65)

    def tearDown(self):
        server.DB = self.previous_db
        self.directory.cleanup()

    def values(self, table):
        with server.connect() as db:
            return [dict(row) for row in db.execute(f"SELECT * FROM {table} WHERE kind='modbus'")]

    def test_copy_defaults_library_duplicate_edit_and_backup_preserve_input_registers(self):
        server.mutate('template-create', self.details)
        server.mutate('device-default-from-template', {'device': 1, 'template': 1})
        server.mutate('assignment', {'project': 1, 'device': 1, 'alias': 'Power'})
        source = self.values('services')[0]['id']
        server.mutate('project', {'name': 'Other'})
        server.mutate('assignment', {'project': 2, 'device': 1, 'alias': 'Other power'})
        with server.connect() as db:
            target = db.execute('SELECT id FROM assignments WHERE project=2').fetchone()[0]
        server.mutate('service-copy', {'service': source, 'assignment': target, 'name': 'Copied'})
        server.mutate('project-duplicate', {'project': 1, 'name': 'Duplicate'})
        server.mutate('service-edit', {**self.details, 'service': source})
        for table in ('services', 'device_service_defaults', 'service_templates'):
            self.assertTrue(self.values(table))
            self.assertTrue(all(row['modbus_function'] == 4 for row in self.values(table)))
        state = server.snapshot()
        for key in ('services', 'device_service_defaults', 'service_templates'):
            self.assertTrue(all(row['modbus_function'] == 4 for row in state[key] if row['kind'] == 'modbus'))
        with server.connect() as db, closing(sqlite3.connect(':memory:')) as backup:
            db.backup(backup)
            self.assertEqual(backup.execute('SELECT modbus_function FROM service_templates').fetchone()[0], 4)

    def test_old_library_formats_default_to_holding_and_reject_invalid_functions(self):
        old = {key: value for key, value in self.details.items() if key != 'modbus_function'}
        for version in (1, 2):
            document = dict(format=service_library.FORMAT, version=version, services=[old])
            server.mutate('library-import', {'mode': 'replace', 'library': document})
            self.assertEqual(self.values('service_templates')[0]['modbus_function'], 3)
        for value in (0, 1, 5, 16, 3.5, True, None, '4.0'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                server.service_details({**self.details, 'modbus_function': value})

    def test_startup_and_legacy_restore_migrate_existing_definitions(self):
        server.mutate('template-create', self.details)
        server.mutate('device-default-from-template', {'device': 1, 'template': 1})
        server.mutate('assignment', {'project': 1, 'device': 1, 'alias': 'Power'})
        # Remove just the new column to reproduce a pre-upgrade database.
        with server.connect() as db:
            for table in ('services', 'service_templates', 'device_service_defaults'):
                db.execute(f'ALTER TABLE {table} DROP COLUMN modbus_function')
        with server.connect() as source, closing(sqlite3.connect(':memory:')) as backup:
            source.backup(backup)
            payload = backup.serialize()
        server.initialize()
        for table in ('services', 'service_templates', 'device_service_defaults'):
            self.assertEqual(self.values(table)[0]['modbus_function'], 3)
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
        for table in ('services', 'service_templates', 'device_service_defaults'):
            self.assertEqual(self.values(table)[0]['modbus_function'], 3)
