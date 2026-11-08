"""Disk-backed SQLite transfers with bounded memory and session-bound review files.

This module never opens the live monitoring database. The server supplies its
connection/lock and existing migration functions when producing or applying files.
"""
from contextlib import contextmanager, closing
import hmac
import os
from pathlib import Path
import secrets
import shutil
import sqlite3
import tempfile
import threading
import time

CHUNK_BYTES = 1024 * 1024
REVIEW_SECONDS = 15 * 60
CONFIG_TABLES = {
    'projects', 'devices', 'assignments', 'services', 'settings', 'users',
    'service_templates', 'device_service_defaults', 'legacy_assignment_addresses',
    'project_logos', 'telegram_config', 'whatsapp_config',
}
REQUIRED_TABLES = {'projects', 'devices', 'assignments', 'services', 'runs', 'settings', 'samples', 'incidents'}
HISTORY_TABLES = ('samples', 'runs', 'incidents', 'incident_acknowledgement_events',
                  'notification_outbox', 'check_stability', 'service_measurements', 'project_deletions')
SLOT = threading.BoundedSemaphore(1)
_REVIEWS = {}
_REVIEW_LOCK = threading.RLock()


class BackupError(ValueError):
    """Safe, actionable transfer errors; never expose SQL or uploaded values."""

    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def limit_bytes():
    try:
        megabytes = int(os.environ.get('MONITOR_MAX_RESTORE_MB', '20480'))
    except ValueError:
        megabytes = 0
    if not 1 <= megabytes <= 1048576:
        raise BackupError('MONITOR_MAX_RESTORE_MB must be a whole number from 1 to 1048576.')
    return megabytes * CHUNK_BYTES


def check_space(directory, required):
    if shutil.disk_usage(directory).free < required + 64 * CHUNK_BYTES:
        raise BackupError('Not enough free disk space for the transfer and SQLite working files.', 507)


@contextmanager
def transfer():
    if not SLOT.acquire(blocking=False):
        raise BackupError('Another backup or restore transfer is running. Try again after it finishes.', 409)
    try:
        yield
    finally:
        SLOT.release()


def workspace(directory):
    # mkdtemp creates mode 0700. Keeping files beside the database uses its volume,
    # rather than filling a container's writable layer or a RAM-backed /tmp.
    return tempfile.TemporaryDirectory(prefix='.backup-transfer-', dir=directory)


def open_database(path):
    db = sqlite3.connect(path, uri=True)
    db.execute('PRAGMA trusted_schema=OFF')
    db.execute('PRAGMA cache_size=-4096')
    db.execute('PRAGMA temp_store=FILE')
    return db


def tables(db):
    return {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def inspect(db):
    names = tables(db)
    if not REQUIRED_TABLES.issubset(names):
        raise BackupError('Backup is missing required Network Monitor tables.')
    if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
        raise BackupError('SQLite integrity validation failed. The destination was not changed.')
    marker = dict(db.execute("SELECT key,value FROM settings WHERE key IN ('backup_format','backup_kind')"))
    if marker and (marker.get('backup_format') != 'network-monitor-1'
                   or marker.get('backup_kind') not in ('complete', 'configuration')):
        raise BackupError('Unsupported backup metadata.')
    kind = marker.get('backup_kind', 'complete')  # Backwards-compatible SQLite backups.
    has_history = any(name in names and db.execute(f'SELECT 1 FROM "{name}" LIMIT 1').fetchone()
                      for name in HISTORY_TABLES)
    if kind == 'configuration' and has_history:
        raise BackupError('Configuration-only backup contains unexpected history.')
    return {'kind': kind, 'has_history': bool(has_history),
            'projects': db.execute('SELECT COUNT(*) FROM projects').fetchone()[0],
            'devices': db.execute('SELECT COUNT(*) FROM devices').fetchone()[0],
            'users': db.execute('SELECT COUNT(*) FROM users').fetchone()[0] if 'users' in names else 0,
            'modes': ['configuration'] if kind == 'configuration' else ['complete', 'configuration']}


def copy_configuration(source, destination):
    """Copy schema plus allowlisted rows, without reading any history-table rows."""
    known = CONFIG_TABLES | set(HISTORY_TABLES) | {'sessions', 'login_attempts'}
    schema = [row for row in source.execute("""SELECT type,name,tbl_name,sql FROM sqlite_master
        WHERE sql IS NOT NULL AND type IN ('table','index') AND name NOT LIKE 'sqlite_%'
        ORDER BY CASE type WHEN 'table' THEN 0 ELSE 1 END, name""") if row[2] in known]
    for kind, name, table, sql in schema:
        if kind == 'table':
            destination.execute(sql)
    present = tables(source)
    source_path = next(row[2] for row in source.execute('PRAGMA database_list') if row[1] == 'main')
    if not source_path:
        raise BackupError('Configuration copying requires an on-disk source database.')
    destination.execute('ATTACH DATABASE ? AS configuration_source', (Path(source_path).as_uri() + '?mode=ro',))
    for name in sorted(CONFIG_TABLES & present):
        # SQLite copies blobs directly between disk databases. Python never loads
        # a table, logo collection or arbitrarily large field into memory.
        destination.execute(f'INSERT INTO "{name}" SELECT * FROM configuration_source."{name}"')
    if 'sqlite_sequence' in present and 'sqlite_sequence' in tables(destination):
        for name, sequence in source.execute('SELECT name,seq FROM sqlite_sequence'):
            if name in CONFIG_TABLES:
                destination.execute('DELETE FROM sqlite_sequence WHERE name=?', (name,))
                destination.execute('INSERT INTO sqlite_sequence VALUES(?,?)', (name, sequence))
    for kind, name, table, sql in schema:
        if kind == 'index':
            destination.execute(sql)
    destination.commit()
    destination.execute('DETACH DATABASE configuration_source')
    destination.execute("DELETE FROM settings WHERE key LIKE 'benchmark_%' OR key IN ('backup_format','backup_kind')")
    for key, value in (('active_run','0'), ('paused_run','0'), ('notifications_paused','1'), ('notifications_resumed_at','0')):
        destination.execute('INSERT OR REPLACE INTO settings VALUES(?,?)', (key, value))
    destination.commit()


def export(source, path, kind):
    if kind not in ('complete', 'configuration'):
        raise BackupError('Choose Complete or Configuration only.')
    with closing(open_database(path)) as destination:
        if kind == 'configuration':
            copy_configuration(source, destination)
        else:
            source.backup(destination, pages=1024)
        for table in ('sessions', 'login_attempts'):
            if table in tables(destination):
                destination.execute(f'DELETE FROM {table}')
        for key, value in (('backup_format','network-monitor-1'), ('backup_kind',kind)):
            destination.execute('INSERT OR REPLACE INTO settings VALUES(?,?)', (key, value))
        destination.commit()
        # Complete snapshots retain their page layout; configuration copies are
        # naturally compact because no history rows were ever copied.


def upload(stream, size, directory, destination_size=0):
    limit = limit_bytes()
    if size <= 0:
        raise BackupError('Choose a non-empty backup file.')
    if size > limit:
        raise BackupError(f'Backup exceeds the restore upload limit of {limit // CHUNK_BYTES} MiB.', 413)
    check_space(directory, size * 3 + destination_size * 2)
    work = workspace(directory)
    try:
        path = Path(work.name) / 'upload.sqlite3'
        with path.open('xb') as output:
            remaining = size
            while remaining:
                block = stream.read(min(CHUNK_BYTES, remaining))
                if not block:
                    raise BackupError('Backup upload was interrupted. The destination was not changed.')
                output.write(block)
                remaining -= len(block)
        with path.open('rb') as incoming:
            if incoming.read(16) != b'SQLite format 3\x00':
                raise BackupError('Choose a Network Monitor SQLite backup file.')
        return work, path
    except BaseException:
        work.cleanup()
        raise


def discard(token, owner):
    with _REVIEW_LOCK:
        review = _REVIEWS.get(token)
        if review is None or not hmac.compare_digest(review['owner'], owner):
            raise BackupError('Backup review is unavailable or expired. Upload the file again.', 409)
        _REVIEWS.pop(token)
        review['timer'].cancel()
        review['work'].cleanup()


def stage(work, path, owner, summary):
    with _REVIEW_LOCK:
        if len(_REVIEWS) >= 2:
            raise BackupError('Two backups are already awaiting review. Cancel one or wait for it to expire.', 409)
        token = secrets.token_urlsafe(32)
        timer = threading.Timer(REVIEW_SECONDS, lambda: expire(token))
        timer.daemon = True
        _REVIEWS[token] = {'owner': owner, 'work': work, 'path': path, 'summary': summary, 'timer': timer}
        timer.start()
        return {**summary, 'token': token, 'expires_in_seconds': REVIEW_SECONDS}


def expire(token):
    with _REVIEW_LOCK:
        review = _REVIEWS.pop(token, None)
        if review:
            review['work'].cleanup()


def consume(token, owner, mode):
    with _REVIEW_LOCK:
        review = _REVIEWS.get(token)
        if review is None or not hmac.compare_digest(review['owner'], owner):
            raise BackupError('Backup review is unavailable or expired. Upload the file again.', 409)
        if mode not in review['summary']['modes']:
            raise BackupError('This backup cannot restore the selected content.')
        _REVIEWS.pop(token)
        review['timer'].cancel()
        return review


def cleanup_stale(directory):
    """Remove only abandoned transfer workspaces, conservatively after 24 hours."""
    cutoff = time.time() - 86400
    for path in Path(directory).glob('.backup-transfer-*'):
        if path.is_symlink():
            continue
        try:
            info = path.stat()
            if path.is_dir() and info.st_uid == os.getuid() and info.st_mtime < cutoff:
                shutil.rmtree(path)
        except OSError:
            pass
