"""Portable inventory imports preserve live projects and require a current review."""
import copy
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from app import server, inventory_transfer


class InventoryTransferTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.previous_db = server.DB
        server.DB = Path(self.directory.name) / 'inventory.sqlite3'
        server.initialize()
        for number in (1, 2):
            server.mutate('device', {'name':f'SW{number}','model':'Switch','address':f'192.0.2.{number}'})
        server.mutate('device-default-create', {'device':1, **self.service()})
        server.mutate('project', {'name':'Existing event'})
        server.mutate('assignment', {'project':1,'device':1,'alias':'Original alias'})
        server.mutate('activate', {'project':1,'description':'Keep event history'})
        with server.connect() as db:
            service = db.execute("SELECT id FROM services WHERE kind='snmp'").fetchone()[0]
            db.execute("INSERT INTO samples(run,service,timestamp,value,status) VALUES(1,?,100,-55,'healthy')", (service,))
            db.execute("INSERT INTO incidents(run,service,opened,closed,status,number) VALUES(1,?,100,101,'warning',1)", (service,))

    def tearDown(self):
        server.DB = self.previous_db
        self.directory.cleanup()

    def service(self, **overrides):
        return {'name':'RSSI','kind':'snmp','target':'.1.2.3','community':'PRIVATE_EXPORT_COMMUNITY',
                'unit':1,'scale':1,'units':'dBm','direction':'below','warning':-65,'critical':-75,
                'persistence':3,'hysteresis':2,'modbus_function':3, **overrides}

    def device(self, name='New', address='192.0.2.50', **overrides):
        return {'name':name,'model':'Imported model','address':address,'service_defaults':[self.service()], **overrides}

    def document(self, *devices):
        return {'format':inventory_transfer.FORMAT,'version':1,'devices':list(devices)}

    def preview(self, document, mode='merge'):
        return server.mutate('inventory-preview', {'inventory':document,'mode':mode})

    def apply(self, document, mode='merge', token=None):
        if token is None:
            token = self.preview(document, mode)['token']
        return server.mutate('inventory-import', {'inventory':document,'mode':mode,'token':token})

    def records(self, tables):
        with server.connect() as db:
            return {table:[tuple(row) for row in db.execute('SELECT * FROM '+table)] for table in tables}

    def test_roundtrip_to_fresh_install_preserves_all_defaults_and_unconfigured_devices(self):
        server.mutate('device-default-create', {'device':2, **self.service(name='Voltage',kind='modbus',
            target='80',modbus_function=4,unit=131,scale=0.1,units='V',direction='above',warning=250,critical=260)})
        server.mutate('device-default-create', {'device':2, **self.service(name='Port',value_type='state',
            state_map={'1':{'label':'Up','status':'healthy'},'2':{'label':'Down','status':'critical'}})})
        with server.connect() as db:
            db.execute("INSERT INTO devices(id,name,model,address) VALUES(99,'Unconfigured','','')")
            exported = inventory_transfer.export_document(db)
        self.assertNotIn('id', exported['devices'][0])
        self.assertEqual(exported['devices'][0]['service_defaults'][0]['community'], 'PRIVATE_EXPORT_COMMUNITY')
        source = server.DB
        server.DB = Path(self.directory.name) / 'fresh.sqlite3'
        try:
            server.initialize()
            result = self.apply(json.loads(json.dumps(exported)))
            self.assertEqual((result['added'],result['updated'],result['skipped']), (3,0,0))
            with server.connect() as db:
                self.assertEqual(inventory_transfer.export_document(db)['devices'], exported['devices'])
                self.assertEqual(db.execute('SELECT COUNT(*) FROM assignments').fetchone()[0], 0)
        finally:
            server.DB = source

    def test_merge_skips_existing_device_ids_without_updating_them(self):
        before = self.records(('devices','device_service_defaults','projects','assignments','services','samples','incidents'))
        document = self.document(self.device('SW1','192.0.2.100'), self.device())
        preview = self.preview(document)
        self.assertEqual((preview['added'],preview['updated'],preview['skipped']), (1,0,1))
        self.assertNotIn('PRIVATE_EXPORT_COMMUNITY', json.dumps(preview))
        self.assertEqual(before, self.records(tuple(before)))  # Preview never writes.
        self.assertEqual(self.apply(document, token=preview['token'])['added'], 1)
        after = self.records(tuple(before))
        self.assertEqual(after['devices'][:2], before['devices'])
        for table in ('projects','assignments','services','samples','incidents'):
            self.assertEqual(before[table], after[table])

    def test_update_preserves_project_data_and_default_ids_and_keeps_absent_devices(self):
        protected = ('projects','assignments','services','runs','samples','incidents','service_templates','users')
        before = self.records(protected)
        with server.connect() as db:
            default_id = db.execute('SELECT id FROM device_service_defaults WHERE device=1').fetchone()[0]
        document = self.document(self.device('SW1','192.0.2.10',service_defaults=[self.service(target='.1.9')]), self.device())
        result = self.apply(document, 'update')
        self.assertEqual((result['added'],result['updated']), (1,1))
        self.assertEqual(before, self.records(protected))
        with server.connect() as db:
            self.assertEqual(tuple(db.execute('SELECT model,address FROM devices WHERE id=1').fetchone()), ('Imported model','192.0.2.10'))
            self.assertEqual(db.execute('SELECT name FROM devices WHERE id=2').fetchone()[0], 'SW2')
            self.assertEqual(tuple(db.execute('SELECT id,target FROM device_service_defaults WHERE device=1').fetchone()), (default_id,'.1.9'))
        empty = self.document(self.device('SW1','192.0.2.10',service_defaults=[]))
        review = self.preview(empty, 'update')
        self.assertEqual(review['entries'][0]['removed_defaults'], ['RSSI'])
        self.apply(empty, 'update', review['token'])
        with server.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM device_service_defaults WHERE device=1').fetchone()[0], 0)
        self.assertEqual(before, self.records(protected))

    def test_ip_conflicts_block_every_write_but_atomic_address_swaps_are_valid(self):
        before = self.records(('devices','device_service_defaults','settings'))
        for document in (self.document(self.device(address='192.0.2.1')),
                         self.document(self.device('A','2001:db8::1'), self.device('B','2001:0db8:0:0::1')),
                         self.document(self.device(address='::ffff:192.0.2.1'))):
            preview = self.preview(document)
            self.assertTrue(preview['conflicts'])
            with self.assertRaises(inventory_transfer.InventoryImportError):
                self.apply(document, token=preview['token'])
            self.assertEqual(before, self.records(tuple(before)))
        document = self.document(self.device('SW1','192.0.2.2'), self.device('SW2','192.0.2.1'))
        self.assertEqual(self.preview(document, 'update')['conflicts'], [])
        self.apply(document, 'update')
        with server.connect() as db:
            self.assertEqual([row[0] for row in db.execute('SELECT address FROM devices ORDER BY id')], ['192.0.2.2','192.0.2.1'])

    def test_stale_or_modified_reviews_cannot_be_applied(self):
        document = self.document(self.device())
        token = self.preview(document)['token']
        for mode, value, proof in (('update',document,token), ('merge',self.document(self.device(address='192.0.2.51')),token),
                                    ('merge',document,'invalid'), ('merge',document,'é')):
            with self.assertRaises(inventory_transfer.InventoryImportError):
                self.apply(value, mode, proof)
        server.mutate('device-edit', {'device':1,'name':'SW1','model':'Changed','address':'192.0.2.1'})
        with self.assertRaisesRegex(inventory_transfer.InventoryImportError, 'review'):
            self.apply(document, token=token)
        self.assertEqual(self.apply(document)['added'], 1)

    def test_invalid_files_reject_the_complete_import_without_exposing_secrets(self):
        before = self.records(('devices','device_service_defaults','settings'))
        documents = [None, [], {'format':'wrong','version':1,'devices':[]},
                     {**self.document(), 'version':True}, self.document(self.device(), self.device()),
                     self.document(self.device(name=' ')), self.document(self.device(address='not-an-ip')),
                     self.document(self.device(service_defaults=None)), self.document({**self.device(),'id':9}),
                     self.document(self.device(service_defaults=[self.service(target='bad-oid')])),
                     self.document(self.device(service_defaults=[self.service(scale=float('nan'))])),
                     self.document(self.device(service_defaults=[self.service(), self.service()]))]
        for document in documents:
            with self.subTest(document_type=type(document).__name__):
                with self.assertRaises(inventory_transfer.InventoryImportError) as error:
                    self.preview(copy.deepcopy(document))
                self.assertNotIn('PRIVATE_EXPORT_COMMUNITY', str(error.exception))
                self.assertEqual(before, self.records(tuple(before)))
        with self.assertRaises(inventory_transfer.InventoryImportError):
            self.preview(self.document(self.device()), 'replace')

    def test_mid_import_database_error_rolls_back_all_updates_additions_and_defaults(self):
        document = self.document(self.device('SW1','192.0.2.10',service_defaults=[]), self.device('Reject'))
        preview = self.preview(document,'update')
        with server.connect() as db:
            db.execute("""CREATE TRIGGER reject_inventory_import BEFORE INSERT ON devices
                WHEN NEW.name='Reject' BEGIN SELECT RAISE(ABORT,'simulated import failure'); END""")
        before = self.records(('devices','device_service_defaults','settings'))
        with self.assertRaises(sqlite3.IntegrityError):
            self.apply(document,'update',preview['token'])
        self.assertEqual(before, self.records(tuple(before)))
