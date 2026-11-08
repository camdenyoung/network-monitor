"""Global project/deployment scope for restricted dashboard roles.

Scope comes from durable deployment settings, never an admin's local dropdown.
Call mutation checks inside the monitor lock and the mutation transaction.
"""


class AccessError(PermissionError):
    """Safe, user-facing permission failure (HTTP 403)."""


OPERATOR_ACTIONS = frozenset(('pause', 'resume', 'notification-pause',
                              'resume-deployment', 'service-monitoring'))
ACK_ACTIONS = frozenset(('ack', 'unack', 'status-ack', 'status-unack'))


def global_scope(db):
    settings = dict(db.execute("SELECT key,value FROM settings WHERE key IN ('active_run','paused_run')"))
    run = int(settings.get('active_run', '0')) or int(settings.get('paused_run', '0'))
    row = db.execute('SELECT id,project FROM runs WHERE id=?', (run,)).fetchone()
    return {'project': row['project'], 'run': row['id']} if row else {'project': None, 'run': None}


def authorize_mutation(db, actor, action, body):
    # Internal monitoring/setup helpers have no actor; HTTP always supplies one.
    if actor is None:
        return
    # Resolve the durable role here too: internal acknowledgement callers may
    # supply only an account ID, and a concurrent account edit revokes access.
    account = db.execute('SELECT role FROM users WHERE id=?', (actor['id'],)).fetchone()
    role = account['role'] if account else None
    if role == 'admin':
        return
    if role != 'operator' or action not in OPERATOR_ACTIONS | ACK_ACTIONS:
        raise AccessError('Admin access required.')
    if action in ACK_ACTIONS:
        return  # Issue handlers independently validate the active run and source.
    scope = global_scope(db)
    if not scope['run'] or body.get('expected_scope_run') != scope['run']:
        raise AccessError('The selected deployment changed. Refresh and try again.')
    if action in ('resume', 'resume-deployment') and int(body['project']) != scope['project']:
        raise AccessError('Operators must stay within the current project.')
    if action == 'resume-deployment' and not db.execute(
            'SELECT 1 FROM runs WHERE id=? AND project=?', (int(body['run']), scope['project'])).fetchone():
        raise AccessError('Choose a deployment within the current project.')
    if action == 'service-monitoring' and not db.execute('''SELECT 1 FROM services s
            JOIN assignments a ON a.id=s.assignment WHERE s.id=? AND a.project=?
            AND a.removed=0 AND s.enabled=1 AND s.kind!='ping' ''',
            (int(body['service']), scope['project'])).fetchone():
        raise AccessError('Choose an additional monitored service within the current project.')


def authorize_history(db, actor, service, run):
    if actor['role'] == 'admin':
        return
    scope = global_scope(db)
    allowed = db.execute('''SELECT 1 FROM services s JOIN assignments a ON a.id=s.assignment
        JOIN runs r ON r.project=a.project WHERE s.id=? AND r.id=? AND a.project=?
        AND a.removed=0 AND s.enabled=1''', (service, run, scope['project'])).fetchone()
    if (not allowed or actor['role'] not in ('viewer', 'operator')
            or (actor['role'] == 'viewer' and run != scope['run'])):
        raise AccessError('History is restricted to your current project/deployment.')


def restrict_snapshot(result, actor, scope):
    """Filter every collection; hidden configuration must not leak through JSON."""
    if actor is None or actor['role'] == 'admin':
        return result
    result['access_scope'] = scope
    result['projects'] = [row for row in result['projects'] if row['id'] == scope['project']]
    result['runs'] = [row for row in result['runs'] if row['project'] == scope['project']
                      and (actor['role'] == 'operator' or row['id'] == scope['run'])]
    result['assignments'] = [row for row in result['assignments']
                             if row['project'] == scope['project'] and not row['removed']]
    assignments = {row['id'] for row in result['assignments']}
    devices = {row['device'] for row in result['assignments']}
    result['devices'] = [row for row in result['devices'] if row['id'] in devices]
    result['services'] = [row for row in result['services'] if row['assignment'] in assignments and row['enabled']]
    services = {row['id'] for row in result['services']}
    result['latest'] = [row for row in result['latest'] if row['service'] in services and row['run'] == scope['run']]
    def permitted(row):
        return row['service'] in services and row['run'] == scope['run']
    result['incidents'] = [row for row in result['incidents'] if permitted(row)]
    result['incident_lists'] = {key: [row for row in rows if permitted(row)]
                                for key, rows in result['incident_lists'].items()}
    for key in ('service_templates', 'device_service_defaults', 'legacy_addresses'):
        result[key] = []
    result['settings'] = {key: result['settings'][key] for key in
                          ('active_run', 'paused_run', 'notifications_paused', 'retention_days')}
    return result
