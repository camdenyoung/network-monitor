# Project context

Build a local-first equipment monitor for 100–150 network and power devices.
The user requested readable, consistently indented code and explanatory comments.

## Requirements
- Project assignment aliases are editable independently; preserve assignment IDs,
  services, history and aliases in other projects.
- Display Healthy, Warning and Critical with initial capitals; keep stored status
  codes lowercase. Confirmed unresolved incidents tint host cards by highest
  severity on both dashboards; acknowledged faults retain colour until recovery.
  Ignore suppressed child faults, stale checks and paused monitoring for card colour.
- Both dashboards have Cards/List views and a case-insensitive substring service
  name filter (e.g. RSSI). Hide hosts without matching enabled services. Persist
  each dashboard's view/filter separately in localStorage; retain public show/hide.
  Filters affect host readings only; incident lists and severity rollups stay complete.
  Preserve role restrictions, history/actions, dependency states and row colours.
- Both dashboards place active incidents above hosts; on the main dashboard,
  acknowledged/suppressed/resolved sections also precede hosts.
- Admins can rename projects and upload/replace/remove PNG/JPEG event logos.
  Logo blobs live in project_logos and are included in backups. Limit 2 MB and
  4096 pixels per side; disallow SVG/active formats. Public logo access is restricted
  to the active project. Renaming preserves identity, assignments and history.
- Both dashboards place active incidents above hosts. List rows retain rounded
  card-like outlines, spacing and severity colours. Navigation/download anchors
  use the shared button-link appearance on login, main and public pages.
- Monitor card headings use `Device ID - Alias`.
- Services depend on a fresh healthy host ping. Poll ping first; suppress child
  polling/failure reports for offline, stale or unknown hosts. Preserve existing
  child incidents as suppressed, without claiming recovery; resume on fresh reads.
- Services and library entries support numeric metrics or numeric state maps.
  State codes map to labels and healthy/warning/critical; unmapped codes warn.
- Every assigned host gets automatic ICMP ping; no manually added service needed.
- Successful add forms show inline confirmation and reset; errors preserve input.
- Permanent inventory; reusable project assignments with per-project aliases.
- Inventory supports full ID/name, model, IP edits and confirmed permanent deletion.
- Device deletion purges all linked assignments, services, history and incidents;
  preserve shared projects/runs and all other equipment.
- IP addresses belong to inventory devices and are shared across all projects.
- Accounts include an optional validated email for future password resets. No reset
  email flow yet. Admins choose must_change_password when creating/editing accounts;
  default true on creation, preserve on edits unless explicitly changed. Bootstrap
  admin always requires an initial change. Migrate old accounts without lockouts.
- Local accounts: Admin, Operator and View Only roles enforced by the server. Admins manage
  users, all configuration, acknowledgements and backups. Operators can inspect
  and acknowledge incidents but cannot modify projects/configuration. Viewers inspect only.
- First-run admin password is generated in /data/initial-admin-password.txt or supplied
  via MONITOR_ADMIN_PASSWORD; require change on first login. Never commit defaults.
- Public /status has a show/hide host cards toggle, persisted per browser. The
  active incident list stays visible when host cards are hidden.
- Public /status overview shows active incidents above host cards. Reuse dependency-
  aware active incidents, excluding acknowledged/resolved/suppressed faults and
  hidden, paused or inactive equipment. Allowlist display fields only.
- Public /status overview needs no login; allowlist active/visible status and values
  without IP addresses, OIDs, credentials, user data or other project inventory.
- Telegram group notifications and optional WhatsApp Business Cloud API templates.
  WhatsApp Business does not connect ordinary app-created groups; Telegram is the
  intended shared group route. Both providers have separate settings and queues.
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
- Telegram is the shared-group notification route; WhatsApp Business is optional.
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

migrate_value_types runs at startup/restore after ensuring the template table.
Keep value_type/state_map in every service/template create/edit/copy/apply path.
Samples retain numeric values and display labels as read. State modes use raw
codes (scale=1) and mapped severity, not numeric thresholds. SNMP uses -Oeqv to
request numeric enum codes. Use incident_lists for current reporting; incidents
contains historical records which can include currently suppressed child faults.

Service monitor cards use a compact native details/summary Actions menu. Retain
open menu state during background refreshes; close on choosing an action.
History supports graph/table views over the latest 200 readings. Numeric graphs
use lines; states use labeled steps. Preserve explicit/long gaps; never connect
readings from different configuration revisions. No external chart dependencies.
Optional UI logic checks: `node tests/dashboard.test.mjs` (Node 18+).

Auth is in app/auth.py: scrypt password hashes, opaque hashed session tokens,
HttpOnly SameSite cookies, CSRF, login throttling, forced temporary-password changes.
Do not authorize by UI hiding alone. Revoke sessions on user changes; protect the
last admin. Restore invalidates sessions and retains accounts for legacy backups.
app/notifications.py implements a durable per-provider outbox with retries, no
secret logs and no replay on restore. Never perform live test sends without user
instructions; unit tests mock external providers. Provider endpoints are fixed.
Store only admin configuration locally; redact all provider tokens from GET APIs.
Health checks use /api/health, not authenticated /api/state.
Testing includes tests/test_access_notifications.py and dashboard.test.mjs.

Admin-only Pause/Resume is per-host service monitoring, separate from soft service
removal. monitoring_since invalidates queued reads and resets persistence without
changing the configuration revision. Log explicit paused/unknown gaps. Paused
services do not poll, colour hosts, report active faults, or send notifications.
Existing incidents stay suppressed, not recovered. Copy/template instances start
independent and enabled.
Removing a device from a project sets assignments.removed=1 and disables its host
monitoring/display. Preserve inventory, other projects, configuration and history.
Exclude archived assignments from polling, current incident lists, selectors and
service targets. Reassign restores the original assignment and invalidates stale
readings. Permanent inventory deletion still purges archived records too.
The configured-service manager starts with no host selected. Filter by host (or
All hosts), name/OID, protocol and monitoring state. Render at most 20 initially
with an explicit Show more; preserve filter choices during background refreshes.
