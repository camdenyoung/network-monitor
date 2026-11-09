"""Authorization and notification delivery tests never contact external services."""
import io
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
import urllib.error
from unittest.mock import patch, Mock

from app import auth, notifications, server, logos


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

    def request(self, path, body=None, token=None, csrf=None, connection=None):
        handler = object.__new__(server.Handler)
        handler.path = path
        handler.client_address = ('127.0.0.1', 1234)
        handler.headers = {'Content-Type': 'application/json'}
        if connection:
            handler.headers['X-Dashboard-Connection'] = connection
        if token:
            handler.headers['Cookie'] = 'monitor_session=' + token
        if csrf:
            handler.headers['X-CSRF-Token'] = csrf
        data = json.dumps(body).encode() if body is not None else b''
        handler.headers['Content-Length'] = str(len(data))
        handler.rfile = io.BytesIO(data)
        response = {}
        handler.send = lambda content, mime=None, status=200, filename=None: response.update(status=status, content=content, mime=mime, filename=filename)
        handler.session_response = lambda token=None: response.update(status=200, token=token)
        handler.send_file = lambda path, filename: response.update(status=200, content=path.read_bytes(), filename=filename)
        handler.send_response = lambda status: response.update(status=status)
        handler.send_header = lambda key, value: response.setdefault('headers', {}).update({key: value})
        handler.end_headers = lambda: None
        if body is None:
            handler.do_GET()
        else:
            handler.do_POST()
        return response

    def test_presence_counts_anonymous_tabs_and_deduplicates_valid_users_admin_only(self):
        from app.presence import DashboardPresence
        with patch.object(server.presence, 'tracker', DashboardPresence()):
            public = self.request('/api/status', connection='anonymous-status-tab')
            self.assertNotIn('dashboard_presence', json.loads(public['content']))
            viewer = self.request('/api/state', token=self.viewer_token, connection='viewer-dashboard-tab')
            self.assertNotIn('dashboard_presence', json.loads(viewer['content']))
            self.request('/api/status', token=self.viewer_token, connection='viewer-second-dashboard')
            response = self.request('/api/state', token=self.admin_token, connection='admin-dashboard-tab')
            counts = json.loads(response['content'])['dashboard_presence']
            # Polling presence counts users; only admitted live streams count
            # towards the connection limit. This fixture opens no streams.
            self.assertEqual(counts['connections'], 0)
            self.assertEqual(counts['connection_limit'], 20)
            self.assertEqual(counts['logged_in_users'], 2)
            # Session revocation takes effect even if the old tab has not polled.
            with server.connect() as db:
                db.execute('DELETE FROM sessions WHERE user_id=2')
            response = self.request('/api/state', token=self.admin_token, connection='admin-dashboard-tab')
            self.assertEqual(json.loads(response['content'])['dashboard_presence']['logged_in_users'], 1)
            self.assertEqual(self.request('/api/state', connection='unauthorised-tab')['status'], 401)
            # A public poll with an expired cookie becomes an anonymous connection.
            self.request('/api/status', token=self.viewer_token, connection='viewer-dashboard-tab')
            response = self.request('/api/state', token=self.admin_token, connection='admin-dashboard-tab')
            self.assertEqual(json.loads(response['content'])['dashboard_presence']['connections'], 0)

    def test_project_deletion_requires_admin_csrf_and_exposes_progress_only_to_admin(self):
        self.create_host()
        body = {'project': 1, 'expected_name': 'Deployment'}
        self.assertEqual(self.request('/api/project-delete', body)['status'], 401)
        token, operator = self.create_operator()
        for session, user in ((self.viewer_token, self.viewer), (token, operator)):
            self.assertEqual(self.request('/api/project-delete', body, session, user['csrf'])['status'], 403)
        self.assertEqual(self.request('/api/project-delete', body, self.admin_token)['status'], 403)
        self.assertEqual(self.request('/api/project-delete', body, self.admin_token, self.admin['csrf'])['status'], 400)
        server.mutate('pause', {})
        result = self.request('/api/project-delete', body, self.admin_token, self.admin['csrf'])
        self.assertEqual(result['status'], 200)
        self.assertIn('job', json.loads(result['content']))
        state = json.loads(self.request('/api/state', token=self.admin_token)['content'])
        self.assertEqual(state['project_deletions'][0]['state'], 'queued')
        self.assertNotIn('project_deletions', json.loads(self.request('/api/state', token=self.viewer_token)['content']))
        self.assertNotIn('project_deletions', json.loads(self.request('/api/status')['content']))
        self.assertEqual(self.request('/api/backup', token=self.admin_token)['status'], 409)
        for _ in range(10):
            with server.connect() as db:
                if not server.project_deletion.step(db):
                    break
        self.assertEqual(server.snapshot()['projects'], [])
        self.assertEqual(len(server.snapshot()['devices']), 1)
        self.assertEqual(self.request('/api/backup', token=self.admin_token)['status'], 200)

    def test_running_deletion_blocks_restore_but_failed_job_can_restore_prior_backup(self):
        self.create_host()
        payload = self.request('/api/backup', token=self.admin_token)['content']
        server.mutate('pause', {})
        server.mutate('project-delete', {'project': 1, 'expected_name': 'Deployment'})

        def restore():
            handler = object.__new__(server.Handler)
            handler.path = '/api/restore'
            handler.headers = {'Content-Type': 'application/octet-stream',
                'Content-Length': str(len(payload)), 'Cookie': 'monitor_session=' + self.admin_token,
                'X-CSRF-Token': self.admin['csrf']}
            handler.rfile = io.BytesIO(payload)
            result = {}
            handler.send = lambda content, mime=None, status=200: result.update(status=status, content=content)
            handler.do_POST()
            return result['status']

        self.assertEqual(restore(), 409)
        with server.connect() as db:
            db.execute("UPDATE project_deletions SET state='failed'")
        self.assertEqual(restore(), 200)
        self.assertEqual(len(server.snapshot()['projects']), 1)
        with server.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM project_deletions').fetchone()[0], 0)

    def test_ranged_history_is_authenticated_and_rejects_invalid_ranges(self):
        host = self.create_host()
        path = f"/api/history?service={host['id']}&run=1&start=1&end=1000&mode=graph"
        self.assertEqual(self.request(path)['status'], 401)
        response = self.request(path, token=self.viewer_token)
        self.assertEqual(response['status'], 200)
        self.assertEqual(json.loads(response['content'])['total'], 0)
        self.assertEqual(self.request(path.replace('end=1000', 'end=nan'), token=self.admin_token)['status'], 400)
        self.assertEqual(self.request(path.replace('run=1', 'run=999'), token=self.admin_token)['status'], 400)
        self.assertEqual(self.request(path.replace('mode=graph', 'mode=table'), token=self.viewer_token)['status'], 200)

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
        server.mutate('activate', {'project': 1, 'description': 'Test deployment'})
        server.mutate('resume', {'project': 1})
        # Most tests exercise normal opted-in notification delivery.
        server.mutate('notification-pause', {'paused': False})
        with server.connect() as db:
            return dict(db.execute('''SELECT s.*, d.address FROM services s
                JOIN assignments a ON a.id=s.assignment JOIN devices d ON d.id=a.device''').fetchone())

    def test_device_duplication_requires_admin_csrf_and_reports_ip_conflicts(self):
        self.create_host()
        operator_token, operator = self.create_operator()
        body = {'device':1,'name':'Switch-2','address':'192.168.1.2'}
        for token, csrf, expected in ((None,None,401),(self.viewer_token,self.viewer['csrf'],403),
                                      (operator_token,operator['csrf'],403),(self.admin_token,None,403)):
            self.assertEqual(self.request('/api/device-duplicate', body, token, csrf)['status'], expected)
        response = self.request('/api/device-duplicate', body, self.admin_token, self.admin['csrf'])
        self.assertEqual(response['status'], 200)
        device = json.loads(response['content'])['device']
        with server.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM assignments WHERE device=?', (device,)).fetchone()[0], 0)
        conflicts = [('/api/device', {'name':'Conflict','address':'192.168.1.1'}),
                     ('/api/device-edit', {'device':device,'name':'Changed','address':'192.168.1.1'}),
                     ('/api/device-address', {'device':device,'address':'192.168.1.1'}),
                     ('/api/device-duplicate', {**body,'name':'Conflict','address':'192.168.1.1'})]
        for path, values in conflicts:
            conflict = self.request(path, values, self.admin_token, self.admin['csrf'])
            self.assertEqual(conflict['status'], 400)
            self.assertIn('already assigned to Switch-1', conflict['content'])

    def test_inventory_transfer_requires_admin_review_and_csrf(self):
        self.create_host()
        operator_token, operator = self.create_operator()
        document = {'format':'network-monitor-inventory','version':1,'devices':[
            {'name':'Imported','model':'Switch','address':'192.168.1.2','service_defaults':[]}]}
        body = {'inventory':document,'mode':'merge'}
        for token, csrf, expected in ((None,None,401),(self.viewer_token,self.viewer['csrf'],403),
                                      (operator_token,operator['csrf'],403),(self.admin_token,None,403)):
            for path in ('/api/inventory-preview','/api/inventory-import'):
                self.assertEqual(self.request(path, body, token, csrf)['status'], expected)
        for token, expected in ((None,401),(self.viewer_token,403),(operator_token,403),(self.admin_token,200)):
            self.assertEqual(self.request('/api/inventory-export', token=token)['status'], expected)
        exported = self.request('/api/inventory-export', token=self.admin_token)
        self.assertEqual(exported['mime'], 'application/json')
        self.assertRegex(exported['filename'], r'^network-monitor-inventory-\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}\.json$')
        self.assertEqual(json.loads(exported['content'])['format'], 'network-monitor-inventory')
        preview = self.request('/api/inventory-preview', body, self.admin_token, self.admin['csrf'])
        self.assertEqual(preview['status'], 200)
        review = json.loads(preview['content'])
        self.assertEqual(review['added'], 1)
        self.assertEqual(self.request('/api/inventory-import', body, self.admin_token,self.admin['csrf'])['status'], 400)
        imported = self.request('/api/inventory-import', {**body,'token':review['token']}, self.admin_token,self.admin['csrf'])
        self.assertEqual(imported['status'], 200)
        self.assertEqual(json.loads(imported['content'])['added'], 1)
        replay = self.request('/api/inventory-import', {**body,'token':review['token']}, self.admin_token,self.admin['csrf'])
        self.assertEqual(replay['status'], 400)
        self.assertIn('review', replay['content'])

    def test_resolved_search_covers_all_current_issues_with_ten_result_pages(self):
        host = self.create_host()
        with server.connect() as db:
            db.executemany("""INSERT INTO incidents(run,service,opened,closed,status,number,
                trigger_value,trigger_display,trigger_units,trigger_timestamp)
                VALUES(1,?,1,?,'critical',?,2,'Port Down','%',1)""",
                ((host['id'], 9999 if number == 1 else 500, number) for number in range(1, 232)))
        self.assertEqual(server.snapshot()['incident_lists']['resolved'][0]['number'], 1)
        path = '/api/resolved?run=1&search=SWITCH-1'
        self.assertEqual(self.request(path)['status'], 401)
        self.assertEqual(self.request('/api/resolved?run=2&search=Switch', token=self.viewer_token)['status'], 400)
        found = []
        while path:
            response = self.request(path, token=self.viewer_token)
            self.assertEqual(response['status'], 200)
            page = json.loads(response['content'])
            self.assertLessEqual(len(page['rows']), 10)
            found.extend(row['number'] for row in page['rows'])
            cursor = page['next']
            path = ('/api/resolved?run=1&search=SWITCH-1&before=' + str(cursor['before'])
                    + '&before_time=' + str(cursor['before_time'])) if cursor else None
        self.assertEqual(len(found), 231)
        self.assertEqual(len(set(found)), 231)
        self.assertEqual(found[0], 1)  # Latest recovery, even though its issue ID is oldest.
        for query in ('Stage', 'Port%20Down', 'Port%20Down%20%25', '%25'):
            result = self.request('/api/resolved?run=1&search=' + query, token=self.viewer_token)
            self.assertEqual(len(json.loads(result['content'])['rows']), 10)
        for query in ('_', '%27%20OR%201%3D1--', 'no-match'):
            result = self.request('/api/resolved?run=1&search=' + query, token=self.viewer_token)
            self.assertEqual(json.loads(result['content'])['rows'], [])
        self.assertEqual(self.request('/api/resolved?run=1&search=Switch&before=1', token=self.viewer_token)['status'], 400)
        server.mutate('assignment-remove', {'assignment':1})
        self.assertEqual(json.loads(self.request('/api/resolved?run=1&search=Switch', token=self.viewer_token)['content'])['rows'], [])

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
        response = self.request('/api/status', token=self.viewer_token)
        content = response['content']
        self.assertIn('Stage switch', content)
        for secret in ('192.168.1.1', 'TEST_SECRET', 'password_hash', 'bot_token', 'community', 'target'):
            self.assertNotIn(secret, content)
        server.mutate('toggle', {'id': 1, 'field': 'visible'})
        self.assertEqual(json.loads(self.request('/api/status', token=self.viewer_token)['content'])['devices'], [])

    def test_status_live_hosts_require_a_complete_authenticated_session(self):
        host = self.create_host()
        with patch.object(server, 'read_metric', return_value=1):
            server.poll_one(host, 1)
        server.mutate('service', {'assignment':1,'name':'Private RSSI','kind':'snmp',
                                  'target':'.1.2.3','direction':'below','warning':-65,'critical':-75})
        with server.connect() as db:
            child = dict(db.execute("""SELECT s.*,d.address FROM services s JOIN assignments a ON a.id=s.assignment
                JOIN devices d ON d.id=a.device WHERE s.name='Private RSSI'""").fetchone())
        with patch.object(server, 'read_metric', return_value=-55):
            server.poll_one(child, 1)
        operator_token, operator = self.create_operator()
        for token in (None, 'invalid-session'):
            response = self.request('/api/status', token=token)
            data = json.loads(response['content'])
            self.assertFalse(data['can_view_hosts'])
            self.assertEqual(data['devices'], [])
            self.assertNotIn('Private RSSI', response['content'])
            self.assertNotIn('Stage switch', response['content'])
        self.assertEqual(server.status_overview()['devices'], [])
        for token in (self.admin_token, self.viewer_token, operator_token):
            data = json.loads(self.request('/api/status', token=token)['content'])
            self.assertTrue(data['can_view_hosts'])
            self.assertEqual(data['devices'][0]['alias'], 'Stage switch')
            self.assertEqual(data['devices'][0]['services'][0]['value'], '-55')
        self.assertEqual(self.request('/api/logout', {}, operator_token, operator['csrf'])['status'], 200)
        self.assertFalse(json.loads(self.request('/api/status', token=operator_token)['content'])['can_view_hosts'])
        with server.connect() as db:
            db.execute('UPDATE sessions SET expires=0 WHERE user_id=2')
            db.execute('UPDATE users SET must_change_password=1 WHERE id=1')
        for token in (self.viewer_token, self.admin_token):
            data = json.loads(self.request('/api/status', token=token)['content'])
            self.assertFalse(data['can_view_hosts'])
            self.assertEqual(data['devices'], [])

    def test_anonymous_status_keeps_public_issue_lists_without_live_hosts(self):
        host = self.create_host()
        with patch.object(server, 'read_metric', side_effect=TimeoutError):
            server.poll_one(host, 1)
            server.poll_one(host, 1)
        data = json.loads(self.request('/api/status')['content'])
        self.assertEqual(data['devices'], [])
        self.assertEqual(data['incidents'][0]['device'], 'Switch-1')
        issue = data['incidents'][0]['id']
        server.mutate('ack', {'id':issue}, actor=self.admin)
        data = json.loads(self.request('/api/status')['content'])
        self.assertEqual(data['devices'], [])
        self.assertEqual(data['incidents'], [])
        self.assertEqual(data['acknowledged_incidents'][0]['id'], issue)
        self.assertFalse(data['can_acknowledge'])

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
            for message in db.execute("SELECT text FROM notification_outbox WHERE event='recovery'"):
                self.assertIn('Host ping: 1', message[0])
                self.assertNotIn('Host unreachable', message[0])
                self.assertNotIn('TimeoutError', message[0])


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

    def test_admin_session_duration_controls_new_sessions_and_cookie(self):
        with server.connect() as db:
            old_expiry = db.execute('SELECT expires FROM sessions WHERE user_id=1').fetchone()[0]
        response = self.request('/api/session-settings', {'hours': 2}, self.admin_token, self.admin['csrf'])
        self.assertEqual(response['status'], 200)
        with server.connect() as db:
            self.assertEqual(db.execute('SELECT expires FROM sessions WHERE user_id=1').fetchone()[0], old_expiry)
            now = auth.time.time()
            with patch.object(auth.time, 'time', return_value=now):
                token = auth.new_session(db, 1)
            with patch.object(auth.time, 'time', return_value=now + 7199):
                self.assertIsNotNone(auth.session_user(db, 'monitor_session=' + token))
            with patch.object(auth.time, 'time', return_value=now + 7200):
                self.assertIsNone(auth.session_user(db, 'monitor_session=' + token))
        handler = object.__new__(server.Handler)
        headers = {}
        handler.send_response = lambda status: None
        handler.send_header = lambda key, value: headers.update({key: value})
        handler.end_headers = lambda: None
        handler.wfile = io.BytesIO()
        handler.session_response(token)
        self.assertIn('Max-Age=7200', headers['Set-Cookie'])
        backup = self.request('/api/backup', token=self.admin_token)
        restored = sqlite3.connect(':memory:')
        try:
            restored.deserialize(backup['content'])
            self.assertEqual(auth.session_seconds(restored), 7200)
        finally:
            restored.close()

    def test_session_settings_require_admin_csrf_and_bounded_whole_hours(self):
        operator_token, operator = self.create_operator()
        for token, actor in ((self.viewer_token, self.viewer), (operator_token, operator)):
            self.assertEqual(self.request('/api/session-settings', {'hours': 2}, token, actor['csrf'])['status'], 403)
        self.assertEqual(self.request('/api/session-settings', {'hours': 2}, self.admin_token)['status'], 403)
        for value in (0, 169, 1.5, True, '12', None):
            self.assertEqual(self.request('/api/session-settings', {'hours': value}, self.admin_token, self.admin['csrf'])['status'], 400)
        for value in (1, 168):
            self.assertEqual(self.request('/api/session-settings', {'hours': value}, self.admin_token, self.admin['csrf'])['status'], 200)
        with server.connect() as db:
            db.execute("DELETE FROM settings WHERE key='session_hours'")
            self.assertEqual(auth.session_seconds(db), 43200)

    def reminder_fault(self):
        host = self.create_host()
        self.configure_channels()
        server.mutate('reminder-settings', {'minutes': 1})
        with patch.object(server, 'read_metric', side_effect=TimeoutError):
            server.poll_one(host, 1)
            server.poll_one(host, 1)
        now = server.time.time()
        issue = server.snapshot()['incident_lists']['active'][0]['id']
        with server.connect() as db:
            db.execute('UPDATE incidents SET opened=? WHERE id=?', (now - 61, issue))
            db.execute("UPDATE settings SET value=? WHERE key='notifications_resumed_at'", (str(now - 61),))
            db.execute("UPDATE notification_outbox SET state='sent',created=?,next_attempt=?", (now - 61, now - 61))
        return host, issue, now

    def test_notifications_use_deployment_issue_number_with_global_ack_id(self):
        host, old_issue, now = self.reminder_fault()
        server.mutate('activate', {'project': 1, 'description': 'Second deployment'})
        server.mutate('resume', {'project': 1})
        with server.connect() as db:
            host.update(dict(db.execute('SELECT * FROM services WHERE id=?', (host['id'],)).fetchone()))
        server.mutate('notification-pause', {'paused': False})
        with patch.object(server, 'read_metric', side_effect=TimeoutError):
            server.poll_one(host, 2)
            server.poll_one(host, 2)
        issue = server.snapshot()['incident_lists']['active'][0]
        self.assertEqual(issue['number'], 1)
        self.assertNotEqual(issue['id'], old_issue)
        with server.connect() as db:
            rows = db.execute('SELECT text FROM notification_outbox WHERE incident=?', (issue['id'],)).fetchall()
            self.assertEqual(len(rows), 2)
            self.assertTrue(all('Issue #1 · Deployment #2' in row['text'] for row in rows))
        public = server.status_overview()['incidents'][0]
        self.assertEqual(public['number'], 1)
        self.assertEqual(public['id'], issue['id'])

    def test_issue_notification_icons_match_status_and_recovery_on_both_channels(self):
        host, issue, now = self.reminder_fault()
        for status, event, heading in (
                ('critical', 'opened', '❌ CRITICAL'),
                ('unreachable', 'opened', '❌ UNREACHABLE'),
                ('warning', 'opened', '⚠️ WARNING'),
                ('critical', 'recovery', '✅ RECOVERED'),
                ('warning', 'reminder:1', '⚠️ REMINDER · WARNING'),
                ('critical', 'reminder:2', '❌ REMINDER · CRITICAL')):
            with self.subTest(status=status, event=event), server.connect() as db:
                db.execute('DELETE FROM notification_outbox')
                db.execute('UPDATE incidents SET status=? WHERE id=?', (status, issue))
                notifications.enqueue_incident(db, issue, event)
                rows = db.execute('SELECT channel,text FROM notification_outbox').fetchall()
                self.assertEqual({row['channel'] for row in rows}, {'telegram', 'whatsapp'})
                self.assertTrue(all(row['text'].startswith(heading + ' · ') for row in rows))
                self.assertTrue(all(f'Issue #{issue}' in row['text'] for row in rows))

    def test_reminders_repeat_per_channel_without_pending_or_restart_bursts(self):
        host, issue, now = self.reminder_fault()
        with patch.object(notifications.time, 'time', return_value=now), server.connect() as db:
            notifications.enqueue_reminders(db, server.host_is_up)
            notifications.enqueue_reminders(db, server.host_is_up)
            rows = db.execute("SELECT * FROM notification_outbox WHERE event LIKE 'reminder:%'").fetchall()
            self.assertEqual(len(rows), 2)
            self.assertEqual({row['channel'] for row in rows}, {'telegram', 'whatsapp'})
            self.assertTrue(all('REMINDER' in row['text'] for row in rows))
            notifications.ensure_tables(db)
            notifications.enqueue_reminders(db, server.host_is_up)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM notification_outbox WHERE event LIKE 'reminder:%'").fetchone()[0], 2)
            db.execute("UPDATE notification_outbox SET state='sent',next_attempt=? WHERE event LIKE 'reminder:%' AND channel='telegram'", (now,))
        for elapsed, expected in ((59, 2), (60, 3), (3600, 3)):
            with patch.object(notifications.time, 'time', return_value=now + elapsed), server.connect() as db:
                db.execute('UPDATE samples SET timestamp=?', (now + elapsed,))
                notifications.enqueue_reminders(db, server.host_is_up)
                self.assertEqual(db.execute("SELECT COUNT(*) FROM notification_outbox WHERE event LIKE 'reminder:%'").fetchone()[0], expected)

    def test_reminders_deliver_through_both_providers_and_disable_cleanly(self):
        host, issue, now = self.reminder_fault()
        with server.connect() as db:
            notifications.enqueue_reminders(db, server.host_is_up)
        with patch.object(notifications, 'send_message', return_value='telegram-reminder') as telegram, patch.object(notifications, 'send_whatsapp', return_value='whatsapp-reminder') as whatsapp:
            notifications.deliver_once(server.connect, server.LOCK, server.host_is_up)
            notifications.deliver_once(server.connect, server.LOCK, server.host_is_up)
            telegram.assert_called_once()
            whatsapp.assert_called_once()
        with server.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM notification_outbox WHERE event LIKE 'reminder:%' AND state='sent'").fetchone()[0], 2)
            db.execute("UPDATE notification_outbox SET state='pending' WHERE event LIKE 'reminder:%'")
        server.mutate('reminder-settings', {'minutes': 0})
        with server.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM notification_outbox WHERE event LIKE 'reminder:%' AND state='pending'").fetchone()[0], 0)
            notifications.enqueue_reminders(db, server.host_is_up)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM notification_outbox WHERE event LIKE 'reminder:%'").fetchone()[0], 2)

    def test_queued_reminders_are_cancelled_if_no_longer_eligible(self):
        host, issue, now = self.reminder_fault()
        with server.connect() as db:
            notifications.enqueue_reminders(db, server.host_is_up)
        changes = [
            "UPDATE incidents SET acknowledged=1",
            "UPDATE incidents SET closed=1",
            "UPDATE settings SET value='0' WHERE key='active_run'",
            "UPDATE assignments SET monitoring=0",
            "UPDATE assignments SET notifications=0",
            "UPDATE assignments SET removed=1",
            "UPDATE services SET monitoring=0",
            "UPDATE services SET enabled=0",
            "UPDATE samples SET timestamp=0",
            "UPDATE settings SET value='0' WHERE key='reminder_minutes'",
        ]
        for change in changes:
            with self.subTest(change=change):
                with server.connect() as db:
                    db.execute('UPDATE incidents SET acknowledged=NULL,closed=NULL')
                    db.execute("UPDATE settings SET value='1' WHERE key IN ('active_run','reminder_minutes')")
                    db.execute('UPDATE assignments SET monitoring=1,notifications=1,removed=0')
                    db.execute('UPDATE services SET monitoring=1,enabled=1')
                    db.execute('UPDATE samples SET timestamp=?', (now,))
                    db.execute("UPDATE notification_outbox SET state='pending',next_attempt=0 WHERE event LIKE 'reminder:%'")
                    db.execute(change)
                with patch.object(notifications, 'send_message') as telegram, patch.object(notifications, 'send_whatsapp') as whatsapp:
                    notifications.deliver_once(server.connect, server.LOCK, server.host_is_up)
                    notifications.deliver_once(server.connect, server.LOCK, server.host_is_up)
                    telegram.assert_not_called()
                    whatsapp.assert_not_called()
                with server.connect() as db:
                    self.assertEqual(db.execute("SELECT COUNT(*) FROM notification_outbox WHERE event LIKE 'reminder:%' AND state='cancelled'").fetchone()[0], 2)

    def test_reminders_require_fresh_faults_and_host_dependency(self):
        host, issue, now = self.reminder_fault()
        with server.connect() as db:
            db.execute("UPDATE services SET kind='snmp' WHERE id=?", (host['id'],))
            with patch.object(server, 'host_is_up', return_value=False):
                notifications.enqueue_reminders(db, server.host_is_up)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM notification_outbox WHERE event LIKE 'reminder:%'").fetchone()[0], 0)
            for status in ('healthy', 'blocked', 'unknown', 'paused'):
                db.execute('UPDATE samples SET status=?', (status,))
                with patch.object(server, 'host_is_up', return_value=True):
                    notifications.enqueue_reminders(db, server.host_is_up)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM notification_outbox WHERE event LIKE 'reminder:%'").fetchone()[0], 0)

    def test_reminder_settings_are_admin_only_validated_and_backed_up(self):
        self.assertEqual(self.request('/api/reminder-settings', {'minutes': 5}, self.viewer_token, self.viewer['csrf'])['status'], 403)
        token, operator = self.create_operator()
        self.assertEqual(self.request('/api/reminder-settings', {'minutes': 5}, token, operator['csrf'])['status'], 403)
        self.assertEqual(self.request('/api/reminder-settings', {'minutes': 5}, self.admin_token)['status'], 403)
        for value in (-1, 10081, 1.5, True, '5', None):
            self.assertEqual(self.request('/api/reminder-settings', {'minutes': value}, self.admin_token, self.admin['csrf'])['status'], 400)
        for value in (0, 1, 10080):
            self.assertEqual(self.request('/api/reminder-settings', {'minutes': value}, self.admin_token, self.admin['csrf'])['status'], 200)
        backup = self.request('/api/backup', token=self.admin_token)
        restored = sqlite3.connect(':memory:')
        try:
            restored.deserialize(backup['content'])
            self.assertEqual(notifications.reminder_interval(restored), 10080 * 60)
        finally:
            restored.close()

    def test_notification_pause_keeps_monitoring_and_does_not_replay_muted_alerts(self):
        host, issue, now = self.reminder_fault()
        with server.connect() as db:
            db.execute("UPDATE notification_outbox SET state='pending'")
            before_config = notifications.configuration(db)
        response = self.request('/api/notification-pause', {'paused': True}, self.admin_token, self.admin['csrf'])
        self.assertEqual(response['status'], 200)
        self.assertEqual(server.snapshot()['settings']['active_run'], '1')
        self.assertEqual(len(server.snapshot()['incident_lists']['active']), 1)
        with patch.object(server, 'read_metric', return_value=1):
            server.poll_one(host, 1)
            server.poll_one(host, 1)
        with patch.object(server, 'read_metric', side_effect=TimeoutError):
            server.poll_one(host, 1)
            server.poll_one(host, 1)
        self.assertEqual(len(server.snapshot()['incident_lists']['active']), 1)
        with server.connect() as db:
            notifications.enqueue_reminders(db, server.host_is_up)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM incidents').fetchone()[0], 2)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM notification_outbox').fetchone()[0], 2)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM notification_outbox WHERE state='cancelled'").fetchone()[0], 2)
            self.assertEqual(notifications.configuration(db), before_config)
        server.initialize()
        with server.connect() as db:
            self.assertTrue(notifications.are_paused(db))
        self.assertEqual(self.request('/api/notification-pause', {'paused': False}, self.admin_token, self.admin['csrf'])['status'], 200)
        with server.connect() as db:
            notifications.enqueue_reminders(db, server.host_is_up)
            self.assertFalse(notifications.are_paused(db))
            self.assertEqual(db.execute("SELECT COUNT(*) FROM notification_outbox WHERE state='pending'").fetchone()[0], 0)

    def test_paused_delivery_rechecks_mute_and_blocks_tests_and_retries(self):
        host, issue, now = self.reminder_fault()
        server.mutate('notification-pause', {'paused': True})
        with server.connect() as db:
            # Simulate a message left pending at a worker boundary/restart.
            db.execute("UPDATE notification_outbox SET state='pending',next_attempt=0")
            with self.assertRaises(ValueError):
                notifications.enqueue_test(db)
            with self.assertRaises(ValueError):
                notifications.retry_failed(db, 'telegram')
        with patch.object(notifications, 'send_message') as telegram, patch.object(notifications, 'send_whatsapp') as whatsapp:
            notifications.deliver_once(server.connect, server.LOCK, server.host_is_up)
            notifications.deliver_once(server.connect, server.LOCK, server.host_is_up)
            telegram.assert_not_called()
            whatsapp.assert_not_called()
        with server.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM notification_outbox WHERE state='cancelled'").fetchone()[0], 2)

    def test_resuming_notifications_restarts_reminder_interval_without_catchup(self):
        host, issue, now = self.reminder_fault()
        server.mutate('notification-pause', {'paused': True})
        with patch.object(notifications.time, 'time', return_value=now + 600):
            server.mutate('notification-pause', {'paused': False})
        for elapsed, expected in ((659, 0), (660, 2)):
            with patch.object(notifications.time, 'time', return_value=now + elapsed), server.connect() as db:
                db.execute('UPDATE samples SET timestamp=?', (now + elapsed,))
                notifications.enqueue_reminders(db, server.host_is_up)
                self.assertEqual(db.execute("SELECT COUNT(*) FROM notification_outbox WHERE event LIKE 'reminder:%'").fetchone()[0], expected)

    def test_each_new_deployment_pauses_notifications_until_explicitly_resumed(self):
        host = self.create_host()
        self.configure_channels()
        with patch.object(server, 'read_metric', side_effect=TimeoutError):
            server.poll_one(host, 1)
            server.poll_one(host, 1)
        with server.connect() as db:
            config = notifications.configuration(db)
            self.assertFalse(notifications.are_paused(db))
            self.assertEqual(db.execute("SELECT COUNT(*) FROM notification_outbox WHERE state='pending'").fetchone()[0], 2)
        server.mutate('activate', {'project': 1, 'description': 'New event setup'})
        server.mutate('resume', {'project': 1})
        with server.connect() as db:
            host.update(dict(db.execute('SELECT * FROM services WHERE id=?', (host['id'],)).fetchone()))
        state = server.snapshot()
        self.assertEqual(state['settings']['active_run'], '2')
        self.assertEqual(state['settings']['notifications_paused'], '1')
        with patch.object(server, 'read_metric', side_effect=TimeoutError):
            server.poll_one(host, 2)
            server.poll_one(host, 2)
        self.assertEqual(len(server.snapshot()['incident_lists']['active']), 1)
        with server.connect() as db:
            self.assertEqual(notifications.configuration(db), config)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM notification_outbox WHERE state='pending'").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM notification_outbox WHERE state='cancelled'").fetchone()[0], 2)
        server.mutate('pause', {})
        server.mutate('resume', {'project': 1})
        self.assertEqual(server.snapshot()['settings']['notifications_paused'], '1')
        server.mutate('notification-pause', {'paused': False})
        server.mutate('pause', {})
        server.mutate('resume', {'project': 1})
        self.assertEqual(server.snapshot()['settings']['notifications_paused'], '0')

    def test_notification_pause_requires_role_scope_csrf_and_boolean(self):
        token, operator = self.create_operator()
        for actor_token, actor in ((self.viewer_token, self.viewer), (token, operator)):
            self.assertEqual(self.request('/api/notification-pause', {'paused': True}, actor_token, actor['csrf'])['status'], 403)
        self.assertEqual(self.request('/api/notification-pause', {'paused': True}, self.admin_token)['status'], 403)
        for value in (1, 'true', None):
            self.assertEqual(self.request('/api/notification-pause', {'paused': value}, self.admin_token, self.admin['csrf'])['status'], 400)

    def test_selected_deployment_delete_requires_admin_and_csrf(self):
        self.create_host()
        server.mutate('activate', {'project': 1, 'description': 'Keep active deployment'})
        server.mutate('resume', {'project': 1})
        body = {'project': 1, 'run': 1, 'expected_active_run': 2}
        token, operator = self.create_operator()
        for actor_token, actor in ((self.viewer_token, self.viewer), (token, operator)):
            self.assertEqual(self.request('/api/delete-deployment', body, actor_token, actor['csrf'])['status'], 403)
        self.assertEqual(self.request('/api/delete-deployment', body, self.admin_token)['status'], 403)
        self.assertEqual(self.request('/api/delete-deployment', body, self.admin_token, self.admin['csrf'])['status'], 200)
        self.assertEqual([row['id'] for row in server.snapshot()['runs']], [2])
        self.assertEqual(self.request('/api/delete-deployment', body, self.admin_token, self.admin['csrf'])['status'], 400)

    def test_resuming_selected_deployment_requires_role_scope_and_csrf(self):
        self.create_host()
        server.mutate('activate', {'project': 1, 'description': 'Second deployment'})
        server.mutate('resume', {'project': 1})
        body = {'project': 1, 'run': 1, 'expected_active_run': 2}
        token, operator = self.create_operator()
        for actor_token, actor in ((self.viewer_token, self.viewer), (token, operator)):
            self.assertEqual(self.request('/api/resume-deployment', body, actor_token, actor['csrf'])['status'], 403)
        self.assertEqual(self.request('/api/resume-deployment', body, self.admin_token)['status'], 403)
        self.assertEqual(self.request('/api/resume-deployment', body, self.admin_token, self.admin['csrf'])['status'], 200)
        self.assertEqual(server.snapshot()['settings']['active_run'], '0')
        self.assertEqual(server.snapshot()['settings']['paused_run'], '1')
        self.assertEqual(server.snapshot()['settings']['notifications_paused'], '1')

    def test_library_export_and_import_require_admin_and_import_csrf(self):
        token, operator = self.create_operator()
        for actor_token, actor in ((self.viewer_token, self.viewer), (token, operator)):
            self.assertEqual(self.request('/api/library-export', token=actor_token)['status'], 403)
            self.assertEqual(self.request('/api/library-import', {'mode': 'merge', 'library': {}}, actor_token, actor['csrf'])['status'], 403)
        self.assertEqual(self.request('/api/library-export')['status'], 401)
        self.assertEqual(self.request('/api/library-import', {'mode': 'replace', 'library': {}}, self.admin_token)['status'], 403)

    def test_library_export_is_portable_and_import_returns_merge_counts(self):
        server.mutate('template-create', {'name': 'Existing', 'kind': 'snmp', 'target': '.1.2.3',
            'direction': 'below', 'community': 'SERVICE_EXPORT_SECRET'})
        exported = self.request('/api/library-export', token=self.admin_token)
        self.assertEqual(exported['status'], 200)
        self.assertRegex(exported['filename'], r'^network-monitor-service-library-\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}\.json$')
        document = json.loads(exported['content'])
        self.assertEqual(document['format'], 'network-monitor-service-library')
        self.assertEqual(document['services'][0]['community'], 'SERVICE_EXPORT_SECRET')
        self.assertNotIn('id', document['services'][0])
        new = dict(document['services'][0], name='New service')
        document['services'].append(new)
        response = self.request('/api/library-import', {'mode': 'merge', 'library': document},
                                self.admin_token, self.admin['csrf'])
        self.assertEqual(response['status'], 200)
        self.assertEqual(json.loads(response['content']), {'ok': True, 'added': 1, 'skipped': 1, 'replaced': 0, 'total': 2})
        before = server.snapshot()['service_templates']
        document['services'][1]['kind'] = 'invalid'
        response = self.request('/api/library-import', {'mode': 'replace', 'library': document},
                                self.admin_token, self.admin['csrf'])
        self.assertEqual(response['status'], 400)
        self.assertNotIn('SERVICE_EXPORT_SECRET', response['content'])
        self.assertEqual(server.snapshot()['service_templates'], before)

    def test_library_import_rejects_oversized_request_before_reading_body(self):
        handler = object.__new__(server.Handler)
        handler.path = '/api/library-import'
        handler.headers = {'Content-Type': 'application/json',
            'Content-Length': str(5 * 1024 * 1024 + 1),
            'Cookie': 'monitor_session=' + self.admin_token, 'X-CSRF-Token': self.admin['csrf']}
        handler.rfile = io.BytesIO(b'')
        result = {}
        handler.send = lambda content, mime=None, status=200: result.update(status=status, content=content)
        handler.do_POST()
        self.assertEqual(result['status'], 400)

    def test_inventory_default_mutations_require_admin_and_csrf(self):
        self.create_host()
        token, operator = self.create_operator()
        actions = ('device-default-create', 'device-default-edit', 'device-default-delete',
                   'device-default-from-template', 'device-defaults-from-assignment')
        for action in actions:
            for actor_token, actor in ((self.viewer_token, self.viewer), (token, operator)):
                self.assertEqual(self.request('/api/' + action, {'device': 1}, actor_token, actor['csrf'])['status'], 403)
            self.assertEqual(self.request('/api/' + action, {'device': 1}, self.admin_token)['status'], 403)

    def test_inventory_defaults_are_redacted_in_state_and_preserved_by_restore(self):
        self.create_host()
        response = self.request('/api/device-default-create', {
            'device': 1, 'name': 'Inventory RSSI', 'kind': 'snmp', 'target': '.1.2.3',
            'community': 'DEFAULT_SECRET', 'direction': 'below',
        }, self.admin_token, self.admin['csrf'])
        self.assertEqual(response['status'], 200)
        state = json.loads(self.request('/api/state', token=self.admin_token)['content'])
        default = state['device_service_defaults'][0]
        self.assertNotIn('community', default)
        self.assertNotIn('DEFAULT_SECRET', json.dumps(state))
        self.assertNotIn('device_service_defaults', json.loads(self.request('/api/status')['content']))
        payload = self.request('/api/backup', token=self.admin_token)['content']
        server.mutate('device-default-delete', {'device': 1, 'default_service': default['id']})
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
        with server.connect() as db:
            self.assertEqual(db.execute('SELECT community FROM device_service_defaults WHERE id=?', (default['id'],)).fetchone()[0], 'DEFAULT_SECRET')
        server.mutate('project', {'name': 'After restore'})
        server.mutate('assignment', {'device': 1, 'project': 2, 'alias': 'New event'})
        with server.connect() as db:
            self.assertEqual(db.execute("SELECT s.community FROM services s JOIN assignments a ON a.id=s.assignment WHERE a.project=2 AND s.kind='snmp'").fetchone()[0], 'DEFAULT_SECRET')

    def test_login_page_accepts_status_return_parameter_without_authentication(self):
        for path in ('/login', '/login?next=%2Fstatus', '/login?next=%2F'):
            response = self.request(path)
            self.assertEqual(response['status'], 200)
            self.assertIn('text/html', response['mime'])
            self.assertIn(b'id="login-form"', response['content'])

    def test_account_pages_redirect_by_session_and_preserve_only_local_destinations(self):
        for token in (self.admin_token, self.viewer_token):
            for query, destination in (('', '/'), ('?next=%2Fstatus', '/status'),
                                       ('?next=https%3A%2F%2Fevil.example', '/'),
                                       ('?next=%2F%2Fevil.example', '/')):
                response = self.request('/login' + query, token=token)
                self.assertEqual(response['status'], 303)
                self.assertEqual(response['headers']['Location'], destination)
                self.assertEqual(response['headers']['Cache-Control'], 'no-store')
            response = self.request('/change-password', token=token)
            self.assertEqual(response['status'], 200)
            self.assertIn(b'id="password-form"', response['content'])
            self.assertNotIn(b'id="login-form"', response['content'])
        for query, destination in (('', '/login'), ('?next=%2Fstatus', '/login?next=%2Fstatus'),
                                   ('?next=https%3A%2F%2Fevil.example', '/login')):
            response = self.request('/change-password' + query)
            self.assertEqual(response['status'], 303)
            self.assertEqual(response['headers']['Location'], destination)
        with server.connect() as db:
            db.execute('UPDATE users SET must_change_password=1 WHERE id=2')
        self.assertEqual(self.request('/login', token=self.viewer_token)['headers']['Location'], '/change-password')
        self.assertEqual(self.request('/login?next=%2Fstatus', token=self.viewer_token)['headers']['Location'],
                         '/change-password?next=%2Fstatus')
        self.assertEqual(self.request('/', token=self.viewer_token)['headers']['Location'], '/change-password')
        self.assertEqual(self.request('/api/state', token=self.viewer_token)['status'], 403)
        self.assertEqual(self.request('/change-password', token=self.viewer_token)['status'], 200)
        with server.connect() as db:
            db.execute('UPDATE sessions SET expires=0')
        self.assertEqual(self.request('/login', token=self.viewer_token)['status'], 200)
        self.assertEqual(self.request('/change-password', token=self.viewer_token)['headers']['Location'], '/login')

    def test_separate_account_forms_and_password_change_security(self):
        login = self.request('/login')['content']
        self.assertEqual(login.count(b'<form '), 1)
        self.assertNotIn(b'id="password-form"', login)
        self.assertIn(b'type="submit"', login)
        self.assertNotIn(b'form.reset()', login)
        self.assertEqual(self.request('/api/password', {
            'current_password': 'Reader-test-123', 'password': 'New-reader-123',
        }, token=self.viewer_token)['status'], 403)
        self.assertEqual(self.request('/api/password', {
            'current_password': 'wrong', 'password': 'New-reader-123',
        }, token=self.viewer_token, csrf=self.viewer['csrf'])['status'], 400)
        with server.connect() as db:
            other_token = auth.new_session(db, 2)
        response = self.request('/api/password', {
            'current_password': 'Reader-test-123', 'password': 'New-reader-123',
        }, token=self.viewer_token, csrf=self.viewer['csrf'])
        self.assertEqual(response['status'], 200)
        with server.connect() as db:
            self.assertIsNone(auth.session_user(db, 'monitor_session=' + self.viewer_token))
            self.assertIsNone(auth.session_user(db, 'monitor_session=' + other_token))
            self.assertFalse(auth.session_user(db, 'monitor_session=' + response['token'])['must_change_password'])

    def test_valid_session_survives_96_hours_and_recovers_after_cookie_free_navigation(self):
        self.assertEqual(self.request('/api/session-settings', {'hours': 96},
                                      self.admin_token, self.admin['csrf'])['status'], 200)
        now = auth.time.time()
        with server.connect() as db:
            with patch.object(auth.time, 'time', return_value=now):
                token = auth.new_session(db, 2)
            original = db.execute('SELECT expires FROM sessions WHERE user_id=2 ORDER BY expires DESC').fetchone()[0]
        # Model the observed request distinction without asserting its browser-level cause.
        self.assertIn(b'id="login-form"', self.request('/login')['content'])
        for hours in (1, 12, 95):
            with patch.object(auth.time, 'time', return_value=now + hours * 3600):
                me = self.request('/api/me', token=token)
                self.assertEqual(me['status'], 200)
                self.assertEqual(json.loads(me['content'])['username'], 'reader')
                self.assertEqual(self.request('/', token=token)['status'], 200)
        with server.connect() as db:
            # Rechecking is read-only: it must not extend the fixed expiry.
            self.assertEqual(db.execute('SELECT MAX(expires) FROM sessions WHERE user_id=2').fetchone()[0], original)
        with patch.object(auth.time, 'time', return_value=now + 96 * 3600):
            self.assertEqual(self.request('/api/me', token=token)['status'], 401)

    def test_me_reports_only_callers_session_expiry_without_renewal(self):
        now = auth.time.time()
        with server.connect() as db:
            db.execute('UPDATE sessions SET expires=? WHERE user_id=1', (now + 345600,))
            db.execute('UPDATE sessions SET expires=? WHERE user_id=2', (now + 7200,))
        for elapsed in (0, 3600):
            with patch.object(auth.time, 'time', return_value=now + elapsed):
                for token, username, lifetime in ((self.admin_token, 'admin', 345600),
                                                  (self.viewer_token, 'reader', 7200)):
                    response = self.request('/api/me', token=token)
                    self.assertEqual(response['status'], 200)
                    body = json.loads(response['content'])
                    self.assertEqual(body['username'], username)
                    self.assertEqual(body['session_expires_at'], now + lifetime)
                    self.assertEqual(body['session_remaining_seconds'], lifetime - elapsed)
                    self.assertIsInstance(body['session_remaining_seconds'], int)
                    self.assertNotIn('token_hash', body)
                    self.assertNotIn('password_hash', body)
        with server.connect() as db:
            self.assertEqual(db.execute('SELECT expires FROM sessions WHERE user_id=1').fetchone()[0], now + 345600)
            self.assertEqual(db.execute('SELECT expires FROM sessions WHERE user_id=2').fetchone()[0], now + 7200)
        self.assertEqual(self.request('/api/me')['status'], 401)
        with patch.object(auth.time, 'time', return_value=now + 7200):
            self.assertEqual(self.request('/api/me', token=self.viewer_token)['status'], 401)
        # Account/public responses must not disclose per-session expiry information.
        for response in (self.request('/api/status'), self.request('/api/users', token=self.admin_token)):
            self.assertNotIn('session_expires_at', response['content'])
            self.assertNotIn('session_remaining_seconds', response['content'])

    def test_local_stylesheets_are_public_allowlisted_and_not_cached(self):
        for name in ('base', 'dashboard', 'status', 'auth'):
            handler = object.__new__(server.Handler)
            handler.path = f'/static/css/{name}.css?v=112'
            handler.headers = {}
            handler.wfile = io.BytesIO()
            result = {}
            handler.send_response = lambda status: result.update(status=status)
            handler.send_header = lambda key, value: result.setdefault('headers', {}).update({key: value})
            handler.end_headers = lambda: None
            handler.do_GET()
            self.assertEqual(result['status'], 200)
            self.assertEqual(result['headers']['Content-Type'], 'text/css; charset=utf-8')
            self.assertEqual(result['headers']['Cache-Control'], 'no-store')
            self.assertEqual(result['headers']['X-Content-Type-Options'], 'nosniff')
            self.assertEqual(handler.wfile.getvalue(), server.STYLESHEETS[f'/static/css/{name}.css'].read_bytes())
        for path in ('/static/css/../auth.py', '/static/css/%2e%2e/auth.py',
                     '/static/css/missing.css', '/static/css/base.css/extra', '/static/server.py'):
            self.assertEqual(self.request(path)['status'], 404)
        for name, stylesheet in (('index.html', 'dashboard'), ('status.html', 'status'),
                                  ('login.html', 'auth'), ('change-password.html', 'auth')):
            page = Path(server.__file__).with_name(name).read_text()
            self.assertIn('/static/css/base.css?v=112', page)
            version = 122 if stylesheet == 'dashboard' else 112
            self.assertIn(f'/static/css/{stylesheet}.css?v={version}', page)
            self.assertNotIn('<style>', page)
            self.assertNotIn('style="max-width', page)

    def test_restore_limit_is_configurable_and_bounded(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(server.restore_limit_bytes(), 20480 * 1024 * 1024)
        for value in ('1', '20480', '1048576'):
            with patch.dict(os.environ, {'MONITOR_MAX_RESTORE_MB': value}):
                self.assertEqual(server.restore_limit_bytes(), int(value) * 1024 * 1024)
        for value in ('0', '-1', '1048577', 'invalid', '1.5'):
            with patch.dict(os.environ, {'MONITOR_MAX_RESTORE_MB': value}):
                with self.assertRaises(ValueError):
                    server.restore_limit_bytes()

    def test_oversized_restore_reports_413_without_reading_or_replacing_data(self):
        handler = object.__new__(server.Handler)
        handler.path = '/api/restore'
        handler.headers = {
            'Content-Type': 'application/octet-stream', 'Content-Length': str(2 * 1024 * 1024),
            'X-CSRF-Token': 'test',
        }
        handler.require_user = lambda **kwargs: {'id': 1, 'role': 'admin', 'csrf': 'test'}
        handler.rfile = Mock()
        result = {}
        handler.send = lambda content, status=200: result.update(status=status, content=content)
        with patch.dict(os.environ, {'MONITOR_MAX_RESTORE_MB': '1'}):
            handler.do_POST()
        self.assertEqual(result['status'], 413)
        self.assertIn('limit of 1 MiB', json.loads(result['content'])['error'])
        handler.rfile.read.assert_not_called()
        self.assertEqual(self.request('/api/me', token=self.admin_token)['status'], 200)

    def test_complete_backup_over_64_mib_restores_into_fresh_installation(self):
        self.create_host()
        with server.connect() as db:
            # Real SQLite backup above the old cap, without a production database.
            db.execute('CREATE TABLE test_restore_padding (data BLOB)')
            db.execute('INSERT INTO test_restore_padding VALUES(zeroblob(?))', (72 * 1024 * 1024,))
        payload = self.request('/api/backup', token=self.admin_token)['content']
        self.assertGreater(len(payload), 64 * 1024 * 1024)
        source_path = server.DB
        try:
            server.DB = Path(self.directory.name) / 'fresh.sqlite3'
            server.initialize()
            with server.connect() as db:
                db.execute('UPDATE users SET must_change_password=0')
                token = auth.new_session(db, 1)
                actor = auth.session_user(db, 'monitor_session=' + token)
            handler = object.__new__(server.Handler)
            handler.path = '/api/restore'
            handler.headers = {
                'Content-Type': 'application/octet-stream', 'Content-Length': str(len(payload)),
                'Cookie': 'monitor_session=' + token, 'X-CSRF-Token': actor['csrf'],
            }
            handler.rfile = io.BytesIO(payload)
            result = {}
            handler.send = lambda content, status=200: result.update(status=status, content=content)
            with patch.dict(os.environ, {'MONITOR_MAX_RESTORE_MB': '256'}):
                handler.do_POST()
            self.assertEqual(result['status'], 200, result)
            with server.connect() as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM devices').fetchone()[0], 1)
                self.assertEqual(db.execute('SELECT COUNT(*) FROM users').fetchone()[0], 2)
                self.assertEqual(db.execute("SELECT value FROM settings WHERE key='active_run'").fetchone()[0], '0')
                self.assertEqual(db.execute('SELECT COUNT(*) FROM sessions').fetchone()[0], 0)
                self.assertEqual(db.execute('SELECT length(data) FROM test_restore_padding').fetchone()[0], 72 * 1024 * 1024)
        finally:
            server.DB = source_path

    def test_backup_requires_admin_and_excludes_live_sessions(self):
        with patch.object(server.time, 'localtime', return_value=(2026, 11, 2, 19, 9, 10, 0, 306, 1)):
            response = self.request('/api/backup', token=self.admin_token)
        self.assertEqual(response['filename'], 'network-monitor-backup-2026-11-02_19-09-10.sqlite3')
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
        self.assertEqual(set(incident), {'id', 'number', 'device', 'alias', 'service', 'status', 'opened', 'trigger_value', 'trigger_display', 'trigger_units', 'trigger_timestamp', 'trigger_error'})
        incident_id = server.snapshot()['incident_lists']['active'][0]['id']
        server.mutate('ack', {'id': incident_id}, actor={'id': 1})
        acknowledged = server.status_overview()['acknowledged_incidents']
        self.assertEqual(len(acknowledged), 1)
        self.assertEqual(acknowledged[0]['acknowledged_by_username'], 'admin')
        self.assertEqual(set(acknowledged[0]), {
            'id', 'number', 'device', 'alias', 'service', 'status', 'opened', 'acknowledged', 'closed', 'acknowledged_by_username', 'acknowledged_by_full_name', 'ack_revision', 'trigger_value', 'trigger_display', 'trigger_units', 'trigger_timestamp', 'trigger_error'})
        with server.connect() as db:
            db.execute('UPDATE assignments SET visible=0 WHERE id=1')
        self.assertEqual(server.status_overview()['acknowledged_incidents'], [])
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
        server.mutate('activate', {'project': 2, 'description': 'Test deployment'})
        server.mutate('resume', {'project': 2})
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

    def test_admin_can_choose_password_policy_when_creating_users(self):
        for required in (False, True):
            username = 'require-change' if required else 'assigned-password'
            response = self.request('/api/user-create', {
                'username': username, 'email': username + '@example.com',
                'role': 'viewer', 'password': 'Assigned-password-123',
                'must_change_password': required,
            }, self.admin_token, self.admin['csrf'])
            self.assertEqual(response['status'], 200)
            with server.connect() as db:
                token, status = auth.login(db, username, 'Assigned-password-123', username)
                self.assertEqual(status, 200)
                user = auth.session_user(db, 'monitor_session=' + token)
                self.assertEqual(user['email'], username + '@example.com')
                self.assertEqual(bool(user['must_change_password']), required)
            self.assertEqual(self.request('/api/state', token=token)['status'], 403 if required else 200)

    def test_admin_can_edit_email_and_allow_a_replacement_password(self):
        response = self.request('/api/user-edit', {
            'user': 2, 'username': 'reader', 'email': '  operations@example.com  ',
            'role': 'viewer', 'password': 'Assigned-replacement-123',
            'must_change_password': False,
        }, self.admin_token, self.admin['csrf'])
        self.assertEqual(response['status'], 200)
        with server.connect() as db:
            row = db.execute('SELECT * FROM users WHERE id=2').fetchone()
            self.assertEqual(row['email'], 'operations@example.com')
            self.assertEqual(row['must_change_password'], 0)
            self.assertTrue(auth.password_matches('Assigned-replacement-123', row['password_hash']))
        self.assertEqual(self.request('/api/state', token=self.viewer_token)['status'], 401)
        users = json.loads(self.request('/api/users', token=self.admin_token)['content'])
        self.assertEqual(next(user for user in users if user['id'] == 2)['email'], 'operations@example.com')
        self.assertNotIn('operations@example.com', self.request('/api/status')['content'])

    def test_admin_can_require_password_change_without_replacing_password(self):
        with server.connect() as db:
            old_hash = db.execute('SELECT password_hash FROM users WHERE id=2').fetchone()[0]
        response = self.request('/api/user-edit', {
            'user': 2, 'username': 'reader', 'role': 'viewer', 'email': '',
            'password': '', 'must_change_password': True,
        }, self.admin_token, self.admin['csrf'])
        self.assertEqual(response['status'], 200)
        with server.connect() as db:
            row = db.execute('SELECT * FROM users WHERE id=2').fetchone()
            self.assertEqual(row['password_hash'], old_hash)
            self.assertEqual(row['must_change_password'], 1)

    def test_invalid_email_or_password_policy_does_not_partially_edit_user(self):
        for fields in ({'email': 'not-an-email'}, {'email': 'a@example.com\nBcc:other@example.com'},
                       {'must_change_password': 'false'}):
            body = {'user': 2, 'username': 'changed', 'role': 'viewer', **fields}
            response = self.request('/api/user-edit', body, self.admin_token, self.admin['csrf'])
            self.assertEqual(response['status'], 400)
        with server.connect() as db:
            self.assertEqual(db.execute('SELECT username FROM users WHERE id=2').fetchone()[0], 'reader')
            self.assertIsNotNone(auth.session_user(db, 'monitor_session=' + self.viewer_token))

    def test_existing_accounts_gain_email_without_changing_password_or_policy(self):
        with server.connect() as db:
            before = db.execute('SELECT password_hash,must_change_password FROM users WHERE id=2').fetchone()
            db.execute('ALTER TABLE users DROP COLUMN email')
        server.initialize()
        with server.connect() as db:
            after = db.execute('SELECT password_hash,must_change_password,email FROM users WHERE id=2').fetchone()
        self.assertEqual(tuple(before), tuple(after)[:2])
        self.assertEqual(after['email'], '')

    def create_operator(self):
        response = self.request('/api/user-create', {
            'username': 'operator', 'email': 'operator@example.com', 'role': 'operator',
            'password': 'Operator-password-123', 'must_change_password': False,
        }, self.admin_token, self.admin['csrf'])
        self.assertEqual(response['status'], 200)
        with server.connect() as db:
            token, status = auth.login(db, 'operator', 'Operator-password-123', 'operator-test')
            self.assertEqual(status, 200)
            user = auth.session_user(db, 'monitor_session=' + token)
        return token, user

    def test_operator_can_acknowledge_incidents_but_cannot_change_configuration(self):
        token, operator = self.create_operator()
        host = self.create_host()
        with patch.object(server, 'read_metric', side_effect=TimeoutError):
            server.poll_one(host, 1)
            server.poll_one(host, 1)
        incident = server.snapshot()['incident_lists']['active'][0]
        self.assertEqual(self.request('/api/state', token=token)['status'], 200)
        self.assertEqual(self.request('/api/history?service=1&run=1', token=token)['status'], 200)
        response = self.request('/api/ack', {'id': incident['id']}, token, operator['csrf'])
        self.assertEqual(response['status'], 200)
        self.assertEqual(server.snapshot()['incident_lists']['active'], [])
        self.assertEqual(len(server.snapshot()['incident_lists']['acknowledged']), 1)
        for action in ('project', 'activate', 'assignment-edit', 'device-edit',
                       'service-edit', 'service-copy', 'template-create', 'retention',
                       'user-edit', 'telegram-save', 'whatsapp-save', 'restore'):
            self.assertEqual(self.request('/api/' + action, {}, token, operator['csrf'])['status'], 403)
        for path in ('/api/users', '/api/backup', '/api/telegram', '/api/telegram-chats', '/api/whatsapp'):
            self.assertEqual(self.request(path, token=token)['status'], 403)

    def test_operator_acknowledgement_requires_csrf(self):
        token, operator = self.create_operator()
        self.assertEqual(self.request('/api/ack', {'id': 1}, token=token)['status'], 403)
        self.assertEqual(self.request('/api/user-edit', {
            'user': operator['id'], 'username': 'operator', 'role': 'admin',
        }, token, operator['csrf'])['status'], 403)

    def test_last_admin_cannot_be_demoted_to_operator(self):
        response = self.request('/api/user-edit', {
            'user': 1, 'username': 'admin', 'role': 'operator',
        }, self.admin_token, self.admin['csrf'])
        self.assertEqual(response['status'], 400)
        self.assertEqual(self.request('/api/state', token=self.admin_token)['status'], 200)

    def logo_image(self, colour=255):
        import struct
        import zlib
        def chunk(kind, data):
            return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff)
        header = struct.pack('>IIBBBBB', 1, 1, 8, 2, 0, 0, 0)
        return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', header)
                + chunk(b'IDAT', zlib.compress(bytes([0, colour, 0, 0]))) + chunk(b'IEND', b''))

    def upload_logo(self, token, csrf, data):
        handler = object.__new__(server.Handler)
        handler.path = '/api/project-logo?project=1'
        handler.headers = {'Cookie': 'monitor_session=' + token,
            'X-CSRF-Token': csrf, 'Content-Type': 'image/png', 'Content-Length': str(len(data))}
        handler.rfile = io.BytesIO(data)
        response = {}
        handler.send = lambda content, mime=None, status=200: response.update(content=content,mime=mime,status=status)
        handler.do_POST()
        return response

    def test_project_logo_upload_replace_remove_and_public_visibility(self):
        self.create_host()
        first = self.logo_image()
        self.assertEqual(self.upload_logo(self.admin_token, self.admin['csrf'], first)['status'], 200)
        project = server.snapshot()['projects'][0]
        self.assertTrue(project['logo_url'].startswith('/api/project-logo?'))
        public_url = server.status_overview()['logo_url']
        self.assertTrue(public_url.startswith('/api/public-logo?'))
        response = self.request(public_url)
        self.assertEqual(response['status'], 200)
        self.assertEqual(response['mime'], 'image/png')
        self.assertEqual(response['content'], first)
        self.assertEqual(self.request(project['logo_url'])['status'], 401)
        self.assertEqual(self.request(project['logo_url'], token=self.viewer_token)['status'], 200)
        self.assertEqual(self.upload_logo(self.viewer_token, self.viewer['csrf'], first)['status'], 403)
        self.assertEqual(self.upload_logo(self.admin_token, '', first)['status'], 403)
        replacement = self.logo_image(128)
        self.assertEqual(self.upload_logo(self.admin_token, self.admin['csrf'], replacement)['status'], 200)
        self.assertNotEqual(server.status_overview()['logo_url'], public_url)
        server.mutate('pause', {})
        self.assertEqual(self.request(public_url)['status'], 200)
        overview = server.status_overview()
        self.assertTrue(overview['monitoring_paused'])
        self.assertEqual(overview['project'], project['name'])
        self.assertIsNotNone(overview['logo_url'])
        self.assertEqual(overview['devices'], [])
        self.assertFalse(overview['acknowledge_enabled'])
        server.mutate('project', {'name': 'Other private event'})
        self.assertEqual(self.request('/api/public-logo?project=2')['status'], 404)
        server.mutate('project-logo-remove', {'project': 1})
        self.assertIsNone(server.snapshot()['projects'][0]['logo_url'])

    def test_new_project_can_reuse_uploaded_logo_as_independent_copy(self):
        self.create_host()
        image = self.logo_image()
        self.assertEqual(self.upload_logo(self.admin_token, self.admin['csrf'], image)['status'], 200)
        response = self.request('/api/project', {'name': 'Reused branding', 'logo_project': '1'},
                                self.admin_token, self.admin['csrf'])
        self.assertEqual(response['status'], 200)
        with server.connect() as db:
            source = db.execute('SELECT image,mime,digest FROM project_logos WHERE project=1').fetchone()
            target = db.execute('SELECT image,mime,digest FROM project_logos WHERE project=2').fetchone()
            self.assertEqual(tuple(source), tuple(target))
        server.mutate('project-logo-remove', {'project': 1})
        with server.connect() as db:
            self.assertEqual(db.execute('SELECT image FROM project_logos WHERE project=2').fetchone()[0], image)
        self.assertEqual(self.request('/api/public-logo?project=2')['status'], 404)

    def test_missing_reused_logo_rolls_back_project_creation_and_no_logo_is_optional(self):
        self.create_host()
        for choice in ('1', '999', 'invalid'):
            response = self.request('/api/project', {'name': 'Missing logo', 'logo_project': choice},
                                    self.admin_token, self.admin['csrf'])
            self.assertEqual(response['status'], 400)
            with server.connect() as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM projects').fetchone()[0], 1)
                self.assertEqual(db.execute('SELECT COUNT(*) FROM project_logos').fetchone()[0], 0)
        response = self.request('/api/project', {'name': 'No branding', 'logo_project': ''},
                                self.admin_token, self.admin['csrf'])
        self.assertEqual(response['status'], 200)
        self.assertIsNone(next(row for row in server.snapshot()['projects'] if row['name'] == 'No branding')['logo_url'])

    def test_invalid_logo_does_not_replace_existing_logo(self):
        self.create_host()
        original = self.logo_image()
        self.upload_logo(self.admin_token, self.admin['csrf'], original)
        for data in (b'<svg></svg>', b'not an image', original[:30], b'x' * (logos.MAX_BYTES + 1)):
            response = self.upload_logo(self.admin_token, self.admin['csrf'], data)
            self.assertEqual(response['status'], 400)
        with server.connect() as db:
            self.assertEqual(db.execute('SELECT image FROM project_logos').fetchone()[0], original)

    def test_project_rename_preserves_assignments_history_and_logo(self):
        host = self.create_host()
        with patch.object(server, 'read_metric', return_value=1):
            server.poll_one(host, 1)
        image = self.logo_image()
        self.upload_logo(self.admin_token, self.admin['csrf'], image)
        response = self.request('/api/project-edit', {'project': 1, 'name': 'Renamed event'}, self.admin_token, self.admin['csrf'])
        self.assertEqual(response['status'], 200)
        state = server.snapshot()
        self.assertEqual(state['projects'][0]['name'], 'Renamed event')
        self.assertEqual(len(state['assignments']), 1)
        self.assertEqual(len(state['latest']), 1)
        self.assertIsNotNone(state['projects'][0]['logo_url'])
        backup = self.request('/api/backup', token=self.admin_token)
        restored = sqlite3.connect(':memory:')
        try:
            restored.deserialize(backup['content'])
            self.assertEqual(restored.execute('SELECT image FROM project_logos').fetchone()[0], image)
        finally:
            restored.close()
        self.assertEqual(self.request('/api/project-edit', {'project':1,'name':'Denied'}, self.viewer_token, self.viewer['csrf'])['status'], 403)

    def test_old_database_gains_logo_table_and_invalid_rename_is_atomic(self):
        self.create_host()
        server.mutate('project', {'name': 'Other event'})
        with server.connect() as db:
            db.execute('DROP TABLE project_logos')
        server.initialize()
        self.assertIsNone(server.snapshot()['projects'][0]['logo_url'])
        for name in ('   ', 'Other event'):
            response = self.request('/api/project-edit', {'project': 1, 'name': name},
                                    self.admin_token, self.admin['csrf'])
            self.assertEqual(response['status'], 400)
        self.assertEqual(server.snapshot()['projects'][0]['name'], 'Deployment')

    def test_service_pause_requires_scope_and_project_removal_is_admin_only(self):
        host = self.create_host()
        server.mutate('service', {'assignment': 1, 'name': 'Port', 'kind': 'snmp',
            'target': '.1.2.3', 'direction': 'above', 'warning': '', 'critical': ''})
        service = next(row for row in server.snapshot()['services'] if row['kind'] == 'snmp')
        token, operator = self.create_operator()
        for user_token, csrf in ((token, operator['csrf']), (self.viewer_token, self.viewer['csrf'])):
            self.assertEqual(self.request('/api/service-monitoring', {'service': service['id'], 'monitoring': False}, user_token, csrf)['status'], 403)
            self.assertEqual(self.request('/api/assignment-remove', {'assignment': 1}, user_token, csrf)['status'], 403)
        self.assertEqual(self.request('/api/service-monitoring', {'service': service['id'], 'monitoring': False}, self.admin_token, self.admin['csrf'])['status'], 200)
        self.assertEqual(self.request('/api/assignment-remove', {'assignment': 1}, self.admin_token, self.admin['csrf'])['status'], 200)

    def test_duplicate_project_copies_current_configuration_but_not_history(self):
        host = self.create_host()
        with patch.object(server, 'read_metric', return_value=1):
            server.poll_one(host, 1)
        server.mutate('service', {'assignment': 1, 'name': 'RSSI', 'kind': 'snmp',
            'target': '.1.2.3', 'direction': 'below', 'warning': '-65', 'critical': '-75',
            'units': 'dBm', 'community': 'test-community'})
        service = next(row for row in server.snapshot()['services'] if row['name'] == 'RSSI')
        server.mutate('service-monitoring', {'service': service['id'], 'monitoring': False})
        server.mutate('toggle', {'id': 1, 'field': 'notifications'})
        server.mutate('project-status-settings', {'project': 1, 'enabled': True})
        self.upload_logo(self.admin_token, self.admin['csrf'], self.logo_image())
        response = self.request('/api/project-duplicate', {'project': 1, 'name': 'Second deployment'},
                                self.admin_token, self.admin['csrf'])
        self.assertEqual(response['status'], 200)
        state = server.snapshot()
        duplicate = next(row for row in state['projects'] if row['name'] == 'Second deployment')
        assignment = next(row for row in state['assignments'] if row['project'] == duplicate['id'])
        self.assertEqual(assignment['device'], 1)
        self.assertEqual(assignment['alias'], 'Stage switch')
        self.assertEqual(assignment['notifications'], 0)
        self.assertEqual(duplicate['status_ack_enabled'], 1)
        self.assertIsNotNone(duplicate['logo_url'])
        copied = next(row for row in state['services'] if row['assignment'] == assignment['id'] and row['kind'] == 'snmp')
        self.assertEqual(copied['warning'], -65)
        self.assertEqual(copied['critical'], -75)
        self.assertEqual(copied['monitoring'], 0)
        self.assertEqual(copied['revision'], 1)
        self.assertEqual(len(state['devices']), 1)
        self.assertEqual(len(state['runs']), 1)
        self.assertEqual(state['settings']['active_run'], '1')
        with server.connect() as db:
            self.assertEqual(db.execute('SELECT community FROM services WHERE id=?', (copied['id'],)).fetchone()[0], 'test-community')
            self.assertEqual(db.execute('SELECT COUNT(*) FROM samples WHERE service=?', (copied['id'],)).fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM project_logos').fetchone()[0], 2)
        server.mutate('service-edit', {'service': service['id'], 'name': 'Changed', 'kind': 'snmp',
            'target': '.1.9', 'direction': 'below', 'warning': '-50', 'critical': '-60'})
        self.assertEqual(next(row for row in server.snapshot()['services'] if row['id'] == copied['id'])['name'], 'RSSI')

    def test_duplicate_project_rejects_duplicate_names_and_skips_archived_assignments(self):
        self.create_host()
        server.mutate('assignment-remove', {'assignment': 1})
        server.mutate('project-duplicate', {'project': 1, 'name': 'Empty copy'})
        self.assertEqual(len(server.snapshot()['assignments']), 1)
        response = self.request('/api/project-duplicate', {'project': 1, 'name': 'Deployment'},
                                self.admin_token, self.admin['csrf'])
        self.assertEqual(response['status'], 400)
        self.assertEqual(len(server.snapshot()['projects']), 2)

    def test_status_acknowledgement_requires_project_opt_in_and_operator_session(self):
        host = self.create_host()
        with patch.object(server, 'read_metric', side_effect=TimeoutError):
            server.poll_one(host, 1)
            server.poll_one(host, 1)
        incident = server.snapshot()['incident_lists']['active'][0]
        token, operator = self.create_operator()
        server.mutate('project-status-settings', {'project':1,'enabled':False})
        self.assertEqual(self.request('/api/status-ack', {'id': incident['id']}, token, operator['csrf'])['status'], 400)
        self.assertEqual(self.request('/api/project-status-settings', {'project':1,'enabled':True},
                                      self.admin_token,self.admin['csrf'])['status'], 200)
        for actor_token in (None, self.viewer_token):
            overview = json.loads(self.request('/api/status', token=actor_token)['content'])
            self.assertTrue(overview['acknowledge_enabled'])
            self.assertFalse(overview['can_acknowledge'])
            self.assertNotIn('csrf', overview)
        overview = json.loads(self.request('/api/status', token=token)['content'])
        self.assertTrue(overview['can_acknowledge'])
        self.assertEqual(overview['csrf'], operator['csrf'])
        self.assertEqual(self.request('/api/status-ack', {'id': incident['id']})['status'], 401)
        self.assertEqual(self.request('/api/status-ack', {'id': incident['id']}, self.viewer_token, self.viewer['csrf'])['status'], 403)
        self.assertEqual(self.request('/api/status-ack', {'id': incident['id']}, token)['status'], 403)
        self.assertEqual(self.request('/api/status-ack', {'id': incident['id']}, token, operator['csrf'])['status'], 200)
        self.assertEqual(server.status_overview()['incidents'], [])
        recorded = server.snapshot()['incident_lists']['acknowledged'][0]
        self.assertEqual(recorded['acknowledged_by_user_id'], operator['id'])
        self.assertEqual(recorded['acknowledged_by_username'], 'operator')

    def test_acknowledgement_actor_is_trusted_and_preserved(self):
        host = self.create_host()
        with patch.object(server, 'read_metric', side_effect=TimeoutError):
            server.poll_one(host, 1)
            server.poll_one(host, 1)
        incident = server.snapshot()['incident_lists']['active'][0]
        token, operator = self.create_operator()
        response = self.request('/api/ack', {
            'id': incident['id'], 'acknowledged_by_username': 'forged',
            'acknowledged_by_user_id': 1,
        }, token, operator['csrf'])
        self.assertEqual(response['status'], 200)
        recorded = server.snapshot()['incident_lists']['acknowledged'][0]
        self.assertEqual(recorded['acknowledged_by_user_id'], operator['id'])
        self.assertEqual(recorded['acknowledged_by_username'], 'operator')
        self.request('/api/ack', {'id': incident['id']}, self.admin_token, self.admin['csrf'])
        with server.connect() as db:
            db.execute('UPDATE users SET username=? WHERE id=?', ('renamed', operator['id']))
            db.execute('DELETE FROM users WHERE id=?', (operator['id'],))
        self.assertEqual(server.snapshot()['incident_lists']['acknowledged'][0], recorded)

    def test_legacy_acknowledgement_migration_does_not_invent_actor(self):
        with server.connect() as db:
            db.execute('ALTER TABLE incidents DROP COLUMN acknowledged_by_user_id')
            db.execute('ALTER TABLE incidents DROP COLUMN acknowledged_by_username')
            db.execute('INSERT INTO incidents(id,acknowledged) VALUES(999,123)')
            server.migrate_incident_acknowledgements(db)
            server.migrate_incident_acknowledgements(db)
            row = db.execute('SELECT * FROM incidents WHERE id=999').fetchone()
            self.assertEqual(row['acknowledged'], 123)
            self.assertIsNone(row['acknowledged_by_user_id'])
            self.assertIsNone(row['acknowledged_by_username'])

    def test_status_ack_disabling_and_hidden_hosts_are_enforced_server_side(self):
        host = self.create_host()
        with patch.object(server, 'read_metric', side_effect=TimeoutError):
            server.poll_one(host, 1)
            server.poll_one(host, 1)
        incident = server.snapshot()['incident_lists']['active'][0]
        server.mutate('project-status-settings', {'project':1,'enabled':True})
        server.mutate('toggle', {'id':1,'field':'visible'})
        self.assertEqual(self.request('/api/status-ack', {'id':incident['id']}, self.admin_token,self.admin['csrf'])['status'],400)
        server.mutate('toggle', {'id':1,'field':'visible'})
        server.mutate('project-status-settings', {'project':1,'enabled':False})
        self.assertEqual(self.request('/api/status-ack', {'id':incident['id']}, self.admin_token,self.admin['csrf'])['status'],400)
        self.assertIsNone(server.snapshot()['incident_lists']['active'][0]['acknowledged'])
        token, operator = self.create_operator()
        for action in ('project-duplicate','project-status-settings'):
            self.assertEqual(self.request('/api/'+action, {'project':1,'name':'Denied','enabled':True}, token,operator['csrf'])['status'],403)

    def test_full_name_management_and_immutable_acknowledgement(self):
        token, operator = self.create_operator()
        with server.connect() as db:
            auth.manage_user(db, 'user-edit', {
                'user': operator['id'], 'username': 'operator', 'role': 'operator',
                'full_name': '  Alex Example  ',
            }, self.admin)
            self.assertEqual(auth.public_user(db.execute('SELECT * FROM users WHERE id=?',
                (operator['id'],)).fetchone())['full_name'], 'Alex Example')
            token = auth.new_session(db, operator['id'])
            operator = auth.session_user(db, 'monitor_session=' + token)
        me = json.loads(self.request('/api/me', token=token)['content'])
        self.assertEqual(me['full_name'], 'Alex Example')
        host = self.create_host()
        with patch.object(server, 'read_metric', side_effect=TimeoutError):
            server.poll_one(host, 1)
            server.poll_one(host, 1)
        incident = server.snapshot()['incident_lists']['active'][0]
        self.assertEqual(self.request('/api/ack', {'id': incident['id'],
            'acknowledged_by_full_name': 'Forged Name'}, token, operator['csrf'])['status'], 200)
        with server.connect() as db:
            db.execute('UPDATE users SET full_name=? WHERE id=?', ('Changed Name', operator['id']))
        recorded = server.status_overview()['acknowledged_incidents'][0]
        self.assertEqual(recorded['acknowledged_by_full_name'], 'Alex Example')
        self.assertNotIn('acknowledged_by_user_id', recorded)

    def test_older_username_acknowledgements_use_later_full_name(self):
        host = self.create_host()
        with patch.object(server, 'read_metric', side_effect=TimeoutError):
            server.poll_one(host, 1)
            server.poll_one(host, 1)
        incident = server.snapshot()['incident_lists']['active'][0]
        server.mutate('ack', {'id': incident['id']}, actor={'id': 1})
        with server.connect() as db:
            db.execute('UPDATE users SET full_name=? WHERE id=1', ('Alex Admin',))
        for stored_name in ('admin', None):
            with server.connect() as db:
                db.execute('UPDATE incidents SET acknowledged_by_full_name=? WHERE id=?',
                           (stored_name, incident['id']))
            self.assertEqual(server.snapshot()['incident_lists']['acknowledged'][0]
                             ['acknowledged_by_full_name'], 'Alex Admin')
            self.assertEqual(server.status_overview()['acknowledged_incidents'][0]
                             ['acknowledged_by_full_name'], 'Alex Admin')
            with server.connect() as db:
                self.assertEqual(db.execute('SELECT acknowledged_by_full_name FROM incidents WHERE id=?',
                                            (incident['id'],)).fetchone()[0], stored_name)
        with server.connect() as db:
            db.execute('UPDATE users SET username=? WHERE id=1', ('replacement',))
        self.assertEqual(server.status_overview()['acknowledged_incidents'][0]
                         ['acknowledged_by_full_name'], 'admin')

    def test_full_name_validation_creation_and_legacy_migration(self):
        for invalid in (123, 'x' * 151):
            response = self.request('/api/user-create', {
                'username': 'named', 'role': 'viewer', 'password': 'Password-12345',
                'full_name': invalid,
            }, self.admin_token, self.admin['csrf'])
            self.assertEqual(response['status'], 400)
        response = self.request('/api/user-create', {
            'username': 'named', 'role': 'viewer', 'password': 'Password-12345',
            'full_name': 'Sam Example',
        }, self.admin_token, self.admin['csrf'])
        self.assertEqual(response['status'], 200)
        users = json.loads(self.request('/api/users', token=self.admin_token)['content'])
        self.assertEqual(next(row for row in users if row['username'] == 'named')['full_name'], 'Sam Example')
        with server.connect() as db:
            db.execute('ALTER TABLE users DROP COLUMN full_name')
            auth.ensure_accounts(db)
            self.assertEqual(db.execute('SELECT full_name FROM users WHERE id=1').fetchone()[0], '')

    def test_status_reports_only_the_callers_login_state(self):
        anonymous = json.loads(self.request('/api/status')['content'])
        self.assertIsNone(anonymous['viewer'])
        self.assertNotIn('csrf', anonymous)
        admin = json.loads(self.request('/api/status', token=self.admin_token)['content'])
        self.assertEqual(admin['viewer'], {'username':'admin','full_name':'','role':'admin','must_change_password':False})
        reader = json.loads(self.request('/api/status', token=self.viewer_token)['content'])
        self.assertEqual(reader['viewer']['username'], 'reader')
        self.assertEqual(reader['viewer']['role'], 'viewer')
        self.assertNotIn('email', reader['viewer'])
        self.assertNotIn('id', reader['viewer'])
        self.assertNotIn('password_hash', reader['viewer'])
        self.assertFalse(reader['can_acknowledge'])

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

    def test_host_unreachable_is_readable_in_saved_and_legacy_issue_displays(self):
        import subprocess
        host = self.create_host()
        self.configure_channels()
        with patch.object(server, 'read_metric', side_effect=subprocess.CalledProcessError(1, ['ping'])):
            server.poll_one(host, 1)
            server.poll_one(host, 1)
        issue = server.snapshot()['incident_lists']['active'][0]
        self.assertEqual(issue['trigger_display'], 'Host unreachable')
        self.assertEqual(issue['trigger_error'], 'CalledProcessError')
        self.assertEqual(server.status_overview()['incidents'][0]['trigger_display'], 'Host unreachable')
        with server.connect() as db:
            messages = db.execute('SELECT text FROM notification_outbox').fetchall()
            self.assertEqual(len(messages), 2)
            for message in messages:
                self.assertIn('Host unreachable', message[0])
                self.assertNotIn('CalledProcessError', message[0])
                self.assertNotIn('Triggered by', message[0])
            # Existing build-16 issues also get the friendly label without
            # rewriting their original diagnostic evidence.
            db.execute('UPDATE incidents SET trigger_display=NULL WHERE id=?', (issue['id'],))
            notifications.enqueue_incident(db, issue['id'], 'reminder:test')
            for message in db.execute("SELECT text FROM notification_outbox WHERE event='reminder:test'"):
                self.assertIn('Host unreachable', message[0])
                self.assertNotIn('CalledProcessError', message[0])
        self.assertEqual(server.status_overview()['incidents'][0]['trigger_display'], 'Host unreachable')

    def test_sample_notifications_queue_without_mutating_monitoring_history(self):
        self.create_host()
        self.configure_channels()
        with server.connect() as db:
            before = {table: db.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0]
                      for table in ('incidents', 'samples', 'runs', 'check_stability')}
        types = ('test', 'critical', 'warning', 'recovery', 'flapping', 'stable', 'host-unreachable', 'port-down')
        for sample_type in types:
            response = self.request('/api/telegram-test', {'sample_type': sample_type}, self.admin_token, self.admin['csrf'])
            self.assertEqual(response['status'], 200)
        with server.connect() as db:
            rows = db.execute('SELECT * FROM notification_outbox ORDER BY id').fetchall()
            self.assertEqual(len(rows), len(types))
            self.assertTrue(all(row['incident'] is None and row['event'] == 'test' for row in rows))
            messages = dict(zip(types, (row['text'] for row in rows)))
            self.assertTrue(messages['critical'].startswith('❌ CRITICAL'))
            self.assertIn('RSSI: -80 dBm', messages['critical'])
            self.assertTrue(messages['warning'].startswith('⚠️ WARNING'))
            self.assertIn('RSSI: -60 dBm', messages['recovery'])
            self.assertNotIn('-80', messages['recovery'])
            self.assertTrue(messages['flapping'].startswith('⚠️ FLAPPING - Sample Project'))
            self.assertNotIn('HEALTHY', messages['flapping'])
            self.assertIn('suppressed until it stabilises', messages['flapping'])
            self.assertEqual(len(messages['flapping'].splitlines()), 5)
            self.assertEqual(messages['stable'].splitlines(), [
                '✅ STABLE - Sample Project', 'Sample Host - Sample Alias',
                'RSSI: -60 dBm', 'Issue #1 - Deployment #1'])
            self.assertIn('Host unreachable', messages['host-unreachable'])
            self.assertNotIn('CalledProcessError', messages['host-unreachable'])
            self.assertIn('Port status: Port Down', messages['port-down'])
            after = {table: db.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0] for table in before}
            self.assertEqual(before, after)
        for value in ('unknown', [], None):
            self.assertEqual(self.request('/api/telegram-test', {'sample_type': value}, self.admin_token, self.admin['csrf'])['status'], 400)
        self.assertEqual(self.request('/api/telegram-test', {'sample_type': 'flapping'}, self.viewer_token, self.viewer['csrf'])['status'], 403)
        self.assertEqual(self.request('/api/telegram-test', {'sample_type': 'flapping'}, self.admin_token, 'wrong')['status'], 403)
        server.mutate('notification-pause', {'paused': True})
        self.assertEqual(self.request('/api/telegram-test', {'sample_type': 'critical'}, self.admin_token, self.admin['csrf'])['status'], 400)
        with server.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM notification_outbox').fetchone()[0], len(types))

    def test_unacknowledgement_permissions_revisions_and_actor_audit(self):
        host, issue_id, now = self.reminder_fault()
        operator_token, operator = self.create_operator()
        with server.connect() as db:
            db.execute("UPDATE users SET full_name='Operator Original' WHERE id=?", (operator['id'],))
        server.mutate('ack', {'id': issue_id}, actor=self.admin)
        issue = server.snapshot()['incident_lists']['acknowledged'][0]
        body = {'id': issue_id, 'expected_revision': issue['ack_revision'], 'acknowledged_by_user_id': 999}
        for path in ('/api/unack', '/api/status-unack'):
            self.assertEqual(self.request(path, body)['status'], 401)
            self.assertEqual(self.request(path, body, self.viewer_token, self.viewer['csrf'])['status'], 403)
            self.assertEqual(self.request(path, body, operator_token)['status'], 403)
        for value in (None, True, -1, 1.5, '1'):
            self.assertEqual(self.request('/api/unack', {**body, 'expected_revision': value}, operator_token, operator['csrf'])['status'], 400)
        self.assertEqual(self.request('/api/unack', body, operator_token, operator['csrf'])['status'], 200)
        active = server.snapshot()['incident_lists']['active'][0]
        self.assertIsNone(active['acknowledged'])
        self.assertIsNone(active['acknowledged_by_username'])
        self.assertEqual(active['acknowledgement_history'][-1]['full_name'], 'Operator Original')
        with server.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM notification_outbox').fetchone()[0], 2)
        server.mutate('ack', {'id': issue_id}, actor=self.admin)
        self.assertEqual(self.request('/api/unack', body, self.admin_token, self.admin['csrf'])['status'], 400)
        newest = server.snapshot()['incident_lists']['acknowledged'][0]
        self.assertEqual(self.request('/api/unack', {'id': issue_id, 'expected_revision': newest['ack_revision']},
                                      self.admin_token, self.admin['csrf'])['status'], 200)
        with server.connect() as db:
            events = [dict(row) for row in db.execute('SELECT * FROM incident_acknowledgement_events ORDER BY id')]
            self.assertEqual([row['action'] for row in events], ['acknowledged', 'unacknowledged', 'acknowledged', 'unacknowledged'])
            self.assertEqual(events[1]['user_id'], operator['id'])
            self.assertEqual([row['revision'] for row in events], [1, 2, 3, 4])
            auth.manage_user(db, 'user-delete', {'user': operator['id']}, self.admin)
            saved = db.execute('SELECT full_name,username FROM incident_acknowledgement_events WHERE id=?', (events[1]['id'],)).fetchone()
            self.assertEqual(tuple(saved), ('Operator Original', 'operator'))

    def test_status_unacknowledgement_opt_in_visibility_and_recovered_routing(self):
        host, issue_id, now = self.reminder_fault()
        server.mutate('ack', {'id': issue_id}, actor=self.admin)
        issue = server.snapshot()['incident_lists']['acknowledged'][0]
        body = {'id': issue_id, 'expected_revision': issue['ack_revision']}
        server.mutate('project-status-settings', {'project':1,'enabled':False})
        self.assertEqual(self.request('/api/status-unack', body, self.admin_token, self.admin['csrf'])['status'], 400)
        server.mutate('project-status-settings', {'project': 1, 'enabled': True})
        server.mutate('toggle', {'id': 1, 'field': 'visible'})
        self.assertEqual(self.request('/api/status-unack', body, self.admin_token, self.admin['csrf'])['status'], 400)
        server.mutate('toggle', {'id': 1, 'field': 'visible'})
        overview = server.status_overview()['acknowledged_incidents'][0]
        self.assertEqual(overview['ack_revision'], issue['ack_revision'])
        self.assertNotIn('acknowledgement_history', overview)
        with patch.object(server, 'read_metric', return_value=1):
            server.poll_one(host, 1)
            server.poll_one(host, 1)
        self.assertEqual(server.snapshot()['incident_lists']['acknowledged'], [])
        resolved = server.snapshot()['incident_lists']['resolved'][0]
        self.assertIsNotNone(resolved['closed'])
        self.assertEqual(resolved['acknowledged_by_username'], 'admin')
        self.assertEqual(server.status_overview()['acknowledged_incidents'], [])
        token, operator = self.create_operator()
        self.assertEqual(self.request('/api/status-unack', body, token, operator['csrf'])['status'], 200)
        data = server.snapshot()
        self.assertEqual(data['incident_lists']['active'], [])
        self.assertEqual(data['incident_lists']['acknowledged'], [])
        self.assertEqual(data['incident_lists']['resolved'][0]['id'], issue_id)
        self.assertEqual(server.status_overview()['incidents'], [])

    def test_unacknowledgement_restarts_reminders_without_replaying_pending(self):
        host, issue_id, now = self.reminder_fault()
        with patch('time.time', return_value=now), server.connect() as db:
            notifications.enqueue_incident(db, issue_id, 'reminder:old')
        with patch('time.time', return_value=now):
            server.mutate('ack', {'id': issue_id}, actor=self.admin)
            issue = server.snapshot()['incident_lists']['acknowledged'][0]
            server.mutate('unack', {'id': issue_id, 'expected_revision': issue['ack_revision']}, actor=self.admin)
        with server.connect() as db:
            self.assertTrue(all(row[0] == 'cancelled' for row in db.execute("SELECT state FROM notification_outbox WHERE event='reminder:old'")))
            with patch('time.time', return_value=now + 59):
                notifications.enqueue_reminders(db, server.host_is_up)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM notification_outbox WHERE state='pending'").fetchone()[0], 0)
            db.execute('UPDATE samples SET timestamp=? WHERE service=?', (now + 61, host['id']))
            db.execute('UPDATE check_stability SET flapping=1 WHERE service=?', (host['id'],))
            with patch('time.time', return_value=now + 61):
                notifications.enqueue_reminders(db, server.host_is_up)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM notification_outbox WHERE state='pending'").fetchone()[0], 0)
            db.execute('UPDATE check_stability SET flapping=0 WHERE service=?', (host['id'],))
            notifications.set_paused(db, True)
            with patch('time.time', return_value=now + 61):
                notifications.enqueue_reminders(db, server.host_is_up)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM notification_outbox WHERE state='pending'").fetchone()[0], 0)
            with patch('time.time', return_value=now + 61):
                notifications.set_paused(db, False)
            db.execute('UPDATE samples SET timestamp=? WHERE service=?', (now + 122, host['id']))
            with patch('time.time', return_value=now + 122):
                notifications.enqueue_reminders(db, server.host_is_up)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM notification_outbox WHERE state='pending'").fetchone()[0], 2)

    def test_ack_audit_migration_backup_and_deployment_purge(self):
        host, issue_id, now = self.reminder_fault()
        server.mutate('ack', {'id': issue_id}, actor=self.admin)
        with server.connect() as db:
            db.execute('DROP TABLE incident_acknowledgement_events')
            server.migrate_incident_acknowledgements(db)
            server.migrate_incident_acknowledgements(db)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM incident_acknowledgement_events').fetchone()[0], 1)
        backup = self.request('/api/backup', token=self.admin_token)['content']
        candidate = sqlite3.connect(':memory:')
        try:
            candidate.deserialize(backup)
            server.migrate_incident_acknowledgements(candidate)
            self.assertEqual(candidate.execute('SELECT COUNT(*) FROM incident_acknowledgement_events').fetchone()[0], 1)
        finally:
            candidate.close()
        server.mutate('pause', {})
        server.mutate('delete-deployment', {'project': 1, 'run': 1, 'expected_active_run': 0})
        with server.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM incident_acknowledgement_events').fetchone()[0], 0)

    def test_live_ack_updates_publish_after_commit_and_not_for_rejected_or_noop_actions(self):
        host, issue_id, now = self.reminder_fault()
        observed = []
        def observe_commit():
            with server.connect() as db:
                row = db.execute('SELECT acknowledged,ack_revision FROM incidents WHERE id=?', (issue_id,)).fetchone()
                observed.append(tuple(row))
        with patch.object(server.live_updates, 'publish_dashboard_change', side_effect=observe_commit):
            with patch.object(server, 'record_acknowledgement_event', side_effect=RuntimeError('Rollback')):
                with self.assertRaises(RuntimeError):
                    server.mutate('ack', {'id': issue_id}, actor=self.admin)
            self.assertEqual(observed, [])
            with server.connect() as db:
                self.assertIsNone(db.execute('SELECT acknowledged FROM incidents WHERE id=?', (issue_id,)).fetchone()[0])
            server.mutate('ack', {'id': issue_id}, actor=self.admin)
            self.assertIsNotNone(observed[0][0])
            self.assertEqual(observed[0][1], 1)
            server.mutate('ack', {'id': issue_id}, actor=self.admin)
            self.assertEqual(len(observed), 1)
            with self.assertRaises(ValueError):
                server.mutate('unack', {'id': issue_id, 'expected_revision': 0}, actor=self.admin)
            self.assertEqual(len(observed), 1)
            server.mutate('unack', {'id': issue_id, 'expected_revision': 1}, actor=self.admin)
            self.assertEqual(observed[1], (None, 2))

    def test_multiple_users_racing_ack_and_unack_keep_first_actor_and_single_event(self):
        import concurrent.futures
        import threading
        host, issue_id, now = self.reminder_fault()
        token, operator = self.create_operator()
        server.mutate('project-status-settings', {'project': 1, 'enabled': True})
        barrier = threading.Barrier(2)
        def acknowledge(actor, action):
            barrier.wait(timeout=2)
            server.mutate(action, {'id': issue_id}, actor=actor)
        with patch.object(server.live_updates, 'publish_dashboard_change') as publish:
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                first = pool.submit(acknowledge, self.admin, 'ack')
                second = pool.submit(acknowledge, operator, 'status-ack')
                first.result(timeout=5)
                second.result(timeout=5)
            self.assertEqual(publish.call_count, 1)
            with server.connect() as db:
                events = db.execute('SELECT user_id FROM incident_acknowledgement_events').fetchall()
                self.assertEqual(len(events), 1)
                saved = db.execute('SELECT acknowledged_by_user_id,ack_revision FROM incidents WHERE id=?', (issue_id,)).fetchone()
                self.assertEqual(saved[0], events[0][0])
                self.assertIn(saved[0], (self.admin['id'], operator['id']))
            barrier = threading.Barrier(2)
            def unacknowledge(actor, action):
                barrier.wait(timeout=2)
                try:
                    server.mutate(action, {'id': issue_id, 'expected_revision': 1}, actor=actor)
                    return 'changed'
                except ValueError:
                    return 'stale'
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                jobs = [pool.submit(unacknowledge, self.admin, 'unack'), pool.submit(unacknowledge, operator, 'status-unack')]
                self.assertEqual(sorted(job.result(timeout=5) for job in jobs), ['changed', 'stale'])
            self.assertEqual(publish.call_count, 2)
            with server.connect() as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM incident_acknowledgement_events').fetchone()[0], 2)


if __name__ == '__main__':
    unittest.main()
