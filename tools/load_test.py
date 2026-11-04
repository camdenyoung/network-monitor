"""Synthetic capacity testing with the load generator on a separate computer.

seed/inspect operate only on explicitly named, marked benchmark databases.
serve/probe run externally. No production polling code or database configuration
is replaced, and benchmark notifications remain disabled.
"""
import argparse
import concurrent.futures
import contextlib
import email.utils
import http.cookiejar
import ipaddress
import json
import math
import os
from pathlib import Path
import platform
import re
import shutil
import sqlite3
import statistics
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

from .device_simulator import OID_PREFIX, PROFILES, Scenario, serve

PASSWORD = 'benchmark-only-password'


def service_definition(host, index, services, modbus_services):
    modbus = index > services - modbus_services
    name, healthy, _fault, units, direction, warning, critical = PROFILES[(index - 1) % len(PROFILES)]
    definition = {'name': f'{index}: {name}', 'kind': 'snmp',
                  'target': '.'.join(map(str, (*OID_PREFIX, host, index, 0))),
                  'community': 'synthetic-test', 'unit': host, 'scale': 1,
                  'units': units, 'direction': direction, 'warning': warning, 'critical': critical}
    if modbus:
        definition.update(name=f'{index}: PSU voltage', kind='modbus', target=str(index - 1),
                          scale=0.01, units='V', direction='below', warning=48, critical=44)
        healthy = 54
    elif name == 'Port status':
        definition.update(value_type='state', state_map={
            '1': {'label': 'Up', 'status': 'healthy'}, '2': {'label': 'Down', 'status': 'critical'}})
    return definition, float(healthy), 'Up' if name == 'Port status' and not modbus else str(float(healthy))


def seed(database, simulator, hosts=150, services=5, modbus_services=0, history_days=0,
         history_interval=15, users=3, password=PASSWORD):
    """Create a new dataset only. Existing paths are never opened for writing."""
    address = ipaddress.ip_address(simulator)
    if address.version != 4:
        raise ValueError('Use the external simulator IPv4 address')
    if not 1 <= hosts <= 247 or not 1 <= services <= 20 or not 0 <= modbus_services <= services:
        raise ValueError('Use 1–247 hosts, 1–20 services, and a valid Modbus service count')
    if not 0 <= history_days <= 30 or history_interval < 1 or not 1 <= users <= 20:
        raise ValueError('History must be 0–30 days; interval positive; users 1–20')
    if not isinstance(password, str) or not 10 <= len(password) <= 256:
        raise ValueError('Benchmark password must contain 10–256 characters')
    database = Path(database).resolve()
    database.parent.mkdir(parents=True, exist_ok=True)
    # Atomic refusal also protects against another seeder or an already-started app.
    descriptor = os.open(database, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(descriptor)
    from app import server, auth
    old_db, old_data = server.DB, server.DATA
    old_password = os.environ.get('MONITOR_ADMIN_PASSWORD')
    server.DB, server.DATA = database, database.parent
    os.environ['MONITOR_ADMIN_PASSWORD'] = password
    rounds = int(history_days * 86400 / history_interval)
    expected_rows = hosts * (services + 1) * rounds
    started = time.time() - rounds * history_interval
    print(f'Creating {hosts} hosts, {hosts * services} services, {expected_rows:,} history rows in {database}', flush=True)
    try:
        server.initialize()
        with server.connect() as db:
            db.execute("INSERT INTO projects(id,name,status_ack_enabled) VALUES(1,'Synthetic capacity test',1)")
            db.execute('UPDATE users SET must_change_password=0,full_name=? WHERE id=1', ('Benchmark administrator',))
            for number in range(1, users + 1):
                auth.manage_user(db, 'user-create', {'username': f'loadtest-{number:02}', 'password': password,
                    'role': 'viewer', 'must_change_password': False}, {'id': 1, 'role': 'admin'})
            for host in range(1, hosts + 1):
                db.execute('INSERT INTO devices(id,name,model,address) VALUES(?,?,?,?)',
                           (host, f'LOAD-{host:03}', 'Synthetic SNMP/Modbus device', str(address)))
                db.execute('INSERT INTO assignments(id,project,device,alias,notifications) VALUES(?,1,?,?,0)',
                           (host, host, f'Virtual host {host:03}'))
                for index in range(1, services + 1):
                    definition, _value, _display = service_definition(host, index, services, modbus_services)
                    server.insert_service(db, host, server.service_details(definition))
            server.ensure_host_checks(db)
        server.mutate('activate', {'project': 1, 'description': 'Isolated synthetic capacity test'})
        # Benchmarks explicitly opt into polling after the normal paused selection.
        server.mutate('resume', {'project': 1})
        with server.connect() as db:
            db.execute('UPDATE services SET monitoring_since=?', (started,))
            db.execute('UPDATE runs SET started=? WHERE id=1', (started,))
            metadata = {'benchmark_dataset': uuid.uuid4().hex, 'benchmark_ready': '0',
                        'benchmark_hosts': str(hosts), 'benchmark_services_per_host': str(services),
                        'benchmark_users': str(users), 'benchmark_modbus_services_per_host': str(modbus_services),
                        'benchmark_history_rows': str(expected_rows), 'benchmark_history_days': str(history_days),
                        'benchmark_history_interval_s': str(history_interval)}
            db.executemany('INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)', metadata.items())
            checks = []
            for row in db.execute('SELECT * FROM services ORDER BY id'):
                if row['kind'] == 'ping':
                    value, display = 1, '1.0'
                else:
                    index = int(row['name'].split(':', 1)[0])
                    _definition, value, display = service_definition(row['assignment'], index, services, modbus_services)
                checks.append((row['id'], value, display))
        inserted, batch = 0, []
        with server.connect() as db:
            for turn in range(rounds):
                timestamp = started + turn * history_interval
                for service_id, value, display in checks:
                    batch.append((1, service_id, timestamp, value, 'healthy', '', 1, display))
                    if len(batch) >= 10000:
                        db.executemany('''INSERT INTO samples
                            (run,service,timestamp,value,status,error,revision,display_value) VALUES(?,?,?,?,?,?,?,?)''', batch)
                        inserted += len(batch)
                        batch.clear()
                        if inserted % 1000000 == 0:
                            db.commit()
                            print(f'History: {inserted:,}/{expected_rows:,} rows', flush=True)
                            if shutil.disk_usage(database.parent).free < 64 * 1024 * 1024:
                                raise OSError('Less than 64 MiB free; seed stopped before running the benchmark')
            if batch:
                db.executemany('''INSERT INTO samples
                    (run,service,timestamp,value,status,error,revision,display_value) VALUES(?,?,?,?,?,?,?,?)''', batch)
            db.execute("UPDATE settings SET value='1' WHERE key='benchmark_ready'")
        result = inspect_database(database)
        print(json.dumps(result, indent=2), flush=True)
        return result
    finally:
        server.DB, server.DATA = old_db, old_data
        if old_password is None:
            os.environ.pop('MONITOR_ADMIN_PASSWORD', None)
        else:
            os.environ['MONITOR_ADMIN_PASSWORD'] = old_password


def inspect_database(database):
    path = Path(database).resolve()
    uri = 'file:' + urllib.parse.quote(str(path), safe='/') + '?mode=ro'
    with contextlib.closing(sqlite3.connect(uri, uri=True)) as db:
        settings = dict(db.execute("SELECT key,value FROM settings WHERE key LIKE 'benchmark_%'"))
        if not settings.get('benchmark_dataset'):
            raise ValueError('This is not a marked benchmark database')
        return {'dataset': settings, 'database_bytes': path.stat().st_size,
                'history_rows': db.execute('SELECT COUNT(*) FROM samples').fetchone()[0],
                'host_count': db.execute('SELECT COUNT(*) FROM devices').fetchone()[0],
                'check_count': db.execute('SELECT COUNT(*) FROM services WHERE enabled=1').fetchone()[0],
                'free_database_pages': db.execute('PRAGMA freelist_count').fetchone()[0],
                'page_size': db.execute('PRAGMA page_size').fetchone()[0],
                'machine': platform.machine(), 'platform': platform.platform()}


class ApiClient:
    def __init__(self, url, timeout):
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme not in ('http', 'https') or not parsed.netloc or parsed.username or parsed.password:
            raise ValueError('Use an HTTP(S) URL without embedded credentials')
        self.url = url.rstrip('/')
        self.timeout = timeout
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def read(self, path, body=None):
        started = time.perf_counter()
        request = urllib.request.Request(self.url + path,
            data=json.dumps(body).encode() if body is not None else None,
            headers={'Content-Type': 'application/json'})
        with self.opener.open(request, timeout=self.timeout) as response:
            payload = json.load(response)
            date = response.headers.get('Date')
        server_time = email.utils.parsedate_to_datetime(date).timestamp() if date else None
        return payload, time.perf_counter() - started, server_time

    def login(self, username, password):
        self.read('/api/login', {'username': username, 'password': password})


def percentile(values, percentage):
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * percentage / 100) - 1)]


class Measurements:
    def __init__(self):
        self.lock = threading.Lock()
        self.latencies, self.errors = {}, {}
        self.latest = {}
        self.intervals = []
        self.interval_services = set()
        self.expected_checks = 0
        self.maximum_age = 0
        self.minimum_fresh_percent = 100
        self.maximum_blocked = 0
        self.maximum_unreachable = 0
        self.configuration_changed = False

    def record(self, path, elapsed=None, error=None):
        with self.lock:
            if error:
                self.errors[error] = self.errors.get(error, 0) + 1
            else:
                self.latencies.setdefault(path, []).append(elapsed)

    def observe(self, state, server_time):
        with self.lock:
            assignments = state.get('assignments')
            active_assignments = ({row['id'] for row in assignments if row['monitoring'] and not row.get('removed')}
                                  if assignments is not None else None)
            expected = {row['id'] for row in state['services'] if row['enabled'] and row['monitoring']
                        and (active_assignments is None or row['assignment'] in active_assignments)}
            if not self.expected_checks:
                self.expected_checks = len(expected)
            elif len(expected) != self.expected_checks:
                self.configuration_changed = True
            fresh, blocked, unreachable = 0, 0, 0
            for sample in state['latest']:
                service = sample['service']
                if service not in expected:
                    continue
                blocked += sample.get('status') == 'blocked'
                unreachable += sample.get('status') == 'unreachable'
                if server_time is not None:
                    age = max(0, server_time - sample['timestamp'])
                    self.maximum_age = max(self.maximum_age, age)
                    fresh += age <= 60
                previous = self.latest.get(service)
                if previous and sample['id'] != previous[0]:
                    gap = sample['timestamp'] - previous[1]
                    if gap > 0:
                        self.intervals.append(gap)
                        self.interval_services.add(service)
                self.latest[service] = (sample['id'], sample['timestamp'])
            self.maximum_blocked = max(self.maximum_blocked, blocked)
            self.maximum_unreachable = max(self.maximum_unreachable, unreachable)
            if server_time is not None and expected:
                self.minimum_fresh_percent = min(self.minimum_fresh_percent, 100 * fresh / len(expected))

    def report(self, maximum_dashboard, maximum_interval, allow_unreachable=False):
        latencies = {path: {'requests': len(values), 'p50_s': statistics.median(values),
                    'p95_s': percentile(values, 95), 'maximum_s': max(values)} for path, values in self.latencies.items()}
        failures = []
        if self.configuration_changed:
            failures.append('The configured workload changed during measurement')
        if self.maximum_blocked:
            failures.append('Host reachability blocked services; the full service workload was not exercised')
        if self.maximum_unreachable and not allow_unreachable:
            failures.append('Unexpected unreachable checks for this scenario')
        if self.errors:
            failures.append('HTTP requests failed during measurement')
        for path in ('/api/state', '/api/status'):
            if path in latencies and latencies[path]['p95_s'] > maximum_dashboard:
                failures.append(path + ' exceeded the dashboard latency target')
        if self.minimum_fresh_percent < 100:
            failures.append('Some current readings were missing or older than 60 seconds')
        if self.intervals and max(self.intervals) > maximum_interval:
            failures.append('Observed check intervals exceeded the target')
        coverage = len(self.interval_services) / self.expected_checks if self.expected_checks else 0
        conclusion = 'FAIL' if failures else 'PASS' if coverage >= 0.95 else 'INCONCLUSIVE'
        return {'result': conclusion, 'failures': failures, 'http': latencies, 'http_errors': self.errors,
                'maximum_blocked_checks': self.maximum_blocked, 'maximum_unreachable_checks': self.maximum_unreachable,
                'checks_expected': self.expected_checks, 'checks_with_observed_interval': len(self.interval_services),
                'interval_coverage_percent': coverage * 100, 'check_interval_p95_s': percentile(self.intervals, 95),
                'check_interval_maximum_s': max(self.intervals) if self.intervals else None,
                'maximum_reading_age_s': self.maximum_age, 'minimum_fresh_readings_percent': self.minimum_fresh_percent,
                'targets': {'dashboard_p95_s': maximum_dashboard, 'maximum_check_interval_s': maximum_interval,
                            'freshness_s': 60, 'minimum_interval_coverage_percent': 95}}


def probe(url, duration=600, warmup=30, users=3, interval=10, timeout=30,
          maximum_dashboard=2, maximum_interval=30, password=PASSWORD, report_path=None, scenario='healthy'):
    if (not all(math.isfinite(value) for value in (duration, warmup, interval, timeout, maximum_dashboard, maximum_interval))
            or min(duration, interval, timeout, maximum_dashboard, maximum_interval) <= 0 or warmup < 0 or not 1 <= users <= 20):
        raise ValueError('Use positive duration/interval, non-negative warmup and 1–20 users')
    if scenario not in ('healthy', 'timeouts', 'flapping'):
        raise ValueError('Choose healthy, timeouts or flapping')
    if report_path and Path(report_path).exists():
        raise FileExistsError('Choose a new report filename; existing files are never overwritten')
    preflight = ApiClient(url, timeout)
    preflight.login('admin', password)
    state, _elapsed, _server_time = preflight.read('/api/state')
    settings = state.get('settings', {})
    if not settings.get('benchmark_dataset') or settings.get('benchmark_ready') != '1':
        raise ValueError('Refusing load: target is not a completed synthetic benchmark installation')
    if users > int(settings['benchmark_users']):
        raise ValueError('Requested users exceed the number created by seed')
    with preflight.opener.open(preflight.url + '/', timeout=timeout) as response:
        match = re.search(r'v[0-9.]+ · Build [0-9]+', response.read(1024 * 1024).decode('utf-8'))
    monitor_version = match.group(0) if match else 'Unknown'
    measurements = Measurements()
    measurements.expected_checks = int(settings['benchmark_hosts']) * (int(settings['benchmark_services_per_host']) + 1)
    start = time.monotonic()
    measure_start, end = start + warmup, start + warmup + duration
    print(f'External HTTP load: {users} users, {warmup}s warmup, {duration}s measurement', flush=True)
    def user(number):
        client = ApiClient(url, timeout)
        try:
            client.login('admin' if number == 0 else f'loadtest-{number + 1:02}', password)
        except Exception as error:
            measurements.record('login', error=type(error).__name__)
            return
        path = '/api/state' if number % 2 == 0 else '/api/status'
        while time.monotonic() < end:
            turn = time.monotonic()
            paths = [path] + (['/api/users', '/api/telegram', '/api/whatsapp'] if number == 0 else [])
            for current in paths:
                measured = time.monotonic() >= measure_start
                try:
                    data, elapsed, server_time = client.read(current)
                    if measured:
                        measurements.record(current, elapsed=elapsed)
                        if number == 0 and current == '/api/state':
                            measurements.observe(data, server_time)
                except Exception as error:
                    if measured:
                        reason = 'HTTP ' + str(error.code) if isinstance(error, urllib.error.HTTPError) else type(error).__name__
                        measurements.record(current, error=reason)
            remaining = min(end, turn + interval) - time.monotonic()
            if remaining > 0:
                time.sleep(remaining)
    with concurrent.futures.ThreadPoolExecutor(max_workers=users) as pool:
        list(pool.map(user, range(users)))
    result = measurements.report(maximum_dashboard, maximum_interval, allow_unreachable=scenario == 'timeouts')
    result.update(monitor_version=monitor_version, scenario=scenario, dataset={key: value for key, value in settings.items() if key.startswith('benchmark_')},
                  users=users, duration_s=duration, warmup_s=warmup, dashboard_interval_s=interval,
                  actual_elapsed_s=time.monotonic() - start,
                  generator_machine=platform.machine(), generator_platform=platform.platform(),
                  limitations=['HTTP/server timings, not browser JavaScript, persistent event streams, rendering or Pi CPU/RAM measurements.',
                               'Freshness uses the monitor HTTP Date header, with one-second resolution.',
                               'Interval observations are sampled through dashboard requests; short tests may be inconclusive.',
                               'Simulator and generator must run on another machine for representative Pi capacity results.'])
    encoded = json.dumps(result, indent=2)
    print(encoded, flush=True)
    if report_path:
        destination = Path(report_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open('x') as report_file:
            report_file.write(encoded + '\n')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    seeder = commands.add_parser('seed', help='Create a NEW isolated database before starting the test app')
    seeder.add_argument('--database', required=True)
    seeder.add_argument('--simulator', required=True, help='External simulator IPv4 address')
    seeder.add_argument('--hosts', type=int, default=150)
    seeder.add_argument('--services', type=int, default=5, help='Additional services per host; automatic ping is extra')
    seeder.add_argument('--modbus-services', type=int, default=0, help='Number of those services using Modbus instead of SNMP')
    seeder.add_argument('--history-days', type=float, default=0)
    seeder.add_argument('--history-interval', type=int, default=15)
    seeder.add_argument('--users', type=int, default=3)
    seeder.add_argument('--password', default=PASSWORD)
    simulator = commands.add_parser('serve', help='Run SNMP/Modbus emulators on a SEPARATE machine')
    simulator.add_argument('--bind', default='0.0.0.0')
    simulator.add_argument('--snmp-port', type=int, default=1161)
    simulator.add_argument('--modbus-port', type=int, default=1502)
    simulator.add_argument('--scenario', choices=('healthy', 'timeouts', 'flapping'), default='healthy')
    simulator.add_argument('--latency-ms', type=float, default=10)
    simulator.add_argument('--failure-percent', type=float, default=10)
    simulator.add_argument('--flap-period', type=float, default=30)
    reader = commands.add_parser('probe', help='Generate dashboard traffic from a SEPARATE machine')
    reader.add_argument('--url', required=True)
    reader.add_argument('--duration', type=float, default=600)
    reader.add_argument('--warmup', type=float, default=30)
    reader.add_argument('--users', type=int, default=3)
    reader.add_argument('--interval', type=float, default=10)
    reader.add_argument('--timeout', type=float, default=30)
    reader.add_argument('--maximum-dashboard', type=float, default=2)
    reader.add_argument('--maximum-interval', type=float, default=30)
    reader.add_argument('--password', default=PASSWORD)
    reader.add_argument('--scenario', choices=('healthy', 'timeouts', 'flapping'), default='healthy', help='Must match the external simulator scenario')
    reader.add_argument('--report', dest='report_path')
    inspection = commands.add_parser('inspect', help='Measure a marked benchmark database AFTER the timed test')
    inspection.add_argument('--database', required=True)
    args = vars(parser.parse_args())
    command = args.pop('command')
    try:
        if command == 'seed':
            seed(**args)
        elif command == 'serve':
            if (not all(math.isfinite(args[key]) for key in ('latency_ms', 'failure_percent', 'flap_period'))
                    or args['latency_ms'] < 0 or not 0 <= args['failure_percent'] <= 100 or args['flap_period'] <= 0):
                raise ValueError('Use non-negative latency, 0–100 failure percent and a positive flap period')
            scenario = Scenario(args.pop('scenario'), args.pop('latency_ms'), args.pop('failure_percent'), args.pop('flap_period'))
            serve(scenario=scenario, **args)
        elif command == 'inspect':
            print(json.dumps(inspect_database(**args), indent=2))
        else:
            return 0 if probe(**args)['result'] == 'PASS' else 2
    except (ValueError, OSError, sqlite3.Error) as error:
        print(f'{type(error).__name__}: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
