"""Durable, bounded project deletion; shared inventory is never deleted here."""
import sqlite3
import time


class DeletionError(ValueError):
    pass


def ensure_table(db):
    # Keep completed job records after the project itself has been removed.
    db.execute('''CREATE TABLE IF NOT EXISTS project_deletions (
        id INTEGER PRIMARY KEY AUTOINCREMENT, project INTEGER NOT NULL,
        project_name TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'queued',
        deleted_samples INTEGER NOT NULL DEFAULT 0, error TEXT NOT NULL DEFAULT '',
        created REAL NOT NULL, updated REAL NOT NULL,
        scan_after INTEGER NOT NULL DEFAULT 0, scan_upper INTEGER NOT NULL DEFAULT 0,
        checked_samples INTEGER NOT NULL DEFAULT 0, phase TEXT NOT NULL DEFAULT 'services'
    )''')


def unfinished(db):
    return db.execute("SELECT * FROM project_deletions WHERE state!='completed' ORDER BY id LIMIT 1").fetchone()


def request(db, project_id, expected_name):
    project = db.execute('SELECT id,name FROM projects WHERE id=?', (project_id,)).fetchone()
    if project is None or project['name'] != expected_name:
        raise DeletionError('Project changed or no longer exists. Refresh and review it again.')
    active = db.execute("""SELECT r.project FROM runs r JOIN settings s
        ON s.key='active_run' AND r.id=CAST(s.value AS INTEGER)""").fetchone()
    if active and active[0] == project_id:
        raise DeletionError('Pause monitoring before deleting the current project.')
    job = unfinished(db)
    if job:
        if job['project'] != project_id:
            raise DeletionError('Finish the current project deletion before deleting another project.')
        if job['state'] == 'failed':
            db.execute("UPDATE project_deletions SET state='queued',error='',updated=? WHERE id=?",
                       (time.time(), job['id']))
        return job['id']
    now = time.time()
    has_runs = db.execute('SELECT 1 FROM runs WHERE project=? LIMIT 1', (project_id,)).fetchone()
    horizon = db.execute('SELECT COALESCE(MAX(id),0) FROM samples').fetchone()[0] if has_runs else 0
    job_id = db.execute('''INSERT INTO project_deletions(project,project_name,created,updated,scan_upper)
        VALUES(?,?,?,?,?)''', (project_id, project['name'], now, now, horizon)).lastrowid
    # Stop new reads and invalidate in-flight results before any deletion commits.
    db.execute('UPDATE assignments SET monitoring=0,visible=0,removed=1 WHERE project=?', (project_id,))
    db.execute('''UPDATE services SET enabled=0,monitoring=0 WHERE assignment IN
        (SELECT id FROM assignments WHERE project=?)''', (project_id,))
    db.execute("""UPDATE settings SET value='0' WHERE key='paused_run' AND value IN
        (SELECT CAST(id AS TEXT) FROM runs WHERE project=?)""", (project_id,))
    return job_id


def step(db, batch_size=1000):
    """One short transaction: purge a sample batch or finish one owned service.

    Sample lookup starts with service, so deleting a large project does not scan
    another project's history. Jobs survive process restarts at batch boundaries.
    """
    job = db.execute("SELECT * FROM project_deletions WHERE state IN ('queued','running') ORDER BY id LIMIT 1").fetchone()
    if job is None:
        return False
    project = job['project']
    db.execute("UPDATE project_deletions SET state='running',updated=? WHERE id=?", (time.time(), job['id']))
    service = db.execute('''SELECT s.id FROM services s JOIN assignments a ON a.id=s.assignment
        WHERE a.project=? ORDER BY s.id LIMIT 1''', (project,)).fetchone()
    if service:
        service_id = service[0]
        deleted = db.execute('''DELETE FROM samples WHERE id IN (
            SELECT id FROM samples WHERE service=? LIMIT ?
        )''', (service_id, batch_size)).rowcount
        if deleted:
            db.execute('UPDATE project_deletions SET deleted_samples=deleted_samples+? WHERE id=?',
                       (deleted, job['id']))
            return True
        db.execute('DELETE FROM notification_outbox WHERE incident IN (SELECT id FROM incidents WHERE service=?)', (service_id,))
        # Incident audit and stability rows have ON DELETE CASCADE ownership.
        db.execute('DELETE FROM incidents WHERE service=?', (service_id,))
        db.execute('DELETE FROM services WHERE id=?', (service_id,))
        return True
    # Legacy databases can contain readings whose service was removed before
    # soft deletion existed. Scan the captured row-ID horizon in bounded chunks
    # to purge those by deployment without a full-table DELETE or a new huge index.
    if job['scan_after'] < job['scan_upper']:
        rows = db.execute('SELECT id FROM samples WHERE id>? AND id<=? ORDER BY id LIMIT ?',
                          (job['scan_after'], job['scan_upper'], batch_size)).fetchall()
        upper = rows[-1][0] if rows else job['scan_upper']
        deleted = db.execute('''DELETE FROM samples WHERE id>? AND id<=? AND run IN
            (SELECT id FROM runs WHERE project=?)''', (job['scan_after'], upper, project)).rowcount
        db.execute('''UPDATE project_deletions SET scan_after=?,phase='deployment history',
            checked_samples=checked_samples+?,deleted_samples=deleted_samples+? WHERE id=?''',
            (upper, len(rows), deleted, job['id']))
        return True
    db.execute('DELETE FROM notification_outbox WHERE incident IN (SELECT id FROM incidents WHERE run IN (SELECT id FROM runs WHERE project=?))', (project,))
    db.execute('DELETE FROM incidents WHERE run IN (SELECT id FROM runs WHERE project=?)', (project,))
    db.execute('DELETE FROM runs WHERE project=?', (project,))
    db.execute('DELETE FROM legacy_assignment_addresses WHERE assignment IN (SELECT id FROM assignments WHERE project=?)', (project,))
    db.execute('DELETE FROM assignments WHERE project=?', (project,))
    db.execute('DELETE FROM projects WHERE id=?', (project,))
    db.execute("UPDATE project_deletions SET state='completed',error='',updated=? WHERE id=?", (time.time(), job['id']))
    return True


def worker(connect, lock):
    while True:
        try:
            with lock, connect() as db:
                busy = step(db)
        except sqlite3.Error:
            # The failed transaction rolls back; keep the remaining project data
            # quarantined until an Admin explicitly retries the durable job.
            try:
                with lock, connect() as db:
                    db.execute("""UPDATE project_deletions SET state='failed',
                        error='Deletion stopped after a database error. Check storage and retry.',updated=?
                        WHERE state IN ('queued','running')""", (time.time(),))
            except sqlite3.Error:
                # Even marking failure can fail on a full disk. Keep the worker
                # alive; rolled-back batches remain resumable after storage recovers.
                print('Project deletion waiting for database access', flush=True)
            busy = False
        time.sleep(0.02 if busy else 1)
