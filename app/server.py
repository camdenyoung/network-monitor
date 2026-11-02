"""Small local monitor: durable SQLite state, bounded polling, and a local web UI.

Local accounts protect configuration; a separate public status view exposes
only the active project and selected current readings.
"""
import concurrent.futures
import json
import ipaddress
import math
import os
import platform
from pathlib import Path
import socket
import sqlite3
import struct
import subprocess
import threading
import time
import hmac
from . import auth, notifications
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DATA = Path(os.environ.get('MONITOR_DATA', './data'))
DATA.mkdir(parents=True, exist_ok=True)
DB = DATA / 'monitor.sqlite3'
LOCK = threading.RLock()


class DatabaseConnection(sqlite3.Connection):
    """Commit/rollback and close: sqlite3's default context manager does not close."""

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


def connect():
    db = sqlite3.connect(DB, timeout=20, factory=DatabaseConnection)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    return db


def initialize():
    with connect() as db:
        db.executescript('''
            CREATE TABLE IF NOT EXISTS projects (
                id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE);
            CREATE TABLE IF NOT EXISTS devices (
                id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE,
                model TEXT NOT NULL DEFAULT '', address TEXT NOT NULL DEFAULT '');
            CREATE TABLE IF NOT EXISTS assignments (
                id INTEGER PRIMARY KEY, project INTEGER REFERENCES projects(id),
                device INTEGER REFERENCES devices(id), alias TEXT NOT NULL,
                monitoring INTEGER DEFAULT 1,
                visible INTEGER DEFAULT 1, notifications INTEGER DEFAULT 1,
                UNIQUE(project, device));
            CREATE TABLE IF NOT EXISTS services (
                id INTEGER PRIMARY KEY, assignment INTEGER REFERENCES assignments(id),
                name TEXT NOT NULL, kind TEXT NOT NULL, target TEXT NOT NULL,
                community TEXT DEFAULT 'public', unit INTEGER DEFAULT 1,
                scale REAL DEFAULT 1, units TEXT DEFAULT '', direction TEXT DEFAULT 'below',
                warning REAL, critical REAL, persistence INTEGER DEFAULT 2,
                enabled INTEGER NOT NULL DEFAULT 1, revision INTEGER NOT NULL DEFAULT 1);
            CREATE TABLE IF NOT EXISTS runs (
                id INTEGER PRIMARY KEY, project INTEGER REFERENCES projects(id), started REAL);
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS samples (
                id INTEGER PRIMARY KEY, run INTEGER, service INTEGER,
                timestamp REAL, value REAL, status TEXT, error TEXT, revision INTEGER NOT NULL DEFAULT 1);
            CREATE INDEX IF NOT EXISTS sample_lookup ON samples(service, timestamp);
            CREATE TABLE IF NOT EXISTS incidents (
                id INTEGER PRIMARY KEY, run INTEGER, service INTEGER,
                opened REAL, closed REAL, status TEXT, acknowledged REAL);
        ''')
        db.execute("INSERT OR IGNORE INTO settings VALUES ('retention_days','30')")
        db.execute("INSERT OR IGNORE INTO settings VALUES ('active_run','0')")
        migrate_inventory_addresses(db)
        migrate_service_lifecycle(db)
        ensure_service_library(db)
        migrate_value_types(db)
        ensure_host_checks(db)
        notifications.ensure_tables(db)
        auth.ensure_accounts(db, DB.with_name('initial-admin-password.txt'),
                             os.environ.get('MONITOR_ADMIN_PASSWORD'))


def migrate_inventory_addresses(db):
    """Move legacy project addresses onto equipment without guessing conflicts.

    Preserve all old values for review. If projects disagree on an address, leave
    the device unconfigured until the operator chooses its correct inventory IP.
    This migration runs at startup and when restoring an older backup.
    """
    columns = {row[1] for row in db.execute('PRAGMA table_info(devices)')}
    if 'address' not in columns:
        db.execute("ALTER TABLE devices ADD COLUMN address TEXT NOT NULL DEFAULT ''")
    db.execute("""
        CREATE TABLE IF NOT EXISTS legacy_assignment_addresses (
            assignment INTEGER PRIMARY KEY, device INTEGER, address TEXT NOT NULL
        )
    """)
    assignment_columns = {row[1] for row in db.execute('PRAGMA table_info(assignments)')}
    if 'address' not in assignment_columns:
        return
    db.execute("""
        INSERT OR IGNORE INTO legacy_assignment_addresses
        SELECT id, device, address FROM assignments
    """)
    db.execute("""
        UPDATE devices SET address=(
            SELECT MIN(TRIM(a.address)) FROM assignments a
            WHERE a.device=devices.id AND TRIM(a.address)!=''
        ) WHERE address='' AND (
            SELECT COUNT(DISTINCT TRIM(a.address)) FROM assignments a
            WHERE a.device=devices.id AND TRIM(a.address)!=''
        )=1
    """)
    db.execute('ALTER TABLE assignments DROP COLUMN address')


def inventory_address(value):
    """Inventory records require an IPv4 or IPv6 literal, not command options."""
    return str(ipaddress.ip_address(value.strip()))


def migrate_service_lifecycle(db):
    """Keep removed service ownership so deleting equipment can purge its history."""
    columns = {row[1] for row in db.execute('PRAGMA table_info(services)')}
    if 'enabled' not in columns:
        db.execute('ALTER TABLE services ADD COLUMN enabled INTEGER NOT NULL DEFAULT 1')
    if 'revision' not in columns:
        db.execute('ALTER TABLE services ADD COLUMN revision INTEGER NOT NULL DEFAULT 1')
    sample_columns = {row[1] for row in db.execute('PRAGMA table_info(samples)')}
    if 'revision' not in sample_columns:
        db.execute('ALTER TABLE samples ADD COLUMN revision INTEGER NOT NULL DEFAULT 1')
    # Remember IDs before deletion, so delayed polling cannot attach to a new item.
    for table in ('devices', 'assignments', 'services'):
        maximum = db.execute(f'SELECT COALESCE(MAX(id), 0) FROM {table}').fetchone()[0]
        db.execute('INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)',
                   ('last_id_' + table, str(maximum)))
        previous = int(setting(db, 'last_id_' + table))
        db.execute('UPDATE settings SET value=? WHERE key=?',
                   (str(max(maximum, previous)), 'last_id_' + table))


def ensure_service_library(db):
    """Library entries are standalone configurations, never linked live to hosts."""
    db.execute("""
        CREATE TABLE IF NOT EXISTS service_templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE, kind TEXT NOT NULL, target TEXT NOT NULL,
            community TEXT NOT NULL DEFAULT 'public', unit INTEGER NOT NULL DEFAULT 1,
            scale REAL NOT NULL DEFAULT 1, units TEXT NOT NULL DEFAULT '',
            direction TEXT NOT NULL DEFAULT 'below', warning REAL, critical REAL,
            persistence INTEGER NOT NULL DEFAULT 2
        )
    """)


def migrate_value_types(db):
    """Defaults keep existing services/templates as ordinary numeric metrics."""
    for table in ('services', 'service_templates'):
        columns = {row[1] for row in db.execute(f'PRAGMA table_info({table})')}
        if 'value_type' not in columns:
            db.execute(f"ALTER TABLE {table} ADD COLUMN value_type TEXT NOT NULL DEFAULT 'metric'")
        if 'state_map' not in columns:
            db.execute(f"ALTER TABLE {table} ADD COLUMN state_map TEXT NOT NULL DEFAULT '{{}}'")
    if 'display_value' not in {row[1] for row in db.execute('PRAGMA table_info(samples)')}:
        db.execute('ALTER TABLE samples ADD COLUMN display_value TEXT')


def state_key(value):
    number = float(value)
    if not math.isfinite(number):
        raise ValueError('State numbers must be finite')
    return str(int(number)) if number.is_integer() else str(number)


def state_definition(service, value):
    mapping = service['state_map']
    if isinstance(mapping, str):
        mapping = json.loads(mapping)
    return mapping.get(state_key(value))


def display_value(service, value):
    if value is None:
        return None
    if service['value_type'] == 'state':
        definition = state_definition(service, value)
        return definition['label'] if definition else f'Unmapped state ({state_key(value)})'
    return str(value)


def next_record_id(db, table):
    """Allocate a durable ID even after the highest existing record is deleted."""
    if table not in ('devices', 'assignments', 'services'):
        raise ValueError('Unsupported record type')
    maximum = db.execute(f'SELECT COALESCE(MAX(id), 0) FROM {table}').fetchone()[0]
    value = max(maximum, int(setting(db, 'last_id_' + table))) + 1
    db.execute('UPDATE settings SET value=? WHERE key=?',
               (str(value), 'last_id_' + table))
    return value


def ensure_host_checks(db):
    """Create built-in ping checks for new, upgraded, and restored assignments."""
    missing = db.execute("""
        SELECT a.id FROM assignments a WHERE NOT EXISTS (
            SELECT 1 FROM services s WHERE s.assignment=a.id AND s.kind='ping'
        )
    """).fetchall()
    for assignment in missing:
        db.execute("""
            INSERT INTO services (id, assignment, name, kind, target)
            VALUES (?, ?, 'Host ping', 'ping', '')
        """, (next_record_id(db, 'services'), assignment[0]))


def device_details(body):
    """Validate editable inventory fields before writing any of them."""
    name = body['name'].strip()
    model = body.get('model', '').strip()
    if not name or len(name) > 100 or len(model) > 100:
        raise ValueError('Invalid device name or model')
    return name, model, inventory_address(body['address'])


def delete_device(db, device_id):
    """Purge a device and all its related data in the caller's transaction.

    Runs and projects are shared with other equipment and must survive deletion.
    Disabled services retain their ownership until this point, so their old
    readings and incidents are removed along with currently monitored services.
    """
    if not db.execute('SELECT id FROM devices WHERE id=?', (device_id,)).fetchone():
        raise ValueError('Unknown device')
    service_ids = [row[0] for row in db.execute("""
        SELECT s.id FROM services s
        JOIN assignments a ON a.id=s.assignment WHERE a.device=?
    """, (device_id,))]
    for service_id in service_ids:
        db.execute('DELETE FROM notification_outbox WHERE incident IN (SELECT id FROM incidents WHERE service=?)', (service_id,))
        db.execute('DELETE FROM samples WHERE service=?', (service_id,))
        db.execute('DELETE FROM incidents WHERE service=?', (service_id,))
        db.execute('DELETE FROM services WHERE id=?', (service_id,))
    db.execute('DELETE FROM legacy_assignment_addresses WHERE device=?', (device_id,))
    db.execute('DELETE FROM assignments WHERE device=?', (device_id,))
    db.execute('DELETE FROM devices WHERE id=?', (device_id,))


def setting(db, key):
    return db.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()[0]


def classify(value, service):
    """Critical takes precedence; null thresholds mean that check is disabled."""
    if service['value_type'] == 'state':
        definition = state_definition(service, value)
        return definition['status'] if definition else 'warning'
    for level in ('critical', 'warning'):
        limit = service[level]
        if limit is not None:
            if service['direction'] == 'below' and value < limit:
                return level
            if service['direction'] == 'above' and value > limit:
                return level
    return 'healthy'


def receive_exact(sock, length):
    result = b''
    while len(result) < length:
        block = sock.recv(length - len(result))
        if not block:
            raise ValueError('Incomplete Modbus response')
        result += block
    return result


def read_metric(service):
    """Read one explicit metric. TCP is reachability of a port, not ICMP ping."""
    host = service['address']
    if service['kind'] == 'ping':
        # Use a subprocess deadline as well as ping's platform-specific timeout.
        # Reject option-like addresses; no shell is involved in any polling call.
        if not host or host.startswith('-'):
            raise ValueError('Invalid ping address')
        wait = '2000' if platform.system() == 'Darwin' else '2'
        subprocess.run(
            ['ping', '-n', '-c', '1', '-W', wait, host],
            capture_output=True, timeout=3, check=True,
        )
        return 1.0
    if service['kind'] == 'tcp':
        with socket.create_connection((host, int(service['target'])), timeout=2):
            return 1.0
    if service['kind'] == 'snmp':
        result = subprocess.run(
            ['snmpget', '-v2c', '-c', service['community'], '-t', '2', '-r', '0',
             '-Oeqv', '--', host, service['target']],
            capture_output=True, text=True, timeout=4, check=True,
        )
        # Request enum codes numerically so states such as up(1) parse as 1.
        # Counters remain raw values, not rates.
        value = float(result.stdout.strip().split()[0])
    elif service['kind'] == 'modbus':
        register = int(service['target'])
        unit = service['unit']
        request = struct.pack('>HHHBBHH', 1, 0, 6, unit, 3, register, 1)
        with socket.create_connection((host, 502), timeout=2) as sock:
            sock.settimeout(2)
            sock.sendall(request)
            header = receive_exact(sock, 7)
            transaction, protocol, length, response_unit = struct.unpack('>HHHB', header)
            if (transaction, protocol, response_unit) != (1, 0, unit) or length != 5:
                raise ValueError('Unexpected Modbus response header')
            response = receive_exact(sock, length - 1)
            if response[:2] != b'\x03\x02':
                raise ValueError('Unexpected Modbus response function')
            value = struct.unpack('>H', response[2:])[0]
    else:
        raise ValueError('Unsupported protocol')
    value *= service['scale']
    if not math.isfinite(value):
        raise ValueError('Non-finite reading')
    return value


def host_is_up(db, service, run):
    """Require a recent successful ping for this deployment and current address."""
    host = db.execute("""
        SELECT samples.status, samples.timestamp FROM samples
        JOIN services ping ON ping.id=samples.service
        JOIN assignments a ON a.id=ping.assignment
        JOIN devices d ON d.id=a.device
        WHERE ping.assignment=? AND ping.kind='ping' AND samples.run=?
          AND samples.revision=ping.revision AND d.address=?
        ORDER BY samples.id DESC LIMIT 1
    """, (service['assignment'], run, service['address'])).fetchone()
    return bool(host and host['status'] == 'healthy' and time.time() - host['timestamp'] <= 60)


def poll_one(service, run):
    with LOCK, connect() as db:
        blocked = service['kind'] != 'ping' and not host_is_up(db, service, run)
    try:
        if blocked:
            value, status, error = None, 'blocked', 'Host unavailable'
        else:
            value = read_metric(service)
            status, error = classify(value, service), ''
    except Exception as exc:
        value, status = None, 'unreachable'
        # subprocess exceptions include command-line credentials; never persist them.
        error = type(exc).__name__
    with LOCK, connect() as db:
        # Discard in-flight results when the operator changes projects or restores.
        if setting(db, 'active_run') != str(run):
            return
        current = db.execute("""
            SELECT d.address, s.revision FROM services s
            JOIN assignments a ON a.id=s.assignment
            JOIN devices d ON d.id=a.device
            JOIN runs r ON r.project=a.project
            WHERE s.id=? AND r.id=? AND a.monitoring=1 AND s.enabled=1
        """, (service['id'], run)).fetchone()
        # Ignore reads made against an old address while an inventory edit was saved.
        if (current is None or current['address'] != service['address']
                or current['revision'] != service['revision']):
            return
        # Recheck after network I/O so a concurrent host failure cannot create
        # a child incident from a reading that completed after the failed ping.
        if service['kind'] != 'ping' and not host_is_up(db, service, run):
            value, status, error = None, 'blocked', 'Host unavailable'
        db.execute('''INSERT INTO samples
            (run,service,timestamp,value,status,error,revision,display_value)
            VALUES(?,?,?,?,?,?,?,?)''',
            (run, service['id'], time.time(), value, status, error,
             service['revision'], display_value(service, value)))
        if status == 'blocked':
            # Preserve existing incidents without claiming recovery; blocked samples
            # break persistence streaks before services resume after host recovery.
            return
        recent = db.execute('SELECT status FROM samples WHERE service=? AND run=? AND revision=? ORDER BY id DESC LIMIT ?',
                            (service['id'], run, service['revision'], service['persistence'])).fetchall()
        confirmed = len(recent) == service['persistence'] and all(row[0] == status for row in recent)
        if not confirmed:
            return
        incident = db.execute('SELECT * FROM incidents WHERE service=? AND run=? AND closed IS NULL',
                              (service['id'], run)).fetchone()
        if incident and (status == 'healthy' or incident['status'] != status):
            db.execute('UPDATE incidents SET closed=? WHERE id=?', (time.time(), incident['id']))
            if status == 'healthy':
                notifications.enqueue_incident(db, incident['id'], 'recovery')
            incident = None
        if status != 'healthy' and incident is None:
            cursor = db.execute('INSERT INTO incidents(run,service,opened,status) VALUES(?,?,?,?)',
                                (run, service['id'], time.time(), status))
            notifications.enqueue_incident(db, cursor.lastrowid, 'opened')


def poll_host(services, run):
    """Complete the host ping before its children, while hosts run concurrently."""
    ping = next((service for service in services if service['kind'] == 'ping'), None)
    if ping:
        poll_one(ping, run)
    for service in services:
        if service['kind'] != 'ping':
            poll_one(service, run)


def poll_loop():
    with concurrent.futures.ThreadPoolExecutor(max_workers=24) as pool:
        while True:
            try:
                with LOCK, connect() as db:
                    run = int(setting(db, 'active_run'))
                    services = [dict(row) for row in db.execute('''
                        SELECT s.*, d.address FROM services s
                        JOIN assignments a ON a.id=s.assignment
                        JOIN devices d ON d.id=a.device
                        JOIN runs r ON r.project=a.project
                        WHERE r.id=? AND a.monitoring=1 AND s.enabled=1 AND d.address!='' ''', (run,))]
                    cutoff = time.time() - int(setting(db, 'retention_days')) * 86400
                    db.execute('DELETE FROM samples WHERE timestamp<?', (cutoff,))
                hosts = {}
                for service in services:
                    hosts.setdefault(service['assignment'], []).append(service)
                list(pool.map(lambda group: poll_host(group, run), hosts.values()))
            except Exception:
                # Keep the scheduler alive; no credentials or raw command lines in logs.
                print('Polling cycle failed', flush=True)
            time.sleep(15)


def snapshot():
    with LOCK, connect() as db:
        result = {table: [dict(row) for row in db.execute('SELECT * FROM ' + table)]
                  for table in ('projects', 'devices', 'assignments', 'runs')}
        result['legacy_addresses'] = [dict(row) for row in db.execute(
            'SELECT * FROM legacy_assignment_addresses')]
        # Never send SNMP communities to the browser in the general state response.
        result['services'] = [dict(row) for row in db.execute('''
            SELECT id,assignment,name,kind,target,unit,scale,units,direction,warning,critical,persistence,enabled,revision,value_type,state_map
            FROM services''')]
        result['service_templates'] = [dict(row) for row in db.execute('''
            SELECT id,name,kind,target,unit,scale,units,direction,warning,critical,persistence,value_type,state_map
            FROM service_templates ORDER BY name
        ''')]
        for configuration in result['services'] + result['service_templates']:
            configuration['state_map'] = json.loads(configuration['state_map'])
        result['settings'] = dict(db.execute('SELECT key,value FROM settings'))
        result['latest'] = [dict(row) for row in db.execute('''
            SELECT s.* FROM samples s JOIN (
            SELECT samples.service, MAX(samples.id) id FROM samples
            JOIN services ON services.id=samples.service
            WHERE run=? AND samples.revision=services.revision GROUP BY samples.service) latest ON s.id=latest.id''',
            (int(result['settings']['active_run']),))]
        result['incidents'] = [dict(row) for row in db.execute(
            'SELECT * FROM incidents ORDER BY id DESC LIMIT 200')]
        # Split by acknowledgement independently of recovery: acknowledged incidents
        # remain in that list after recovery, with their recovery time visible.
        run = int(result['settings']['active_run'])
        predicates = {
            'active': 'closed IS NULL AND acknowledged IS NULL',
            'acknowledged': 'acknowledged IS NOT NULL',
            'resolved': 'closed IS NOT NULL AND acknowledged IS NULL',
        }
        result['incident_lists'] = {}
        for category, predicate in predicates.items():
            limit = '' if category == 'active' else ' LIMIT 200'
            result['incident_lists'][category] = [dict(row) for row in db.execute(
                f'SELECT * FROM incidents WHERE run=? AND {predicate} ORDER BY id DESC{limit}',
                (run,))]
        result['incident_lists']['suppressed'] = []
        configurations = {row['id']: row for row in db.execute('''
            SELECT s.*, d.address FROM services s
            JOIN assignments a ON a.id=s.assignment JOIN devices d ON d.id=a.device
        ''')}
        latest = {row['service']: row for row in result['latest']}
        for category in ('active', 'acknowledged'):
            visible = []
            for incident in result['incident_lists'][category]:
                service = configurations.get(incident['service'])
                reading = latest.get(incident['service'])
                suppressed = (not incident['closed'] and service is not None
                    and service['kind'] != 'ping' and (
                        not host_is_up(db, service, run)
                        or reading is None or reading['status'] == 'blocked'))
                if suppressed:
                    incident['suppressed'] = True
                    if category == 'acknowledged':
                        # Acknowledgement remains the primary list membership.
                        visible.append(incident)
                    else:
                        result['incident_lists']['suppressed'].append(incident)
                else:
                    visible.append(incident)
            result['incident_lists'][category] = visible
        return result


def service_details(body, existing=None):
    """Shared validation for service creation/editing; blank edited secrets stay put."""
    name = body['name'].strip()
    kind = body['kind']
    target = body['target'].strip()
    if not name or len(name) > 100 or kind not in ('tcp', 'snmp', 'modbus'):
        raise ValueError('Invalid service name or protocol')
    if kind == 'snmp' and not all(part.isdigit() for part in target.lstrip('.').split('.')):
        raise ValueError('Use a numeric SNMP OID')
    if kind in ('tcp', 'modbus') and not (0 if kind == 'modbus' else 1) <= int(target) <= 65535:
        raise ValueError('Invalid port/register')
    warning = float(body['warning']) if body.get('warning') not in (None, '') else None
    critical = float(body['critical']) if body.get('critical') not in (None, '') else None
    scale = float(body.get('scale', 1))
    if not all(math.isfinite(n) for n in (warning, critical, scale) if n is not None):
        raise ValueError('Values must be finite')
    direction = body['direction']
    if direction not in ('above', 'below'):
        raise ValueError('Invalid threshold direction')
    if warning is not None and critical is not None:
        if (direction == 'below' and critical > warning) or (direction == 'above' and critical < warning):
            raise ValueError('Critical threshold must be more severe than warning')
    unit = int(body.get('unit', 1))
    persistence = int(body.get('persistence', 2))
    if not 1 <= unit <= 247 or not 1 <= persistence <= 120:
        raise ValueError('Invalid unit ID or persistence')
    community = body.get('community') or (existing['community'] if existing else 'public')
    value_type = body.get('value_type', 'metric')
    mapping = body.get('state_map', {})
    if isinstance(mapping, str):
        mapping = json.loads(mapping)
    if value_type not in ('metric', 'state') or not isinstance(mapping, dict):
        raise ValueError('Invalid value type or state mapping')
    normalized = {}
    if value_type == 'state':
        if not mapping or len(mapping) > 100:
            raise ValueError('State services require 1–100 mapped values')
        for key, definition in mapping.items():
            numeric_key = state_key(key)
            if numeric_key in normalized or not isinstance(definition, dict):
                raise ValueError('Duplicate state value or invalid definition')
            label = definition.get('label', '')
            if not isinstance(label, str):
                raise ValueError('State labels must be text')
            label = label.strip()
            status = definition.get('status', 'healthy')
            if not label or len(label) > 100 or any(c in label for c in '|\r\n') or status not in ('healthy', 'warning', 'critical'):
                raise ValueError('Invalid state label or severity')
            normalized[numeric_key] = {'label': label, 'status': status}
        # State codes are interpreted before scaling and have no numeric thresholds.
        scale, warning, critical = 1, None, None
    return (name, kind, target, community, unit, scale, body.get('units', ''),
            direction, warning, critical, persistence, value_type, json.dumps(normalized))


def reusable_service(db, service_id):
    """Only configured, enabled services can be copied or saved as templates."""
    row = db.execute('SELECT * FROM services WHERE id=? AND enabled=1',
                     (int(service_id),)).fetchone()
    if row is None or row['kind'] == 'ping':
        raise ValueError('Unknown service or managed host check')
    return row


def library_template(db, template_id):
    row = db.execute('SELECT * FROM service_templates WHERE id=?',
                     (int(template_id),)).fetchone()
    if row is None:
        raise ValueError('Unknown library service')
    return row


def insert_service(db, assignment_id, details):
    """Materialize a new independent service; never copy history or incident state."""
    if not db.execute('SELECT id FROM assignments WHERE id=?', (assignment_id,)).fetchone():
        raise ValueError('Unknown target host')
    db.execute("""INSERT INTO services
        (id,assignment,name,kind,target,community,unit,scale,units,direction,
         warning,critical,persistence,value_type,state_map) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (next_record_id(db, 'services'), assignment_id, *details))


def mutate(action, body):
    with LOCK, connect() as db:
        if action == 'project':
            db.execute('INSERT INTO projects(name) VALUES(?)', (body['name'],))
        elif action == 'device':
            details = device_details(body)
            db.execute('INSERT INTO devices(id,name,model,address) VALUES(?,?,?,?)',
                       (next_record_id(db, 'devices'), *details))
        elif action == 'device-edit':
            details = device_details(body)
            cursor = db.execute('UPDATE devices SET name=?,model=?,address=? WHERE id=?',
                                (*details, int(body['device'])))
            if cursor.rowcount != 1:
                raise ValueError('Unknown device')
        elif action == 'delete-device':
            delete_device(db, int(body['device']))
        elif action == 'device-address':
            db.execute('UPDATE devices SET address=? WHERE id=?',
                       (inventory_address(body['address']), int(body['device'])))
        elif action == 'assignment':
            db.execute('INSERT INTO assignments(id,project,device,alias) VALUES(?,?,?,?)',
                       (next_record_id(db, 'assignments'), int(body['project']),
                        int(body['device']), body['alias']))
            ensure_host_checks(db)
        elif action == 'assignment-edit':
            alias = body['alias'].strip()
            if not alias or len(alias) > 100:
                raise ValueError('Alias must contain 1–100 characters')
            cursor = db.execute('UPDATE assignments SET alias=? WHERE id=?',
                                (alias, int(body['assignment'])))
            if cursor.rowcount != 1:
                raise ValueError('Unknown project assignment')
        elif action == 'toggle':
            field = body['field']
            if field not in ('monitoring', 'visible', 'notifications'):
                raise ValueError('Invalid control')
            db.execute(f'UPDATE assignments SET {field}=1-{field} WHERE id=?', (int(body['id']),))
        elif action == 'activate':
            project = int(body['project'])
            if not db.execute('SELECT id FROM projects WHERE id=?', (project,)).fetchone():
                raise ValueError('Unknown project')
            cursor = db.execute('INSERT INTO runs(project,started) VALUES(?,?)', (project, time.time()))
            db.execute("UPDATE settings SET value=? WHERE key='active_run'", (str(cursor.lastrowid),))
        elif action == 'pause':
            db.execute("UPDATE settings SET value='0' WHERE key='active_run'")
        elif action == 'ack':
            db.execute('UPDATE incidents SET acknowledged=? WHERE id=? AND closed IS NULL AND acknowledged IS NULL',
                       (time.time(), int(body['id'])))
        elif action == 'retention':
            days = int(body['days'])
            if not 1 <= days <= 3650:
                raise ValueError('Retention must be 1–3650 days')
            db.execute("UPDATE settings SET value=? WHERE key='retention_days'", (str(days),))
        elif action == 'service':
            details = service_details(body)
            insert_service(db, int(body['assignment']), details)
        elif action == 'service-edit':
            service_id = int(body['service'])
            existing = db.execute('SELECT * FROM services WHERE id=? AND enabled=1',
                                  (service_id,)).fetchone()
            if existing is None or existing['kind'] == 'ping':
                raise ValueError('Unknown service or managed host check')
            details = service_details(body, existing)
            # Retain identity/history but start persistence counting for the new config.
            db.execute("""UPDATE services SET name=?,kind=?,target=?,community=?,unit=?,
                scale=?,units=?,direction=?,warning=?,critical=?,persistence=?,value_type=?,state_map=?,
                revision=revision+1 WHERE id=?""", (*details, service_id))
        elif action == 'service-copy':
            source = reusable_service(db, body['service'])
            assignment = int(body['assignment'])
            if assignment == source['assignment']:
                raise ValueError('Choose a different target host')
            configuration = dict(source)
            configuration['name'] = body.get('name', source['name'])
            configuration['community'] = body.get('community') or source['community']
            insert_service(db, assignment, service_details(configuration))
        elif action == 'template-create':
            # Saving from a service retains its secret on the server. The browser
            # only sends non-secret fields and an optional replacement community.
            source = reusable_service(db, body['source']) if body.get('source') else None
            details = service_details(body, source)
            db.execute("""INSERT INTO service_templates
                (name,kind,target,community,unit,scale,units,direction,warning,critical,persistence,value_type,state_map)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""", details)
        elif action == 'template-edit':
            source = library_template(db, body['template'])
            details = service_details(body, source)
            db.execute("""UPDATE service_templates SET name=?,kind=?,target=?,community=?,
                unit=?,scale=?,units=?,direction=?,warning=?,critical=?,persistence=?,value_type=?,state_map=?
                WHERE id=?""", (*details, source['id']))
        elif action == 'template-delete':
            source = library_template(db, body['template'])
            db.execute('DELETE FROM service_templates WHERE id=?', (source['id'],))
        elif action == 'template-apply':
            source = library_template(db, body['template'])
            configuration = dict(source)
            configuration['name'] = body.get('name', source['name'])
            configuration['community'] = body.get('community') or source['community']
            insert_service(db, int(body['assignment']), service_details(configuration))
        elif action == 'remove-service':
            # Keep ownership for history and later full-device deletion.
            db.execute("UPDATE services SET enabled=0 WHERE id=? AND kind!='ping'",
                       (int(body['id']),))
        else:
            raise ValueError('Unknown action')


def status_overview():
    """Allowlist public output: no addresses, OIDs, secrets, users or history."""
    data = snapshot()
    run = next((row for row in data['runs'] if row['id'] == int(data['settings']['active_run'])), None)
    if run is None:
        return {'project': None, 'devices': [], 'updated': time.time()}
    project = next(row for row in data['projects'] if row['id'] == run['project'])
    devices = {row['id']: row for row in data['devices']}
    latest = {row['service']: row for row in data['latest']}
    output = []
    for assignment in data['assignments']:
        if assignment['project'] != run['project'] or not assignment['visible']:
            continue
        device = devices[assignment['device']]
        services = [row for row in data['services'] if row['assignment'] == assignment['id'] and row['enabled']]
        ping = next((row for row in services if row['kind'] == 'ping'), None)
        reading = latest.get(ping['id']) if ping else None
        host_status = reading['status'] if (assignment['monitoring'] and reading
            and time.time() - reading['timestamp'] <= 60) else 'unknown'
        children = []
        for service in services:
            if service['kind'] == 'ping':
                continue
            sample = latest.get(service['id'])
            usable = host_status == 'healthy' and sample and time.time() - sample['timestamp'] <= 60
            status = sample['status'] if usable else 'blocked'
            children.append({'name': service['name'], 'status': status,
                'value': sample['display_value'] if usable and status != 'blocked' else None,
                'units': service['units'] if service['value_type'] == 'metric' else ''})
        output.append({'name': device['name'], 'alias': assignment['alias'],
                       'status': host_status, 'services': children})
    return {'project': project['name'], 'devices': output, 'updated': time.time()}


class Handler(BaseHTTPRequestHandler):
    def send(self, content, mime='application/json', status=200):
        if not isinstance(content, bytes):
            content = content.encode()
        self.send_response(status)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(content)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        self.wfile.write(content)

    def require_user(self, admin=False, allow_password_change=False):
        with connect() as db:
            user = auth.session_user(db, self.headers.get('Cookie'))
        if user is None:
            self.send('{"error":"Login required"}', status=401)
            return None
        if user['must_change_password'] and not allow_password_change:
            self.send('{"error":"Change your temporary password first"}', status=403)
            return None
        if admin and user['role'] != 'admin':
            self.send('{"error":"Administrator access required"}', status=403)
            return None
        return user

    def session_response(self, token=None):
        self.send_response(200)
        cookie = 'monitor_session=' + (token or '') + '; Path=/; HttpOnly; SameSite=Strict; Max-Age=' + str(auth.SESSION_SECONDS if token else 0)
        if os.environ.get('MONITOR_SECURE_COOKIE') == 'true':
            cookie += '; Secure'
        self.send_header('Set-Cookie', cookie)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(b'{"ok":true}')

    def do_GET(self):
        if self.path == '/api/health':
            return self.send('{"ok":true}')
        if self.path == '/login':
            return self.send(Path(__file__).with_name('login.html').read_bytes(), 'text/html; charset=utf-8')
        if self.path == '/status':
            return self.send(Path(__file__).with_name('status.html').read_bytes(), 'text/html; charset=utf-8')
        if self.path == '/api/status':
            return self.send(json.dumps(status_overview()))
        if self.path == '/':
            with connect() as db:
                user = auth.session_user(db, self.headers.get('Cookie'))
            if not user or user['must_change_password']:
                self.send_response(303)
                self.send_header('Location', '/login')
                self.end_headers()
                return
            return self.send(Path(__file__).with_name('index.html').read_bytes(), 'text/html; charset=utf-8')
        if self.path == '/api/me':
            user = self.require_user(allow_password_change=True)
            if user:
                return self.send(json.dumps({**auth.public_user(user), 'csrf': user['csrf']}))
            return
        admin = self.path in ('/api/users', '/api/backup', '/api/telegram', '/api/whatsapp', '/api/telegram-chats')
        user = self.require_user(admin=admin)
        if not user:
            return
        if self.path == '/api/telegram-chats':
            try:
                with connect() as db:
                    self.send(json.dumps(notifications.telegram_chats(db)))
            except Exception:
                self.send('{"error":"Could not discover groups. Check the saved token, bot membership, and send it a command in the group."}', status=400)
        elif self.path in ('/api/telegram', '/api/whatsapp'):
            channel = self.path.removeprefix('/api/')
            with connect() as db:
                self.send(json.dumps({'configuration': notifications.public_configuration(db, channel),
                    'outbox': [dict(row) for row in db.execute('SELECT id,event,state,attempts,error,created FROM notification_outbox WHERE channel=? ORDER BY id DESC LIMIT 50', (channel,))]}))
        elif self.path == '/api/users':
            with connect() as db:
                users = [auth.public_user(row) for row in db.execute('SELECT * FROM users ORDER BY username')]
            self.send(json.dumps(users))
        elif self.path == '/api/state':
            self.send(json.dumps(snapshot()))
        elif self.path == '/api/backup':
            # Exclude live sessions from portable backups.
            with LOCK, connect() as source:
                destination = sqlite3.connect(':memory:')
                source.backup(destination)
                destination.execute('DELETE FROM sessions')
                destination.execute('DELETE FROM login_attempts')
                destination.commit()
                payload = destination.serialize()
                destination.close()
            self.send(payload, 'application/octet-stream')
        elif self.path.startswith('/api/history?'):
            from urllib.parse import parse_qs, urlsplit
            try:
                query = parse_qs(urlsplit(self.path).query)
                with connect() as db:
                    rows = db.execute('SELECT timestamp,value,status,display_value,revision FROM samples WHERE service=? AND run=? ORDER BY id DESC LIMIT 200',
                                      (int(query['service'][0]), int(query['run'][0]))).fetchall()
                self.send(json.dumps([dict(row) for row in rows]))
            except (KeyError, ValueError):
                self.send('{"error":"Invalid history request"}', status=400)
        else:
            self.send('{"error":"Not found"}', status=404)

    def do_POST(self):
        from urllib.parse import urlsplit
        origin = self.headers.get('Origin')
        if origin and (urlsplit(origin).netloc != self.headers.get('Host', '')
                       or urlsplit(origin).scheme not in ('http', 'https')):
            return self.send('{"error":"Origin rejected"}', status=403)
        user = None
        if self.path != '/api/login':
            user = self.require_user(admin=self.path not in ('/api/logout', '/api/password'),
                                     allow_password_change=self.path in ('/api/logout', '/api/password'))
            if not user:
                return
            if not hmac.compare_digest(self.headers.get('X-CSRF-Token', ''), user['csrf']):
                return self.send('{"error":"Invalid request token"}', status=403)
        try:
            size = int(self.headers.get('Content-Length', '0'))
            limit = 64 * 1024 * 1024 if self.path == '/api/restore' else 65536
            if not 0 < size <= limit:
                raise ValueError('Invalid request size')
            payload = self.rfile.read(size)
            if self.path == '/api/restore':
                if self.headers.get('Content-Type') != 'application/octet-stream':
                    raise ValueError('Expected backup file')
                candidate = sqlite3.connect(':memory:')
                try:
                    candidate.deserialize(payload)
                    if candidate.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                        raise ValueError('Invalid backup')
                    required = {'projects', 'devices', 'assignments', 'services', 'runs', 'settings', 'samples', 'incidents'}
                    tables = {row[0] for row in candidate.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                    if not required.issubset(tables):
                        raise ValueError('Incompatible backup')
                    candidate.execute("UPDATE settings SET value='0' WHERE key='active_run'")
                    migrate_inventory_addresses(candidate)
                    migrate_service_lifecycle(candidate)
                    ensure_service_library(candidate)
                    migrate_value_types(candidate)
                    ensure_host_checks(candidate)
                    notifications.ensure_tables(candidate)
                    candidate.execute("UPDATE notification_outbox SET state='cancelled',error='Restored backup' WHERE state IN ('pending','sending')")
                    auth.ensure_accounts(candidate)
                    # Older backups have no accounts: retain current accounts so
                    # restoring equipment cannot silently reset access to a default.
                    if not candidate.execute('SELECT 1 FROM users LIMIT 1').fetchone():
                        with connect() as current:
                            for account in current.execute('SELECT * FROM users'):
                                candidate.execute('INSERT INTO users VALUES(?,?,?,?,?)', tuple(account))
                    if not candidate.execute("SELECT 1 FROM users WHERE role='admin' LIMIT 1").fetchone():
                        raise ValueError('Backup has no administrator')
                    candidate.execute('DELETE FROM sessions')
                    candidate.execute('DELETE FROM login_attempts')
                    candidate.commit()
                    with LOCK, connect() as destination:
                        candidate.backup(destination)
                finally:
                    candidate.close()
            else:
                if self.headers.get('Content-Type') != 'application/json':
                    raise ValueError('Expected JSON')
                body = json.loads(payload)
                if self.path == '/api/login':
                    with LOCK, connect() as db:
                        token, status = auth.login(db, body.get('username', ''), body.get('password', ''), self.client_address[0])
                    if token:
                        return self.session_response(token)
                    return self.send(json.dumps({'error': 'Too many attempts; try again in a minute' if status == 429 else 'Invalid username or password'}), status=status)
                if self.path == '/api/logout':
                    with connect() as db:
                        db.execute('DELETE FROM sessions WHERE csrf=?', (user['csrf'],))
                    return self.session_response()
                if self.path == '/api/password':
                    with LOCK, connect() as db:
                        account = db.execute('SELECT * FROM users WHERE id=?', (user['id'],)).fetchone()
                        if not auth.password_matches(body['current_password'], account['password_hash']):
                            raise ValueError('Current password is incorrect')
                        if auth.password_matches(body['password'], account['password_hash']):
                            raise ValueError('Choose a different password')
                        encoded = auth.password_hash(body['password'])
                        db.execute('UPDATE users SET password_hash=?,must_change_password=0 WHERE id=?', (encoded, user['id']))
                        db.execute('DELETE FROM sessions WHERE user_id=?', (user['id'],))
                        token = auth.new_session(db, user['id'])
                    return self.session_response(token)
                if self.path in ('/api/telegram-save', '/api/telegram-test', '/api/whatsapp-save', '/api/whatsapp-test', '/api/telegram-retry', '/api/whatsapp-retry'):
                    with LOCK, connect() as db:
                        if self.path == '/api/telegram-save':
                            notifications.save_configuration(db, body)
                        elif self.path.endswith('-retry'):
                            notifications.retry_failed(db, 'whatsapp' if self.path.startswith('/api/whatsapp') else 'telegram')
                        elif self.path == '/api/whatsapp-save':
                            notifications.save_whatsapp(db, body)
                        else:
                            notifications.enqueue_test(db, 'whatsapp' if self.path == '/api/whatsapp-test' else 'telegram')
                elif self.path.startswith('/api/user-'):
                    if self.path not in ('/api/user-create', '/api/user-edit', '/api/user-delete'):
                        raise ValueError('Unknown action')
                    with LOCK, connect() as db:
                        auth.manage_user(db, self.path.removeprefix('/api/'), body, user)
                else:
                    mutate(self.path.removeprefix('/api/'), body)
            self.send('{"ok":true}')
        except (ValueError, KeyError, sqlite3.Error, OverflowError, TypeError):
            self.send('{"error":"Request rejected: check values and referenced records"}', status=400)


if __name__ == '__main__':
    initialize()
    threading.Thread(target=poll_loop, daemon=True).start()
    threading.Thread(target=notifications.worker, args=(connect, LOCK, host_is_up), daemon=True).start()
    print('Local monitor listening on port 8080', flush=True)
    ThreadingHTTPServer((os.environ.get('MONITOR_HOST', '0.0.0.0'), 8080), Handler).serve_forever()
