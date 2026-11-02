"""Small local monitor: durable SQLite state, bounded polling, and a local web UI.

This first pass deliberately has no public listener authentication. Keep it on a
trusted machine until the authenticated relay and user accounts are implemented.
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
        ensure_host_checks(db)


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
             '-Oqv', '--', host, service['target']],
            capture_output=True, text=True, timeout=4, check=True,
        )
        # Only numeric OIDs are accepted; counters are raw values, not rates.
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


def poll_one(service, run):
    try:
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
        db.execute('INSERT INTO samples(run,service,timestamp,value,status,error,revision) VALUES(?,?,?,?,?,?,?)',
                   (run, service['id'], time.time(), value, status, error, service['revision']))
        recent = db.execute('SELECT status FROM samples WHERE service=? AND run=? AND revision=? ORDER BY id DESC LIMIT ?',
                            (service['id'], run, service['revision'], service['persistence'])).fetchall()
        confirmed = len(recent) == service['persistence'] and all(row[0] == status for row in recent)
        if not confirmed:
            return
        incident = db.execute('SELECT * FROM incidents WHERE service=? AND run=? AND closed IS NULL',
                              (service['id'], run)).fetchone()
        if incident and (status == 'healthy' or incident['status'] != status):
            db.execute('UPDATE incidents SET closed=? WHERE id=?', (time.time(), incident['id']))
            incident = None
        if status != 'healthy' and incident is None:
            db.execute('INSERT INTO incidents(run,service,opened,status) VALUES(?,?,?,?)',
                       (run, service['id'], time.time(), status))


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
                list(pool.map(lambda service: poll_one(service, run), services))
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
            SELECT id,assignment,name,kind,target,unit,scale,units,direction,warning,critical,persistence,enabled,revision
            FROM services''')]
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
    return (name, kind, target, community, unit, scale, body.get('units', ''),
            direction, warning, critical, persistence)


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
            db.execute("""INSERT INTO services
                (id,assignment,name,kind,target,community,unit,scale,units,direction,
                 warning,critical,persistence) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (next_record_id(db, 'services'), int(body['assignment']), *details))
        elif action == 'service-edit':
            service_id = int(body['service'])
            existing = db.execute('SELECT * FROM services WHERE id=? AND enabled=1',
                                  (service_id,)).fetchone()
            if existing is None or existing['kind'] == 'ping':
                raise ValueError('Unknown service or managed host check')
            details = service_details(body, existing)
            # Retain identity/history but start persistence counting for the new config.
            db.execute("""UPDATE services SET name=?,kind=?,target=?,community=?,unit=?,
                scale=?,units=?,direction=?,warning=?,critical=?,persistence=?,
                revision=revision+1 WHERE id=?""", (*details, service_id))
        elif action == 'remove-service':
            # Keep ownership for history and later full-device deletion.
            db.execute("UPDATE services SET enabled=0 WHERE id=? AND kind!='ping'",
                       (int(body['id']),))
        else:
            raise ValueError('Unknown action')


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

    def do_GET(self):
        if self.path == '/':
            self.send(Path(__file__).with_name('index.html').read_bytes(), 'text/html; charset=utf-8')
        elif self.path == '/api/state':
            self.send(json.dumps(snapshot()))
        elif self.path == '/api/backup':
            # SQLite's backup API produces a consistent snapshot during live polling.
            with LOCK, connect() as source:
                destination = sqlite3.connect(':memory:')
                source.backup(destination)
                payload = destination.serialize()
                destination.close()
            self.send(payload, 'application/octet-stream')
        elif self.path.startswith('/api/history?'):
            from urllib.parse import parse_qs, urlsplit
            try:
                query = parse_qs(urlsplit(self.path).query)
                with connect() as db:
                    rows = db.execute('SELECT timestamp,value,status FROM samples WHERE service=? AND run=? ORDER BY id DESC LIMIT 200',
                                      (int(query['service'][0]), int(query['run'][0]))).fetchall()
                self.send(json.dumps([dict(row) for row in rows]))
            except (KeyError, ValueError):
                self.send('{"error":"Invalid history request"}', status=400)
        else:
            self.send('{"error":"Not found"}', status=404)

    def do_POST(self):
        # JSON/custom content type plus same-origin validation blocks browser form CSRF.
        origin = self.headers.get('Origin')
        if origin and origin != 'http://' + self.headers.get('Host', ''):
            return self.send('{"error":"Origin rejected"}', status=403)
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size <= 64 * 1024 * 1024:
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
                    ensure_host_checks(candidate)
                    candidate.commit()
                    with LOCK, connect() as destination:
                        candidate.backup(destination)
                finally:
                    candidate.close()
            else:
                if self.headers.get('Content-Type') != 'application/json':
                    raise ValueError('Expected JSON')
                mutate(self.path.removeprefix('/api/'), json.loads(payload))
            self.send('{"ok":true}')
        except (ValueError, KeyError, sqlite3.Error, OverflowError):
            self.send('{"error":"Request rejected: check values and referenced records"}', status=400)


if __name__ == '__main__':
    initialize()
    threading.Thread(target=poll_loop, daemon=True).start()
    print('Local monitor listening on port 8080', flush=True)
    ThreadingHTTPServer((os.environ.get('MONITOR_HOST', '0.0.0.0'), 8080), Handler).serve_forever()
