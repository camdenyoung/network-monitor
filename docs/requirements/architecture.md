# Architecture and operations

Equipment scope, runtime, deployment and safe capacity testing.

Current requirements. Read [AGENTS.md](../../AGENTS.md) first. The
[migration audit](MIGRATION.md) records the source of each section; anchor IDs
are navigation aids, not priorities.

Related areas: [Monitoring and issue lifecycle](monitoring.md), [History, backup and restore](history-backups.md), [Dashboard connections and synchronization](connections.md).
Read the related rules affected by the task; these links do not load documents automatically.

<a id="r045"></a>

## Monitoring scope

- Selected SNMP metrics and Mean Well DRS Modbus metrics, not exhaustive discovery.

<a id="r048"></a>

## Offline operation

- Local dashboard remains usable without internet.

<a id="r049"></a>

## Future relay gating

- A future public relay uses an outbound authenticated connection for dashboard
  synchronization and remote acknowledgement behind NAT/CGNAT.

<a id="r051"></a>

## Packaging and persistence

- Docker Compose, persistent storage, consistent backup and safe restore.

<a id="r052"></a>

## Equipment and unverified mappings

Cisco SG350/SBS350, Ubiquiti EdgeSwitch, Teltonika TSW202, generic industrial
switches; Siklu EH600/614/700/710/2500 and possibly MultiHaul/Terragraph;
Mean Well DRS units. Exact OIDs, register maps, and Modbus transport remain
unverified. Never present guessed mappings as verified profiles.

<a id="r053"></a>

## Runtime, commands and safety boundaries

Python standard-library HTTP server and SQLite, vanilla HTML/CSS/JS.
SNMP polling invokes net-snmp's snmpget in the container; Modbus TCP uses a
small bounded read-only client. No SNMP SET or Modbus writes.
Run `python3 -m unittest discover -s tests -v` and `python3 -m compileall app`.
Run locally with `MONITOR_DATA=./data python3 -m app.server`.
Do not commit runtime data or secrets. Keep the relay/public exposure gated
until authentication, encrypted transport, and replay-safe commands exist.
See README.md for first-pass scope and limitations. Update it honestly.

<a id="r054"></a>

## Ping migration and repository publishing

Automatic ping uses an internal non-removable service, sharing issue/history
handling. `ensure_host_checks` backfills legacy assignments at startup and restore.
GitHub repository: https://github.com/camdenyoung/network-monitor (public).
Git HTTPS credentials are not configured locally; use the connected GitHub app
for publishing if needed. Never upload runtime databases or secrets.

<a id="r055"></a>

## Compose bind configuration

Compose host address/port use MONITOR_BIND and MONITOR_PORT in a gitignored
.env file. Keep the container port and health check on 8080. Maintain .env.example.

<a id="r134"></a>

## Synthetic capacity testing

Synthetic capacity tests live in tools/load_test.py and tools/device_simulator.py,
with compose.loadtest.yaml and LOAD_TESTING.md. Simulator and HTTP users run on a
separate machine; Pi runs the ordinary monitor against real SNMP/Modbus peers in
an isolated Compose project/volume. No mocked read_metric, scheduler or SQLite
settings in performance runs. Seed history before measurement and stop a second
normal monitor during timing. Seed atomically refuses existing DB paths; probe
requires benchmark_dataset and benchmark_ready markers. Never seed live data.
Defaults: 150 hosts + five services + automatic ping; optionally replace some
SNMP services with Modbus. Profiles include healthy, latency, dropped responses
and flapping. Same simulator IP means independent ICMP failures are not emulated.
Reports distinguish PASS/FAIL/INCONCLUSIVE, coverage, actual sample gaps, HTTP
latency and explicit targets; do not claim Pi capacity from local smoke tests.
Notifications remain disabled; inspection is read-only and requires the marker.

<a id="r135"></a>

## Docker build exclusions

Docker build context excludes database files, live data, local environment files
and bytecode caches so generated multi-gigabyte test history is never copied into images.
