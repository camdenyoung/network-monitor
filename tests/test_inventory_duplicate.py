"""Independent inventory cloning, unique canonical IPs and atomic copy failures."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest

from app import server


class InventoryDuplicateTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.previous_db = server.DB
        server.DB = Path(self.directory.name) / 'inventory.sqlite3'
        server.initialize()
        for number in (1, 2):
            server.mutate('device', {'name':f'SW{number}', 'model':'Industrial', 'address':f'192.0.2.{number}'})

    def tearDown(self):
        server.DB = self.previous_db
        self.directory.cleanup()

    def definition(self, **overrides):
        return {**dict(device=1, name='RSSI', kind='snmp', target='.1.2.3',
                    community='PRIVATE_TEST_COMMUNITY', unit=1, scale=1, units='dBm',
                    direction='below', warning=-65, critical=-75, persistence=3,
                    flap_enabled=True, flap_changes=6, flap_window=8, flap_stable=9,
                    hysteresis=2), **overrides}

    def defaults(self, device):
        with server.connect() as db:
            return [dict(row) for row in db.execute('SELECT * FROM device_service_defaults WHERE device=? ORDER BY id', (device,))]

    def duplicate(self, **overrides):
        body = {'device':1, 'name':'SW3', 'address':'192.0.2.3', **overrides}
        return server.mutate('device-duplicate', body)

    def test_duplicate_copies_all_defaults_but_no_project_or_runtime_records(self):
        definitions = [self.definition(), self.definition(name='Voltage',kind='modbus',target='80',
            unit=131,modbus_function=4,scale=0.1,units='V',direction='above',warning=250,critical=260),
            self.definition(name='Port',value_type='state',state_map={
                '1':{'label':'Up','status':'healthy'},'2':{'label':'Down','status':'critical'}})]
        for definition in definitions:
            server.mutate('device-default-create', definition)
        server.mutate('template-create', self.definition(name='Shared library'))
        server.mutate('project', {'name':'Existing'})
        server.mutate('assignment', {'device':1,'project':1,'alias':'Original alias'})
        server.mutate('activate', {'project':1,'description':'Keep history'})
        with server.connect() as db:
            service = db.execute("SELECT id FROM services WHERE kind='snmp'").fetchone()[0]
            db.execute("INSERT INTO samples(run,service,timestamp,value,status) VALUES(1,?,100,-55,'healthy')", (service,))
            db.execute("INSERT INTO incidents(run,service,opened,closed,status,number) VALUES(1,?,100,101,'warning',1)", (service,))
            tables = ('projects','assignments','services','runs','samples','incidents','service_templates','service_measurements')
            before = {table:[tuple(row) for row in db.execute('SELECT * FROM '+table)] for table in tables}
        source = self.defaults(1)
        copied_id = self.duplicate()['device']
        copied = self.defaults(copied_id)
        self.assertEqual(len(copied), 3)
        for original, copy in zip(source, copied):
            self.assertNotEqual(original['id'], copy['id'])
            self.assertEqual(copy['device'], copied_id)
            self.assertEqual({field:original[field] for field in server.SERVICE_CONFIGURATION_FIELDS},
                             {field:copy[field] for field in server.SERVICE_CONFIGURATION_FIELDS})
        with server.connect() as db:
            self.assertEqual(db.execute('SELECT model FROM devices WHERE id=?', (copied_id,)).fetchone()[0], 'Industrial')
            after = {table:[tuple(row) for row in db.execute('SELECT * FROM '+table)] for table in tables}
        self.assertEqual(before, after)
        server.mutate('device-default-edit', {**copied[0], 'default_service':copied[0]['id'], 'target':'.1.2.99'})
        self.assertEqual(self.defaults(1), source)
        server.mutate('project', {'name':'New event'})
        server.mutate('assignment', {'device':copied_id,'project':2,'alias':'Clone'})
        with server.connect() as db:
            self.assertEqual(db.execute("""SELECT s.target FROM services s JOIN assignments a ON a.id=s.assignment
                WHERE a.device=? AND s.kind='snmp'""", (copied_id,)).fetchone()[0], '.1.2.99')

    def test_conflicting_ips_are_rejected_for_create_edit_address_update_and_duplicate(self):
        actions = [('device',{'name':'Conflict','address':'192.0.2.1'}),
                   ('device-edit',{'device':2,'name':'Changed','model':'Changed','address':'192.0.2.1'}),
                   ('device-address',{'device':2,'address':'192.0.2.1'}),
                   ('device-duplicate',{'device':2,'name':'Conflict','address':'192.0.2.1'})]
        for action, body in actions:
            with self.subTest(action=action), self.assertRaisesRegex(ValueError, 'already assigned to SW1'):
                server.mutate(action, body)
        with server.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM devices').fetchone()[0], 2)
            self.assertEqual(tuple(db.execute('SELECT name,model,address FROM devices WHERE id=2').fetchone()),
                             ('SW2','Industrial','192.0.2.2'))
        server.mutate('device-edit', {'device':1,'name':'SW1 renamed','model':'New model','address':'192.0.2.1'})
        server.mutate('device-address', {'device':1,'address':'192.0.2.1'})

    def test_canonical_ipv6_and_ipv4_mapped_addresses_cannot_bypass_uniqueness(self):
        server.mutate('device', {'name':'IPv6','address':'2001:0db8:0000:0000:0000:0000:0000:0001'})
        with server.connect() as db:
            # A restored pre-upgrade address may not already have canonical spelling.
            db.execute("UPDATE devices SET address='2001:0DB8:0:0:0:0:0:1' WHERE name='IPv6'")
        for address in ('2001:db8::1','::ffff:192.0.2.1'):
            with self.subTest(address=address), self.assertRaisesRegex(ValueError, 'already assigned'):
                self.duplicate(address=address)
        for address in ('', 'not-an-ip', None, 123):
            with self.subTest(address=address), self.assertRaises(ValueError):
                self.duplicate(address=address)

    def test_copy_failure_rolls_back_the_device_defaults_and_id_counter(self):
        server.mutate('device-default-create', self.definition())
        server.mutate('device-default-create', self.definition(name='Reject copy'))
        with server.connect() as db:
            before_counter = db.execute("SELECT value FROM settings WHERE key='last_id_devices'").fetchone()[0]
            db.execute("""CREATE TRIGGER reject_duplicate BEFORE INSERT ON device_service_defaults
                WHEN NEW.name='Reject copy' AND NEW.device!=1
                BEGIN SELECT RAISE(ABORT,'simulated copy failure'); END""")
        with self.assertRaises(sqlite3.IntegrityError):
            self.duplicate()
        with server.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM devices').fetchone()[0], 2)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM device_service_defaults').fetchone()[0], 2)
            self.assertEqual(db.execute("SELECT value FROM settings WHERE key='last_id_devices'").fetchone()[0], before_counter)

    def test_simultaneous_creates_cannot_claim_the_same_address(self):
        ready = threading.Barrier(2)
        def add(name):
            ready.wait()
            try:
                server.mutate('device', {'name':name,'address':'192.0.2.50'})
                return 'created'
            except ValueError:
                return 'rejected'
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(add, ('First','Second')))
        self.assertEqual(sorted(results), ['created','rejected'])
        with server.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM devices WHERE address='192.0.2.50'").fetchone()[0], 1)

    def test_unknown_source_and_duplicate_ids_do_not_create_partial_devices(self):
        with self.assertRaises(ValueError):
            self.duplicate(device=999)
        with self.assertRaises(sqlite3.IntegrityError):
            self.duplicate(name='SW1')
        with server.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM devices').fetchone()[0], 2)
        created = self.duplicate(name='No defaults')['device']
        self.assertEqual(self.defaults(created), [])
