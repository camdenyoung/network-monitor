"""Bounded history reads and graph summaries over a requested deployment/time range."""
import math
import threading
import time

MAX_RANGE = 31 * 86400
PAGE_SIZE = 200
GRAPH_LIMIT = 2000
BUCKETS = 300
GAP_STATUSES = {'blocked', 'paused', 'unknown', 'unreachable'}
_HISTORY_SLOTS = threading.BoundedSemaphore(4)


class HistoryError(ValueError):
    pass


def parameters(query):
    service, run = int(query['service'][0]), int(query['run'][0])
    start, end = float(query['start'][0]), float(query['end'][0])
    if (service < 1 or run < 1 or not all(math.isfinite(value) for value in (start, end))
            or start < 0 or end <= start or end - start > MAX_RANGE):
        raise HistoryError('Choose a valid time range of up to 31 days.')
    mode = query.get('mode', ['graph'])[0]
    if mode not in ('graph', 'table'):
        raise HistoryError('Choose Graph or Table.')
    cursor = None
    if 'before_time' in query or 'before_id' in query:
        cursor = (float(query['before_time'][0]), int(query['before_id'][0]))
        if mode != 'table' or not math.isfinite(cursor[0]) or not start <= cursor[0] <= end or cursor[1] < 1:
            raise HistoryError('Invalid history page.')
    return service, run, start, end, mode, cursor


def read(connect, query):
    # Bound expensive range work independently of live monitoring requests.
    if not _HISTORY_SLOTS.acquire(blocking=False):
        raise HistoryError('History is busy. Wait for another history request to finish and try again.')
    try:
        return _read(connect, query)
    finally:
        _HISTORY_SLOTS.release()


def _read(connect, query):
    service, run, start, end, mode, cursor = parameters(query)
    with connect() as db:
        definition = db.execute('''SELECT s.value_type FROM services s JOIN assignments a ON a.id=s.assignment
            JOIN runs r ON r.project=a.project WHERE s.id=? AND r.id=?''', (service, run)).fetchone()
        if definition is None:
            raise HistoryError('Service or deployment is no longer available.')
        retention = int(db.execute("SELECT value FROM settings WHERE key='retention_days'").fetchone()[0])
    if mode == 'table':
        with connect() as db:
            before = '' if cursor is None else ' AND (timestamp<? OR (timestamp=? AND id<?))'
            args = (service, start, end if cursor is None else min(end, cursor[0]), run) + (() if cursor is None else (cursor[0], cursor[0], cursor[1]))
            rows = [dict(row) for row in db.execute('''SELECT * FROM samples INDEXED BY sample_lookup
                WHERE service=? AND timestamp>=? AND timestamp<=? AND run=?''' + before +
                ' ORDER BY timestamp DESC,id DESC LIMIT ?', args + (PAGE_SIZE + 1,))]
        more = len(rows) > PAGE_SIZE
        rows = rows[:PAGE_SIZE]
        next_page = {'before_time': rows[-1]['timestamp'], 'before_id': rows[-1]['id']} if more else None
        return {'rows': rows, 'next': next_page, 'aggregated': False, 'retention_days': retention}

    # Read in timestamp-keyed batches, releasing the connection between batches.
    # A long history request must not hold the monitor lock or a long read transaction.
    # Numeric summaries keep first/last/min/max in each of 300 time buckets.
    # State graphs keep exact transitions until the point limit, then explicitly
    # flag the fallback summary so a short state change is never implied absent.
    deadline = time.monotonic() + 20
    raw, transitions, buckets = [], [], {}
    total = segment = 0
    previous = None

    def usable(row):
        return (row['status'] not in GAP_STATUSES and isinstance(row['value'], (int, float))
                and math.isfinite(row['value']))

    state_overflow = False
    position = None
    while True:
        if time.monotonic() >= deadline:
            raise HistoryError('History took too long to read. Choose a shorter time range and try again.')
        with connect() as db:
            lower = start if position is None else position[0]
            after = '' if position is None else ' AND (timestamp>? OR id>?)'
            args = (service, lower, end, run) + (() if position is None else position)
            batch = [dict(row) for row in db.execute('''SELECT * FROM samples INDEXED BY sample_lookup
                WHERE service=? AND timestamp>=? AND timestamp<=? AND run=?''' + after +
                ' ORDER BY timestamp,id LIMIT 1000', args)]
        if not batch:
            break
        for row in batch:
            total += 1
            if (previous is None or row['timestamp'] - previous['timestamp'] > 60
                    or row['revision'] != previous['revision']
                    or not usable(row) or not usable(previous)):
                segment += 1
            row['_segment'] = segment
            row['aggregated'] = True
            if total <= GRAPH_LIMIT:
                raw.append(row)
            if definition[0] == 'state' and not state_overflow:
                if previous is None or (row['value'], row['status'], segment) != (previous['value'], previous['status'], previous['_segment']):
                    if previous is not None:
                        transitions.append(previous)
                    transitions.append(row)
                if len(transitions) > GRAPH_LIMIT - 2:
                    transitions.clear()
                    state_overflow = True
            bucket = min(BUCKETS - 1, int((row['timestamp'] - start) / (end - start) * BUCKETS))
            summary = buckets.setdefault(bucket, {'first': row, 'last': row, 'min': row, 'max': row})
            summary['last'] = row
            if usable(row):
                if not usable(summary['min']) or row['value'] < summary['min']['value']:
                    summary['min'] = row
                if not usable(summary['max']) or row['value'] > summary['max']['value']:
                    summary['max'] = row
            previous = row
        position = (batch[-1]['timestamp'], batch[-1]['id'])
    if total <= GRAPH_LIMIT:
        selected = raw
    elif definition[0] == 'state' and not state_overflow:
        selected = transitions + ([previous] if previous is not None else [])
    else:
        selected = [row for summary in buckets.values() for row in summary.values()]
    selected = sorted({row['id']: row for row in selected}.values(), key=lambda row: (row['timestamp'], row['id']))
    last_segment = None
    for row in selected:
        row['gap_before'] = last_segment is not None and row['_segment'] != last_segment
        last_segment = row.pop('_segment')
    return {'rows': list(reversed(selected)), 'total': total, 'aggregated': total > GRAPH_LIMIT,
            'state_overflow': state_overflow, 'retention_days': retention, 'next': None}
