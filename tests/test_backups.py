"""Disk transfers use disposable databases; no production files/providers are used."""
from contextlib import closing
import io
import json
from pathlib import Path
import shutil
import sqlite3
import unittest
from unittest.mock import Mock, patch

from app import auth, backups, server
import test_access_notifications as fixtures


class DiskBackupTests(unittest.TestCase):
    def setUp(self):
        # Reuse fixture helpers without inheriting/repeating their test methods.
        self.fixture = fixtures.AccessAndNotificationTests()
        self.fixture.setUp()
        self.fixture.create_host()
        self.image = self.fixture.logo_image()
        self.fixture.upload_logo(self.fixture.admin_token, self.fixture.admin['csrf'], self.image)
        definition = {'name':'RSSI', 'kind':'snmp', 'target':'.1.2.3', 'community':'BACKUP_TEST_SECRET', 'warning':-65, 'critical':-75, 'direction':'below'}
        server.mutate('template-create', definition)
        server.mutate('device-default-create', {**definition, 'device':1})
        with server.connect() as db:
            service = db.execute('SELECT id FROM services LIMIT 1').fetchone()[0]
            db.execute("INSERT INTO samples(run,service,timestamp,value,status) VALUES(1,?,1,1,'healthy')", (service,))
            db.execute("INSERT INTO incidents(run,service,opened,status) VALUES(1,?,1,'critical')", (service,))
        self.payload = self.fixture.request('/api/backup', token=self.fixture.admin_token)['content']

    def tearDown(self):
        for token in list(backups._REVIEWS):
            backups.expire(token)
        self.fixture.tearDown()

    def upload(self, payload=None, token=None, csrf=None):
        payload = self.payload if payload is None else payload
        handler = object.__new__(server.Handler)
        handler.path = '/api/restore-preview'
        handler.headers = {'Content-Type':'application/octet-stream', 'Content-Length':str(len(payload)),
                           'Cookie':'monitor_session=' + (token or self.fixture.admin_token),
                           'X-CSRF-Token':csrf or self.fixture.admin['csrf']}
        handler.rfile = io.BytesIO(payload)
        response = {}
        handler.send = lambda content, status=200: response.update(status=status, body=json.loads(content))
        handler.do_POST()
        return response

    def apply(self, review, mode):
        return self.fixture.request('/api/restore-apply', {'token':review['token'], 'mode':mode},
                                    self.fixture.admin_token, self.fixture.admin['csrf'])

    def assert_configuration(self, db):
        self.assertEqual(db.execute('SELECT COUNT(*) FROM devices').fetchone()[0], 1)
        self.assertEqual(db.execute('SELECT COUNT(*) FROM users').fetchone()[0], 2)
        self.assertEqual(db.execute('SELECT image FROM project_logos').fetchone()[0], self.image)
        self.assertEqual(db.execute('SELECT community FROM service_templates').fetchone()[0], 'BACKUP_TEST_SECRET')
        self.assertEqual(db.execute('SELECT community FROM device_service_defaults').fetchone()[0], 'BACKUP_TEST_SECRET')
        self.assertEqual(db.execute('SELECT COUNT(*) FROM assignments').fetchone()[0], 1)
        self.assertEqual(db.execute('SELECT alias FROM assignments').fetchone()[0], 'Stage switch')

    def test_configuration_export_omits_history_without_reading_history_rows(self):
        target = server.DB.with_name('configuration.sqlite3')
        with server.connect() as source, closing(backups.open_database(target)) as destination:
            def authorize(action, table, column, database, trigger):
                if action == sqlite3.SQLITE_READ and database == 'configuration_source' and table in backups.HISTORY_TABLES:
                    return sqlite3.SQLITE_DENY
                return sqlite3.SQLITE_OK
            destination.set_authorizer(authorize)
            backups.copy_configuration(source, destination)
        response = self.fixture.request('/api/backup?kind=configuration', token=self.fixture.admin_token)
        self.assertEqual(response['status'], 200)
        self.assertIn('configuration-', response['filename'])
        target.write_bytes(response['content'])
        with closing(backups.open_database(target)) as db:
            self.assert_configuration(db)
            for name in backups.HISTORY_TABLES + ('sessions','login_attempts'):
                self.assertEqual(db.execute(f'SELECT COUNT(*) FROM {name}').fetchone()[0], 0, name)
            self.assertEqual(backups.inspect(db)['modes'], ['configuration'])
        # Exporting configuration never pauses or deletes the live deployment.
        with server.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM samples').fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT value FROM settings WHERE key='active_run'").fetchone()[0], '1')

    def test_review_full_backup_then_restore_configuration_only(self):
        review = self.upload()['body']
        self.assertEqual(review['modes'], ['complete','configuration'])
        self.assertTrue(review['has_history'])
        server.mutate('project', {'name':'Destination-only project'})
        self.assertEqual(self.apply(review, 'configuration')['status'], 200)
        with server.connect() as db:
            self.assert_configuration(db)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM projects').fetchone()[0], 1)
            for table in backups.HISTORY_TABLES + ('sessions','login_attempts'):
                self.assertEqual(db.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0], 0)
            for key, value in (('active_run','0'),('paused_run','0'),('notifications_paused','1')):
                self.assertEqual(server.setting(db,key), value)
        self.assertFalse(list(server.DB.parent.glob('.backup-transfer-*')))

    def test_review_complete_restore_preserves_history_but_pauses_and_invalidates_sessions(self):
        review = self.upload()['body']
        self.assertEqual(self.apply(review, 'complete')['status'], 200)
        with server.connect() as db:
            self.assert_configuration(db)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM samples').fetchone()[0], 1)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM incidents').fetchone()[0], 1)
            self.assertEqual(server.setting(db,'active_run'), '0')
            self.assertEqual(server.setting(db,'paused_run'), '1')
            self.assertEqual(server.setting(db,'notifications_paused'), '1')
            self.assertEqual(db.execute('SELECT COUNT(*) FROM sessions').fetchone()[0], 0)

    def test_configuration_file_cannot_restore_history_and_review_can_be_cancelled(self):
        payload = self.fixture.request('/api/backup?kind=configuration', token=self.fixture.admin_token)['content']
        review = self.upload(payload)['body']
        self.assertEqual(self.apply(review,'complete')['status'], 400)
        self.assertIn(review['token'], backups._REVIEWS)
        response = self.fixture.request('/api/restore-discard', {'token':review['token']}, self.fixture.admin_token, self.fixture.admin['csrf'])
        self.assertEqual(response['status'], 200)
        self.assertEqual(self.apply(review,'configuration')['status'], 409)
        self.assertFalse(list(server.DB.parent.glob('.backup-transfer-*')))

    def test_review_is_bound_to_session_not_username_and_expires(self):
        review = self.upload()['body']
        with server.connect() as db:
            other_token = auth.new_session(db,1)
            other = auth.session_user(db,'monitor_session=' + other_token)
        response = self.fixture.request('/api/restore-apply', {'token':review['token'],'mode':'complete'}, other_token, other['csrf'])
        self.assertEqual(response['status'], 409)
        self.assertIn(review['token'], backups._REVIEWS)
        backups.expire(review['token'])
        self.assertEqual(self.apply(review,'complete')['status'], 409)
        self.assertFalse(list(server.DB.parent.glob('.backup-transfer-*')))

    def test_invalid_and_truncated_uploads_do_not_change_destination(self):
        before = server.DB.read_bytes()
        self.assertEqual(self.upload(b'not sqlite')['status'], 400)
        self.assertEqual(server.DB.read_bytes(), before)
        with self.assertRaises(backups.BackupError):
            backups.upload(io.BytesIO(b'SQLite format 3\x00'),100,server.DB.parent)
        self.assertFalse(list(server.DB.parent.glob('.backup-transfer-*')))

    def test_disk_shortage_busy_transfer_and_pending_review_limit(self):
        usage = shutil.disk_usage(server.DB.parent)._replace(free=0)
        with patch.object(backups.shutil,'disk_usage',return_value=usage):
            self.assertEqual(self.upload()['status'], 507)
        with backups.transfer():
            self.assertEqual(self.upload()['status'], 409)
        self.upload()
        self.upload()
        self.assertEqual(self.upload()['status'], 409)
        self.assertEqual(len(backups._REVIEWS),2)

    def test_preview_and_apply_require_admin_and_csrf(self):
        self.assertEqual(self.upload(token=self.fixture.viewer_token,csrf=self.fixture.viewer['csrf'])['status'],403)
        self.assertEqual(self.upload(csrf='invalid')['status'],403)
        self.assertEqual(self.fixture.request('/api/backup?kind=configuration',token=self.fixture.viewer_token)['status'],403)
        self.assertEqual(self.fixture.request('/api/backup?kind=invalid',token=self.fixture.admin_token)['status'],400)
        self.assertEqual(self.fixture.request('/api/restore-apply',{'token':'invalid','mode':'complete'})['status'],401)

    def test_failed_migration_and_low_disk_apply_preserve_live_database(self):
        broken = server.DB.with_name('no-admin.sqlite3')
        broken.write_bytes(self.payload)
        with sqlite3.connect(broken) as db:
            db.execute("UPDATE users SET role='viewer'")
        before = server.DB.read_bytes()
        review = self.upload(broken.read_bytes())['body']
        self.assertEqual(self.apply(review,'complete')['status'],400)
        self.assertEqual(server.DB.read_bytes(),before)
        self.assertFalse(list(server.DB.parent.glob('.backup-transfer-*')))
        review = self.upload()['body']
        usage = shutil.disk_usage(server.DB.parent)._replace(free=0)
        with patch.object(backups.shutil,'disk_usage',return_value=usage):
            self.assertEqual(self.apply(review,'complete')['status'],507)
        self.assertEqual(server.DB.read_bytes(),before)
        self.assertFalse(list(server.DB.parent.glob('.backup-transfer-*')))

    def test_config_only_file_restores_and_cannot_be_replayed(self):
        payload = self.fixture.request('/api/backup?kind=configuration',token=self.fixture.admin_token)['content']
        review = self.upload(payload)['body']
        self.assertEqual(self.apply(review,'configuration')['status'],200)
        with server.connect() as db:
            self.assert_configuration(db)
            token = auth.new_session(db,1)
            actor = auth.session_user(db,'monitor_session=' + token)
        self.assertEqual(self.fixture.request('/api/restore-apply',{'token':review['token'],'mode':'configuration'},token,actor['csrf'])['status'],409)

    def test_streaming_upload_download_use_bounded_chunks(self):
        class Reader(io.BytesIO):
            def read(self, size=-1):
                if size < 0 or size > backups.CHUNK_BYTES:
                    raise AssertionError('Unbounded upload read')
                return super().read(size)
        with backups.transfer():
            work,path = backups.upload(Reader(self.payload),len(self.payload),server.DB.parent)
            try:
                class Sink:
                    count = 0
                    def write(self, block):
                        self.count += len(block)
                        if len(block)>backups.CHUNK_BYTES:
                            raise AssertionError('Unbounded download write')
                handler=object.__new__(server.Handler)
                handler.send_response=lambda status:None
                handler.send_header=lambda key,value:None
                handler.end_headers=lambda:None
                handler.wfile=Sink()
                handler.send_file(path,'test.sqlite3')
                self.assertEqual(handler.wfile.count,len(self.payload))
            finally:
                work.cleanup()
