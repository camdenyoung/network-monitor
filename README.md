# Field Monitor — first implementation

Local-first equipment monitoring for a single server and roughly 100–150 devices.
This is a runnable development foundation, not the completed production system.

## Start with Docker Compose

```sh
docker compose up --build -d
```

Open http://localhost:8080. The default published address is loopback. To use a
custom port or trusted LAN address, copy `.env.example` to `.env` and edit it:

```dotenv
MONITOR_BIND=127.0.0.1
MONITOR_PORT=8090
```

Run `docker compose up --build -d` after changing these settings. The example
publishes http://localhost:8090; for trusted LAN access use the server's LAN IP
as `MONITOR_BIND`. The container port and health check remain on 8080.
Keep machine-specific settings in `.env`, which Git ignores, rather than editing
`compose.yaml`. If `.env` already exists, edit it without replacing other settings.
There is no login yet: anyone able to reach the port can read, change, back up,
and restore the system. Do not expose this version to the internet.

The `monitor-data` named volume holds the SQLite database, including configuration,
metrics, incidents, and SNMP communities. Container replacement preserves it.
`docker compose down` retains it; `docker compose down -v` deletes it.

Without Docker (Python 3.11+):

```sh
MONITOR_DATA=./data MONITOR_HOST=127.0.0.1 python3 -m app.server
```

Local host checks require the `ping` executable. Compose enables ICMP datagram
sockets for the non-root container through `net.ipv4.ping_group_range`.
Local SNMP polling additionally requires the net-snmp `snmpget` executable. It is
installed in the container. The database backup uses Python's SQLite serialization
support, which must be present in the local Python build.

## Initial workflow

1. Expand inventory/configuration and create a project.
2. Add permanent equipment with its IP address, then assign it to the selected
   project with its project-specific alias. The IP belongs to inventory and is
   shared by every project; change it using the inventory Edit button. A device
   may appear in multiple saved projects.
3. Host ping is configured automatically on assignment. Add any additional services
   using verified OIDs or register addresses.
4. Activate the project. Activation creates a new deployment run and switches the
   sole active project. Pausing stops collection without deleting configuration.
5. Read current metrics, recent readings, and incidents in the dashboard.

Numeric thresholds may be above or below a value. Critical is evaluated first;
two consecutive identical statuses open or recover an incident. Acknowledgement
records a timestamp without clearing the incident. The three assignment controls
are independent; notification flags are currently stored only.

## Implemented

- Permanent inventory with full ID/name, model and IP editing; confirmed permanent
  deletion removes the device and its assignments, services, readings, incidents,
  and legacy address records across all projects. Shared projects/runs survive.
- Shared device IP; saved project assignments with
  per-project aliases. Inventory IP edits apply to all projects.
- One active project, separate deployment runs, retained historical records.
- Independent monitoring and visibility controls.
- Bounded concurrent polling (24 workers), 15-second cycle delay.
- Automatic ICMP host ping (including existing/restored assignments); numeric
  SNMP v2c GET; TCP port reachability; basic Modbus TCP function 03.
- Inline success confirmations and cleared add forms; failed submissions preserve
  input and background refreshes preserve unfinished selections.
- Warning/critical thresholds, two-reading persistence, incident recovery and local
  acknowledgement; unknown/stale status after 60 seconds without a reading.
- Recent metric table (latest 200 readings per service/run), retention in days.
- Consistent SQLite backup and validated restore with polling paused afterwards.
- Local web UI, Compose health check, non-root container, persistent volume.

## Backup and restore

Use the UI's download link to produce a consistent full database snapshot while
monitoring continues. The file includes credentials in plaintext: protect it as a
secret. Copy backups off the monitoring server. Restore accepts this application's
SQLite backup, checks database integrity/table presence, replaces the database,
and sets monitoring to paused. Download a backup before replacing current state.
Older backups with assignment addresses migrate during restore (and existing
databases migrate on startup). Matching addresses move to inventory automatically.
Conflicting addresses are preserved in `legacy_assignment_addresses` and shown in
inventory; the device stays unconfigured and is not polled until an IP is selected.
This migration requires SQLite 3.35 or newer (included in the Docker image).
The current file format remains development-only, without general migration/version
guarantees. Take a backup before upgrading.

For recovery without a working UI: stop the container, use a temporary container
mounting the same named volume to replace `/data/monitor.sqlite3` with a validated
backup, and set `settings.active_run` to `0` using SQLite before restarting. A guided
CLI recovery command and versioned encrypted archives remain planned.

## Explicit limitations / next milestones

- No relay, remote dashboard, Telegram/WhatsApp delivery, or remote acknowledgement.
- No users, authentication, TLS, audit actor identity, or credential encryption.
- No verified manufacturer profiles: do not invent OIDs or Mean Well registers.
- SNMP v2c only. Raw counters are not throughput; counter-rate calculation, counter
  rollover handling, SNMPv3 and vendor profiles are required next.
- Modbus TCP port 502/unit 1 only, unsigned 16-bit holding registers with scale.
  RTU/gateways, alternate unit IDs, signed/multi-register values, bitfields and
  manufacturer fault decoding are pending confirmation of the actual DRS interface.
- Host cards show ICMP online/offline/unknown independently of additional services.
  Paired-radio views and a combined host/service health rollup remain pending.
  Networks that block ICMP will show hosts as offline despite other services working.
- Inventory creation/editing/deletion and service removal are present; assignment
  editing/removal, reusable profile management, cloning, and project readiness
  checks remain to be added.
- No graphs or historical run selector yet; data remains in the database.
- No hysteresis, dependencies, maintenance windows, configurable polling intervals,
  or notification reminders yet. Recovery uses the same thresholds as triggering.
- No scheduled/off-site/encrypted backups, pre-upgrade backup automation, schema
  migration tooling, or downgrade support yet.
- Polling is a cycle, not a precise interval: slow endpoints lengthen the cycle.
  Load testing against 150 actual or simulated endpoints is still required.

## Verification

```sh
python3 -m unittest discover -s tests -v
python3 -m compileall app
```

Tests cover threshold persistence/recovery, acknowledgement, deployment isolation,
credential redaction, OID validation, backup preservation, full inventory edits,
transactional deletion and isolation from delayed polling results. Hardware polling
requires validation with real equipment. See AGENTS.md for full agent context.

Removed services are now disabled rather than detached from their equipment. This
preserves their history and allows subsequent full-device deletion to remove it.
Older versions could leave history for already-deleted services without ownership;
those legacy orphan records cannot reliably be attributed to an inventory item.
