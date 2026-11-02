"""Authorization and notification delivery tests never contact external services."""
import io
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
import urllib.error
from unittest.mock import patch

from app import auth, notifications, server


class AccessAndNotificationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.previous_db = server.DB
        server.DB = Path(self.directory.name) / 'test.sqlite3'
        self.environment = patch.dict(os.environ, {'MONITOR_ADMIN_PASSWORD': 'Temporary-test-123'})
        self.environment.start()
        server.initialize()
        with server.connect() as db:
            db.execute('UPDATE users SET must_change_password=0')
            self.admin_token = auth.new_session(db, 1)
            self.admin = auth.session_user(db, 'monitor_session=' + self.admin_token)
            auth.manage_user(db, 'user-create', {
                'username': 'reader', 'password': 'Reader-test-123', 'role': 'viewer',
            }, self.admin)
            db.execute("UPDATE users SET must_change_password=0 WHERE username='reader'")
            self.viewer_token = auth.new_session(db, 2)
            self.viewer = auth.session_user(db, 'monitor_session=' + self.viewer_token)

    def tearDown(self):
        server.DB = self.previous_db
        self.environment.stop()
        self.directory.cleanup()

    def request(self, path, body=None, token=None, csrf=None):
        handler = object.__new__(server.Handler)
        handler.path = path
        handler.client_address = ('127.0.0.1', 1234)
        handler.headers = {'Content-Type': 'application/json'}
        if token:
            handler.headers['Cookie'] = 'monitor_session=' + token
        if csrf:
            handler.headers['X-CSRF-Token'] = csrf
        data = json.dumps(body).encode() if body is not None else b''
        handler.headers['Content-Length'] = str(len(data))
        handler.rfile = io.BytesIO(data)
        response = {}
        handler.send = lambda content, mime=None, status=200: response.update(status=status, content=content)
        handler.session_response = lambda token=None: response.update(status=200, token=token)
        if body is None:
            handler.do_GET()
        else:
            handler.do_POST()
        return response

    def test_unauthenticated_requests_cannot_read_private_data_or_modify_it(self):
        for path in ('/api/state', '/api/backup', '/api/users', '/api/history?service=1&run=1'):
            self.assertEqual(self.request(path)['status'], 401)
        self.assertEqual(self.request('/api/project', {'name': 'Forbidden'})['status'], 401)
        self.assertEqual(self.request('/api/status')['status'], 200)
        self.assertEqual(self.request('/api/health')['status'], 200)

    def test_viewer_can_inspect_but_cannot_mutate_or_manage_secrets(self):
        self.assertEqual(self.request('/api/state', token=self.viewer_token)['status'], 200)
        for path in ('/api/users', '/api/backup', '/api/telegram', '/api/whatsapp'):
            self.assertEqual(self.request(path, token=self.viewer_token)['status'], 403)
        for path in ('/api/project', '/api/ack', '/api/user-create', '/api/telegram-save', '/api/restore'):
            response = self.request(path, {}, self.viewer_token, self.viewer['csrf'])
            self.assertEqual(response['status'], 403)

    def test_csrf_is_required_for_admin_mutations(self):
        response = self.request('/api/project', {'name': 'Blocked'}, self.admin_token)
        self.assertEqual(response['status'], 403)
        response = self.request('/api/project', {'name': 'Allowed'}, self.admin_token, self.admin['csrf'])
        self.assertEqual(response['status'], 200)

    def test_login_password_hashes_and_rate_limit(self):
        with server.connect() as db:
            encoded = db.execute('SELECT password_hash FROM users WHERE id=1').fetchone()[0]
            self.assertNotIn('Temporary-test-123', encoded)
            self.assertTrue(auth.password_matches('Temporary-test-123', encoded))
            self.assertFalse(auth.password_matches('wrong', encoded))
            for _ in range(5):
                token, status = auth.login(db, 'admin', 'wrong', 'test-ip')
                self.assertIsNone(token)
                self.assertEqual(status, 401)
            self.assertEqual(auth.login(db, 'admin', 'Temporary-test-123', 'test-ip')[1], 429)

    def test_last_admin_and_self_deletion_are_protected(self):
        with server.connect() as db:
            with self.assertRaises(ValueError):
                auth.manage_user(db, 'user-edit', {'user': 1, 'username': 'admin', 'role': 'viewer'}, self.admin)
            with self.assertRaises(ValueError):
                auth.manage_user(db, 'user-delete', {'user': 1}, self.admin)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM users WHERE role='admin'").fetchone()[0], 1)

    def test_user_edit_resets_password_and_revokes_sessions(self):
        response = self.request('/api/user-edit', {
            'user': 2, 'username': 'renamed', 'role': 'admin', 'password': 'Replacement-123',
        }, self.admin_token, self.admin['csrf'])
        self.assertEqual(response['status'], 200)
        self.assertEqual(self.request('/api/state', token=self.viewer_token)['status'], 401)
        with server.connect() as db:
            row = db.execute('SELECT * FROM users WHERE id=2').fetchone()
            self.assertEqual(row['must_change_password'], 1)
            self.assertTrue(auth.password_matches('Replacement-123', row['password_hash']))

    def test_temporary_password_blocks_dashboard_until_changed(self):
        with server.connect() as db:
            db.execute('UPDATE users SET must_change_password=1 WHERE id=2')
        self.assertEqual(self.request('/api/state', token=self.viewer_token)['status'], 403)
        response = self.request('/api/password', {
            'current_password': 'Reader-test-123', 'password': 'New-reader-123',
        }, self.viewer_token, self.viewer['csrf'])
        self.assertEqual(response['status'], 200)
        self.assertEqual(self.request('/api/state', token=self.viewer_token)['status'], 401)
        self.assertEqual(self.request('/api/state', token=response['token'])['status'], 200)

    def create_host(self):
        server.mutate('project', {'name': 'Deployment'})
        server.mutate('device', {'name': 'Switch-1', 'model': 'Switch', 'address': '192.168.1.1'})
        server.mutate('assignment', {'project': 1, 'device': 1, 'alias': 'Stage switch'})
        server.mutate('activate', {'project': 1})
        with server.connect() as db:
            return dict(db.execute('''SELECT s.*, d.address FROM services s
                JOIN assignments a ON a.id=s.assignment JOIN devices d ON d.id=a.device''').fetchone())

    def configure_channels(self):
        with server.connect() as db:
            notifications.save_configuration(db, {
                'enabled': True, 'bot_token': '123:TEST_SECRET', 'chat_id': '-100123', 'recoveries': True,
            })
            notifications.save_whatsapp(db, {
                'enabled': True, 'bot_token': 'TEST_META_SECRET', 'chat_id': '61400111222',
                'phone_number_id': '12345', 'api_version': 'v23.0', 'template_name': 'monitor_incident',
                'language': 'en_US', 'recipient_type': 'individual', 'recoveries': True,
            })

    def test_public_overview_does_not_expose_inventory_addresses_or_secrets(self):
        host = self.create_host()
        with patch.object(server, 'read_metric', return_value=1):
            server.poll_one(host, 1)
        self.configure_channels()
        response = self.request('/api/status')
        content = response['content']
        self.assertIn('Stage switch', content)
        for secret in ('192.168.1.1', 'TEST_SECRET', 'password_hash', 'bot_token', 'community', 'target'):
            self.assertNotIn(secret, content)
        server.mutate('toggle', {'id': 1, 'field': 'visible'})
        self.assertEqual(json.loads(self.request('/api/status')['content'])['devices'], [])

    def test_new_incident_and_recovery_queue_both_channels_once(self):
        host = self.create_host()
        self.configure_channels()
        with patch.object(server, 'read_metric', side_effect=TimeoutError):
            for _ in range(3):
                server.poll_one(host, 1)
        with server.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM notification_outbox').fetchone()[0], 2)
        with patch.object(server, 'read_metric', return_value=1):
            server.poll_one(host, 1)
            server.poll_one(host, 1)
        with server.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM notification_outbox').fetchone()[0], 4)

    def test_muted_host_does_not_queue_notifications(self):
        host = self.create_host()
        self.configure_channels()
        server.mutate('toggle', {'id': 1, 'field': 'notifications'})
        with patch.object(server, 'read_metric', side_effect=TimeoutError):
            server.poll_one(host, 1)
            server.poll_one(host, 1)
        with server.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM notification_outbox').fetchone()[0], 0)

    def test_delivery_retry_and_token_redaction(self):
        self.configure_channels()
        with server.connect() as db:
            notifications.enqueue_test(db)
        with patch.object(notifications, 'send_message', side_effect=TimeoutError('secret URL')):
            notifications.deliver_once(server.connect, server.LOCK, server.host_is_up)
        with server.connect() as db:
            row = db.execute('SELECT * FROM notification_outbox').fetchone()
            self.assertEqual(row['state'], 'pending')
            self.assertEqual(row['error'], 'TimeoutError')
            self.assertNotIn('secret', row['error'])
            db.execute('UPDATE notification_outbox SET next_attempt=0')
        with patch.object(notifications, 'send_message', return_value='42'):
            notifications.deliver_once(server.connect, server.LOCK, server.host_is_up)
        with server.connect() as db:
            row = db.execute('SELECT * FROM notification_outbox').fetchone()
            self.assertEqual(row['state'], 'sent')
            self.assertEqual(row['message_id'], '42')
            self.assertNotIn('bot_token', notifications.public_configuration(db))

    def test_configuration_changes_cancel_pending_messages(self):
        self.configure_channels()
        with server.connect() as db:
            notifications.enqueue_test(db)
            notifications.save_configuration(db, {'enabled': True, 'chat_id': '-100456'})
            self.assertEqual(db.execute('SELECT state FROM notification_outbox').fetchone()[0], 'cancelled')

    def test_bootstrap_password_file_is_private_and_not_recreated_on_restart(self):
        password_file = server.DB.with_name('initial-admin-password.txt')
        self.assertEqual(password_file.stat().st_mode & 0o777, 0o600)
        password_file.unlink()
        server.initialize()
        self.assertFalse(password_file.exists())

    def test_session_cookie_is_http_only_and_same_site(self):
        handler = object.__new__(server.Handler)
        headers = {}
        handler.send_response = lambda status: None
        handler.send_header = lambda key, value: headers.update({key: value})
        handler.end_headers = lambda: None
        handler.wfile = io.BytesIO()
        with patch.dict(os.environ, {'MONITOR_SECURE_COOKIE': 'true'}):
            handler.session_response('test-session')
        cookie = headers['Set-Cookie']
        for flag in ('HttpOnly', 'SameSite=Strict', 'Secure'):
            self.assertIn(flag, cookie)

    def test_backup_requires_admin_and_excludes_live_sessions(self):
        response = self.request('/api/backup', token=self.admin_token)
        self.assertEqual(response['status'], 200)
        restored = sqlite3.connect(':memory:')
        try:
            restored.deserialize(response['content'])
            self.assertEqual(restored.execute('SELECT COUNT(*) FROM sessions').fetchone()[0], 0)
            self.assertEqual(restored.execute('SELECT COUNT(*) FROM users').fetchone()[0], 2)
        finally:
            restored.close()

    def test_permanent_provider_failure_stops_retrying(self):
        self.configure_channels()
        with server.connect() as db:
            notifications.enqueue_test(db)
        error = urllib.error.HTTPError('secret-url', 401, 'Unauthorized', None, None)
        with patch.object(notifications, 'send_message', side_effect=error):
            notifications.deliver_once(server.connect, server.LOCK, server.host_is_up)
        with server.connect() as db:
            row = db.execute('SELECT * FROM notification_outbox').fetchone()
            self.assertEqual(row['state'], 'failed')
            self.assertEqual(row['error'], 'HTTP 401')

    def test_expired_session_is_rejected(self):
        with server.connect() as db:
            db.execute('UPDATE sessions SET expires=0')
        self.assertEqual(self.request('/api/state', token=self.admin_token)['status'], 401)

    def test_discovered_telegram_groups_do_not_return_messages_or_people(self):
        self.configure_channels()
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self, size):
                return json.dumps({'ok': True, 'result': [{'message': {
                    'text': 'private message', 'from': {'username': 'private-user'},
                    'chat': {'id': -100123, 'title': 'Network team', 'type': 'supergroup'},
                }}]}).encode()
        with server.connect() as db, patch.object(notifications.urllib.request, 'urlopen', return_value=Response()):
            groups = notifications.telegram_chats(db)
        self.assertEqual(groups, [{'id': '-100123', 'title': 'Network team'}])

    def test_group_discovery_route_is_admin_only(self):
        with patch.object(notifications, 'telegram_chats', return_value=[{'id': '-1001', 'title': 'Team'}]):
            response = self.request('/api/telegram-chats', token=self.admin_token)
            self.assertEqual(response['status'], 200)
            self.assertEqual(json.loads(response['content'])[0]['title'], 'Team')
            response = self.request('/api/telegram-chats', token=self.viewer_token)
            self.assertEqual(response['status'], 403)

    def test_retry_route_requeues_only_current_provider_configuration(self):
        self.configure_channels()
        with server.connect() as db:
            notifications.enqueue_test(db)
            db.execute("UPDATE notification_outbox SET state='failed'")
        response = self.request('/api/telegram-retry', {}, self.admin_token, self.admin['csrf'])
        self.assertEqual(response['status'], 200)
        with server.connect() as db:
            self.assertEqual(db.execute('SELECT state FROM notification_outbox').fetchone()[0], 'pending')

    def test_legacy_restore_preserves_accounts_and_invalidates_sessions(self):
        with server.connect() as source:
            backup = sqlite3.connect(':memory:')
            source.backup(backup)
            backup.executescript('DROP TABLE sessions; DROP TABLE users; DROP TABLE login_attempts;')
            payload = backup.serialize()
            backup.close()
        handler = object.__new__(server.Handler)
        handler.path = '/api/restore'
        handler.headers = {'Content-Type': 'application/octet-stream',
            'Content-Length': str(len(payload)), 'Cookie': 'monitor_session=' + self.admin_token,
            'X-CSRF-Token': self.admin['csrf']}
        handler.rfile = io.BytesIO(payload)
        result = {}
        handler.send = lambda content, mime=None, status=200: result.update(status=status, content=content)
        handler.do_POST()
        self.assertEqual(result['status'], 200)
        self.assertEqual(self.request('/api/state', token=self.admin_token)['status'], 401)
        with server.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM users').fetchone()[0], 2)
            token, status = auth.login(db, 'admin', 'Temporary-test-123', 'restore-test')
            self.assertEqual(status, 200)
            self.assertIsNotNone(token)

    def test_public_incidents_are_allowlisted_and_acknowledgement_removes_them(self):
        host = self.create_host()
        with patch.object(server, 'read_metric', side_effect=TimeoutError):
            server.poll_one(host, 1)
            server.poll_one(host, 1)
        public = json.loads(self.request('/api/status')['content'])
        self.assertEqual(len(public['incidents']), 1)
        incident = public['incidents'][0]
        self.assertEqual(incident['device'], 'Switch-1')
        self.assertEqual(incident['alias'], 'Stage switch')
        self.assertEqual(set(incident), {'device', 'alias', 'service', 'status', 'opened'})
        incident_id = server.snapshot()['incident_lists']['active'][0]['id']
        server.mutate('ack', {'id': incident_id})
        self.assertEqual(json.loads(self.request('/api/status')['content'])['incidents'], [])

    def test_public_incidents_exclude_hidden_paused_and_inactive_equipment(self):
        host = self.create_host()
        with patch.object(server, 'read_metric', side_effect=TimeoutError):
            server.poll_one(host, 1)
            server.poll_one(host, 1)
        for field in ('visible', 'monitoring'):
            server.mutate('toggle', {'id': 1, 'field': field})
            self.assertEqual(server.status_overview()['incidents'], [])
            server.mutate('toggle', {'id': 1, 'field': field})
        server.mutate('project', {'name': 'Other deployment'})
        server.mutate('activate', {'project': 2})
        self.assertEqual(server.status_overview()['incidents'], [])
        server.mutate('pause', {})
        self.assertEqual(server.status_overview()['incidents'], [])

    def test_public_incidents_respect_host_dependency_suppression(self):
        host = self.create_host()
        server.mutate('service', {'assignment': 1, 'name': 'Temperature', 'kind': 'snmp',
            'target': '.1.2.3', 'direction': 'above', 'warning': '80', 'critical': '90'})
        with server.connect() as db:
            child = dict(db.execute("""SELECT s.*,d.address FROM services s
                JOIN assignments a ON a.id=s.assignment JOIN devices d ON d.id=a.device
                WHERE s.kind='snmp'""").fetchone())
        with patch.object(server, 'read_metric', return_value=1):
            server.poll_one(host, 1)
        with patch.object(server, 'read_metric', return_value=95):
            server.poll_one(child, 1)
            server.poll_one(child, 1)
        self.assertEqual(server.status_overview()['incidents'][0]['service'], 'Temperature')
        with patch.object(server, 'read_metric', side_effect=TimeoutError):
            server.poll_one(host, 1)
            server.poll_one(host, 1)
        incidents = server.status_overview()['incidents']
        self.assertEqual(len(incidents), 1)
        self.assertEqual(incidents[0]['service'], 'Host ping')

    def test_provider_payloads_use_group_id_and_three_whatsapp_parameters(self):
        self.configure_channels()
        captured = []
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self, size): return b'{"ok":true,"result":{"message_id":42},"messages":[{"id":"wa42"}]}'
        def send(request, **kwargs):
            captured.append(request)
            return Response()
        with server.connect() as db, patch.object(notifications.urllib.request, 'urlopen', side_effect=send):
            notifications.send_message(notifications.configuration(db), 'Incident message')
            notifications.send_whatsapp(notifications.configuration(db, 'whatsapp'), 'CRITICAL\nDevice - Alias\nPort down')
        telegram = json.loads(captured[0].data)
        whatsapp = json.loads(captured[1].data)
        self.assertEqual(telegram['chat_id'], '-100123')
        self.assertEqual(whatsapp['messaging_product'], 'whatsapp')
        self.assertEqual(len(whatsapp['template']['components'][0]['parameters']), 3)
        self.assertEqual(whatsapp['recipient_type'], 'individual')


if __name__ == '__main__':
    unittest.main()
