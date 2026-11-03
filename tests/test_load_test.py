"""Benchmark safety, measured conclusions, and protocol fixtures; no network I/O."""
import contextlib
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from tools import load_test
from tools.device_simulator import Scenario, children, parse_tlv, snmp_response


class LoadTestTests(unittest.TestCase):
    def test_seeding_isolated_database_includes_ping_and_preserves_existing_files(self):
        from app import server
        original = server.DB
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()):
            database = Path(directory) / 'benchmark.sqlite3'
            result = load_test.seed(database, '127.0.0.1', hosts=2, services=5,
                                    modbus_services=1, history_days=0.0004, users=2)
            self.assertEqual(result['check_count'], 12)
            self.assertEqual(result['host_count'], 2)
            self.assertEqual(result['history_rows'], 24)  # Two rounds, 12 total checks.
            self.assertEqual(server.DB, original)
            with contextlib.closing(sqlite3.connect(database)) as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM services').fetchone()[0], 12)
                self.assertEqual(db.execute("SELECT COUNT(*) FROM services WHERE kind='ping'").fetchone()[0], 2)
                self.assertEqual(db.execute("SELECT COUNT(*) FROM services WHERE kind='modbus'").fetchone()[0], 2)
                self.assertEqual(db.execute('SELECT SUM(notifications) FROM assignments').fetchone()[0], 0)
                self.assertEqual(db.execute("SELECT value FROM settings WHERE key='notifications_paused'").fetchone()[0], '1')
                self.assertEqual(db.execute("SELECT value FROM settings WHERE key='benchmark_ready'").fetchone()[0], '1')
                self.assertEqual(db.execute('SELECT COUNT(*) FROM services WHERE monitoring_since > (SELECT MIN(timestamp) FROM samples)').fetchone()[0], 0)
            original_bytes = database.read_bytes()
            with self.assertRaises(FileExistsError):
                load_test.seed(database, '127.0.0.1', hosts=1)
            self.assertEqual(database.read_bytes(), original_bytes)
            self.assertEqual(server.DB, original)

    def test_inspection_refuses_unmarked_database(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / 'ordinary.sqlite3'
            with contextlib.closing(sqlite3.connect(database)) as db:
                db.execute('CREATE TABLE settings(key,value)')
            with self.assertRaises(ValueError):
                load_test.inspect_database(database)

    def test_probe_refuses_unmarked_target_before_generating_users(self):
        with patch.object(load_test.ApiClient, 'login'), patch.object(load_test.ApiClient, 'read',
                return_value=({'settings': {}}, 0.1, 100)) as read:
            with self.assertRaises(ValueError):
                load_test.probe('http://127.0.0.1:8081', duration=1, warmup=0)
            self.assertEqual(read.call_count, 1)

    def test_report_path_cannot_overwrite_existing_files(self):
        with tempfile.TemporaryDirectory() as directory:
            existing = Path(directory) / 'keep.json'
            existing.write_text('keep this file')
            with self.assertRaises(FileExistsError):
                load_test.probe('http://127.0.0.1:8081', report_path=existing)
            self.assertEqual(existing.read_text(), 'keep this file')

    def test_pass_requires_real_observed_intervals_and_fresh_samples(self):
        measurements = load_test.Measurements()
        state = {'services': [{'id': 1, 'enabled': 1, 'monitoring': 1}],
                 'latest': [{'id': 1, 'service': 1, 'timestamp': 100}]}
        measurements.record('/api/state', elapsed=0.2)
        measurements.observe(state, 100)
        self.assertEqual(measurements.report(2, 30)['result'], 'INCONCLUSIVE')
        state['latest'][0] = {'id': 2, 'service': 1, 'timestamp': 120}
        measurements.observe(state, 120)
        report = measurements.report(2, 30)
        self.assertEqual(report['result'], 'PASS')
        self.assertEqual(report['check_interval_maximum_s'], 20)
        measurements.observe(state, 181)
        self.assertEqual(measurements.report(2, 30)['result'], 'FAIL')

    def test_failures_and_slow_dashboard_are_reported(self):
        measurements = load_test.Measurements()
        measurements.record('/api/state', elapsed=3)
        measurements.record('/api/state', error='TimeoutError')
        result = measurements.report(2, 30)
        self.assertEqual(result['result'], 'FAIL')
        self.assertEqual(len(result['failures']), 2)
        self.assertEqual(result['http_errors']['TimeoutError'], 1)

    def test_blocked_or_reduced_workload_cannot_falsely_pass(self):
        measurements = load_test.Measurements()
        state = {'services': [{'id': 1, 'enabled': 1, 'monitoring': 1}],
                 'latest': [{'id': 1, 'service': 1, 'timestamp': 100, 'status': 'blocked'}]}
        measurements.observe(state, 100)
        state['latest'][0].update(id=2, timestamp=120)
        measurements.observe(state, 120)
        self.assertEqual(measurements.report(2, 30)['result'], 'FAIL')
        reduced = load_test.Measurements()
        reduced.expected_checks = 900
        state['latest'][0]['status'] = 'healthy'
        reduced.observe(state, 120)
        self.assertTrue(reduced.configuration_changed)
        self.assertEqual(reduced.report(2, 30)['result'], 'FAIL')

    def test_unreachable_values_allowed_only_for_explicit_timeout_scenario(self):
        measurements = load_test.Measurements()
        state = {'services': [{'id': 1, 'enabled': 1, 'monitoring': 1}],
                 'latest': [{'id': 1, 'service': 1, 'timestamp': 100, 'status': 'unreachable'}]}
        measurements.observe(state, 100)
        state['latest'][0].update(id=2, timestamp=120)
        measurements.observe(state, 120)
        self.assertEqual(measurements.report(2, 30)['result'], 'FAIL')
        self.assertEqual(measurements.report(2, 30, allow_unreachable=True)['result'], 'PASS')

    def test_known_snmp_get_fixture_returns_signed_rssi_and_original_request_id(self):
        # SNMP v2c GET, community public, request ID 1,
        # OID 1.3.6.1.4.1.99999.1.1.0, NULL value.
        request = bytes.fromhex('302902010104067075626c6963a01c0201010201000201003011300f060b2b06010401868d1f0101000500')
        response = snmp_response(request, Scenario())
        fields = children(parse_tlv(response)[1])
        pdu = children(fields[2][1])
        self.assertEqual(fields[2][0], 162)
        self.assertEqual(pdu[0], (2, b'\x01'))
        binding = children(children(pdu[3][1])[0][1])
        self.assertEqual(binding[1][0], 2)
        self.assertEqual(int.from_bytes(binding[1][1], 'big', signed=True), -55)
        self.assertIsNone(snmp_response(request, Scenario('timeouts', failure_percent=100)))
        with self.assertRaises(ValueError):
            snmp_response(b'bad packet', Scenario())

    def test_modbus_fixture_stays_unsigned_and_in_register_range(self):
        self.assertEqual(Scenario().value(150, 5, modbus=True), 5400)
        self.assertIsNone(Scenario('timeouts', failure_percent=100).value(150, 5, modbus=True))
        with patch('tools.device_simulator.time.monotonic', return_value=31):
            self.assertEqual(Scenario('flapping', failure_percent=100).value(150, 5, modbus=True), 4000)


if __name__ == '__main__':
    unittest.main()
