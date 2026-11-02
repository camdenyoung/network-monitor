# Project context

Build a local-first equipment monitor for 100–150 network and power devices.
The user requested readable, consistently indented code and explanatory comments.

## Requirements
- Every assigned host gets automatic ICMP ping; no manually added service needed.
- Successful add forms show inline confirmation and reset; errors preserve input.
- Permanent inventory; reusable project assignments with per-project alias/address.
- Exactly one active project. Each activation creates a deployment run; retain history.
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
