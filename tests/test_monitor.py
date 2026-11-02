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
        server.mutate('project', {'name': 'Festival'})
        server.mutate('device', {'name': 'MW-014', 'model': 'Siklu'})
        server.mutate('assignment', {
            'project': 1, 'device': 1, 'alias': 'Stage link', 'address': '127.0.0.1',
        })
        server.mutate('service', {
            'assignment': 1, 'name': 'RSSI', 'kind': 'snmp', 'target': '.1.2.3',
            'direction': 'below', 'warning': '-65', 'critical': '-75',
        })
        server.mutate('activate', {'project': 1})
        with server.connect() as db:
            self.service = dict(db.execute('SELECT s.*,a.address FROM services s JOIN assignments a ON a.id=s.assignment').fetchone())

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
            'Content-Length': str(len(payload)),
            'Content-Type': 'application/octet-stream',
        }
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

    def test_poll_failure_does_not_log_credential(self):
        with patch.object(server, 'read_metric', side_effect=RuntimeError('secret community')):
            server.poll_one(self.service, 1)
        self.assertEqual(server.snapshot()['latest'][0]['error'], 'RuntimeError')


if __name__ == '__main__':
    unittest.main()
