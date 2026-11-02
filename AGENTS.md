# Project context

Build a local-first equipment monitor for 100–150 network and power devices.
The user requested readable, consistently indented code and explanatory comments.

## Requirements
- Every assigned host gets automatic ICMP ping; no manually added service needed.
- Successful add forms show inline confirmation and reset; errors preserve input.
- Permanent inventory; reusable project assignments with per-project aliases.
- Inventory supports full ID/name, model, IP edits and confirmed permanent deletion.
- Device deletion purges all linked assignments, services, history and incidents;
  preserve shared projects/runs and all other equipment.
- IP addresses belong to inventory devices and are shared across all projects.
- Exactly one active project. Each activation creates a deployment run; retain history.
- Services can be copied between host assignments, including across projects.
- Reusable service library supports creation, saving from a host, editing, deletion
  and applying to a host. Copies/templates materialize independent configurations;
  never copy metric history, incidents, acknowledgements or managed host ping.
- Services can be edited in place; retain identity/history and keep blank edited
  SNMP credentials unchanged. Built-in host ping stays managed by the application.
- Active incidents exclude acknowledged ones; show acknowledged and resolved lists.
  Acknowledgement does not clear the fault and stays recorded after recovery.
- Selected SNMP metrics and Mean Well DRS Modbus metrics, not exhaustive discovery.
- Warning/critical thresholds, persistence, recovery, acknowledgement, retention.
- Independent monitoring, visibility, notification controls.
- Local dashboard remains usable without internet.
- A future public relay uses an outbound authenticated connection for dashboard
  synchronization and remote acknowledgement behind NAT/CGNAT.
- Telegram/WhatsApp notifications; provider preference remains undecided.
- Docker Compose, persistent storage, consistent backup and safe restore.

## Equipment
Cisco SG350/SBS350, Ubiquiti EdgeSwitch, Teltonika TSW202, generic industrial
switches; Siklu EH600/614/700/710/2500 and possibly MultiHaul/Terragraph;
Mean Well DRS units. Exact OIDs, register maps, and Modbus transport remain
unverified. Never present guessed mappings as verified profiles.

## Implementation
Python standard-library HTTP server and SQLite, vanilla HTML/CSS/JS.
SNMP polling invokes net-snmp's snmpget in the container; Modbus TCP uses a
small bounded read-only client. No SNMP SET or Modbus writes.
Run `python3 -m unittest discover -s tests -v` and `python3 -m compileall app`.
Run locally with `MONITOR_DATA=./data python3 -m app.server`.
Do not commit runtime data or secrets. Keep the relay/public exposure gated
until authentication, encrypted transport, and replay-safe commands exist.
See README.md for first-pass scope and limitations. Update it honestly.

Automatic ping uses an internal non-removable service, sharing incident/history
handling. `ensure_host_checks` backfills legacy assignments at startup and restore.
GitHub repository: https://github.com/camdenyoung/network-monitor (public).
Git HTTPS credentials are not configured locally; use the connected GitHub app
for publishing if needed. Never upload runtime databases or secrets.

Compose host address/port use MONITOR_BIND and MONITOR_PORT in a gitignored
.env file. Keep the container port and health check on 8080. Maintain .env.example.

`migrate_inventory_addresses` moves old assignment addresses to inventory on startup
and restore. Conflicts are preserved in legacy_assignment_addresses; no address
is chosen automatically and those devices are not polled until configured.
SQLite >=3.35 is required for the migration. Do not restore project-specific IPs.

Service removal disables the service and preserves ownership/history. Poll only
enabled services. Device deletion purges both active and disabled services.
Persistent ID counters in settings prevent ID reuse after deletion; use
next_record_id for device, assignment and service creation, including built-in ping.
The editor must retain failed edits and must not be overwritten by dashboard refresh.

Service configuration revisions isolate in-flight reads and persistence counts
when edited. Migrate revision fields on services/samples at startup and restore.
Never expose stored communities in state or service edit responses.

service_templates stores independent reusable definitions, including credentials.
ensure_service_library runs on startup/restore for backward-compatible backups.
Redact template communities from snapshot, just like normal service credentials.
Deleting a host or library entry must not affect already-materialized copies.
