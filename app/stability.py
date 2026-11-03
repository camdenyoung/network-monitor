"""Persistent flap episodes and recovery hysteresis, independent of notification delivery."""
import json
import math

POLICY_FIELDS = ('flap_enabled', 'flap_changes', 'flap_window', 'flap_stable', 'hysteresis')
DEFAULTS = {'flap_enabled': 1, 'flap_changes': 4, 'flap_window': 5, 'flap_stable': 5, 'hysteresis': 0}


def ensure_tables(db):
    for table in ('services', 'service_templates', 'device_service_defaults'):
        columns = {row[1] for row in db.execute(f'PRAGMA table_info({table})')}
        for field in POLICY_FIELDS:
            if field not in columns:
                kind = 'REAL' if field == 'hysteresis' else 'INTEGER'
                db.execute(f'ALTER TABLE {table} ADD COLUMN {field} {kind} NOT NULL DEFAULT {DEFAULTS[field]}')
    db.execute('''CREATE TABLE IF NOT EXISTS check_stability (
        run INTEGER REFERENCES runs(id) ON DELETE CASCADE,
        service INTEGER REFERENCES services(id) ON DELETE CASCADE,
        revision INTEGER NOT NULL, monitoring_since REAL NOT NULL,
        confirmed TEXT, raw TEXT, stable_since REAL NOT NULL, last_sample REAL NOT NULL,
        transitions TEXT NOT NULL DEFAULT '[]', flapping INTEGER NOT NULL DEFAULT 0,
        episode INTEGER NOT NULL DEFAULT 0, ended REAL,
        PRIMARY KEY(run,service)
    )''')


def policy_details(body, existing=None):
    previous = dict(existing) if existing else DEFAULTS
    values = {key: body.get(key, previous.get(key, DEFAULTS[key])) for key in POLICY_FIELDS}
    if type(values['flap_enabled']) not in (bool, int) or values['flap_enabled'] not in (0, 1):
        raise ValueError('Flap protection must be enabled or disabled')
    values['flap_enabled'] = int(values['flap_enabled'])
    for field, minimum, maximum in (('flap_changes', 2, 100), ('flap_window', 1, 1440), ('flap_stable', 1, 1440)):
        value = values[field]
        if isinstance(value, bool) or (isinstance(value, float) and not value.is_integer()):
            raise ValueError('Flap settings require whole numbers')
        value = int(value)
        if not minimum <= value <= maximum:
            raise ValueError('Flap changes must be 2–100; time windows must be 1–1440 minutes')
        values[field] = value
    if isinstance(values['hysteresis'], bool):
        raise ValueError('Hysteresis must be numeric')
    margin = float(values['hysteresis'])
    if not math.isfinite(margin) or margin < 0:
        raise ValueError('Hysteresis must be a finite non-negative number')
    values['hysteresis'] = 0 if body.get('value_type', previous.get('value_type')) == 'state' else margin
    return tuple(values[key] for key in POLICY_FIELDS)


def state_for(db, run, service, revision, monitoring_since):
    row = db.execute('''SELECT * FROM check_stability
        WHERE run=? AND service=? AND revision=? AND monitoring_since=?''',
        (run, service, revision, monitoring_since)).fetchone()
    return dict(row) if row else None


def observe(db, service, run, status, confirmed, now):
    """Count confirmed transitions, but require continuously stable raw readings to clear.

    This runs in the polling transaction, so an episode and its one-time messages
    are committed together. Pauses/config edits start a fresh generation; process
    restarts retain an episode and cannot duplicate its start notification.
    """
    old = db.execute('SELECT * FROM check_stability WHERE run=? AND service=?', (run, service['id'])).fetchone()
    episode = old['episode'] if old else 0
    state = state_for(db, run, service['id'], service['revision'], service['monitoring_since'])
    if state is None:
        state = {'confirmed': None, 'raw': status, 'stable_since': now, 'last_sample': now,
                 'transitions': '[]', 'flapping': 0, 'episode': episode, 'ended': None}
    transitions = [stamp for stamp in json.loads(state['transitions']) if stamp >= now - service['flap_window'] * 60]
    if now - state['last_sample'] > 60 or status == 'blocked':
        # A monitoring/dependency gap cannot count as stable time or a transition.
        transitions = []
        state['confirmed'] = None
        state['stable_since'] = now
    if status != state['raw']:
        state['stable_since'] = now
    event = None
    if confirmed and status != 'blocked':
        if state['confirmed'] is not None and status != state['confirmed']:
            transitions.append(now)
        state['confirmed'] = status
    if not service['flap_enabled']:
        state['flapping'], transitions, state['ended'] = 0, [], None
    elif not state['flapping'] and len(transitions) >= service['flap_changes']:
        state['flapping'], state['ended'] = 1, None
        state['episode'] += 1
        event = f"flap-start:{state['episode']}"
    elif state['flapping'] and confirmed and status != 'blocked' and now - state['stable_since'] >= service['flap_stable'] * 60:
        state['flapping'], state['ended'], transitions = 0, now, []
        event = f"flap-stable:{state['episode']}"
    db.execute('''INSERT OR REPLACE INTO check_stability
        (run,service,revision,monitoring_since,confirmed,raw,stable_since,last_sample,transitions,flapping,episode,ended)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''',
        (run, service['id'], service['revision'], service['monitoring_since'], state['confirmed'], status,
         state['stable_since'], now, json.dumps(transitions[-100:]), state['flapping'], state['episode'], state['ended']))
    return event


def event_is_current(state, event, now):
    if not state or now - state['last_sample'] > 60 or state['raw'] == 'blocked':
        return False
    kind, _, episode = event.partition(':')
    if episode != str(state['episode']):
        return False
    if kind == 'flap-start':
        return bool(state['flapping'])
    return bool(kind == 'flap-stable' and not state['flapping'] and state['ended'] is not None
                and state['raw'] == state['confirmed'])
