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
from urllib.parse import parse_qs, urlsplit
import socket
import sqlite3
import struct
import subprocess
import threading
import time
import hmac
from . import auth, notifications, logos, service_library, stability, live_updates, presence, project_deletion, history, resolved, inventory_transfer
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
        db.execute("INSERT OR IGNORE INTO settings VALUES ('session_hours','12')")
        db.execute("INSERT OR IGNORE INTO settings VALUES ('active_run','0')")
        # Older releases stored only active_run=0 when paused; their most recent
        # deployment is the one that can be resumed after upgrading.
        db.execute("""INSERT OR IGNORE INTO settings SELECT 'paused_run',
            CASE WHEN (SELECT value FROM settings WHERE key='active_run')='0'
            THEN CAST(COALESCE(MAX(id),0) AS TEXT) ELSE '0' END FROM runs""")
        migrate_inventory_addresses(db)
        migrate_service_lifecycle(db)
        project_deletion.ensure_table(db)
        ensure_service_library(db)
        ensure_inventory_services(db)
        migrate_value_types(db)
        stability.ensure_tables(db)
        migrate_issue_evidence(db)
        ensure_host_checks(db)
        migrate_project_settings(db)
        migrate_incident_acknowledgements(db)
        migrate_issue_numbers(db)
        migrate_deployment_descriptions(db)
        logos.ensure_table(db)
        notifications.ensure_tables(db)
        migrate_modbus_functions(db)
        history.ensure_tables(db)
        resolved.ensure_index(db)
        auth.ensure_accounts(db, DB.with_name('initial-admin-password.txt'),
                             os.environ.get('MONITOR_ADMIN_PASSWORD'))


# Keep inventory defaults independent from project services and shared library entries.
SERVICE_CONFIGURATION_FIELDS = service_library.FIELDS


def ensure_inventory_services(db):
    """Legacy devices start without defaults; never pick an arbitrary project's config."""
    db.execute("""CREATE TABLE IF NOT EXISTS device_service_defaults (
        id INTEGER PRIMARY KEY AUTOINCREMENT, device INTEGER NOT NULL REFERENCES devices(id),
        name TEXT NOT NULL, kind TEXT NOT NULL, target TEXT NOT NULL,
        community TEXT NOT NULL DEFAULT 'public', unit INTEGER NOT NULL DEFAULT 1,
        scale REAL NOT NULL DEFAULT 1, units TEXT NOT NULL DEFAULT '',
        direction TEXT NOT NULL DEFAULT 'below', warning REAL, critical REAL,
        persistence INTEGER NOT NULL DEFAULT 2, value_type TEXT NOT NULL DEFAULT 'metric',
        state_map TEXT NOT NULL DEFAULT '{}', UNIQUE(device,name)
    )""")


def require_inventory_device(db, device):
    if not db.execute('SELECT 1 FROM devices WHERE id=?', (device,)).fetchone():
        raise ValueError('Unknown inventory device')


def save_inventory_default(db, device, details, default_id=None):
    require_inventory_device(db, device)
    if default_id is None:
        columns = ','.join(SERVICE_CONFIGURATION_FIELDS)
        values = ','.join('?' for _ in SERVICE_CONFIGURATION_FIELDS)
        db.execute(f'INSERT INTO device_service_defaults(device,{columns}) VALUES(?,{values})',
                   (device, *details))
    else:
        setters = ','.join(field + '=?' for field in SERVICE_CONFIGURATION_FIELDS)
        cursor = db.execute(f'UPDATE device_service_defaults SET {setters} WHERE id=? AND device=?',
                            (*details, default_id, device))
        if cursor.rowcount != 1:
            raise ValueError('Unknown device service default')


def replace_defaults_from_assignment(db, device, assignment):
    """Explicitly adopt one project's definitions, preserving all project records."""
    require_inventory_device(db, device)
    source = db.execute('SELECT id FROM assignments WHERE id=? AND device=? AND removed=0',
                        (assignment, device)).fetchone()
    if not source:
        raise ValueError('Choose an existing project assignment for this device')
    rows = db.execute("SELECT * FROM services WHERE assignment=? AND enabled=1 AND kind!='ping' ORDER BY id",
                      (assignment,)).fetchall()
    if not rows or len({row['name'] for row in rows}) != len(rows):
        raise ValueError('Source needs at least one service and unique service names')
    # Validate everything before replacing; blank credentials stay on the server.
    definitions = [service_details(dict(row)) for row in rows]
    db.execute('DELETE FROM device_service_defaults WHERE device=?', (device,))
    for definition in definitions:
        save_inventory_default(db, device, definition)


def migrate_deployment_descriptions(db):
    """Keep old deployment records intact without inventing a reason for them."""
    if 'description' not in {row[1] for row in db.execute('PRAGMA table_info(runs)')}:
        db.execute("ALTER TABLE runs ADD COLUMN description TEXT NOT NULL DEFAULT ''")


def migrate_issue_numbers(db):
    """Assign stable per-deployment labels while preserving internal issue IDs.

    Counters live on runs so deleting a device and its issues cannot reuse an
    already-issued number. Legacy records are numbered in their creation order.
    """
    if 'issue_counter' not in {row[1] for row in db.execute('PRAGMA table_info(runs)')}:
        db.execute('ALTER TABLE runs ADD COLUMN issue_counter INTEGER NOT NULL DEFAULT 0')
    if 'number' not in {row[1] for row in db.execute('PRAGMA table_info(incidents)')}:
        db.execute('ALTER TABLE incidents ADD COLUMN number INTEGER')
    outbox_exists = db.execute("SELECT 1 FROM sqlite_master WHERE name='notification_outbox'").fetchone()
    for run_id, old_counter in db.execute('SELECT id,issue_counter FROM runs').fetchall():
        highest = db.execute('SELECT COALESCE(MAX(number),0) FROM incidents WHERE run=?', (run_id,)).fetchone()[0]
        counter = max(old_counter, highest)
        unnumbered = db.execute('SELECT id FROM incidents WHERE run=? AND number IS NULL ORDER BY id',
                                (run_id,)).fetchall()
        for (issue_id,) in unnumbered:
            counter += 1
            db.execute('UPDATE incidents SET number=? WHERE id=?', (counter, issue_id))
            if outbox_exists:
                # Update unsent legacy payloads; previously delivered messages stay intact.
                rows = db.execute("""SELECT id,text FROM notification_outbox WHERE incident=?
                    AND state IN ('pending','sending','failed')""", (issue_id,)).fetchall()
                for message_id, message in rows:
                    head, separator, footer = message.rpartition('\n')
                    if separator and footer.startswith('Issue #'):
                        db.execute('UPDATE notification_outbox SET text=? WHERE id=?',
                                   (f"{head}\nIssue #{counter} · Deployment #{run_id}", message_id))
        db.execute('UPDATE runs SET issue_counter=? WHERE id=?', (counter, run_id))
    db.execute('CREATE UNIQUE INDEX IF NOT EXISTS deployment_issue_number ON incidents(run,number)')


def migrate_incident_acknowledgements(db):
    """Keep current acknowledgement state separately from the immutable audit trail."""
    columns = {row[1] for row in db.execute('PRAGMA table_info(incidents)')}
    for name, kind in (('acknowledged_by_user_id', 'INTEGER'),
                       ('acknowledged_by_username', 'TEXT'),
                       ('acknowledged_by_full_name', 'TEXT'),
                       ('ack_revision', 'INTEGER NOT NULL DEFAULT 0'),
                       ('unacknowledged_at', 'REAL')):
        if name not in columns:
            db.execute(f'ALTER TABLE incidents ADD COLUMN {name} {kind}')
    existed = db.execute("SELECT 1 FROM sqlite_master WHERE name='incident_acknowledgement_events'").fetchone()
    db.execute("""CREATE TABLE IF NOT EXISTS incident_acknowledgement_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        incident INTEGER NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
        action TEXT NOT NULL CHECK(action IN ('acknowledged','unacknowledged')),
        timestamp REAL NOT NULL, user_id INTEGER, username TEXT, full_name TEXT,
        revision INTEGER NOT NULL
    )""")
    db.execute('CREATE INDEX IF NOT EXISTS acknowledgement_events_issue ON incident_acknowledgement_events(incident,id)')
    if not existed:
        # Existing snapshots are the only defensible historical evidence. Never
        # invent an actor or replace their recorded name with a current account.
        db.execute("""INSERT INTO incident_acknowledgement_events
            (incident,action,timestamp,user_id,username,full_name,revision)
            SELECT id,'acknowledged',acknowledged,acknowledged_by_user_id,
                   acknowledged_by_username,acknowledged_by_full_name,ack_revision
            FROM incidents WHERE acknowledged IS NOT NULL""")


def acknowledgement_actor(db, actor):
    account = db.execute('SELECT id,username,full_name,role FROM users WHERE id=?',
                         (actor.get('id') if actor else None,)).fetchone()
    if not account or account['role'] not in ('admin', 'operator'):
        raise ValueError('An authenticated Admin or Operator is required')
    return account


def record_acknowledgement_event(db, incident_id, action, now, account):
    """Snapshot actors without a user FK so account deletion cannot rewrite history."""
    db.execute("""INSERT INTO incident_acknowledgement_events
        (incident,action,timestamp,user_id,username,full_name,revision)
        SELECT id,?,?,?,?,?,ack_revision FROM incidents WHERE id=?""",
        (action, now, account['id'], account['username'], account['full_name'] or account['username'], incident_id))
    db.execute("""UPDATE notification_outbox SET state='cancelled',error='Acknowledgement changed'
        WHERE incident=? AND event LIKE 'reminder:%' AND state='pending'""", (incident_id,))


def record_acknowledgement(db, incident_id, actor):
    account = acknowledgement_actor(db, actor)
    now = time.time()
    updated = db.execute("""UPDATE incidents SET acknowledged=?, acknowledged_by_user_id=?,
        acknowledged_by_username=?, acknowledged_by_full_name=?,ack_revision=ack_revision+1
        WHERE id=? AND closed IS NULL AND acknowledged IS NULL""",
        (now, account['id'], account['username'], account['full_name'] or account['username'], incident_id))
    if updated.rowcount:
        record_acknowledgement_event(db, incident_id, 'acknowledged', now, account)
        return True
    return False


def record_unacknowledgement(db, incident_id, actor, expected_revision):
    """Clear current state atomically; retain recovery and all earlier audit events."""
    account = acknowledgement_actor(db, actor)
    if type(expected_revision) is not int or expected_revision < 0:
        raise ValueError('Review the current acknowledgement before removing it')
    issue = db.execute("""SELECT i.* FROM incidents i JOIN services s ON s.id=i.service
        JOIN assignments a ON a.id=s.assignment
        WHERE i.id=? AND i.run=CAST((SELECT value FROM settings WHERE key='active_run') AS INTEGER)
          AND i.acknowledged IS NOT NULL AND s.enabled=1 AND a.removed=0""", (incident_id,)).fetchone()
    if not issue or issue['ack_revision'] != expected_revision:
        raise ValueError('Acknowledgement changed or issue is unavailable. Refresh and review it again.')
    now = time.time()
    updated = db.execute("""UPDATE incidents SET acknowledged=NULL,acknowledged_by_user_id=NULL,
        acknowledged_by_username=NULL,acknowledged_by_full_name=NULL,unacknowledged_at=?,
        ack_revision=ack_revision+1 WHERE id=? AND acknowledged IS NOT NULL AND ack_revision=?""",
        (now, incident_id, expected_revision))
    if not updated.rowcount:
        raise ValueError('Acknowledgement changed. Refresh and review it again.')
    record_acknowledgement_event(db, incident_id, 'unacknowledged', now, account)
    return True


def migrate_project_settings(db):
    if 'status_ack_enabled' not in {row[1] for row in db.execute('PRAGMA table_info(projects)')}:
        db.execute('ALTER TABLE projects ADD COLUMN status_ack_enabled INTEGER NOT NULL DEFAULT 0')


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
    if not isinstance(value, str):
        raise ValueError('Enter a valid IP address')
    return str(ipaddress.ip_address(value.strip()))


class InventoryAddressConflict(ValueError):
    """Safe inventory feedback that can identify the device already using an IP."""


def require_unique_inventory_address(db, address, excluding_device=None):
    """Compare canonical IPs in the serialized mutation transaction, including legacy rows.

    Do not rebuild existing inventory on upgrade: older backups and isolated
    benchmark datasets may contain shared addresses. New API writes must be unique.
    """
    candidate = inventory_transfer.address_key(address)
    for device in db.execute('SELECT id,name,address FROM devices ORDER BY id'):
        if device['id'] == excluding_device or not device['address']:
            continue
        try:
            existing = inventory_transfer.address_key(device['address'])
        except (ValueError, AttributeError):
            continue  # An unconfigured/legacy address does not claim a valid IP.
        if existing == candidate:
            raise InventoryAddressConflict(f"IP address {address} is already assigned to {device['name']}.")


def migrate_service_lifecycle(db):
    """Keep removed service ownership so deleting equipment can purge its history."""
    columns = {row[1] for row in db.execute('PRAGMA table_info(services)')}
    if 'enabled' not in columns:
        db.execute('ALTER TABLE services ADD COLUMN enabled INTEGER NOT NULL DEFAULT 1')
    if 'revision' not in columns:
        db.execute('ALTER TABLE services ADD COLUMN revision INTEGER NOT NULL DEFAULT 1')
    if 'monitoring' not in columns:
        db.execute('ALTER TABLE services ADD COLUMN monitoring INTEGER NOT NULL DEFAULT 1')
    if 'monitoring_since' not in columns:
        db.execute('ALTER TABLE services ADD COLUMN monitoring_since REAL NOT NULL DEFAULT 0')
    assignment_columns = {row[1] for row in db.execute('PRAGMA table_info(assignments)')}
    if 'removed' not in assignment_columns:
        db.execute('ALTER TABLE assignments ADD COLUMN removed INTEGER NOT NULL DEFAULT 0')
    sample_columns = {row[1] for row in db.execute('PRAGMA table_info(samples)')}
    if 'revision' not in sample_columns:
        db.execute('ALTER TABLE samples ADD COLUMN revision INTEGER NOT NULL DEFAULT 1')
    ensure_sample_indexes(db)
    # Remember IDs before deletion, so delayed polling cannot attach to a new item.
    for table in ('projects', 'devices', 'assignments', 'services', 'runs', 'incidents'):
        maximum = db.execute(f'SELECT COALESCE(MAX(id), 0) FROM {table}').fetchone()[0]
        db.execute('INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)',
                   ('last_id_' + table, str(maximum)))
        previous = int(setting(db, 'last_id_' + table))
        db.execute('UPDATE settings SET value=? WHERE key=?',
                   (str(max(maximum, previous)), 'last_id_' + table))


def ensure_sample_indexes(db):
    """Index current readings and expiry without discarding existing history.

    Building these once can take time on an existing multi-million-row database.
    Log each build so an upgrade does not look like a silently stalled startup.
    """
    indexes = {
        'sample_lookup': 'samples(service,timestamp)',
        'sample_current': 'samples(service,run,revision,id DESC)',
        'sample_expiry': 'samples(timestamp)',
    }
    existing = {row[1] for row in db.execute('PRAGMA index_list(samples)')}
    for name, columns in indexes.items():
        if name not in existing:
            print(f'Building history index {name}; existing readings are retained', flush=True)
            db.execute(f'CREATE INDEX {name} ON {columns}')
            print(f'History index {name} ready', flush=True)


def current_samples(db, service, run, revision, since, limit=1):
    """Read the latest IDs without walking pre-resume history to fill a limit.

    The common path uses the current-reading index and stops after `limit` rows.
    If any are from before resume, use the timestamp index to search only the
    eligible time range. Keep ID ordering authoritative, even for unusual imports
    whose timestamps are out of order.
    """
    rows = db.execute("""SELECT * FROM samples
        WHERE service=? AND run=? AND revision=? ORDER BY id DESC LIMIT ?""",
        (service, run, revision, limit)).fetchall()
    if all(row['timestamp'] is not None and row['timestamp'] >= since for row in rows):
        return rows
    return db.execute("""SELECT * FROM samples INDEXED BY sample_lookup
        WHERE service=? AND timestamp>=? AND run=? AND revision=?
        ORDER BY id DESC LIMIT ?""", (service, since, run, revision, limit)).fetchall()


def prune_samples(db, cutoff, batch_size=1000):
    """Drain expired history in small transactions rather than blocking a poll round.

    The timestamp index makes an empty expiry check cheap even with weeks of data.
    A reduced retention setting can leave a backlog, removed over subsequent rounds.
    """
    return db.execute("""DELETE FROM samples WHERE id IN (
        SELECT id FROM samples WHERE timestamp<? ORDER BY timestamp LIMIT ?
    )""", (cutoff, batch_size)).rowcount


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


def migrate_issue_evidence(db):
    """Preserve opening evidence independently of history retention and later edits.

    Legacy issues cannot safely use the latest reading: it may describe recovery.
    Backfill only a matching pre-opening sample; otherwise leave evidence unknown.
    """
    columns = {row[1] for row in db.execute('PRAGMA table_info(incidents)')}
    for name, kind in (('trigger_value', 'REAL'), ('trigger_display', 'TEXT'),
                       ('trigger_units', 'TEXT'), ('trigger_timestamp', 'REAL'),
                       ('trigger_error', 'TEXT')):
        if name not in columns:
            db.execute(f'ALTER TABLE incidents ADD COLUMN {name} {kind}')

    if 'trigger_timestamp' not in columns:
        # Only run on schema upgrade. Never re-label old readings using today's
        # state map; units are defensible only when the service revision matches.
        for issue_id, run, service_id, opened, status in db.execute(
                'SELECT id,run,service,opened,status FROM incidents').fetchall():
            sample = db.execute("""SELECT p.value,p.display_value,p.timestamp,p.error,
                CASE WHEN p.revision=s.revision AND s.value_type='metric' THEN s.units ELSE '' END
                FROM samples p JOIN services s ON s.id=p.service
                WHERE p.run=? AND p.service=? AND p.status=? AND p.timestamp<=?
                AND p.timestamp>=? ORDER BY p.timestamp DESC,p.id DESC LIMIT 1""",
                (run, service_id, status, opened, opened - 60)).fetchone()
            if sample:
                value, display, timestamp, error, units = sample
                db.execute("""UPDATE incidents SET trigger_value=?,trigger_display=?,trigger_timestamp=?,
                    trigger_error=?,trigger_units=? WHERE id=?""",
                    (value, display if display is not None else str(value) if value is not None else None,
                     timestamp, error, units, issue_id))


def migrate_modbus_functions(db):
    """Preserve old Function 03 behaviour across services, defaults and templates."""
    for table in ('services', 'service_templates', 'device_service_defaults'):
        if 'modbus_function' not in {row[1] for row in db.execute(f'PRAGMA table_info({table})')}:
            db.execute(f'ALTER TABLE {table} ADD COLUMN modbus_function INTEGER NOT NULL DEFAULT 3')


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
    # Scaling (for example 231 * 0.1) can leave binary floating-point residue.
    # Round only the display text; stored values and alarm comparisons stay exact
    # to the original reading. Significant digits also preserve very small metrics.
    return format(value, '.15g')


def next_record_id(db, table):
    """Allocate a durable ID even after the highest existing record is deleted."""
    if table not in ('projects', 'devices', 'assignments', 'services', 'runs', 'incidents'):
        raise ValueError('Unsupported record type')
    maximum = db.execute(f'SELECT COALESCE(MAX(id), 0) FROM {table}').fetchone()[0]
    value = max(maximum, int(setting(db, 'last_id_' + table))) + 1
    db.execute('UPDATE settings SET value=? WHERE key=?',
               (str(value), 'last_id_' + table))
    return value


def ensure_host_checks(db):
    """Create built-in ping checks for new, upgraded, and restored assignments."""
    missing = db.execute("""
        SELECT a.id FROM assignments a WHERE a.removed=0 AND NOT EXISTS (
            SELECT 1 FROM services s WHERE s.assignment=a.id AND s.kind='ping'
        )
    """).fetchall()
    for assignment in missing:
        db.execute("""
            INSERT INTO services (id, assignment, name, kind, target)
            VALUES (?, ?, 'Host ping', 'ping', '')
        """, (next_record_id(db, 'services'), assignment[0]))


def device_details(body, allow_unconfigured=False):
    """Validate editable inventory fields before writing any of them."""
    name = body['name']
    model = body.get('model', '')
    if not isinstance(name, str) or not isinstance(model, str):
        raise ValueError('Device ID and model must be text')
    name, model = name.strip(), model.strip()
    if not name or len(name) > 100 or len(model) > 100:
        raise ValueError('Invalid device name or model')
    address = body['address']
    if allow_unconfigured and isinstance(address, str) and not address.strip():
        return name, model, ''
    return name, model, inventory_address(address)


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
    db.execute('DELETE FROM device_service_defaults WHERE device=?', (device_id,))
    db.execute('DELETE FROM devices WHERE id=?', (device_id,))


def setting(db, key):
    return db.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()[0]


def classify(value, service, previous_status=None):
    """Critical takes precedence; null thresholds mean that check is disabled."""
    if service['value_type'] == 'state':
        definition = state_definition(service, value)
        return definition['status'] if definition else 'warning'
    nominal = 'healthy'
    for level in ('critical', 'warning'):
        limit = service[level]
        if limit is not None and ((service['direction'] == 'below' and value < limit)
                                  or (service['direction'] == 'above' and value > limit)):
            nominal = level
            break
    margin = dict(service).get('hysteresis', 0)
    ranks = {'healthy': 0, 'warning': 1, 'critical': 2}
    # Escalation uses original limits; only recovery needs to clear the margin.
    for level in ('critical', 'warning'):
        limit = service[level]
        if (margin and previous_status in ranks and ranks[previous_status] >= ranks[level]
                and ranks[nominal] < ranks[level] and limit is not None):
            held = value < limit + margin if service['direction'] == 'below' else value > limit - margin
            if held:
                return level
    return nominal


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
        function = service.get('modbus_function', 3)
        if function not in (3, 4):
            raise ValueError('Unsupported Modbus read function')
        # The gateway receives ordinary Modbus TCP; only the read function changes.
        request = struct.pack('>HHHBBHH', 1, 0, 6, unit, function, register, 1)
        with socket.create_connection((host, 502), timeout=2) as sock:
            sock.settimeout(2)
            sock.sendall(request)
            header = receive_exact(sock, 7)
            transaction, protocol, length, response_unit = struct.unpack('>HHHB', header)
            if (transaction, protocol, response_unit) != (1, 0, unit) or length not in (3, 5):
                raise ValueError('Unexpected Modbus response header')
            response = receive_exact(sock, length - 1)
            if response[0] == (function | 0x80) and length == 3:
                raise ValueError(f'Modbus exception {response[1]}')
            if length != 5 or response[:2] != bytes((function, 2)):
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
    ping = db.execute("""
        SELECT ping.id,ping.revision,ping.monitoring_since FROM services ping
        JOIN assignments a ON a.id=ping.assignment
        JOIN devices d ON d.id=a.device
        WHERE ping.assignment=? AND ping.kind='ping' AND d.address=?
    """, (service['assignment'], service['address'])).fetchone()
    if ping is None:
        return False
    # Start from the host's check, never scan other hosts' history to find its ping.
    readings = current_samples(db, ping['id'], run, ping['revision'], ping['monitoring_since'])
    host = readings[0] if readings else None
    return bool(host and host['status'] == 'healthy' and time.time() - host['timestamp'] <= 60)


def poll_one(service, run):
    with LOCK, connect() as db:
        current = db.execute('''SELECT s.monitoring,s.monitoring_since FROM services s
            JOIN assignments a ON a.id=s.assignment
            WHERE s.id=? AND s.enabled=1 AND a.removed=0 AND a.monitoring=1''', (service['id'],)).fetchone()
        if (current is None or not current['monitoring']
                or current['monitoring_since'] != service['monitoring_since']):
            return
        blocked = service['kind'] != 'ping' and not host_is_up(db, service, run)
        prior = stability.state_for(db, run, service['id'], service['revision'], service['monitoring_since'])
        previous_status = prior['confirmed'] if prior else None
    try:
        if blocked:
            value, status, error = None, 'blocked', 'Host unavailable'
        else:
            value = read_metric(service)
            status, error = classify(value, service, previous_status), ''
    except Exception as exc:
        value, status = None, 'unreachable'
        # subprocess exceptions include command-line credentials; never persist them.
        error = type(exc).__name__
    with LOCK, connect() as db:
        # Discard in-flight results when the operator changes projects or restores.
        if setting(db, 'active_run') != str(run):
            return
        current = db.execute("""
            SELECT d.address, s.revision, s.monitoring_since, s.measurement_revision FROM services s
            JOIN assignments a ON a.id=s.assignment
            JOIN devices d ON d.id=a.device
            JOIN runs r ON r.project=a.project
            WHERE s.id=? AND r.id=? AND a.monitoring=1 AND a.removed=0 AND s.monitoring=1 AND s.enabled=1
        """, (service['id'], run)).fetchone()
        # Ignore reads made against an old address while an inventory edit was saved.
        if (current is None or current['address'] != service['address']
                or current['revision'] != service['revision']
                or current['monitoring_since'] != service['monitoring_since']):
            return
        # Recheck after network I/O so a concurrent host failure cannot create
        # a child incident from a reading that completed after the failed ping.
        if service['kind'] != 'ping' and not host_is_up(db, service, run):
            value, status, error = None, 'blocked', 'Host unavailable'
        observed_at = time.time()
        db.execute('''INSERT INTO samples
            (run,service,timestamp,value,status,error,revision,display_value,measurement_revision)
            VALUES(?,?,?,?,?,?,?,?,?)''',
            (run, service['id'], observed_at, value, status, error,
             service['revision'], display_value(service, value), current['measurement_revision']))
        if status == 'blocked':
            stability.observe(db, service, run, status, False, observed_at)
            # Preserve existing incidents without claiming recovery; blocked samples
            # break persistence streaks before services resume after host recovery.
            return
        recent = current_samples(db, service['id'], run, service['revision'],
                                 service['monitoring_since'], service['persistence'])
        confirmed = len(recent) == service['persistence'] and all(row['status'] == status for row in recent)
        flap_event = stability.observe(db, service, run, status, confirmed, observed_at)
        if not confirmed:
            return
        incident = db.execute('SELECT * FROM incidents WHERE service=? AND run=? AND closed IS NULL',
                              (service['id'], run)).fetchone()
        if incident and (status == 'healthy' or incident['status'] != status):
            db.execute('UPDATE incidents SET closed=? WHERE id=?', (time.time(), incident['id']))
            if status == 'healthy' and not flap_event:
                notifications.enqueue_incident(db, incident['id'], 'recovery')
            incident = None
        if status != 'healthy' and incident is None:
            number = db.execute('UPDATE runs SET issue_counter=issue_counter+1 WHERE id=? RETURNING issue_counter',
                                (run,)).fetchone()[0]
            cursor = db.execute('''INSERT INTO incidents
                (id,run,service,opened,status,number,trigger_value,trigger_display,
                 trigger_units,trigger_timestamp,trigger_error) VALUES(?,?,?,?,?,?,?,?,?,?,?)''',
                (next_record_id(db, 'incidents'), run, service['id'], observed_at, status, number,
                 value, 'Host unreachable' if service['kind'] == 'ping' and value is None else display_value(service, value), service['units'] if service['value_type'] == 'metric' else '',
                 observed_at, error))
            if not flap_event:
                notifications.enqueue_incident(db, cursor.lastrowid, 'opened')

        if flap_event:
            notifications.enqueue_flap_event(db, service['id'], run, flap_event)


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
                        WHERE r.id=? AND a.monitoring=1 AND a.removed=0 AND s.monitoring=1 AND s.enabled=1 AND d.address!='' ''', (run,))]
                    cutoff = time.time() - int(setting(db, 'retention_days')) * 86400
                    prune_samples(db, cutoff)
                hosts = {}
                for service in services:
                    hosts.setdefault(service['assignment'], []).append(service)
                list(pool.map(lambda group: poll_host(group, run), hosts.values()))
            except Exception:
                # Keep the scheduler alive; no credentials or raw command lines in logs.
                print('Polling cycle failed', flush=True)
            time.sleep(15)


def acknowledgement_display_name(incident, accounts):
    """Resolve older username-only records without changing their stored audit data.

    A real name captured at acknowledgement time stays authoritative. Older
    records can use the account's full name once it is filled in. Match both ID
    and recorded username so a replacement account cannot inherit attribution.
    """
    recorded = incident.get('acknowledged_by_full_name')
    username = incident.get('acknowledged_by_username')
    if recorded and recorded != username:
        return recorded
    account = accounts.get(incident.get('acknowledged_by_user_id'))
    if account and account['username'] == username and account['full_name']:
        return account['full_name']
    return recorded or username


def snapshot():
    with LOCK, connect() as db:
        result = {table: [dict(row) for row in db.execute('SELECT * FROM ' + table)]
                  for table in ('projects', 'devices', 'assignments', 'runs')}
        project_images = {row['project']: row['digest'] for row in db.execute('SELECT project,digest FROM project_logos')}
        for project in result['projects']:
            project['logo_url'] = logos.logo_url(project['id'], project_images.get(project['id']))
        result['legacy_addresses'] = [dict(row) for row in db.execute(
            'SELECT * FROM legacy_assignment_addresses')]
        # Never send SNMP communities to the browser in the general state response.
        result['services'] = [dict(row) for row in db.execute('''
            SELECT id,assignment,name,kind,target,unit,modbus_function,scale,units,direction,warning,critical,persistence,enabled,revision,measurement_revision,value_type,state_map,monitoring,monitoring_since,flap_enabled,flap_changes,flap_window,flap_stable,hysteresis
            FROM services''')]
        for service in result['services']:
            runtime = stability.state_for(db, int(setting(db, 'active_run')), service['id'],
                                          service['revision'], service['monitoring_since'])
            service['flapping'] = bool(runtime and runtime['flapping'])
        result['service_templates'] = [dict(row) for row in db.execute('''
            SELECT id,name,kind,target,unit,modbus_function,scale,units,direction,warning,critical,persistence,value_type,state_map,flap_enabled,flap_changes,flap_window,flap_stable,hysteresis
            FROM service_templates ORDER BY name
        ''')]
        result['device_service_defaults'] = [dict(row) for row in db.execute('''
            SELECT id,device,name,kind,target,unit,modbus_function,scale,units,direction,warning,critical,
                   persistence,value_type,state_map,flap_enabled,flap_changes,flap_window,flap_stable,hysteresis FROM device_service_defaults ORDER BY name,id
        ''')]
        for configuration in result['services'] + result['service_templates'] + result['device_service_defaults']:
            configuration['state_map'] = json.loads(configuration['state_map'])
        result['settings'] = dict(db.execute('SELECT key,value FROM settings'))
        # Bound lookups both during ordinary polling and immediately after
        # resuming, when a check may have no eligible readings yet.
        run = int(result['settings']['active_run'])
        result['latest'] = []
        for service in sorted(result['services'], key=lambda row: row['id']):
            result['latest'].extend(dict(row) for row in current_samples(
                db, service['id'], run, service['revision'], service['monitoring_since']))
        result['incidents'] = [dict(row) for row in db.execute(
            'SELECT * FROM incidents ORDER BY id DESC LIMIT 200')]
        # Recovery takes precedence over acknowledgement for list membership.
        # Keep acknowledgement fields/audit intact when moving an issue to Resolved.
        run = int(result['settings']['active_run'])
        predicates = {
            'active': 'closed IS NULL AND acknowledged IS NULL',
            'acknowledged': 'closed IS NULL AND acknowledged IS NOT NULL',
            'resolved': 'closed IS NOT NULL',
        }
        result['incident_lists'] = {}
        for category, predicate in predicates.items():
            limit = '' if category == 'active' else ' LIMIT 200'
            order = 'i.closed DESC,i.id DESC' if category == 'resolved' else 'i.id DESC'
            result['incident_lists'][category] = [dict(row) for row in db.execute(
                f'''SELECT i.* FROM incidents i JOIN services s ON s.id=i.service
                JOIN assignments a ON a.id=s.assignment
                WHERE i.run=? AND a.removed=0 AND s.enabled=1 AND {predicate} ORDER BY {order}{limit}''' ,
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
                        not service['monitoring'] or not host_is_up(db, service, run)
                        or reading is None or reading['status'] in ('blocked','paused','unknown')))
                if suppressed:
                    incident['suppressed'] = True
                    incident['suppressed_reason'] = 'Service monitoring paused' if not service['monitoring'] else 'Awaiting host / service check'
                    if category == 'acknowledged':
                        # Acknowledgement remains the primary list membership.
                        visible.append(incident)
                    else:
                        result['incident_lists']['suppressed'].append(incident)
                else:
                    visible.append(incident)
            result['incident_lists'][category] = visible
        history = {}
        for event in db.execute("""SELECT * FROM incident_acknowledgement_events WHERE incident IN (
            SELECT id FROM incidents WHERE run=? OR id IN (SELECT id FROM incidents ORDER BY id DESC LIMIT 200))
            ORDER BY id""", (run,)):
            entry = dict(event)
            history.setdefault(entry['incident'], []).append(entry)
        # Enrich response copies only: preserve the durable acknowledgement snapshot.
        accounts = {row['id']: dict(row) for row in db.execute('SELECT id,username,full_name FROM users')}
        for incidents in [result['incidents'], *result['incident_lists'].values()]:
            for incident in incidents:
                incident['acknowledged_by_full_name'] = acknowledgement_display_name(incident, accounts)
                incident['acknowledgement_history'] = history.get(incident['id'], [])
                service = configurations.get(incident['service'])
                # Older saved ping failures contain only an internal exception name.
                # Their recorded Unreachable status still gives a clear host state.
                if service and service['kind'] == 'ping' and incident['status'] == 'unreachable' and incident['trigger_value'] is None:
                    incident['trigger_display'] = 'Host unreachable'
        update_card_incidents(result)
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
    # Disabled protocol fields are absent from browser FormData on edit.
    function = body.get('modbus_function', existing['modbus_function'] if existing else 3)
    if type(function) not in (int, str) or str(function) not in ('3', '4'):
        raise ValueError('Choose Holding (03) or Input (04) registers')
    function = int(function)
    unit = int(body.get('unit', existing['unit'] if existing else 1))
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
            if not isinstance(status, str):
                raise ValueError('State severity must be text')
            status = status.strip().lower()
            if not label or len(label) > 100 or any(c in label for c in '|\r\n') or status not in ('healthy', 'warning', 'critical'):
                raise ValueError('Invalid state label or severity')
            normalized[numeric_key] = {'label': label, 'status': status}
        # State codes are interpreted before scaling and have no numeric thresholds.
        scale, warning, critical = 1, None, None
    return (name, kind, target, community, unit, scale, body.get('units', ''),
            direction, warning, critical, persistence, value_type, json.dumps(normalized),
            *stability.policy_details({**body, 'value_type': value_type}, existing), function)


def reusable_service(db, service_id):
    """Only configured, enabled services can be copied or saved as templates."""
    row = db.execute('SELECT s.* FROM services s JOIN assignments a ON a.id=s.assignment WHERE s.id=? AND s.enabled=1 AND a.removed=0',
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
    if not db.execute('SELECT id FROM assignments WHERE id=? AND removed=0', (assignment_id,)).fetchone():
        raise ValueError('Unknown target host')
    columns = ','.join(SERVICE_CONFIGURATION_FIELDS)
    values = ','.join('?' for _ in SERVICE_CONFIGURATION_FIELDS)
    db.execute(f'INSERT INTO services(id,assignment,{columns}) VALUES(?,?,{values})',
               (next_record_id(db, 'services'), assignment_id, *details))


def duplicate_project(db, source_id, name):
    """Copy current configuration against shared inventory, with fresh history."""
    name = name.strip()
    if not name or len(name) > 100:
        raise ValueError('Project names must contain 1–100 characters')
    source = db.execute('SELECT * FROM projects WHERE id=?', (source_id,)).fetchone()
    if source is None:
        raise ValueError('Unknown source project')
    project = next_record_id(db, 'projects')
    db.execute('INSERT INTO projects(id,name,status_ack_enabled) VALUES(?,?,?)',
               (project, name, source['status_ack_enabled']))
    db.execute("""INSERT INTO project_logos(project,image,mime,digest)
        SELECT ?,image,mime,digest FROM project_logos WHERE project=?""", (project, source_id))
    for assignment in db.execute('SELECT * FROM assignments WHERE project=? AND removed=0', (source_id,)).fetchall():
        target = next_record_id(db, 'assignments')
        db.execute("""INSERT INTO assignments
            (id,project,device,alias,monitoring,visible,notifications) VALUES(?,?,?,?,?,?,?)""",
            (target, project, assignment['device'], assignment['alias'], assignment['monitoring'],
             assignment['visible'], assignment['notifications']))
        fields = (*SERVICE_CONFIGURATION_FIELDS, 'monitoring')
        for service in db.execute('SELECT * FROM services WHERE assignment=? AND enabled=1', (assignment['id'],)).fetchall():
            values = (next_record_id(db, 'services'), target, *(service[field] for field in fields))
            db.execute('INSERT INTO services(id,assignment,' + ','.join(fields) + ') VALUES(' +
                       ','.join('?' for _ in values) + ')', values)
    ensure_host_checks(db)


def change_status_acknowledgement(db, incident_id, actor, undo=False, expected_revision=None):
    """Enforce active-project opt-in and the same public incident visibility rules."""
    condition = "i.acknowledged IS NOT NULL" if undo else "i.closed IS NULL"
    row = db.execute(f"""SELECT i.*,s.assignment,s.kind,s.revision,s.monitoring_since,d.address
        FROM incidents i JOIN services s ON s.id=i.service
        JOIN assignments a ON a.id=s.assignment JOIN projects p ON p.id=a.project
        JOIN devices d ON d.id=a.device JOIN runs r ON r.project=p.id AND r.id=i.run
        JOIN settings setting ON setting.key='active_run' AND r.id=CAST(setting.value AS INTEGER)
        WHERE i.id=? AND {condition} AND p.status_ack_enabled=1
          AND a.visible=1 AND a.monitoring=1 AND a.removed=0 AND s.enabled=1 AND s.monitoring=1""", (incident_id,)).fetchone()
    if not row:
        raise ValueError('Status acknowledgement disabled or issue unavailable')
    if row['closed'] is None and row['kind'] != 'ping':
        latest = db.execute("""SELECT status FROM samples WHERE service=? AND run=? AND revision=?
            AND timestamp>=? ORDER BY id DESC LIMIT 1""",
            (row['service'], row['run'], row['revision'], row['monitoring_since'])).fetchone()
        if not host_is_up(db, row, row['run']) or not latest or latest[0] in ('blocked','paused','unknown'):
            raise ValueError('Service issue is suppressed')
    if undo:
        return record_unacknowledgement(db, incident_id, actor, expected_revision)
    return record_acknowledgement(db, incident_id, actor)


def acknowledge_status_incident(db, incident_id, actor):
    return change_status_acknowledgement(db, incident_id, actor)


def mutate(action, body, actor=None):
    acknowledgement_changed = False
    created_project = None
    created_device = None
    with LOCK, connect() as db:
        deletion = project_deletion.unfinished(db)
        operational = ('ack', 'status-ack', 'unack', 'status-unack', 'pause', 'resume', 'notification-pause', 'project-delete')
        if deletion and (action not in operational or
                         (action == 'resume' and int(body['project']) == deletion['project'])):
            raise project_deletion.DeletionError('Project deletion is in progress. Configuration changes are unavailable until it finishes or is retried.')
        if action == 'project-delete':
            job = project_deletion.request(db, int(body['project']), body['expected_name'])
            return {'job': job}
        elif action == 'project':
            name = body['name'].strip()
            if not name or len(name) > 100:
                raise ValueError('Project names must contain 1–100 characters')
            project = next_record_id(db, 'projects')
            db.execute('INSERT INTO projects(id,name,status_ack_enabled) VALUES(?,?,1)', (project, name))
            created_project = project
            source_logo = body.get('logo_project')
            if source_logo not in (None, ''):
                # Copy image data, not a link to another project's mutable branding.
                cursor = db.execute('''INSERT INTO project_logos(project,image,mime,digest)
                    SELECT ?,image,mime,digest FROM project_logos WHERE project=?''',
                    (project, int(source_logo)))
                if cursor.rowcount != 1:
                    raise ValueError('Selected uploaded logo is no longer available')
        elif action == 'project-duplicate':
            duplicate_project(db, int(body['project']), body['name'])
        elif action == 'project-status-settings':
            if type(body['enabled']) is not bool:
                raise ValueError('Enabled must be true or false')
            cursor = db.execute('UPDATE projects SET status_ack_enabled=? WHERE id=?',
                                (int(body['enabled']), int(body['project'])))
            if cursor.rowcount != 1:
                raise ValueError('Unknown project')
        elif action == 'status-unack':
            acknowledgement_changed = change_status_acknowledgement(db, int(body['id']), actor, undo=True, expected_revision=body.get('expected_revision'))
        elif action == 'status-ack':
            acknowledgement_changed = acknowledge_status_incident(db, int(body['id']), actor)
        elif action == 'project-edit':
            name = body['name'].strip()
            if not name or len(name) > 100:
                raise ValueError('Project names must contain 1–100 characters')
            cursor = db.execute('UPDATE projects SET name=? WHERE id=?', (name, int(body['project'])))
            if cursor.rowcount != 1:
                raise ValueError('Unknown project')
        elif action == 'project-logo-remove':
            db.execute('DELETE FROM project_logos WHERE project=?', (int(body['project']),))
        elif action == 'device':
            details = device_details(body)
            require_unique_inventory_address(db, details[2])
            db.execute('INSERT INTO devices(id,name,model,address) VALUES(?,?,?,?)',
                       (next_record_id(db, 'devices'), *details))
        elif action == 'device-edit':
            device = int(body['device'])
            require_inventory_device(db, device)
            details = device_details(body)
            require_unique_inventory_address(db, details[2], excluding_device=device)
            cursor = db.execute('UPDATE devices SET name=?,model=?,address=? WHERE id=?',
                                (*details, int(body['device'])))
            if cursor.rowcount != 1:
                raise ValueError('Unknown device')
        elif action == 'delete-device':
            delete_device(db, int(body['device']))
        elif action == 'device-address':
            device = int(body['device'])
            require_inventory_device(db, device)
            address = inventory_address(body['address'])
            require_unique_inventory_address(db, address, excluding_device=device)
            db.execute('UPDATE devices SET address=? WHERE id=?', (address, device))
        elif action == 'device-duplicate':
            source = db.execute('SELECT * FROM devices WHERE id=?', (int(body['device']),)).fetchone()
            if source is None:
                raise ValueError('Source inventory device no longer exists')
            details = device_details({**body, 'model': body.get('model', source['model'])})
            require_unique_inventory_address(db, details[2])
            created_device = next_record_id(db, 'devices')
            db.execute('INSERT INTO devices(id,name,model,address) VALUES(?,?,?,?)', (created_device, *details))
            # Copy complete independent defaults, including credentials; never copy
            # assignments, project services, samples, issues or runtime state.
            for default in db.execute('SELECT * FROM device_service_defaults WHERE device=? ORDER BY id', (source['id'],)).fetchall():
                save_inventory_default(db, created_device, tuple(default[field] for field in SERVICE_CONFIGURATION_FIELDS))
        elif action == 'assignment':
            project, device = int(body['project']), int(body['device'])
            require_inventory_device(db, device)
            if not db.execute('SELECT 1 FROM projects WHERE id=?', (project,)).fetchone():
                raise ValueError('Unknown project')
            previous = db.execute('SELECT id FROM assignments WHERE project=? AND device=? AND removed=1',
                                  (project, device)).fetchone()
            if previous:
                # Reassigning restores the former configuration and history.
                db.execute('UPDATE assignments SET alias=?,removed=0,monitoring=1,visible=1 WHERE id=?',
                           (body['alias'], previous['id']))
                db.execute('UPDATE services SET monitoring_since=? WHERE assignment=?',
                           (time.time(), previous['id']))
            else:
                assignment = next_record_id(db, 'assignments')
                db.execute('INSERT INTO assignments(id,project,device,alias) VALUES(?,?,?,?)',
                           (assignment, project, device, body['alias']))
                # Only genuinely new assignments receive defaults. Reassignment and
                # project duplication retain the event's own existing configuration.
                for default in db.execute('SELECT * FROM device_service_defaults WHERE device=? ORDER BY id', (device,)):
                    insert_service(db, assignment, service_details(dict(default)))
            ensure_host_checks(db)
        elif action == 'assignment-remove':
            cursor = db.execute('UPDATE assignments SET removed=1,monitoring=0,visible=0 WHERE id=? AND removed=0',
                                (int(body['assignment']),))
            if cursor.rowcount != 1:
                raise ValueError('Unknown project assignment')
            db.execute('''UPDATE notification_outbox SET state='cancelled',error='Host removed from project'
                WHERE state='pending' AND incident IN (
                    SELECT i.id FROM incidents i JOIN services s ON s.id=i.service WHERE s.assignment=?)''',
                (int(body['assignment']),))
        elif action == 'assignment-edit':
            alias = body['alias'].strip()
            if not alias or len(alias) > 100:
                raise ValueError('Alias must contain 1–100 characters')
            cursor = db.execute('UPDATE assignments SET alias=? WHERE id=? AND removed=0',
                                (alias, int(body['assignment'])))
            if cursor.rowcount != 1:
                raise ValueError('Unknown project assignment')
        elif action == 'toggle':
            field = body['field']
            if field not in ('monitoring', 'visible', 'notifications'):
                raise ValueError('Invalid control')
            db.execute(f'UPDATE assignments SET {field}=1-{field} WHERE id=? AND removed=0', (int(body['id']),))
        elif action == 'activate':
            description = body.get('description')
            if not isinstance(description, str) or not 1 <= len(description.strip()) <= 500:
                raise ValueError('Enter a deployment description of 1–500 characters')
            project = int(body['project'])
            if not db.execute('SELECT id FROM projects WHERE id=?', (project,)).fetchone():
                raise ValueError('Unknown project')
            cursor = db.execute('INSERT INTO runs(id,project,started,description) VALUES(?,?,?,?)',
                                (next_record_id(db, 'runs'), project, time.time(), description.strip()))
            # Select the deployment without starting checks or sending messages.
            # The existing global Resume action is the explicit monitoring opt-in.
            db.execute("UPDATE settings SET value='0' WHERE key='active_run'")
            db.execute("INSERT OR REPLACE INTO settings VALUES ('paused_run',?)", (str(cursor.lastrowid),))
            # Each deployment requires an explicit decision to enable delivery.
            notifications.set_paused(db, True)
        elif action == 'pause':
            run = setting(db, 'active_run')
            # Repeated Pause clicks must not discard the resumable deployment.
            if run != '0':
                db.execute("INSERT OR REPLACE INTO settings VALUES ('paused_run',?)", (run,))
                db.execute("UPDATE settings SET value='0' WHERE key='active_run'")
        elif action == 'resume':
            if setting(db, 'active_run') != '0':
                raise ValueError('Monitoring is already active')
            run = db.execute('SELECT id,project FROM runs WHERE id=?',
                             (setting(db, 'paused_run'),)).fetchone()
            if not run or run['project'] != int(body['project']):
                raise ValueError('Select the paused project to resume monitoring')
            # Fresh reads are required after a pause. This also rejects network
            # results still in flight from before the pause, without erasing history.
            db.execute("""UPDATE services SET monitoring_since=? WHERE assignment IN
                (SELECT id FROM assignments WHERE project=?)""", (time.time(), run['project']))
            db.execute("UPDATE settings SET value=? WHERE key='active_run'", (str(run['id']),))
            db.execute("INSERT OR REPLACE INTO settings VALUES ('paused_run','0')")
        elif action == 'resume-deployment':
            active = int(setting(db, 'active_run'))
            if active != int(body['expected_active_run']):
                raise ValueError('Active deployment changed; review the selection again')
            run = db.execute('SELECT id,project FROM runs WHERE id=? AND project=?',
                             (int(body['run']), int(body['project']))).fetchone()
            if not run or active == run['id']:
                raise ValueError('Choose an inactive deployment for the selected project')
            # Resume with current project configuration; retain original metadata,
            # issue counters and history, but invalidate stale/in-flight readings.
            db.execute("""UPDATE services SET monitoring_since=? WHERE assignment IN
                (SELECT id FROM assignments WHERE project=?)""", (time.time(), run['project']))
            db.execute("UPDATE settings SET value='0' WHERE key='active_run'")
            db.execute("INSERT OR REPLACE INTO settings VALUES ('paused_run',?)", (str(run['id']),))
            notifications.set_paused(db, True)
        elif action == 'delete-deployment':
            active = int(setting(db, 'active_run'))
            target = int(body['run'])
            if active != int(body['expected_active_run']):
                raise ValueError('Active deployment changed; review the selection again')
            if not db.execute('SELECT 1 FROM runs WHERE id=? AND project=?',
                              (target, int(body['project']))).fetchone():
                raise ValueError('Unknown deployment for the selected project')
            if target == active:
                raise ValueError('Pause monitoring before deleting the active deployment')
            # Remove only this run's records. Service configs and other runs survive.
            db.execute('DELETE FROM notification_outbox WHERE incident IN (SELECT id FROM incidents WHERE run=?)', (target,))
            db.execute('DELETE FROM samples WHERE run=?', (target,))
            db.execute('DELETE FROM incidents WHERE run=?', (target,))
            db.execute('DELETE FROM runs WHERE id=?', (target,))
            if setting(db, 'paused_run') == str(target):
                db.execute("UPDATE settings SET value='0' WHERE key='paused_run'")
        elif action == 'ack':
            acknowledgement_changed = record_acknowledgement(db, int(body['id']), actor)
        elif action == 'unack':
            acknowledgement_changed = record_unacknowledgement(db, int(body['id']), actor, body.get('expected_revision'))
        elif action == 'notification-pause':
            notifications.set_paused(db, body['paused'])
        elif action == 'reminder-settings':
            minutes = body['minutes']
            if type(minutes) is not int or not 0 <= minutes <= 10080:
                raise ValueError('Reminder interval must be 0–10080 whole minutes')
            db.execute("INSERT OR REPLACE INTO settings VALUES ('reminder_minutes',?)", (str(minutes),))
            db.execute("""UPDATE notification_outbox SET state='cancelled',error='Reminder interval changed'
                WHERE event LIKE 'reminder:%' AND state='pending'""")
        elif action == 'session-settings':
            hours = body['hours']
            if type(hours) is not int or not 1 <= hours <= 168:
                raise ValueError('Session duration must be 1–168 whole hours')
            db.execute("INSERT OR REPLACE INTO settings VALUES ('session_hours',?)", (str(hours),))
        elif action == 'retention':
            days = int(body['days'])
            if not 1 <= days <= 3650:
                raise ValueError('Retention must be 1–3650 days')
            db.execute("UPDATE settings SET value=? WHERE key='retention_days'", (str(days),))
        elif action in ('device-default-create', 'device-default-edit'):
            device = int(body['device'])
            existing = None
            if action == 'device-default-edit':
                existing = db.execute('SELECT * FROM device_service_defaults WHERE id=? AND device=?',
                                      (int(body['default_service']), device)).fetchone()
                if not existing:
                    raise ValueError('Unknown device service default')
            save_inventory_default(db, device, service_details(body, existing),
                                   existing['id'] if existing else None)
        elif action == 'device-default-delete':
            cursor = db.execute('DELETE FROM device_service_defaults WHERE id=? AND device=?',
                                (int(body['default_service']), int(body['device'])))
            if cursor.rowcount != 1:
                raise ValueError('Unknown device service default')
        elif action == 'device-default-from-template':
            template = library_template(db, body['template'])
            configuration = dict(template)
            if 'name' in body:
                if not isinstance(body['name'], str):
                    raise ValueError('Service name must be text')
                configuration['name'] = body['name']
            save_inventory_default(db, int(body['device']), service_details(configuration))
        elif action == 'device-defaults-from-assignment':
            replace_defaults_from_assignment(db, int(body['device']), int(body['assignment']))
        elif action == 'service':
            details = service_details(body)
            insert_service(db, int(body['assignment']), details)
        elif action == 'service-edit':
            service_id = int(body['service'])
            existing = db.execute('SELECT s.* FROM services s JOIN assignments a ON a.id=s.assignment WHERE s.id=? AND s.enabled=1 AND a.removed=0',
                                  (service_id,)).fetchone()
            if existing is None or existing['kind'] == 'ping':
                raise ValueError('Unknown service or managed host check')
            details = service_details(body, existing)
            # Retain identity/history but start persistence counting for the new config.
            setters = ','.join(field + '=?' for field in SERVICE_CONFIGURATION_FIELDS)
            updated = dict(zip(SERVICE_CONFIGURATION_FIELDS, details))
            changed = history.measurement_changed(existing, updated)
            if changed:
                history.remember_measurement(db, existing)
            db.execute(f'UPDATE services SET {setters},revision=revision+1,measurement_revision=measurement_revision+? WHERE id=?',
                       (*details, int(changed), service_id))
        elif action == 'service-copy':
            source = reusable_service(db, body['service'])
            assignment = int(body['assignment'])
            if assignment == source['assignment']:
                raise ValueError('Choose a different target host')
            configuration = dict(source)
            configuration['name'] = body.get('name', source['name'])
            configuration['community'] = body.get('community') or source['community']
            insert_service(db, assignment, service_details(configuration))
        elif action in ('inventory-preview', 'inventory-import'):
            if not isinstance(body, dict):
                raise inventory_transfer.InventoryImportError('Choose an inventory file and import mode.')
            validator = lambda entry: device_details(entry, allow_unconfigured=True)
            if action == 'inventory-preview':
                return inventory_transfer.preview_document(db, body.get('inventory'), body.get('mode'), validator, service_details)
            return inventory_transfer.import_document(db, body.get('inventory'), body.get('mode'), body.get('token'),
                validator, service_details, next_record_id, save_inventory_default)
        elif action == 'library-import':
            if not isinstance(body, dict):
                raise service_library.LibraryImportError('Choose a library file and Merge or Replace mode.')
            return service_library.import_document(db, body.get('library'), body.get('mode'), service_details)
        elif action == 'template-create':
            # Saving from a service retains its secret on the server. The browser
            # only sends non-secret fields and an optional replacement community.
            source = reusable_service(db, body['source']) if body.get('source') else None
            details = service_details(body, source)
            columns = ','.join(SERVICE_CONFIGURATION_FIELDS)
            values = ','.join('?' for _ in SERVICE_CONFIGURATION_FIELDS)
            db.execute(f'INSERT INTO service_templates({columns}) VALUES({values})', details)
        elif action == 'template-edit':
            source = library_template(db, body['template'])
            details = service_details(body, source)
            setters = ','.join(field + '=?' for field in SERVICE_CONFIGURATION_FIELDS)
            db.execute(f'UPDATE service_templates SET {setters} WHERE id=?', (*details, source['id']))
        elif action == 'template-delete':
            source = library_template(db, body['template'])
            db.execute('DELETE FROM service_templates WHERE id=?', (source['id'],))
        elif action == 'template-apply':
            source = library_template(db, body['template'])
            configuration = dict(source)
            configuration['name'] = body.get('name', source['name'])
            configuration['community'] = body.get('community') or source['community']
            insert_service(db, int(body['assignment']), service_details(configuration))
        elif action == 'host-stability':
            host = db.execute("""SELECT s.* FROM services s JOIN assignments a ON a.id=s.assignment
                WHERE s.id=? AND s.kind='ping' AND s.enabled=1 AND a.removed=0""", (int(body['service']),)).fetchone()
            if not host:
                raise ValueError('Unknown managed host check')
            policy = stability.policy_details({**body, 'hysteresis': 0}, host)
            db.execute("""UPDATE services SET flap_enabled=?,flap_changes=?,flap_window=?,flap_stable=?,hysteresis=?,
                revision=revision+1 WHERE id=?""", (*policy, host['id']))
        elif action == 'service-monitoring':
            service = reusable_service(db, body['service'])
            enabled = body['monitoring']
            if type(enabled) is not bool:
                raise ValueError('Monitoring must be true or false')
            if bool(service['monitoring']) != enabled:
                changed = time.time()
                db.execute('UPDATE services SET monitoring=?,monitoring_since=? WHERE id=?',
                           (int(enabled), changed, service['id']))
                if not enabled:
                    db.execute('''UPDATE notification_outbox SET state='cancelled',error='Service monitoring paused'
                        WHERE state='pending' AND incident IN (SELECT id FROM incidents WHERE service=?)''',
                        (service['id'],))
                run = int(setting(db, 'active_run'))
                project = db.execute('SELECT project FROM assignments WHERE id=?', (service['assignment'],)).fetchone()[0]
                active = db.execute('SELECT project FROM runs WHERE id=?', (run,)).fetchone()
                if active and active[0] == project:
                    # Explicit gaps preserve history and prevent alerts spanning a pause.
                    db.execute("""INSERT INTO samples
                        (run,service,timestamp,value,status,error,revision,display_value,measurement_revision)
                        VALUES(?,?,?,NULL,?,'',?,NULL,?)""",
                        (run, service['id'], changed, 'unknown' if enabled else 'paused', service['revision'], service['measurement_revision']))
        elif action == 'remove-service':
            # Keep ownership for history and later full-device deletion.
            db.execute("UPDATE services SET enabled=0 WHERE id=? AND kind!='ping'",
                       (int(body['id']),))
        else:
            raise ValueError('Unknown action')
    # All listeners must see committed state, including changes from other users.
    # Duplicate acknowledgements and rejected/rolled-back actions emit nothing.
    if acknowledgement_changed:
        live_updates.publish_acknowledgement_change()
    if created_project is not None:
        return {'project': created_project}
    if created_device is not None:
        return {'device': created_device}


def update_card_incidents(data):
    """Roll up confirmed open incidents, including acknowledged unresolved faults."""
    priorities = {'warning': 1, 'critical': 2, 'unreachable': 2}
    run = next((row for row in data['runs'] if row['id'] == int(data['settings']['active_run'])), None)
    assignments = {row['id']: row for row in data['assignments']}
    services = {row['id']: row for row in data['services']}
    latest = {row['service']: row for row in data['latest']}
    online = {}
    for assignment in assignments.values():
        assignment['incident_status'] = None
    for service in services.values():
        if service['kind'] == 'ping':
            sample = latest.get(service['id'])
            online[service['assignment']] = sample['status'] if (
                sample and time.time() - sample['timestamp'] <= 60) else 'unknown'
    candidates = data['incident_lists']['active'] + data['incident_lists']['acknowledged']
    for incident in candidates:
        service = services.get(incident['service'])
        assignment = assignments.get(service['assignment']) if service else None
        if (not run or not assignment or not assignment['monitoring'] or not service['enabled'] or not service['monitoring'] or assignment['removed']
                or assignment['project'] != run['project'] or incident['closed'] or incident.get('suppressed')):
            continue
        host = online.get(assignment['id'], 'unknown')
        if host == 'unknown' or (service['kind'] != 'ping' and host != 'healthy'):
            continue
        level = 'critical' if priorities.get(incident['status'], 0) == 2 else incident['status']
        if priorities.get(level, 0) > priorities.get(assignment['incident_status'], 0):
            assignment['incident_status'] = level


def status_overview(include_hosts=False):
    """Allowlist status output; live hosts require an authorised session at the caller."""
    data = snapshot()
    run = next((row for row in data['runs'] if row['id'] == int(data['settings']['active_run'])), None)
    if run is None:
        # Pausing stops public live readings, but retains the event branding.
        paused = next((row for row in data['runs']
                       if row['id'] == int(data['settings'].get('paused_run', '0'))), None)
        project = next((row for row in data['projects'] if paused and row['id'] == paused['project']), None)
        logo_url = project['logo_url'] if project else None
        return {'project': project['name'] if project else None,
                'logo_url': logo_url.replace('/api/project-logo?', '/api/public-logo?') if logo_url else None,
                'deployment': paused['id'] if paused else None,
                'monitoring_paused': True, 'devices': [], 'incidents': [],
                'acknowledged_incidents': [], 'acknowledge_enabled': False, 'updated': time.time()}
    project = next(row for row in data['projects'] if row['id'] == run['project'])
    devices = {row['id']: row for row in data['devices']}
    latest = {row['service']: row for row in data['latest']}
    output = []
    for assignment in (data['assignments'] if include_hosts else ()):
        if assignment['project'] != run['project'] or not assignment['visible'] or assignment['removed']:
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
            status = 'paused' if not service['monitoring'] else sample['status'] if usable else 'blocked'
            children.append({'name': service['name'], 'status': status,
                'value': sample['display_value'] if usable and status not in ('blocked','paused') else None,
                'units': service['units'] if service['value_type'] == 'metric' else '',
                'flapping': service['flapping']})
        output.append({'name': device['name'], 'alias': assignment['alias'],
                       'status': host_status, 'services': children, 'flapping': bool(ping and ping['flapping']),
                       'incident_status': assignment['incident_status']})
    # Both public lists use the same visibility rules. Only the recorded actor
    # display name and username are public; account IDs and other account details remain private.
    assignments = {row['id']: row for row in data['assignments']
                   if row['project'] == run['project'] and row['visible']
                   and row['monitoring'] and not row['removed']}
    services = {row['id']: row for row in data['services'] if row['enabled'] and row['monitoring']}

    def public_incidents(category):
        output = []
        for incident in data['incident_lists'][category]:
            service = services.get(incident['service'])
            assignment = assignments.get(service['assignment']) if service else None
            if assignment is None or incident.get('suppressed'):
                continue
            item = {'id': incident['id'], 'number': incident['number'], 'device': devices[assignment['device']]['name'],
                'alias': assignment['alias'], 'service': service['name'],
                'status': incident['status'], 'opened': incident['opened']}
            item.update({key: incident.get(key) for key in ('trigger_value', 'trigger_display',
                         'trigger_units', 'trigger_timestamp', 'trigger_error')})
            if category == 'acknowledged':
                item.update(acknowledged=incident['acknowledged'], closed=incident['closed'], ack_revision=incident['ack_revision'],
                            acknowledged_by_username=incident['acknowledged_by_username'],
                            acknowledged_by_full_name=incident['acknowledged_by_full_name'])
            output.append(item)
        return output

    incidents = public_incidents('active')
    acknowledged = public_incidents('acknowledged')
    return {'project': project['name'], 'deployment': run['id'], 'monitoring_paused': False,
            'logo_url': project['logo_url'].replace('/api/project-logo?', '/api/public-logo?') if project['logo_url'] else None, 'devices': output,
            'incidents': incidents, 'acknowledged_incidents': acknowledged, 'acknowledge_enabled': bool(project['status_ack_enabled']), 'updated': time.time()}


class Handler(BaseHTTPRequestHandler):
    def send(self, content, mime='application/json', status=200, filename=None):
        if not isinstance(content, bytes):
            content = content.encode()
        self.send_response(status)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(content)))
        self.send_header('Cache-Control', 'no-store')
        if filename:
            self.send_header('Content-Disposition', f'attachment; filename="{filename}"')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        self.wfile.write(content)

    def redirect(self, destination):
        """Redirect without caching account-dependent routing or response bodies."""
        self.send_response(303)
        self.send_header('Location', destination)
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', '0')
        self.end_headers()

    def require_user(self, admin=False, allow_password_change=False, roles=None):
        with connect() as db:
            user = auth.session_user(db, self.headers.get('Cookie'))
        if user is None:
            self.send('{"error":"Login required"}', status=401)
            return None
        if user['must_change_password'] and not allow_password_change:
            self.send('{"error":"Change your temporary password first"}', status=403)
            return None
        if (admin and user['role'] != 'admin') or (roles is not None and user['role'] not in roles):
            message = 'Administrator access required' if admin else 'Admin or Operator access required'
            self.send(json.dumps({'error': message}), status=403)
            return None
        return user

    def session_response(self, token=None):
        self.send_response(200)
        with connect() as db:
            lifetime = auth.session_seconds(db) if token else 0
        cookie = 'monitor_session=' + (token or '') + '; Path=/; HttpOnly; SameSite=Strict; Max-Age=' + str(lifetime)
        if os.environ.get('MONITOR_SECURE_COOKIE') == 'true':
            cookie += '; Secure'
        self.send_header('Set-Cookie', cookie)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(b'{"ok":true}')

    def send_logo(self, public=False):
        try:
            project = int(parse_qs(urlsplit(self.path).query)['project'][0])
            with connect() as db:
                if public:
                    # Only the current event is public, whether running or paused.
                    run = setting(db, 'active_run')
                    if run == '0':
                        run = setting(db, 'paused_run')
                    active = db.execute('SELECT project FROM runs WHERE id=?', (run,)).fetchone()
                    if not active or active['project'] != project:
                        return self.send('{"error":"Not found"}', status=404)
                row = db.execute('SELECT image,mime FROM project_logos WHERE project=?', (project,)).fetchone()
            if row:
                return self.send(row['image'], row['mime'])
        except (KeyError, ValueError):
            pass
        self.send('{"error":"Not found"}', status=404)

    def stream_acknowledgement_changes(self):
        """Public invalidation stream: no issue IDs, actors, credentials or metrics."""
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Accel-Buffering', 'no')
        self.end_headers()
        revision = live_updates.current_revision()
        try:
            # Initial state also refreshes reconnecting clients after missed events.
            self.wfile.write(('retry: 1000\ndata: ' + json.dumps({'revision': revision}) + '\n\n').encode())
            self.wfile.flush()
            while True:
                updated = live_updates.wait_for_change(revision)
                payload = (': keepalive\n\n' if updated == revision else
                           'data: ' + json.dumps({'revision': updated}) + '\n\n')
                self.wfile.write(payload.encode())
                self.wfile.flush()
                revision = updated
        except OSError:
            # Disconnections are normal. EventSource reconnects automatically.
            pass

    def do_GET(self):
        if self.path == '/api/ack-events':
            return self.stream_acknowledgement_changes()
        if self.path.startswith('/api/public-logo?'):
            return self.send_logo(public=True)
        if self.path == '/api/health':
            return self.send('{"ok":true}')
        page = urlsplit(self.path)
        if page.path in ('/login', '/change-password'):
            # Preserve the originating dashboard, but never redirect to arbitrary URLs.
            requested = parse_qs(page.query).get('next', ['/'])[0]
            destination = '/status' if requested == '/status' else '/'
            suffix = '?next=%2Fstatus' if destination == '/status' else ''
            with connect() as db:
                user = auth.session_user(db, self.headers.get('Cookie'))
            if page.path == '/login' and user:
                return self.redirect('/change-password' + suffix
                                     if user['must_change_password'] else destination)
            if page.path == '/change-password' and not user:
                return self.redirect('/login' + suffix)
            filename = 'login.html' if page.path == '/login' else 'change-password.html'
            return self.send(Path(__file__).with_name(filename).read_bytes(), 'text/html; charset=utf-8')
        if self.path == '/status':
            return self.send(Path(__file__).with_name('status.html').read_bytes(), 'text/html; charset=utf-8')
        if self.path == '/api/status':
            with connect() as db:
                user = auth.session_user(db, self.headers.get('Cookie'))
            can_view_hosts = bool(user and not user['must_change_password'])
            overview = status_overview(include_hosts=can_view_hosts)
            overview['can_view_hosts'] = can_view_hosts
            presence.tracker.record(self.headers.get('X-Dashboard-Connection'), user)
            can_acknowledge = bool(overview['acknowledge_enabled'] and user
                and not user['must_change_password'] and user['role'] in ('admin','operator'))
            # Return only the caller's identity, never the account list.
            overview['viewer'] = ({'username': user['username'], 'full_name': user['full_name'], 'role': user['role'],
                'must_change_password': bool(user['must_change_password'])} if user else None)
            overview['can_acknowledge'] = can_acknowledge
            if can_acknowledge:
                overview['csrf'] = user['csrf']
            return self.send(json.dumps(overview))
        if self.path == '/':
            with connect() as db:
                user = auth.session_user(db, self.headers.get('Cookie'))
            if not user or user['must_change_password']:
                return self.redirect('/change-password' if user else '/login')
            return self.send(Path(__file__).with_name('index.html').read_bytes(), 'text/html; charset=utf-8')
        if self.path == '/api/me':
            user = self.require_user(allow_password_change=True)
            if user:
                return self.send(json.dumps({**auth.public_user(user), 'csrf': user['csrf']}))
            return
        admin = self.path in ('/api/users', '/api/backup', '/api/telegram', '/api/whatsapp', '/api/telegram-chats', '/api/library-export', '/api/inventory-export')
        user = self.require_user(admin=admin)
        if not user:
            return
        if self.path.startswith('/api/project-logo?'):
            return self.send_logo()
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
            presence.tracker.record(self.headers.get('X-Dashboard-Connection'), user)
            state = snapshot()
            if user['role'] == 'admin':
                with connect() as db:
                    sessions = dict(db.execute('SELECT csrf,user_id FROM sessions WHERE expires>?',
                                               (time.time(),)))
                state['dashboard_presence'] = presence.tracker.counts(sessions)
                with connect() as db:
                    state['project_deletions'] = [dict(row) for row in db.execute(
                        'SELECT * FROM project_deletions ORDER BY id DESC LIMIT 20')]
            self.send(json.dumps(state))
        elif self.path == '/api/inventory-export':
            with LOCK, connect() as db:
                document = inventory_transfer.export_document(db)
            stamp = time.strftime('%Y-%m-%d_%H-%M-%S', time.localtime())
            self.send(json.dumps(document, ensure_ascii=False, indent=2), 'application/json',
                      filename=f'network-monitor-inventory-{stamp}.json')
        elif self.path == '/api/library-export':
            with connect() as db:
                payload = json.dumps(service_library.export_document(db), indent=2, ensure_ascii=False, allow_nan=False)
            stamp = time.strftime('%Y-%m-%d_%H-%M-%S', time.localtime())
            self.send(payload, 'application/json; charset=utf-8',
                      filename=f'network-monitor-service-library-{stamp}.json')
        elif self.path == '/api/backup':
            # Exclude live sessions from portable backups.
            with LOCK, connect() as source:
                if project_deletion.unfinished(source):
                    return self.send(json.dumps({'error': 'Finish or retry project deletion before downloading a backup.'}), status=409)
                destination = sqlite3.connect(':memory:')
                source.backup(destination)
                destination.execute('DELETE FROM sessions')
                destination.execute('DELETE FROM login_attempts')
                destination.commit()
                payload = destination.serialize()
                destination.close()
            # Use the monitoring host timezone, shared with the container by Compose.
            stamp = time.strftime('%Y-%m-%d_%H-%M-%S', time.localtime())
            self.send(payload, 'application/octet-stream',
                      filename=f'network-monitor-backup-{stamp}.sqlite3')
        elif self.path.startswith('/api/resolved?'):
            try:
                result = resolved.read(connect, parse_qs(urlsplit(self.path).query), acknowledgement_display_name)
                self.send(json.dumps(result))
            except (resolved.SearchError, KeyError, ValueError, OverflowError) as error:
                message = str(error) if isinstance(error, resolved.SearchError) else 'Invalid resolved issue search.'
                self.send(json.dumps({'error': message}), status=400)
        elif self.path.startswith('/api/history?'):
            try:
                query = parse_qs(urlsplit(self.path).query)
                if 'start' in query or 'end' in query:
                    result = history.read(connect, query)
                else:
                    # Keep the legacy latest-200 response for older clients.
                    with connect() as db:
                        result = [dict(row) for row in db.execute(
                            'SELECT timestamp,value,status,display_value,revision,measurement_revision FROM samples WHERE service=? AND run=? ORDER BY id DESC LIMIT 200',
                            (int(query['service'][0]), int(query['run'][0])))]
                self.send(json.dumps(result))
            except history.HistoryError as error:
                self.send(json.dumps({'error': str(error)}), status=400)
            except (KeyError, ValueError, OverflowError):
                self.send('{"error":"Choose an available service/deployment and a valid time range of up to 31 days."}', status=400)
        else:
            self.send('{"error":"Not found"}', status=404)

    def do_POST(self):
        origin = self.headers.get('Origin')
        if origin and (urlsplit(origin).netloc != self.headers.get('Host', '')
                       or urlsplit(origin).scheme not in ('http', 'https')):
            return self.send('{"error":"Origin rejected"}', status=403)
        user = None
        if self.path != '/api/login':
            user = self.require_user(admin=self.path not in ('/api/logout', '/api/password', '/api/ack', '/api/status-ack', '/api/unack', '/api/status-unack'),
                                     allow_password_change=self.path in ('/api/logout', '/api/password'),
                                     roles=('admin', 'operator') if self.path in ('/api/ack','/api/status-ack','/api/unack','/api/status-unack') else None)
            if not user:
                return
            if not hmac.compare_digest(self.headers.get('X-CSRF-Token', ''), user['csrf']):
                return self.send('{"error":"Invalid request token"}', status=403)
        try:
            size = int(self.headers.get('Content-Length', '0'))
            limit = (64 * 1024 * 1024 if self.path == '/api/restore' else
                     inventory_transfer.MAX_IMPORT_BYTES + 65536 if self.path in ('/api/inventory-preview','/api/inventory-import') else
                     service_library.MAX_IMPORT_BYTES if self.path == '/api/library-import' else
                     logos.MAX_BYTES if self.path.startswith('/api/project-logo?') else 65536)
            if not 0 < size <= limit:
                raise ValueError('Invalid request size')
            payload = self.rfile.read(size)
            if self.path.startswith('/api/project-logo?'):
                project = int(parse_qs(urlsplit(self.path).query)['project'][0])
                with LOCK, connect() as db:
                    if project_deletion.unfinished(db):
                        raise project_deletion.DeletionError('Finish project deletion before changing logos.')
                    logos.save(db, project, payload)
            elif self.path == '/api/restore':
                if self.headers.get('Content-Type') != 'application/octet-stream':
                    raise ValueError('Expected backup file')
                candidate = sqlite3.connect(':memory:')
                try:
                    candidate.deserialize(payload)
                    with LOCK, connect() as current:
                        job = project_deletion.unfinished(current)
                        if job and job['state'] != 'failed':
                            raise project_deletion.DeletionError('Wait for running project deletion before restoring a backup.')
                    if candidate.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                        raise ValueError('Invalid backup')
                    required = {'projects', 'devices', 'assignments', 'services', 'runs', 'settings', 'samples', 'incidents'}
                    tables = {row[0] for row in candidate.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                    if not required.issubset(tables):
                        raise ValueError('Incompatible backup')
                    # Preserve the backed-up deployment for an explicit Resume.
                    if setting(candidate, 'active_run') != '0':
                        candidate.execute("INSERT OR REPLACE INTO settings VALUES ('paused_run',?)",
                                          (setting(candidate, 'active_run'),))
                    candidate.execute("INSERT OR IGNORE INTO settings VALUES ('paused_run','0')")
                    candidate.execute("UPDATE settings SET value='0' WHERE key='active_run'")
                    migrate_inventory_addresses(candidate)
                    migrate_service_lifecycle(candidate)
                    project_deletion.ensure_table(candidate)
                    ensure_service_library(candidate)
                    ensure_inventory_services(candidate)
                    migrate_value_types(candidate)
                    stability.ensure_tables(candidate)
                    migrate_issue_evidence(candidate)
                    ensure_host_checks(candidate)
                    migrate_project_settings(candidate)
                    migrate_incident_acknowledgements(candidate)
                    migrate_issue_numbers(candidate)
                    migrate_deployment_descriptions(candidate)
                    logos.ensure_table(candidate)
                    notifications.ensure_tables(candidate)
                    candidate.execute("UPDATE notification_outbox SET state='cancelled',error='Restored backup' WHERE state IN ('pending','sending')")
                    migrate_modbus_functions(candidate)
                    history.ensure_tables(candidate)
                    resolved.ensure_index(candidate)
                    auth.ensure_accounts(candidate)
                    # Older backups have no accounts: retain current accounts so
                    # restoring equipment cannot silently reset access to a default.
                    if not candidate.execute('SELECT 1 FROM users LIMIT 1').fetchone():
                        with connect() as current:
                            for account in current.execute('SELECT * FROM users'):
                                candidate.execute('''INSERT INTO users
                                    (id,username,password_hash,role,must_change_password,email,full_name)
                                    VALUES(?,?,?,?,?,?,?)''', tuple(account[key] for key in
                                    ('id','username','password_hash','role','must_change_password','email','full_name')))
                    if not candidate.execute("SELECT 1 FROM users WHERE role='admin' LIMIT 1").fetchone():
                        raise ValueError('Backup has no administrator')
                    candidate.execute('DELETE FROM sessions')
                    candidate.execute('DELETE FROM login_attempts')
                    candidate.commit()
                    with LOCK, connect() as destination:
                        job = project_deletion.unfinished(destination)
                        if job and job['state'] != 'failed':
                            raise project_deletion.DeletionError('Wait for running project deletion before restoring a backup.')
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
                            notifications.enqueue_test(db, 'whatsapp' if self.path == '/api/whatsapp-test' else 'telegram',
                                                       body.get('sample_type', 'test'))
                elif self.path.startswith('/api/user-'):
                    if self.path not in ('/api/user-create', '/api/user-edit', '/api/user-delete'):
                        raise ValueError('Unknown action')
                    with LOCK, connect() as db:
                        auth.manage_user(db, self.path.removeprefix('/api/'), body, user)
                else:
                    result = mutate(self.path.removeprefix('/api/'), body, actor=user)
                    if result is not None:
                        return self.send(json.dumps({'ok': True, **result}))
            self.send('{"ok":true}')
        except inventory_transfer.InventoryImportError as error:
            self.send(json.dumps({'error': str(error)}), status=400)
        except InventoryAddressConflict as error:
            self.send(json.dumps({'error': str(error)}), status=400)
        except project_deletion.DeletionError as error:
            self.send(json.dumps({'error': str(error)}), status=400)
        except service_library.LibraryImportError as error:
            self.send(json.dumps({'error': str(error)}), status=400)
        except (ValueError, KeyError, sqlite3.Error, OverflowError, TypeError, RecursionError):
            self.send('{"error":"Request rejected: check values and referenced records"}', status=400)


if __name__ == '__main__':
    initialize()
    threading.Thread(target=poll_loop, daemon=True).start()
    threading.Thread(target=project_deletion.worker, args=(connect, LOCK), daemon=True).start()
    threading.Thread(target=notifications.worker, args=(connect, LOCK, host_is_up), daemon=True).start()
    print('Local monitor listening on port 8080', flush=True)
    ThreadingHTTPServer((os.environ.get('MONITOR_HOST', '0.0.0.0'), 8080), Handler).serve_forever()
