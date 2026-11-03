"""Durable outbound Telegram and WhatsApp Business delivery, isolated from the monitoring workers."""
from . import stability

import json
import re
import time
import urllib.error
import urllib.request


def ensure_tables(db):
    db.executescript('''
        CREATE TABLE IF NOT EXISTS telegram_config (
            id INTEGER PRIMARY KEY CHECK(id=1), enabled INTEGER NOT NULL DEFAULT 0,
            bot_token TEXT NOT NULL DEFAULT '', chat_id TEXT NOT NULL DEFAULT '',
            thread_id INTEGER, recoveries INTEGER NOT NULL DEFAULT 1,
            revision INTEGER NOT NULL DEFAULT 1
        );
        INSERT OR IGNORE INTO telegram_config(id) VALUES(1);
        CREATE TABLE IF NOT EXISTS whatsapp_config (
            id INTEGER PRIMARY KEY CHECK(id=1), enabled INTEGER NOT NULL DEFAULT 0,
            bot_token TEXT NOT NULL DEFAULT '', chat_id TEXT NOT NULL DEFAULT '',
            phone_number_id TEXT NOT NULL DEFAULT '', api_version TEXT NOT NULL DEFAULT '',
            template_name TEXT NOT NULL DEFAULT '', language TEXT NOT NULL DEFAULT 'en_US',
            recipient_type TEXT NOT NULL DEFAULT 'individual',
            recoveries INTEGER NOT NULL DEFAULT 1, revision INTEGER NOT NULL DEFAULT 1
        );
        INSERT OR IGNORE INTO whatsapp_config(id) VALUES(1);
        CREATE TABLE IF NOT EXISTS notification_outbox (
            id INTEGER PRIMARY KEY AUTOINCREMENT, incident INTEGER, event TEXT NOT NULL,
            channel TEXT NOT NULL DEFAULT 'telegram',
            text TEXT NOT NULL, config_revision INTEGER NOT NULL,
            state TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0,
            next_attempt REAL NOT NULL, created REAL NOT NULL, error TEXT NOT NULL DEFAULT '',
            message_id TEXT, UNIQUE(incident,event,channel)
        );
    ''')

    db.execute("INSERT OR IGNORE INTO settings VALUES ('reminder_minutes','0')")
    db.execute("INSERT OR IGNORE INTO settings VALUES ('notifications_paused','0')")
    db.execute("INSERT OR IGNORE INTO settings VALUES ('notifications_resumed_at','0')")


def are_paused(db):
    row = db.execute("SELECT value FROM settings WHERE key='notifications_paused'").fetchone()
    return bool(row and row[0] == '1')


def set_paused(db, paused):
    """Mute delivery independently of polling; discard pending alerts, not issues."""
    if type(paused) is not bool:
        raise ValueError('Paused must be true or false')
    previous = are_paused(db)
    db.execute("INSERT OR REPLACE INTO settings VALUES ('notifications_paused',?)", (str(int(paused)),))
    if paused:
        db.execute("UPDATE notification_outbox SET state='cancelled',error='Notifications paused' WHERE state='pending'")
    elif previous:
        # Reminders restart their cadence rather than catching up after a mute.
        db.execute("INSERT OR REPLACE INTO settings VALUES ('notifications_resumed_at',?)", (str(time.time()),))


def configuration(db, channel='telegram'):
    if channel not in ('telegram', 'whatsapp'):
        raise ValueError('Unknown channel')
    return dict(db.execute(f'SELECT * FROM {channel}_config WHERE id=1').fetchone())


def public_configuration(db, channel='telegram'):
    config = configuration(db, channel)
    config['token_configured'] = bool(config.pop('bot_token'))
    return config


def save_configuration(db, body):
    old = configuration(db)
    token = (body.get('bot_token') or '').strip() or old['bot_token']
    chat = str(body.get('chat_id', '')).strip()
    thread = int(body['thread_id']) if body.get('thread_id') else None
    enabled = bool(body.get('enabled'))
    if token and not re.fullmatch(r'[0-9]+:[A-Za-z0-9_-]+', token):
        raise ValueError('Invalid bot token')
    if chat and not re.fullmatch(r'-?[0-9]+', chat):
        raise ValueError('Use the numeric group chat ID')
    if thread is not None and thread <= 0:
        raise ValueError('Invalid topic ID')
    if enabled and (not token or not chat):
        raise ValueError('Configure a bot token and chat ID before enabling')
    db.execute('''UPDATE telegram_config SET enabled=?,bot_token=?,chat_id=?,thread_id=?,
        recoveries=?,revision=revision+1 WHERE id=1''',
        (int(enabled), token, chat, thread, int(bool(body.get('recoveries', True)))))
    # Never send queued messages to a newly configured destination.
    db.execute("UPDATE notification_outbox SET state='cancelled',error='Configuration changed' WHERE state='pending' AND channel='telegram'")


def save_whatsapp(db, body):
    old = configuration(db, 'whatsapp')
    token = (body.get('bot_token') or '').strip() or old['bot_token']
    if len(token) > 8192 or any(char in token for char in '\r\n'):
        raise ValueError('Invalid access token')
    values = {key: str(body.get(key, '')).strip() for key in
              ('chat_id', 'phone_number_id', 'api_version', 'template_name', 'language', 'recipient_type')}
    enabled = bool(body.get('enabled'))
    if values['recipient_type'] not in ('individual', 'group'):
        raise ValueError('Invalid recipient type')
    if values['phone_number_id'] and not values['phone_number_id'].isdigit():
        raise ValueError('Invalid phone number ID')
    if values['api_version'] and not re.fullmatch(r'v[0-9]+\.0', values['api_version']):
        raise ValueError('Use the API version configured in your Meta app')
    if values['template_name'] and not re.fullmatch(r'[a-z0-9_]+', values['template_name']):
        raise ValueError('Invalid template name')
    if values['language'] and not re.fullmatch(r'[A-Za-z_]{2,12}', values['language']):
        raise ValueError('Invalid language')
    if values['recipient_type'] == 'individual' and values['chat_id'] and not re.fullmatch(r'[0-9]{5,20}', values['chat_id']):
        raise ValueError('Use an international phone number without +')
    if len(values['chat_id']) > 200 or any(c in values['chat_id'] for c in '\r\n'):
        raise ValueError('Invalid destination')
    if enabled and (not token or not all(values.values())):
        raise ValueError('Complete WhatsApp Business settings first')
    db.execute("""UPDATE whatsapp_config SET enabled=?,bot_token=?,chat_id=?,phone_number_id=?,
        api_version=?,template_name=?,language=?,recipient_type=?,recoveries=?,revision=revision+1 WHERE id=1""",
        (int(enabled), token, values['chat_id'], values['phone_number_id'], values['api_version'],
         values['template_name'], values['language'], values['recipient_type'], int(bool(body.get('recoveries', True)))))
    db.execute("UPDATE notification_outbox SET state='cancelled',error='Configuration changed' WHERE state='pending' AND channel='whatsapp'")


def enqueue_incident(db, incident_id, event):
    for channel in ('telegram', 'whatsapp'):
        enqueue_for_channel(db, incident_id, event, channel)


def enqueue_for_channel(db, incident_id, event, channel):
    if are_paused(db):
        return
    config = configuration(db, channel)
    if not config['enabled'] or (event == 'recovery' and not config['recoveries']):
        return
    row = db.execute('''SELECT i.*, s.name service_name,s.kind,s.units,s.value_type,
        a.alias,a.notifications,d.name device_name,p.name project_name
        FROM incidents i JOIN services s ON s.id=i.service
        JOIN assignments a ON a.id=s.assignment JOIN devices d ON d.id=a.device
        JOIN projects p ON p.id=a.project WHERE i.id=?''', (incident_id,)).fetchone()
    if not row or not row['notifications']:
        return
    runtime = db.execute('SELECT * FROM check_stability WHERE run=? AND service=?',
                         (row['run'], row['service'])).fetchone()
    flap_event = event.startswith(('flap-start:', 'flap-stable:'))
    if runtime and runtime['flapping'] and not flap_event:
        return
    reading = db.execute('SELECT value,display_value FROM samples WHERE service=? AND run=? ORDER BY id DESC LIMIT 1',
                         (row['service'], row['run'])).fetchone()
    value = (reading['display_value'] or str(reading['value'])) if reading and reading['value'] is not None else 'No reading'
    units = row['units'] if row['value_type'] == 'metric' else ''
    if event == 'opened' and row['trigger_timestamp'] is not None:
        value = row['trigger_display'] if row['trigger_value'] is not None else 'No usable reading (' + (row['trigger_error'] or 'Unavailable') + ')'
        units = row['trigger_units'] or ''
    title = 'RECOVERED' if event == 'recovery' else row['status'].upper()
    if event.startswith('reminder:'):
        title = 'REMINDER · ' + title
    icons = {'warning': '⚠️', 'critical': '❌', 'unreachable': '❌'}
    icon = '✅' if event == 'recovery' else icons.get(row['status'], 'ℹ️')
    if flap_event:
        title = ('FLAPPING' if event.startswith('flap-start:') else 'STABLE') + ' · ' + (runtime['confirmed'] or 'unknown').upper()
        icon = '⚠️' if runtime['flapping'] else '✅' if runtime['confirmed'] == 'healthy' else icons.get(runtime['confirmed'], 'ℹ️')
    title = f'{icon} {title}'
    text = (f"{title} · {row['project_name']}\n{row['device_name']} - {row['alias']}\n"
            f"{row['service_name']}: {value} {units}\nIssue #{row['number']} · Deployment #{row['run']}")
    if event != 'opened' and row['trigger_timestamp'] is not None:
        cause = (str(row['trigger_display'] or row['trigger_value']) + ' ' + (row['trigger_units'] or '')
                 if row['trigger_value'] is not None else 'No usable reading (' + (row['trigger_error'] or 'Unavailable') + ')')
        text += '\nTriggered by: ' + cause.strip()
    db.execute('''INSERT OR IGNORE INTO notification_outbox
        (incident,event,channel,text,config_revision,next_attempt,created) VALUES(?,?,?,?,?,?,?)''',
        (incident_id, event, channel, text[:3500], config['revision'], time.time(), time.time()))


def enqueue_flap_event(db, service_id, run, event):
    """Use the latest issue as a durable outbox anchor for this check episode."""
    db.execute("""UPDATE notification_outbox SET state='cancelled',error='Check is flapping'
        WHERE state='pending' AND incident IN (SELECT id FROM incidents WHERE service=? AND run=?)""",
        (service_id, run))
    issue = db.execute('SELECT id FROM incidents WHERE service=? AND run=? ORDER BY id DESC LIMIT 1',
                       (service_id, run)).fetchone()
    if issue:
        enqueue_incident(db, issue['id'], event)


def reminder_interval(db):
    row = db.execute("SELECT value FROM settings WHERE key='reminder_minutes'").fetchone()
    try:
        minutes = int(row[0]) if row else 0
        return minutes * 60 if 0 <= minutes <= 10080 else 0
    except (ValueError, TypeError):
        return 0


def reminder_source(db, incident_id):
    return db.execute("""SELECT i.*,s.kind,s.assignment,s.enabled,
        s.monitoring service_monitoring,s.revision,s.monitoring_since,d.address,
        a.monitoring,a.notifications,a.removed
        FROM incidents i JOIN services s ON s.id=i.service
        JOIN assignments a ON a.id=s.assignment JOIN devices d ON d.id=a.device
        WHERE i.id=?""", (incident_id,)).fetchone()


def reminder_eligible(db, source, host_is_up):
    """Require an open, unacknowledged fault backed by a fresh current reading."""
    run = int(db.execute("SELECT value FROM settings WHERE key='active_run'").fetchone()[0])
    if (not source or source['run'] != run or source['closed'] is not None
            or source['acknowledged'] is not None or source['removed']
            or not source['notifications'] or not source['monitoring']
            or not source['enabled'] or not source['service_monitoring']):
        return False
    runtime = stability.state_for(db, run, source['service'], source['revision'], source['monitoring_since'])
    if runtime and runtime['flapping']:
        return False
    reading = db.execute("""SELECT status,timestamp FROM samples WHERE service=? AND run=?
        AND revision=? AND timestamp>=? ORDER BY id DESC LIMIT 1""",
        (source['service'], run, source['revision'], source['monitoring_since'])).fetchone()
    if (not reading or time.time() - reading['timestamp'] > 60
            or reading['status'] != source['status']):
        return False
    return source['kind'] == 'ping' or host_is_up(db, source, run)


def enqueue_reminders(db, host_is_up):
    """Durable per-channel cadence; never accumulate reminders behind a retry.

    The outbox is also the schedule ledger, so restarts cannot duplicate a due
    reminder. Queue at most one per channel per issue, without catch-up bursts.
    """
    interval = reminder_interval(db)
    if not interval or are_paused(db):
        return
    now = time.time()
    resumed = db.execute("SELECT value FROM settings WHERE key='notifications_resumed_at'").fetchone()
    resumed_at = float(resumed[0]) if resumed else 0
    candidates = db.execute("""SELECT id FROM incidents WHERE closed IS NULL AND acknowledged IS NULL
        AND run=CAST((SELECT value FROM settings WHERE key='active_run') AS INTEGER)""").fetchall()
    for candidate in candidates:
        source = reminder_source(db, candidate['id'])
        if not reminder_eligible(db, source, host_is_up):
            continue
        for channel in ('telegram', 'whatsapp'):
            if not configuration(db, channel)['enabled']:
                continue
            pending = db.execute("""SELECT 1 FROM notification_outbox WHERE incident=? AND channel=?
                AND state IN ('pending','sending') AND (event='opened' OR event LIKE 'reminder:%' OR event LIKE 'flap-stable:%')""",
                (source['id'], channel)).fetchone()
            if pending:
                continue
            last = db.execute("""SELECT MAX(CASE WHEN state='sent' THEN next_attempt ELSE created END)
                FROM notification_outbox WHERE incident=? AND channel=?
                AND (event='opened' OR event LIKE 'reminder:%' OR event LIKE 'flap-stable:%')""", (source['id'], channel)).fetchone()[0]
            if now - max(source['opened'], last or source['opened'], resumed_at) >= interval:
                enqueue_for_channel(db, source['id'], f'reminder:{int(now)}', channel)


def enqueue_test(db, channel='telegram'):
    if are_paused(db):
        raise ValueError('Resume notifications before sending a test')
    config = configuration(db, channel)
    if not config['enabled']:
        raise ValueError('Enable the notification channel first')
    db.execute('''INSERT INTO notification_outbox
        (event,channel,text,config_revision,next_attempt,created) VALUES('test',?,?,?,?,?)''',
        (channel, 'TEST · Network Monitor\nNotification test\nThis destination is configured for issue alerts.',
         config['revision'], time.time(), time.time()))


def retry_failed(db, channel):
    if are_paused(db):
        raise ValueError('Resume notifications before retrying messages')
    config = configuration(db, channel)
    if not config['enabled']:
        raise ValueError('Enable the notification channel first')
    db.execute("""UPDATE notification_outbox SET state='pending',attempts=0,
        next_attempt=?,error='' WHERE state='failed' AND channel=? AND config_revision=?""",
        (time.time(), channel, config['revision']))


def telegram_chats(db):
    """Discover group IDs from recent bot updates without returning message content."""
    config = configuration(db)
    if not config['bot_token']:
        raise ValueError('Save a bot token first')
    request = urllib.request.Request(
        'https://api.telegram.org/bot' + config['bot_token'] + '/getUpdates',
        data=json.dumps({'timeout': 0, 'limit': 100}).encode(),
        headers={'Content-Type': 'application/json'}, method='POST')
    with urllib.request.urlopen(request, timeout=10) as response:
        result = json.loads(response.read(1024 * 1024))
    if not result.get('ok'):
        raise ValueError('Could not retrieve bot updates')
    chats = {}
    for update in result.get('result', []):
        message = update.get('message') or update.get('my_chat_member') or update.get('channel_post') or {}
        chat = message.get('chat', {})
        if chat.get('type') in ('group', 'supergroup', 'channel'):
            chats[str(chat['id'])] = {'id': str(chat['id']), 'title': chat.get('title', str(chat['id']))}
    return list(chats.values())


def send_message(config, text):
    body = {'chat_id': config['chat_id'], 'text': text}
    if config['thread_id']:
        body['message_thread_id'] = config['thread_id']
    request = urllib.request.Request(
        'https://api.telegram.org/bot' + config['bot_token'] + '/sendMessage',
        data=json.dumps(body).encode(), headers={'Content-Type': 'application/json'}, method='POST')
    # Do not log request URLs: Telegram embeds the token in the URL.
    with urllib.request.urlopen(request, timeout=10) as response:
        result = json.loads(response.read(65536))
    if not result.get('ok'):
        raise ValueError('Telegram rejected message')
    return str(result['result']['message_id'])


def send_whatsapp(config, text):
    # Approved template body must have three positional text parameters:
    # device/service, status/project, details. No free-form session window needed.
    lines = text.split('\n')
    parameters = [lines[1] if len(lines) > 1 else 'Network Monitor', lines[0], ' '.join(lines[2:]) or 'Notification']
    body = {'messaging_product': 'whatsapp', 'recipient_type': config['recipient_type'],
        'to': config['chat_id'], 'type': 'template', 'template': {
            'name': config['template_name'], 'language': {'code': config['language']},
            'components': [{'type': 'body', 'parameters': [
                {'type': 'text', 'text': value[:1000]} for value in parameters]}]}}
    request = urllib.request.Request(
        f"https://graph.facebook.com/{config['api_version']}/{config['phone_number_id']}/messages",
        data=json.dumps(body).encode(), headers={'Content-Type': 'application/json',
            'Authorization': 'Bearer ' + config['bot_token']}, method='POST')
    with urllib.request.urlopen(request, timeout=10) as response:
        result = json.loads(response.read(65536))
    return str(result['messages'][0]['id'])


def deliver_once(connect, lock, host_is_up):
    with lock, connect() as db:
        row = db.execute("SELECT * FROM notification_outbox WHERE state='pending' AND next_attempt<=? ORDER BY id LIMIT 1", (time.time(),)).fetchone()
        if row is None:
            return False
        config = configuration(db, row['channel'])
        reason = 'Notifications paused' if are_paused(db) else ''
        if not config['enabled'] or row['config_revision'] != config['revision']:
            reason = 'Notifications disabled or configuration changed'
        if row['incident'] is not None:
            source = db.execute('''SELECT i.*,s.kind,s.assignment,s.enabled,s.monitoring service_monitoring,s.revision,s.monitoring_since,d.address,a.monitoring,a.notifications
                FROM incidents i JOIN services s ON s.id=i.service
                JOIN assignments a ON a.id=s.assignment JOIN devices d ON d.id=a.device
                WHERE i.id=?''', (row['incident'],)).fetchone()
            run = int(db.execute("SELECT value FROM settings WHERE key='active_run'").fetchone()[0])
            if not source or source['run'] != run or not source['notifications'] or not source['monitoring'] or not source['enabled'] or not source['service_monitoring']:
                reason = 'Source removed, inactive, or muted'
            elif row['event'] == 'opened' and source['closed']:
                reason = 'Issue already resolved'
            elif source['kind'] != 'ping' and not host_is_up(db, source, run):
                reason = 'Suppressed by host dependency'
            if source:
                runtime = stability.state_for(db, source['run'], source['service'], source['revision'], source['monitoring_since'])
                if row['event'].startswith(('flap-start:', 'flap-stable:')):
                    if not stability.event_is_current(runtime, row['event'], time.time()):
                        reason = 'Flap episode is no longer current'
                elif runtime and runtime['flapping']:
                    reason = 'Check is flapping'
        if row['event'].startswith('reminder:') and (
                not reminder_interval(db) or not reminder_eligible(db, reminder_source(db, row['incident']), host_is_up)):
            reason = 'Reminder disabled, acknowledged, recovered, paused, or suppressed'
        if reason:
            db.execute("UPDATE notification_outbox SET state='cancelled',error=? WHERE id=?", (reason, row['id']))
            return True
        db.execute("UPDATE notification_outbox SET state='sending',attempts=attempts+1 WHERE id=?", (row['id'],))
    try:
        message_id = (send_whatsapp(config, row['text']) if row['channel'] == 'whatsapp'
                      else send_message(config, row['text']))
        state, error, delay = 'sent', '', 0
    except Exception as exc:
        # Keep errors useful without leaking tokens, response bodies, or URLs.
        code = exc.code if isinstance(exc, urllib.error.HTTPError) else None
        error = 'HTTP ' + str(code) if code else type(exc).__name__
        retry = code is None or code == 429 or code >= 500
        state = 'pending' if retry and row['attempts'] < 4 else 'failed'
        delay = min(300, 15 * 2 ** row['attempts'])
    with lock, connect() as db:
        db.execute("UPDATE notification_outbox SET state=?,error=?,next_attempt=?,message_id=? WHERE id=? AND state='sending'",
                   (state, error, time.time() + delay, message_id if state == 'sent' else None, row['id']))
    return True


def worker(connect, lock, host_is_up):
    with connect() as db:
        db.execute("UPDATE notification_outbox SET state='pending' WHERE state='sending'")
    while True:
        try:
            with lock, connect() as db:
                enqueue_reminders(db, host_is_up)
            deliver_once(connect, lock, host_is_up)
        except Exception:
            print('Notification queue processing failed', flush=True)
        time.sleep(2)
