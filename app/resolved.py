"""Bounded, read-only search across resolved issues in the current deployment."""
import math
import sqlite3
import threading
import time

PAGE_SIZE = 10
_SEARCH_SLOTS = threading.BoundedSemaphore(4)


class SearchError(ValueError):
    """Safe feedback for invalid or overly expensive issue searches."""


def ensure_index(db):
    db.execute('''CREATE INDEX IF NOT EXISTS resolved_issue_lookup
                  ON incidents(run,closed DESC,id DESC) WHERE closed IS NOT NULL''')


def read(connect, query, display_name):
    text = query.get('search', [''])[0].strip()
    run = int(query['run'][0])
    before = None
    if 'before' in query or 'before_time' in query:
        before = (float(query['before_time'][0]), int(query['before'][0]))
    if (not text or len(text) > 100 or run < 0
            or (before is not None and (not math.isfinite(before[0]) or before[0] < 0 or before[1] < 1))):
        raise SearchError('Enter up to 100 characters to search resolved issues.')
    if not _SEARCH_SLOTS.acquire(blocking=False):
        raise SearchError('Issue search is busy. Try again shortly.')
    try:
        with connect() as db:
            if int(db.execute("SELECT value FROM settings WHERE key='active_run'").fetchone()[0]) != run:
                raise SearchError('The deployment changed. Refresh and search again.')
            # Literal, Unicode-aware substring matching: %, _ and quotes are not SQL patterns.
            db.create_function('searchfold', 1, lambda value: str(value or '').casefold(), deterministic=True)
            deadline = time.monotonic() + 3
            db.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
            fields = ("'Issue #' || COALESCE(i.number,i.id)", 'd.name', 'd.address', 'a.alias', 's.name',
                      'i.status',
                      "COALESCE(i.trigger_display,CAST(i.trigger_value AS TEXT),'') || ' ' || COALESCE(i.trigger_units,'')",
                      'CAST(i.trigger_value AS TEXT)',
                      'i.trigger_units', 'i.trigger_error', 'i.acknowledged_by_full_name',
                      'i.acknowledged_by_username')
            haystack = " || ' ' || ".join(f"COALESCE({field},'')" for field in fields)
            cursor = '' if before is None else ' AND (i.closed<? OR (i.closed=? AND i.id<?))'
            args = (run, text.casefold()) + (() if before is None else (before[0], before[0], before[1]))
            try:
                rows = [dict(row) for row in db.execute(f'''SELECT i.*,s.kind AS source_kind
                    FROM incidents i INDEXED BY resolved_issue_lookup
                    JOIN services s ON s.id=i.service JOIN assignments a ON a.id=s.assignment
                    JOIN devices d ON d.id=a.device
                    WHERE i.run=? AND i.closed IS NOT NULL AND a.removed=0 AND s.enabled=1
                    AND instr(searchfold({haystack}),?)>0{cursor}
                    ORDER BY i.closed DESC,i.id DESC LIMIT ?''', args + (PAGE_SIZE + 1,))]
                more = len(rows) > PAGE_SIZE
                rows = rows[:PAGE_SIZE]
                accounts = {row['id']: dict(row) for row in db.execute('SELECT id,username,full_name FROM users')}
            except sqlite3.OperationalError as error:
                if 'interrupted' in str(error).lower():
                    raise SearchError('Search took too long. Try more specific search text.') from None
                raise
            for row in rows:
                row['acknowledged_by_full_name'] = display_name(row, accounts)
                if row.pop('source_kind') == 'ping' and row['status'] == 'unreachable' and row['trigger_value'] is None:
                    row['trigger_display'] = 'Host unreachable'
            return {'rows': rows, 'next': {'before': rows[-1]['id'], 'before_time': rows[-1]['closed']} if more else None, 'run': run}
    finally:
        _SEARCH_SLOTS.release()
