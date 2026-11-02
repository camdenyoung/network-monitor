"""Local accounts and opaque server-side sessions; passwords never leave this module."""
import hashlib
import hmac
from http.cookies import SimpleCookie, CookieError
import re
import secrets
import time

SESSION_SECONDS = 12 * 60 * 60


def password_hash(password):
    if not isinstance(password, str) or not 10 <= len(password) <= 256:
        raise ValueError('Passwords must contain 10–256 characters')
    salt = secrets.token_hex(16)
    digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1)
    return salt + ':' + digest.hex()


def password_matches(password, encoded):
    try:
        if not isinstance(password, str) or len(password) > 256:
            return False
        salt, expected = encoded.split(':')
        digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1)
        return hmac.compare_digest(digest.hex(), expected)
    except (ValueError, TypeError):
        return False


def ensure_accounts(db, bootstrap_path=None, initial_password=None):
    db.executescript('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL COLLATE NOCASE UNIQUE,
            password_hash TEXT NOT NULL, role TEXT NOT NULL,
            must_change_password INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS sessions (
            token_hash TEXT PRIMARY KEY, user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
            csrf TEXT NOT NULL, expires REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS login_attempts (
            key TEXT PRIMARY KEY, failures INTEGER NOT NULL, started REAL NOT NULL
        );
    ''')
    if bootstrap_path is not None and not db.execute('SELECT 1 FROM users LIMIT 1').fetchone():
        password = initial_password or secrets.token_urlsafe(18)
        encoded = password_hash(password)
        # Exclusive creation and mode 0600 keep the one-time credential off logs.
        import os
        descriptor = os.open(bootstrap_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, 'w') as output:
            output.write(password + '\n')
        db.execute('INSERT INTO users(username,password_hash,role) VALUES(?,?,?)',
                   ('admin', encoded, 'admin'))


def public_user(user):
    return {key: user[key] for key in ('id', 'username', 'role', 'must_change_password')}


def session_user(db, cookie_header):
    try:
        cookie = SimpleCookie()
        cookie.load(cookie_header or '')
        token = cookie['monitor_session'].value if 'monitor_session' in cookie else ''
    except CookieError:
        return None
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    row = db.execute('''SELECT u.*, s.csrf FROM sessions s JOIN users u ON u.id=s.user_id
        WHERE s.token_hash=? AND s.expires>?''', (token_hash, time.time())).fetchone()
    return dict(row) if row else None


def new_session(db, user_id):
    token = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(32)
    db.execute('DELETE FROM sessions WHERE expires<=?', (time.time(),))
    db.execute('INSERT INTO sessions VALUES(?,?,?,?)',
               (hashlib.sha256(token.encode()).hexdigest(), user_id, csrf, time.time() + SESSION_SECONDS))
    return token


def login(db, username, password, client):
    """Return failure rather than raise so the transaction retains rate-limit counts."""
    username = str(username).strip()[:64]
    now = time.time()
    db.execute('DELETE FROM login_attempts WHERE started<?', (now - 60,))
    # Rate-limit by client AND account, preventing simple account/IP rotation.
    keys = [hashlib.sha256(value.encode()).hexdigest()
            for value in ('client:' + client, 'user:' + username.casefold())]
    for key in keys:
        row = db.execute('SELECT failures FROM login_attempts WHERE key=?', (key,)).fetchone()
        if row and row[0] >= 5:
            return None, 429
    user = db.execute('SELECT * FROM users WHERE username=?', (username,)).fetchone()
    # A dummy hash equalizes the expensive work for unknown users.
    encoded = user['password_hash'] if user else db.execute('SELECT password_hash FROM users LIMIT 1').fetchone()[0]
    valid = password_matches(password, encoded)
    if not user or not valid:
        for key in keys:
            db.execute('''INSERT INTO login_attempts VALUES(?,1,?)
                ON CONFLICT(key) DO UPDATE SET failures=failures+1''', (key, now))
        return None, 401
    db.execute('DELETE FROM login_attempts WHERE key=?', (keys[1],))
    return new_session(db, user['id']), 200


def manage_user(db, action, body, actor):
    """Admin operations preserve at least one administrator and revoke old sessions."""
    if actor['role'] != 'admin':
        raise ValueError('Admin required')
    if action == 'user-create':
        username, role = user_details(body)
        db.execute('INSERT INTO users(username,password_hash,role) VALUES(?,?,?)',
                   (username, password_hash(body['password']), role))
        return
    target = db.execute('SELECT * FROM users WHERE id=?', (int(body['user']),)).fetchone()
    if target is None:
        raise ValueError('Unknown user')
    if action == 'user-delete':
        if target['id'] == actor['id']:
            raise ValueError('You cannot delete your own account')
        role = None
    else:
        username, role = user_details(body)
    if target['role'] == 'admin' and role != 'admin':
        count = db.execute("SELECT COUNT(*) FROM users WHERE role='admin'").fetchone()[0]
        if count <= 1:
            raise ValueError('Keep at least one administrator')
    db.execute('DELETE FROM sessions WHERE user_id=?', (target['id'],))
    if action == 'user-delete':
        db.execute('DELETE FROM users WHERE id=?', (target['id'],))
    else:
        db.execute('UPDATE users SET username=?,role=? WHERE id=?', (username, role, target['id']))
        if body.get('password'):
            db.execute('UPDATE users SET password_hash=?,must_change_password=1 WHERE id=?',
                       (password_hash(body['password']), target['id']))


def user_details(body):
    username = body['username'].strip()
    role = body['role']
    if not re.fullmatch(r'[A-Za-z0-9_.@-]{1,64}', username) or role not in ('admin', 'viewer'):
        raise ValueError('Use a valid username and Admin or View Only role')
    return username, role
