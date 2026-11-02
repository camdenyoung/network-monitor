# Project context

Build a local-first equipment monitor for 100–150 network and power devices.
The user requested readable, consistently indented code and explanatory comments.

## Requirements
- Project assignment aliases are editable independently; preserve assignment IDs,
  services, history and aliases in other projects.
- Display Healthy, Warning and Critical with initial capitals; keep stored status
  codes lowercase. Confirmed unresolved issues tint host cards by highest
  severity on both dashboards; acknowledged faults retain colour until recovery.
  Ignore suppressed child faults, stale checks and paused monitoring for card colour.
- Both dashboards can hide/show services for host-only Cards/List views. Persist
  this separately per dashboard in localStorage. Keep host details, issue
  severity colours and complete issue lists; presentation does not pause polling.
- Both dashboards have Cards/List views and a case-insensitive substring service
  name filter (e.g. RSSI). Hide hosts without matching enabled services. Persist
  each dashboard's view/filter separately in localStorage; retain public show/hide.
  Filters affect host readings only; issue lists and severity rollups stay complete.
  Preserve role restrictions, history/actions, dependency states and row colours.
- Main dashboard host display controls (Cards/List, service filter, All services
  and host count) sit after Resolved issues, immediately before the hosts.
- Both dashboards place active issues above hosts; on the main dashboard,
  acknowledged/suppressed/resolved sections also precede hosts.
- Keep the signed-in user label in its existing top-left navigation position;
  style it as a bordered, rounded badge without adding a fake button action.
- Align the main project dropdown with activation/pause buttons along the bottom;
  keep the polling note on its own line.
- Reserve a fixed logo slot on the main project toolbar, including when no logo
  is assigned, so project controls stay in place. Public status stacks the project
  logo above the project name in the centre, with Network Status on the left and
  the sign-in/dashboard button on the right (stack branding beneath on narrow screens).
- Admins can duplicate a project into a uniquely named inactive project, copying
  active assignments, current service configs/flags, logo and status settings against
  shared inventory. Never copy runs, samples, issues, sessions or outbox messages.
- Public status supports persisted hostname/alias/host-status/severity sorting.
- Status acknowledgement is an opt-in per-project Admin setting, default off.
  Require a signed-in Admin/Operator and CSRF; enforce the flag/current project,
  visible monitored source and dependency visibility on /api/status-ack. Anonymous
  users and View Only users remain read-only.
- Admins can rename projects and upload/replace/remove PNG/JPEG event logos.
  Logo blobs live in project_logos and are included in backups. Limit 2 MB and
  4096 pixels per side; disallow SVG/active formats. Public logo access is restricted
  to the active project. Renaming preserves identity, assignments and history.
- Both dashboards place active issues above hosts. List rows retain rounded
  card-like outlines, spacing and severity colours. Navigation/download anchors
  use the shared button-link appearance on login, main and public pages.
- Monitor card headings use `Device ID - Alias`.
- Services depend on a fresh healthy host ping. Poll ping first; suppress child
  polling/failure reports for offline, stale or unknown hosts. Preserve existing
  child issues as suppressed, without claiming recovery; resume on fresh reads.
- Services and library entries support numeric metrics or numeric state maps.
  State codes map to labels and healthy/warning/critical; unmapped codes warn.
- Every assigned host gets automatic ICMP ping; no manually added service needed.
- Successful add forms show inline confirmation and reset; errors preserve input.
- Permanent inventory; reusable project assignments with per-project aliases.
- Inventory supports full ID/name, model, IP edits and confirmed permanent deletion.
- Device deletion purges all linked assignments, services, history and issues;
  preserve shared projects/runs and all other equipment.
- IP addresses belong to inventory devices and are shared across all projects.
- Accounts include an optional validated email for future password resets. No reset
  email flow yet. Admins choose must_change_password when creating/editing accounts;
  default true on creation, preserve on edits unless explicitly changed. Bootstrap
  admin always requires an initial change. Migrate old accounts without lockouts.
- Local accounts: Admin, Operator and View Only roles enforced by the server. Admins manage
  users, all configuration, acknowledgements and backups. Operators can inspect
  and acknowledge issues but cannot modify projects/configuration. Viewers inspect only.
- First-run admin password is generated in /data/initial-admin-password.txt or supplied
  via MONITOR_ADMIN_PASSWORD; require change on first login. Never commit defaults.
- Public /status has a show/hide host cards toggle, persisted per browser. The
  active issue list stays visible when host cards are hidden.
- Public /status overview shows active issues above host cards. Reuse dependency-
  aware active issues, excluding resolved/suppressed faults and
  hidden, paused or inactive equipment. Allowlist display fields only.
- Public /status overview needs no login; allowlist active/visible status and values
  without IP addresses, OIDs, credentials, account details or other project inventory;
  acknowledged issues explicitly expose recorded display names and usernames only.
- Telegram group notifications and optional WhatsApp Business Cloud API templates.
  WhatsApp Business does not connect ordinary app-created groups; Telegram is the
  intended shared group route. Both providers have separate settings and queues.
- Exactly one active project. Each activation creates a deployment run; retain history.
- Services can be copied between host assignments, including across projects.
- Reusable service library supports creation, saving from a host, editing, deletion
  and applying to a host. Copies/templates materialize independent configurations;
  never copy metric history, issues, acknowledgements or managed host ping.
- Services can be edited in place; retain identity/history and keep blank edited
  SNMP credentials unchanged. Built-in host ping stays managed by the application.
- Active issues exclude acknowledged ones; show acknowledged and resolved lists.
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

Automatic ping uses an internal non-removable service, sharing issue/history
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
request numeric enum codes. Use incident_lists for current reporting; issues
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
Existing issues stay suppressed, not recovered. Copy/template instances start
independent and enabled.
Removing a device from a project sets assignments.removed=1 and disables its host
monitoring/display. Preserve inventory, other projects, configuration and history.
Exclude archived assignments from polling, current issue lists, selectors and
service targets. Reassign restores the original assignment and invalidates stale
readings. Permanent inventory deletion still purges archived records too.
The configured-service manager starts with no host selected. Filter by host (or
All hosts), name/OID, protocol and monitoring state. Render at most 20 initially
with an explicit Show more; preserve filter choices during background refreshes.

Edit selected project uses separate responsive panels for name, event logo,
status-page settings and duplication. Keep stable form IDs, inline checkbox
alignment, current-logo preview and consistent bottom-aligned actions. Background
refresh must not replace unfinished form edits.
Permanent inventory is collapsed by default and searchable by ID/name, model or
IP. Searching expands it, with 50 initial results and explicit Show more. Preserve
open/search state during refresh; don't render the whole inventory while collapsed.

Public status shows Not signed in or the caller's display name/role, with Sign in /
Dashboard navigation. /api/status exposes the caller's identity and recorded
acknowledging display names and usernames, never account lists, email or password/session hashes. Temporary-password users
get Change password navigation and remain unable to acknowledge.

Acknowledgements retain the authenticated account ID and username at the time of
acknowledgement, including after account rename/deletion. Legacy records display
Unknown user (legacy). The main dashboard has independent Show/Hide controls for
acknowledged, suppressed, resolved and live host/service sections, saved in browser
localStorage. Hiding sections does not pause monitoring or hide active issues.

Main dashboard section visibility buttons use the shared aria-pressed active
colour while their section is visible, including after restoring browser preferences.

Public status includes an allowlisted acknowledged-issue list above hosts, with
a colour-coded Show/Hide toggle persisted separately in localStorage. Apply current
project/host/service visibility rules. Show the recorded acknowledging full name (or username fallback),
with Unknown user (legacy) for older records; never expose actor IDs or account details.

Use Issue/Issues in all user-facing wording, notifications and help text. Preserve
legacy incident API keys, DOM identifiers, storage keys and database names for compatibility.

Accounts have an editable Full Name (up to 150 characters) separate from the login
username. Signed-in labels and acknowledgement attribution prefer the full name,
falling back to username for existing accounts. Acknowledgements snapshot the full
name at acknowledgement time; later profile edits do not rewrite history. Both
startup and restore migrate account/audit fields. Public issue attribution includes
this display name. The main navigation link is labelled Status Dashboard.

User management keeps the add-user form independent. Edit opens a native dialog
with all account fields and inline errors; Cancel leaves the creation form intact.
Populate the editor only when opened; background refresh must preserve edits.

Permanent inventory is its own top-level Admin section, separate from Project
configuration. Keep inventory creation/search/edit/removal there; project assignment
and service configuration remain under Project configuration.

Main dashboard configuration sections use colour-coded Show/Hide buttons instead
of disclosure arrows: Permanent inventory, Project configuration, Reusable service
library, User management, Telegram, WhatsApp Business, and Backup/restore/retention.
These panels always start hidden on page load and do not persist visibility.
Issue-list and live-status visibility preferences remain separate.

Older username-only acknowledgements display the account Full Name after it is
filled in, matching both recorded account ID and username. This enriches response
data without rewriting stored audit records. A real full name captured at the time
of acknowledgement remains authoritative, even after profile changes/deletion.

Status dashboard host display controls (Cards/List, sorting, services and filters)
sit immediately above hosts, below issue lists, and hide when hosts are hidden.
The Show/Hide hosts button stays accessible above the issue lists.

The status Show/Hide hosts button sets aria-pressed to host visibility so the
shared active background follows toggles and restored browser preferences.

The product name is Network Monitor. Retain legacy field-monitor localStorage keys
to preserve browser preferences. Complete backup downloads use a server-generated
network-monitor-backup-YYYY-MM-DD_HH-MM-SS.sqlite3 filename via Content-Disposition,
using the monitoring host local timezone. Compose mounts /etc/localtime read-only
from the host so container time follows the host, including daylight saving.

Current displayed release is v0.1.1. Show it after the title on both the main and
status dashboards. Browser page titles omit the version.

Dashboard version labels use a muted 13px inline small.app-version beside the
main heading, following the AxisPy reference; do not render them at heading size.

Pause all monitoring retains paused_run. Resume all monitoring continues that same
deployment for the selected paused project; it never creates a run or resets history,
issues or per-service pause flags. New deployment remains a separate action and
clears paused_run. Resume requires fresh reads and invalidates pre-pause in-flight
results. Paused deployment survives restart; restore remains paused but resumable.

Pause/Resume all monitoring is one toggle button. Running uses the active green
background; paused uses a slow flashing amber background (static amber when reduced
motion is requested). Resuming retains the paused deployment and still requires
selecting its project. No existing deployment means Resume is disabled.

Pausing all monitoring preserves the current event name and logo on public status.
Public logo access permits the active run, or paused_run when no run is active;
other project logos remain private. The status summary explicitly says Monitoring
paused and does not present live readings or enable acknowledgements while paused.

Activate / start new deployment opens a confirmation dialog with Continue and
Cancel before sending any activation request. Explain that the new run starts a
fresh current history/issue list while prior data remains stored. Resume continues
a paused run. Capture the selected project on opening and retain errors in the dialog.

Main dashboard live hosts and all their display controls sit together inside a
rounded bordered panel, separate from issue lists. Edit alias sits in the host heading beside Device ID - Alias in Cards and
List views. List services use shared grid columns and fixed-width Pause/Resume
and Actions controls so varying names, values and labels do not shift buttons.
