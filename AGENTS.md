# Project context

Build a local-first equipment monitor for 100–150 network and power devices.
The user requested readable, consistently indented code and explanatory comments.

## Documentation and release workflow

Keep build history and release notes in CHANGELOG.md, linked near the top of
README.md. README.md contains setup/usage guidance, not duplicated release logs.

Every displayed version change must update the README title and add concise release
notes in CHANGELOG.md describing that release. Keep both dashboard labels and this version context
in sync; do not add versions to browser tab titles.

Every future update commit must increment the displayed build number on BOTH
dashboards, update the README current build and add a brief build note to
CHANGELOG.md in the same commit. Keep the small inline format vVERSION · Build N. Build numbers
increase monotonically across releases; do not reset them when the version changes.
Do not put version/build numbers in browser tab titles. Build 1 starts this policy;
earlier commits were not numbered.

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
- Status acknowledgement is a per-project Admin setting, enabled for newly created
  projects. Preserve existing flags on startup/restore and copy the flag on duplication.
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
  users, all configuration, acknowledgements and backups. Operators follow the globally
  active/paused project, can resume its existing deployments, toggle global monitoring/
  notifications and individual additional services, and acknowledge/unacknowledge issues.
  Viewers follow the global project AND deployment, including history, and inspect only.
  Neither restricted role can switch projects or create/delete deployments; configuration
  stays Admin-only. Scope APIs server-side, not just controls in the UI.
- First-run admin password is generated in /data/initial-admin-password.txt or supplied
  via MONITOR_ADMIN_PASSWORD; require change on first login. Never commit defaults.
- Signed-in /status users have a show/hide host cards toggle, persisted per browser.
  Anonymous visitors see no Live Hosts or host controls; public issue lists stay available.
- Public /status overview shows active issues above host cards. Reuse dependency-
  aware active issues, excluding resolved/suppressed faults and
  hidden, paused or inactive equipment. Allowlist display fields only.
- Public /status issue overview needs no login; live hosts/readings require an
  authenticated session without a forced-password-change restriction. Never expose
  IP addresses, OIDs, credentials, account details or other project inventory;
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
History supports graph/table views over selected deployment/time ranges (legacy API retains latest 200). Numeric graphs
use lines; states use labeled steps. Preserve explicit/long gaps; never connect
readings from different measurement versions. Alarm-only edits keep compatible graph continuity. No external chart dependencies.
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

Admin/Operator Pause/Resume is per-host service monitoring, separate from soft service
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

Main dashboard configuration sections are exclusive. Project configuration uses
a top disclosure button before the issue visibility controls; other areas use
lower colour-coded tabs (inventory, library, users, reminders, providers and backups).
These panels start hidden on page load. Selecting a tab shows only that configuration
area, without hiding issue/live host sections; selection is not persisted.
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

Current displayed release is v0.6.3, Build 120. Show it after the title on both the main and
status dashboards. Browser page titles omit the version.

Dashboard version labels use a muted 13px inline small.app-version beside the
main heading, following the AxisPy reference; do not render them at heading size.

Pause all monitoring retains paused_run. Resume all monitoring continues that same
deployment for the selected paused project; it never creates a run or resets history,
issues or per-service pause flags. New deployment remains a separate action and
selects its new run in paused_run with active_run=0. Resume requires fresh reads and invalidates pre-pause in-flight
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

Main account navigation keeps the signed-in badge left and groups Status Dashboard
and Sign out on the right, wrapping the action group on narrow screens. Do not
show a separate Change password link in the Admin Dashboard top navigation.

Sign-in from the status dashboard uses /login?next=%2Fstatus and returns there
after login, including any required password change. Admin dashboard sign-in
defaults to /. Only /status and / are allowed return destinations; external or
unrecognised URLs fall back to /. Return context is kept in the login URL per tab.

Admins can set the fixed session duration in User management → Login sessions
(1–168 whole hours, default 12). Changes apply to new sign-ins, not existing
sessions; activity does not extend expiry. The database setting controls both
server session expiry and cookie Max-Age and is included in backups.

The status dashboard groups live hosts, display controls and filter helper text
inside a single padded rounded border, matching the Admin dashboard. Card grids
have 16px spacing below the helper text. Show/Hide hosts hides the entire bordered
panel; issue lists, their controls and the update timestamp remain outside it.

Both dashboard live host panels have a Live Hosts heading above their controls,
inside the border, and it hides together with the panel.

Admin issue lists use the shared metric row spacing and top separator border,
matching public status for active, acknowledged, suppressed and resolved issues.

Both dashboards require a confirmation popup before acknowledging an issue.
Cancelling sends no acknowledgement request; confirming preserves existing role,
CSRF and status-project acknowledgement restrictions.

Admins configure a shared Telegram/WhatsApp issue reminder interval in Issue
reminders (0 disables, default 0; otherwise 1–10080 whole minutes). Repeat only
active, unacknowledged issues with fresh matching fault readings. Respect project
activation, host dependency, monitoring/removal and notification flags. Recheck
eligibility before delivery. The durable outbox tracks per-channel cadence, with
at most one pending/in-flight reminder per issue/channel and no restart catch-up
bursts. Reminder settings are included in database backups.

Acknowledgement confirmation on both dashboards uses a styled in-app dialog,
not window.confirm. Show the target issue, explicit Acknowledge issue and Cancel
buttons, inline errors, and matching dark panel/backdrop styling. Opening or
cancelling sends no request; disable repeat submits while saving.

Both dashboards display deployment-specific issue numbers on rows and acknowledgement
dialogs, matching Telegram/WhatsApp notifications. Internal IDs remain API keys.

Telegram and WhatsApp Business issue notifications start with severity icons:
✅ recovered, ❌ critical/unreachable, ⚠️ warning. Reminders retain the severity
icon and explicit REMINDER label; keep the text status for clarity.

Displayed issue numbers start at #1 for every deployment. Keep incidents.id as
the internal globally unique API/acknowledgement key; use incidents.number for
UI and notification labels. runs.issue_counter is durable across deletions and
pause/resume. Startup/restore number legacy issues by ID order within each run,
without changing their IDs. Notifications include the deployment ID for context.

Starting a deployment requires a 1–500 character description in the confirmation
dialog, validated on the server. runs stores the description and original start
timestamp. The main dashboard shows both for the active or paused run. Pause/Resume
preserves them; older runs retain an empty description rather than invented text.
Deployment descriptions are included in SQLite backups but not public status APIs.

Permanent inventory devices have independent standard service definitions in
`device_service_defaults`. New project assignments materialize copies of these
configs/credentials with monitoring enabled; never link runtime services back to
defaults or copy samples/issues. Existing and reactivated archived assignments
retain their configs. Project duplication copies the project's services, not the
inventory defaults. Defaults have CRUD, library import, and explicit replacement
from a selected project assignment of that same device. Do not infer defaults
from existing projects on migration; offer explicit adoption to avoid conflicts.
Duplicate names are rejected rather than silently losing definitions. Ping stays
managed and is never a default. Redact default communities from snapshots, include
all defaults in backup/restore, and purge only that device's defaults on deletion.

Admin configuration areas are exclusive accessible tabs with arrow/Home/End
navigation and active colour. Keep unfinished forms intact when switching areas.
Status background pulses three times (red Critical/Unreachable, yellow Warning) for new active issues, not
initial load or reappearing previously seen issues. Track internal IDs/labels per
deployment and preserve the seen set across pause/resume. Honour reduced motion
with a brief static red highlight instead of animation.

Clicking the selected configuration tab closes its panel, allowing all config
areas to be hidden. Other tabs switch areas. Preserve the keyboard tab stop and
unsaved form values when closing/reopening.

Admin Pause/Resume notifications is a separate global toggle beside monitoring.
It gates both providers, tests, retries, initial/recovery alerts and reminders,
without modifying provider/host configuration, polling or issues. Persist the
mute setting in SQLite. Cancel pending alerts on pause and do not queue events
while muted. Resume restarts reminder cadence without replaying a backlog.
An HTTP send already in flight at the time of pause cannot be recalled.

Starting any new deployment always pauses global notifications and cancels pending
alerts in the same transaction. Explain this in the start confirmation dialog.
Admins must explicitly Resume notifications for the new deployment. Resuming an
existing deployment preserves the current global notification state.

Status navigation (Admin Dashboard / Sign in / Change password) sits on the
same control row as acknowledged-issue and host visibility toggles, aligned
right with auto margin. The logged-in badge remains at the header top right.

The new-project form can reuse a logo from any existing project with a preview.
Copy project_logos image/mime/digest into an independent new-project row in the
same transaction as project creation. Invalid/deleted choices reject creation
without leaving a partial project. Blank means no logo; refresh preserves drafts.

Reusable service library import/export is Admin-only. Export versioned JSON of
service definitions including communities, with a host-local timestamp filename.
No database IDs, accounts or runtime/history records travel in the file. Merge
keeps exact case-sensitive name matches; Replace changes only service_templates.
Fully validate all entries before any mutation; import runs in one transaction,
rejecting duplicate file names, unsupported schema/types and invalid service
configs without partial writes. Keep instance services/defaults/history untouched.
Use in-app confirmation for imports, report added/skipped/replaced totals, and
keep errors in the dialog. Bound files to 5 MB and 5000 services. Export files
contain credentials and must be described as sensitive. app/service_library.py
owns the portable format; server.service_details remains the config validator.

The Admin dashboard subtitle is Project based network monitoring.

Admins can select previous deployments for the selected project and resume one
through an in-app confirmation. Show run number, original start time and
description; clearly disclose stopping any current run, current project config,
fresh checks and paused notifications. /api/resume-deployment requires Admin/CSRF,
validates run ownership and an expected_active_run lease before changes, preserves
run metadata/history/issue counters/service flags, invalidates stale in-flight
reads via monitoring_since, and pauses notifications/cancels pending messages.
Never create a run or restore old service configs when resuming an existing run.
The quick Pause/Resume monitoring toggle keeps its existing behavior.

Delete selected deployment is Admin/CSRF-protected and requires explicit in-app
confirmation describing permanent deletion of run/readings/issues/acknowledgements/
related outbox rows. Require inactive target, project ownership and expected active
run before changes. Purge only the chosen run, transactionally; preserve configs,
other runs and inventory. Clear paused_run only when it references the target.
Durable last_id_runs and last_id_incidents counters prevent ID reuse after deletion,
protecting delayed polling and stale acknowledgement/resume dialogs. Migrate these
counters on startup/restore and allocate both IDs through next_record_id.

Status attention pulses use yellow for new Warning issues and red for new
Critical/Unreachable issues, three cycles. Critical wins mixed arrivals and is
not downgraded by a warning arriving mid-pulse. Both visuals remain independent
of global notification pause; reduced-motion highlights use the same severity colour.


Flap protection lives in app/stability.py. Per-check settings travel through library,
inventory defaults, copies and project duplication. Defaults: enabled, four confirmed
changes within five minutes, five continuous stable minutes to clear; hysteresis zero.
Runtime is durable and scoped to run/service/revision/monitoring_since. Gaps and blocked
reads cannot count as stable. Suppress ordinary alerts/reminders while flapping;
unique episode start/end events use the durable outbox and obey global notification pause.
Opening issues store immutable trigger_value/display/units/timestamp/error. Show these
on both dashboards and use them in opening notifications. Never replace historical
cause with a later sample or edited state mapping. Legacy missing evidence stays unknown.

Display recorded issue values without a Triggered by prefix. Ping failures display
Host unreachable on both dashboards and notifications, including older saved issues;
retain internal exception classes for diagnostics, not the host-facing state.

Telegram delivery log is wrapped in its own bordered section. Show/Hide log
starts hidden on every page load; reflect visibility with aria-expanded and
aria-pressed plus the standard green active button. Data refresh preserves visibility.

Recovery notifications include only the current reading/state, never the original
triggering value. Opening evidence remains available in issue records and reminders.

Both dashboards use span.issue-value with identical 16px regular text for saved
issue readings, outside small metadata. Severity labels use normal-weight spans;
timestamps, recovery and acknowledgement details use small on both dashboards.

Flap-start notifications begin with four lines: ⚠️ FLAPPING - project; host - alias;
service: current value/units; Issue #n - Deployment #n. Omit the momentary severity
and historical opening value from that notification.

Append Notifications for this check are suppressed until it stabilises. to
flap-start notifications, making the scope of temporary suppression clear.

Keep the warning icon at the start of flap-start notifications: ⚠️ FLAPPING.

Telegram sample selector sends connectivity, critical, warning, recovery, flapping,
stable, host-unreachable and port-state examples through the existing Admin/CSRF
protected test endpoint and durable outbox. Use sample_notification and the same
format_issue_message renderer as live events; fictitious data never creates issues,
samples or deployments. Respect saved provider settings and global notification
pause. Test outbox rows have no incident and bypass real-check suppression. Reject
unknown sample types before queueing; old callers default to connectivity test.

STABLE notifications match the four-line flapping layout with icon, project,
host/alias, current service reading and issue/deployment numbers. Do not append
HEALTHY or other severity to the heading, or the historical opening value.

UI polish: user-management entries have independent rounded borders. All app
checkboxes use 24px native controls; stacked checkbox fields reserve the same
35px control height as other fields so Enabled/Send recoveries labels align.
Keep inline checkbox labels and project settings at the same 24px size.
Project and previous-deployment selectors share grid columns and right edges;
primary and previous-deployment action groups start in the same next column.
Collapse to a single column on narrow screens and reserve the logo slot.
Status navigation groups Admin Dashboard and Sign out at the right. Sign out is
visible to all signed-in roles (including temporary-password users), uses the
CSRF token from /api/me with /api/logout, and stays on public status afterwards.
Do not expose additional account information or widen acknowledgement permissions.

Previous-deployment dropdown spans the logo and project-selector columns so it
starts at the toolbar's left edge and ends at Selected project's right edge.
Keep its action group in the shared next column. Telegram Discover groups sits
inside the settings form between Send recoveries and Save settings; type=button
must prevent accidental saves. Telegram delivery log keeps the newest ten
single-line 40px entries visible (400px maximum), with keyboard-accessible vertical
and horizontal scrolling inside its border for older entries and long text.

Host flap-protection dialog identifies its target with Device ID - project alias
using textContent every time it opens. Reject missing/removed targets. The host
form has no numeric hysteresis control. Service editing uses a responsive wide
three-column grid; .flap-settings spans its own row, with side-by-side settings
that wrap on narrower screens. Use the same horizontal fieldset for library,
inventory defaults and service creation. Keep Save/Cancel together below settings.

In the service editor, Consecutive readings follows Critical in the same
Warning / Critical / Consecutive readings row, before the flap settings.

Service forms disable irrelevant protocol fields on initial load, editor opening,
protocol changes and successful add-form reset. SNMP enables community only;
Modbus enables unit ID only; TCP disables both. Do not clear disabled drafts.
Keep native disabled styling visible. Missing unit on edit preserves the existing
value in service_details, as missing community already preserves the secret.
Apply the shared editor rules to services, library definitions and device defaults.

Project configuration no longer contains the inline Selected services creation
form or its assignment selector. Create definitions in Reusable service library
and apply them with Add to host. Preserve the separate Configured services
filter/management section, service feedback and host actions, existing services,
inventory defaults and history. The shared editor still supports library/default
creation and editing of existing project services.

Assign-equipment dropdown excludes all non-removed assignments in the selected
project, including hidden/paused hosts. Devices assigned only elsewhere and
removed assignments remain eligible. Recompute on project change and refresh;
preserve eligible selection, clear it after assignment, and explain empty choices.

Actions menus use viewport-fixed floating panels in Cards, List and configured
services, escaping list scroll clipping without growing rows. One menu may be
open globally; outside clicks, action selection, Escape, page/list scroll and
resize close it. Escape restores trigger focus. Internal menu scrolling remains
usable. Polling restores only a unique location:service key, never both live and
catalogue occurrences; clear it if the target disappears. Keep popup within the
viewport, opening upward near the bottom. Other details elements are unaffected.

Removing a host service uses the shared styled in-app confirmation, never native
confirm(). Show Device ID - Alias / service name using textContent, explain that
history is retained, and capture the target. Cancel/Escape send no mutation.
Disable controls while saving, keep errors in the dialog, reject unavailable
services and preserve backend Admin/CSRF enforcement and soft-removal semantics.

All destructive/replacement confirmations use app-styled dialogs; no native
confirm/alert/prompt calls remain. The shared administrative confirmation captures
IDs or the actual backup File before approval, uses textContent for target labels,
keeps Cancel focused, blocks duplicate saves/closing in flight and retains API
errors inline. Success refresh failures must not imply the mutation failed.
Covers device deletion, project removal, library deletion, default deletion/adoption,
user deletion and backup restore. Preserve server-side Admin/CSRF/last-admin checks.
Restore invalidates sessions; after success return to login, not authenticated refresh.

Configured Services rows separate name/protocol details from right-aligned
Pause/Actions controls with a 24px gap, wrapping safely on small screens.
Project Assignments identifies equipment as Device ID - Alias / Address;
resolve Device ID and IP from permanent inventory and escape all displayed text.

Admins/Operators can Unacknowledge via app-styled dialogs on both dashboards.
Main /api/unack requires the active deployment and a current acknowledged,
enabled, non-removed source; it can undo suppressed or recovered issues.
Status /api/status-unack additionally enforces project acknowledgement opt-in,
public visibility/monitoring and dependency rules (skip dependency for recovered
issues). Require CSRF and an integer expected_revision matching ack_revision;
stale confirmations cannot undo newer cycles. Clear only current acknowledgement
fields, preserving recovery/evidence/history; normal list predicates route to
Active/Suppressed/Resolved. No new opening notification. Restart reminders from
unacknowledged_at and cancel pending reminder rows on ack-state changes.
incident_acknowledgement_events snapshots actor ID, username/full name, time,
action and revision; retain through user rename/deletion and backup/restore,
cascade with issue/deployment/device deletion. Migrate existing acknowledgement
snapshots once. Authenticated state includes acknowledgement_history; public
status allowlists only current attribution and ack_revision, not the audit table.

Issue acknowledgements and committed operational changes publish an opaque revision through /api/ack-events SSE
only after mutate commits; rejected actions and duplicate no-op acknowledgements
do not emit. No issue/actor/account data travels over this public stream. Each
browser fetches its existing role-filtered API data. Connect on load/reconnect,
refresh on visibility/focus, close on pagehide and reconnect on cached pageshow.
Keep 10-second polling fallback. Coalesce/serialize refreshes and fetch once more
when an event arrives in flight, preventing stale responses overwriting changes.
Condition waits hold no SQLite connection or monitor lock; heartbeat every 15s,
flush events immediately and disable reverse-proxy buffering via response header.

Row-level acknowledgement controls use class issue-action on both dashboards
with explicit 15px font, 20px line height and 4px/8px padding, including inside small metadata.

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

Docker build context excludes database files, live data, local environment files
and bytecode caches so generated multi-gigabyte test history is never copied into images.

History performance: ensure_sample_indexes runs through lifecycle migration on startup
and restore. sample_current supports service/run/revision/latest-ID lookups;
sample_expiry supports bounded retention. Snapshot uses one indexed latest-ID lookup
per service, respecting revision and monitoring_since. host_is_up resolves ping first.
Never group all samples for live state. prune_samples removes at most 1,000 expired
rows per polling cycle, so retention reductions drain gradually. First index creation
on large existing databases takes time and disk space; logs identify each build.

current_samples handles fresh-read gaps after resume: fetch the latest N IDs first,
then fall back to sample_lookup's timestamp range if pre-resume rows are present.
Use it for snapshot, host dependency and persistence checks. Never fill a limit by
scanning all pre-resume history. Keep latest-ID semantics for out-of-order imports.

Dashboard presence lives in app/presence.py. Main and public status polling carry
an opaque per-tab X-Dashboard-Connection ID. Count tabs/connections (including
anonymous viewers) separately from distinct active authenticated accounts. Expire
at 60 seconds using monotonic time; cap at 4,096 entries. Validate session CSRF IDs
against current nonexpired sessions before counting users; never expose IDs/tokens
or counts on public/status or non-Admin state responses. No new DB writes or
session-lifetime extension. Counts rebuild after restart and are approximate;
multiple tabs count as multiple connections. UI is a top navigation badge for Admins.
Build 114 supersedes the badge's approximate connection count: use the actual
admitted live-update stream count from app/connections.py and display current/limit.
The presence tracker still supplies the distinct active-account count only.
Default dashboard_connection_limit=20, Admin/CSRF configurable 1–200 in Settings
(legacy reminder-panel/tab IDs), alongside issue reminders. Preserve drafts and
the setting on restart and backup/restore; legacy databases get the default.
Lowering the limit retains existing streams. Overflow receives 503; both dashboards
close failed EventSources and retry via normal refresh/focus after 30 seconds,
retaining ten-second polling. Stream slots always release in finally. Ordinary
requests have a separate pre-thread limit of 32 and 30-second socket inactivity
timeout, preserving sign-in/Admin capacity even with full stream slots. Counts
and settings remain Admin-only; anonymous streams consume capacity normally.

Build 115 keys /api/ack-events streams by the validated optional connection query
ID (the existing browser tab identity). Reconnects reserve/reuse that slot even
at capacity: cancel the previous socket, wake live_updates waiters without changing
the revision, and wait at most one second for cleanup AND the actual worker exit.
Only then start the replacement; timed-out handovers retain real capacity until
the old worker exits. StreamLease handles isolate generations and delayed cleanup.
The HTTP server releases registered leases after handler/socket cleanup; do not
merely decrement the counter while an old worker is still waiting. Legacy clients
without IDs get independent bounded slots. Browser BroadcastChannel arbitration
separates duplicated sessionStorage identities before opening streams on both
dashboards; pagehide releases claims and pageshow rechecks on cached restores.
Keep the opaque IDs separate from authorization; all existing API roles/CSRF stay.
Tests use normal 15s heartbeats and held upstream sockets at twenty-stream capacity,
checking old thread exit, not just counts. Also run dashboard_stream.test.mjs.

Build 116 resolves BroadcastChannel conflicts throughout the document lifetime,
including replies after the initial 150ms startup wait. Older document timestamps
win, with unique document-owner IDs breaking ties; Build 115 messages without a
timestamp count as older peers for compatibility. Losing documents close their
old EventSource, persist a fresh tab ID, and announce/recheck the new claim. Ignore
wrong-target, malformed, stale-channel and stale-stream callbacks. Missing/failed
coordination uses ten-second polling WITHOUT opening an EventSource; cancel timers,
close the channel/stream and retry coordination on cached-page restoration. Retain
server admission/handover limits, monitoring, role checks and acknowledgement CSRF.
The global 20-stream default does not override browser HTTP/1 per-origin socket
limits; six streams in one browser can starve API requests. Document that separate
limit and leave browser-level stream sharing outside this focused fix.

Store dashboard connection identity under network-monitor.dashboard-connection
in sessionStorage on both dashboards. Reuse it on reload/navigation, validate
stored values, and fall back to a temporary ID if storage is unavailable. Do not
use shared localStorage (which would merge separate tabs).

Recovery takes precedence over acknowledgement for issue list membership:
Active = open/unacknowledged; Acknowledged = open/acknowledged; Resolved = closed,
regardless of acknowledgement. Retain acknowledgement attribution, revision and
audit history on recovery. Public status consumes the same open-only acknowledged
list; recovered entries disappear there (no new public history section). No data
migration is needed: existing recovered/acknowledged records route to Resolved.
Resolved issues display acknowledgement attribution but no Unacknowledge button.
Only unresolved acknowledged issues can open/confirm that dashboard dialog. If
recovery arrives while the dialog is open, reject submission and request review.

Deployment selection defaults to paused monitoring and notifications: activate and
resume-deployment set active_run=0 and paused_run to the selected run. Only global
resume starts checks (without unpausing notifications). Retain per-service/host
flags, metadata, history and counters; invalidate in-flight reads when switching.
Both pause buttons pulse while paused, with prefers-reduced-motion disabling the
animation. Confirmations explain the two explicit resume steps. Benchmark seeding
opts into global resume after activation so the harness still measures polling.

Dashboard connection recovery: both inline scripts share identical marked guard
blocks. dashboardFetch bounds reads/JSON bodies (8s) and writes (60s), aborts hung
requests and blocks new writes while locked. Never replay mutations automatically.
After 30s without a completed refresh, make existing body children inert and show
an app-styled modal that cannot be dismissed until fresh data finishes rendering.
Normal polling/focus/SSE GET retries continue. Restore prior inert state, preserve
forms/confirmations and clear only recorded connectivity messages after recovery.
Main refresh retries loadSession if initial authentication lookup failed. Resume
SSE after a successful refresh, including startup recovery. Test both dashboard
scripts using tests/dashboard.test.mjs and tests/connection.test.mjs (fake network,
clock, timeout, stalled JSON body, blocked writes, recovery and preserved drafts).

Both disconnect dialogs show three softly pulsing teal dots next to Reconnecting
automatically, using the app accent colour. Animate only while the dialog is open;
show static dots under reduced motion. Keep decorative dots aria-hidden and retain
accessible status text.

Status Dashboard connection-notice sits immediately below summary near the top,
so the initial retry notice appears beneath Failed to fetch before issue/host lists.

Admin report appends — Server connection lost only for errors recorded by the
connection guard. Recovery clears both the original and annotated error messages.

Admin Live Hosts has the same six sorting choices as public status. Persist under
field-monitor.main.host-sort independently from field-monitor.status.host-sort.
Use fresh ping status via readingStatus for ordering and server incident_status
for severity; numeric, case-insensitive hostname comparison breaks ties. Sorting
applies after filtering to both Cards/List and never changes issue/config lists.

Initial Admin project selection follows active_run's project, then paused_run's
project, then the first available project. Validate that the project still exists.
Never overwrite a valid manual selection on polling/focus/SSE refresh. Use the
same fallback if a selected project becomes unavailable; handle empty inventory.

Admin project toolbar's fixed logo slot shows a themed network-icon placeholder
when the selected project has no logo; hide it when an image is present. With no
project, label it Select a project. Keep toolbar dimensions/alignment unchanged.

Project deletion: app/project_deletion.py owns a durable project_deletions job table.
Admin/CSRF project-delete queues a named/captured project, rejects a running target,
quarantines assignments/services and clears a matching paused_run. Worker batches
1,000 samples per transaction, purges service-owned issues/outbox/audit/stability,
then scans a captured row-ID horizon in bounded chunks for legacy orphan readings
owned by the project's deployments. Finally remove runs/assignments/logo/project.
Preserve devices, defaults, library, accounts and other projects. Keep completed
job metadata. Persist project ID counters through next_record_id to prevent reuse.
Resume queued/running jobs on startup; failed jobs require explicit retry. While
unfinished, reject configuration changes and backup downloads. Block restore
while queued/running; allow restoring a prior backup as recovery from a failed job. Operational pause,
notification pause and acknowledgement remain available. Status/progress is Admin-only
in /api/state. Restore migrates the job table; never delete shared inventory.

History ranges: app/history.py validates service/run project ownership, finite
start/end and a 31-day maximum. Query sample_lookup in timestamp-keyed batches
without LOCK, cap concurrency at four and graph work at 20s. Short graphs <=2,000
points are exact; numeric summaries retain first/last/min/max in 300 buckets.
State transitions are exact until the cap, then explicitly flag summary overflow.
Segment IDs preserve invalid/missing/measurement gaps; aggregated points must not
create false gaps just because points are farther than 60s apart. Table mode uses
200 exact readings per page with timestamp/id cursors. Keep the legacy no-range
API response for older clients. Browser history GET timeout is 30s; other reads
remain 8s. Dialog presets/custom datetime-local ranges use browser timezone and
all project deployments, including paused/previous runs. Request tokens reject
stale/closed-dialog responses; graph and exact table use the same interval.

Admin project toolbar measures complete button groups against the shared action
column's available width. If the three project actions do not fit, move the whole
group below Selected project. Independently move both previous-deployment actions
below their dropdown if they do not fit. Keep groups nowrap until moved; allow
narrow-screen wrapping afterward. ResizeObserver watches toolbar/buttons and
refresh/resize also update placement; no fixed desktop breakpoint or DOM moves.
Preserve logo reservation, dropdown edges, button listeners and keyboard order.

When the project action group moves below, span the full toolbar and align its
left edge under the logo. Preserve the previous-deployment action placement.

Account actions stay right-aligned when they fit beside visible user/presence
badges. Otherwise move the complete group to a full-width left-aligned row.
Measure button/badge widths, observe nav and label changes, and handle non-Admin
hidden presence badges. Do not allow auto left margin to right-align a wrapped row.

Responsive host view: identical createHostViewFit helpers in both dashboards
measure an inert, aria-hidden, fixed/clipped list probe at its intrinsic minimum
width. Remove popup contents and duplicate IDs/menu keys from the probe. Do not
let it participate in live action restoration. Cache markup, observe container
and probe widths, and ignore height-only changes/hidden panels. Force effective
Cards and disable List with an explanation when the list overflows; never overwrite
the saved hostView preference automatically. Restore preferred List with 24px of
spare width to prevent scrollbar/rounding oscillation. Explicit Cards selection
still updates the saved preference. Re-evaluate on service/filter changes and
when hosts are shown. Public toggle labels use effective view. Resize-only status
renders must not clear connection-loss messages; fresh-data renders may do so.
Cards use min(290px,100%) grid tracks to fit narrow containers. Test with
node tests/host_view.test.mjs plus dashboard and connection suites.

Live host card controls must never break Pause/Resume labels letter-by-letter.
Use non-shrinking nowrap buttons and a wrap-reverse service-controls group so
Pause/Resume moves below Actions when space runs out. Keep list/catalogue layout
rules unchanged; use matching defensive card styles on both dashboard pages.

Admin #dashboard.grid is capped at three card columns using its minimum track
width, while auto-fit still reduces to two/one and fills space for fewer hosts.
Do not apply this three-column cap to the public Status Dashboard.

Modbus TCP services have a separate modbus_function field, limited to 3 or 4.
The shared editor reuses the community slot: SNMP shows the community password,
Modbus shows Holding (03)/Input (04), TCP hides both. Disable irrelevant controls
without clearing drafts. Persist the function through all shared configuration
paths. migrate_modbus_functions defaults legacy service/template/device-default
rows to 3 on startup/restore. Library format v3 exports it; import v1/v2 remains
accepted with default 3. Validate MBAP identity, unit, length, function and byte
count; handle exception/truncated responses without treating them as readings.
Keep the TCP-to-RTU gateway transport on port 502 and existing unsigned single
16-bit scaling. Test protocol framing and migration in tests/test_modbus.py.

Numeric display_value uses 15 significant digits to remove binary scaling residue.
Keep raw sample values and threshold/persistence calculations unchanged; state labels
remain authoritative. Existing recorded history/evidence is not rewritten.

Admin Project configuration is above Active issues, below its top control button.
Keep its button outside lower-tab arrow-key navigation; coordinate exclusive visibility. Reusable service library mirrors inventory
with collapsed-by-default details, case-insensitive name/protocol/target/units search,
auto-expand on searching and 50-entry Show more. Preserve query/open/limit on refresh,
and retain library create/import/export and row actions. Header status uses separate
green Active/yellow Paused bordered badges before project/deployment text.

Admin body > header reserves 18px bottom padding before account navigation.
Keep project/status badges clear of logged-in user controls when the header wraps.

Service history uses measurement_revision independently of the existing revision.
Every service edit still increments revision to invalidate in-flight reads and
reset persistence safely. Only kind/target/scale/units/value_type/state code/label
changes (plus unit/function for Modbus) increment measurement_revision. Credentials,
alarm limits/direction, persistence, flap rules and state severities do not.
Samples record both IDs, including pause markers. history.ensure_tables migrates
startup/restore with default 1, without rewriting old samples. Old test history is
intentionally one measurement; no reconstruction of unknown past settings.
Before a measurement change, remember its non-secret definition in service_measurements
(FK cascade with service deletion). Current definition comes from the service row.
Range graph queries filter measurement before aggregation; graph UI offers previous
versions with their stored units/type/maps. Exact table includes every version.
Historical statuses/values remain recorded; current thresholds overlay only the
current version. Keep bounded queries, retention, stale-read guards and backups.

New project creation returns its ID after commit; the Admin form selects it without
activation. pendingCreatedProject holds that choice across stale in-flight refreshes
until the project appears; a manual project selection clears the pending choice.
Project assignments use collapsed-by-default native details/summary and retain their
open state through refreshes, without changing host monitoring/visibility flags.
Successful notify calls add a top-right, dismissible six-second save toast using
textContent and a polite live region, alongside the existing inline feedback.
Project name/status/logo saves explicitly notify after a confirmed write. Error
responses do not reset forms or produce success toasts. Paused monitoring button
text stays white; the separate Paused header badge remains yellow.

Keep the full Admin #project-configuration region inside one rounded border with
16px padding, matching the Live Hosts panel. Preserve the nested section borders.

Save confirmations stack newest-first in #save-toasts. Insert only the new item;
never rerender existing toasts (which would restart progress animations). Each has
its own timer/ID, close button and CSS countdown tied to SAVE_TOAST_DURATION.
Dismissal/expiry removes only that item and clears its timer; hide the container
when empty. Populate message spans via textContent. Cap the stack viewport height
and allow scrolling; use stepped countdowns under prefers-reduced-motion.

Toast stacks use a compact 320px width, shrinking to fit narrow viewports.
Unacknowledgement keeps inline issue feedback and list updates without a toast.

Confirmed configuration saves and operational changes show one success toast with
their inline feedback, including Settings, account creation/editing of other users,
provider settings, library imports and inventory-default library additions. Provider
tests/retries confirm queueing, never delivery. Acknowledgement/unacknowledgement,
display-only changes, previews/downloads and sign-in/out/password/restore redirects
retain their existing inline or navigation feedback without success toasts.
Show success only after the write response; rejected writes retain drafts and show
no success toast. A failed follow-up refresh reports that the action succeeded but
the displayed data may be stale; never report a failed write or replay it. Retire
new-deployment confirmations before refreshing so stale clicks cannot create an
extra deployment. Toast dismissal uses a fixed-size circular button in the top-right
corner with a centred SVG cross. Reserve space for it so wrapped messages do not
overlap it; shared control padding must not stretch the button.

Admin Resolved issues displays the latest 10, ordered by closed DESC/id DESC.
Keep snapshot's bounded 200-row list for compatibility. app/resolved.py supplies
an authenticated /api/resolved search across all eligible resolved issues in the
current active deployment, 10 per page with closed/id cursors, literal Unicode
casefold matching and no monitor LOCK. Scope by active_run, non-removed assignment
and enabled service. Retain display-name enrichment and legacy ping evidence text.
Install the partial resolved_issue_lookup index on startup/restore. Bound query work
to 3s and four concurrent searches. UI retains filter/page on refresh, debounces
input and rejects stale responses when query/deployment changes. Clear returns to
latest 10. No acknowledgement actions or new notifications are introduced.

Inventory Add from library supports an optional server-side name override for
its independent device_service_defaults copy. Keep missing-name compatibility
(library name), but reject explicit blank/non-text/overlong names and existing
per-device duplicates. Never change the template, credentials or existing projects.
The UI prefills the device name on template selection, preserves custom drafts on
polling/failed saves, and clears selection/name after confirmed success. Do not
clear another device/selection or a newer draft if the save finishes late.

Status Dashboard Live Hosts is sign-in-only for all three roles. /api/status
resolves the session first, sets can_view_hosts and calls status_overview with the
corresponding include_hosts flag (default false). Anonymous/expired/invalid and
forced-password-change sessions receive devices=[]; issue lists and branding remain
public. No query parameter may opt into live hosts. Client rendering requires both
viewer and can_view_hosts; hide the panel/toggle from first paint, guard controls,
clear host DOM/datalists/publicState.devices and hostViewFit.clear() on lost access.
Keep signed-in browser display preferences; anonymous actions must not change them.
Logout clears hosts immediately and increments statusSessionEpoch so a pre-logout
GET cannot restore them. Shared responsive helpers expose clear() on both pages
and clear their hidden measurement probe/cache without changing layout preferences.

Permanent inventory lists sort by the user-facing Device ID/name, case-insensitive
with natural numeric ordering (SW2 before SW10), before applying the display limit.
Apply the same order to search results; sort a filtered copy without mutating state.devices.

Permanent inventory Duplicate opens an Admin-only app-styled dialog with a captured
source ID, blank new Device ID/IP and editable prefilled model. /api/device-duplicate
requires Admin/CSRF, validates a fresh unique name/IP, allocates a durable device ID
and copies every SERVICE_CONFIGURATION_FIELDS value from all source defaults in
the same transaction. Return the new device ID only after commit. Copy no assignments,
project services, readings, issues or runtime state. Preserve rejected drafts and
prevent duplicate submits or Cancel/Escape while saving; distinguish refresh failure
from write failure. Copies and their defaults remain independent of the source.
require_unique_inventory_address runs inside mutate's LOCK/transaction for device
create/edit/address updates/duplication, excluding the edited row. Canonicalize
IPv4/IPv6, compare IPv4-mapped IPv6 equivalently, and return InventoryAddressConflict
as safe HTTP feedback identifying the existing Device ID. Do not expose arbitrary
ValueError messages or credentials. Existing legacy/restored inventory is not
rewritten, and benchmark seeds intentionally insert shared simulator IPs directly;
do not add a global unique index that breaks those datasets. Tests cover clone
ownership/configuration, rollback, concurrency, IP aliases, API roles/CSRF and UI.

Inventory transfer: app/inventory_transfer.py owns version-1 network-monitor-inventory
JSON (name/model/address/service_defaults per device; no database IDs or projects).
Admin-only /api/inventory-export includes raw default credentials and a host-local
filename timestamp. /api/inventory-preview and /api/inventory-import require Admin/CSRF.
Merge skips existing exact Device IDs; update adds new and updates matched model/IP
and the complete defaults set, retaining default IDs when names match. Never delete
absent inventory or modify assignments, project services/history, accounts or library.
Allow blank imported IPs as unconfigured; ordinary device creation/duplication still
requires an IP. Validate all definitions via the shared service validator, cap 10 MB,
5,000 devices and 10,000 defaults, and reject unknown IDs/fields and duplicate names.
Validate final canonical IP ownership before any writes, permitting atomic swaps;
untouched legacy duplicates are preserved. Bound conflict owner lists. Apply under
mutate's LOCK/transaction and roll back every change on failure. address_key is shared
with normal unique-IP validation, including IPv4-mapped IPv6 normalization.
Preview contains no communities and includes default removals. HMAC binds file/mode
and current inventory/defaults using a process-only random key. Revalidate on confirm;
changed inventory, edited files or restart require re-review. No pending DB jobs or
schema migrations. The in-app dialog captures file/mode/token, prevents double saves
and closing during writes, blocks IP conflicts, preserves rejected inputs and resets
only after success. Export/import does not include project logos or deployment data.


Authentication pages are separate: /login contains only the sign-in form;
/change-password contains only the current/new/confirm password form plus a readonly
username with autocomplete=username. GET /login redirects existing sessions to
/ (or allowlisted next=/status), except mandatory-change sessions go to
/change-password with the same return context. Anonymous/expired sessions on
/change-password go to /login; direct / redirects forced-change sessions to
/change-password. Voluntary self-service changes are linked in User Management;
all authenticated roles may use the change page/API. Keep API enforcement for
mandatory changes, current-password verification, CSRF and full session rotation.
Do not clear credential forms before navigation; password managers need their values.
Use explicit submit buttons and native form submission, no duplicate Enter handlers.
Test routing/security in test_access_notifications.py and isolated browser-script
flows in tests/login.test.mjs (also imported by dashboard.test.mjs). Real Chrome
with authorised iCloud Passwords is required to verify Enter/save interoperability;
separating forms does not establish the cause of either extension interaction.


Password-change layout uses a two-column grid: Username/Current password first,
New password/Confirm new password second, then Save password and Cancel in an
independent full-width actions row. Stack fields on very narrow screens. Cancel
returns to the originating dashboard for voluntary changes; keep it hidden for
mandatory changes, whose API restrictions remain enforced.
Chrome/iCloud diagnostics on 7 November 2026 reproduced Enter cancellation with
the extension's cachedIsCompletionListVisible=true. Its document keydown handler
calls preventDefault for Enter while suggestions are marked visible/requested.
Escape cleared both flags and native submission worked; refocusing also worked
in one test. Separating forms did not fix Enter or saving. Do not claim credential
saving is fixed or add a blind Enter handler that submits while choosing a saved
credential. Temporary browser diagnostics were removed by reload; no credentials
were saved or passwords changed. Coordinate explicit browser handover before UI
interaction; concurrent user input invalidates tests.


Follow-up to the Chrome/iCloud diagnostics: the user confirmed that refreshing/
restarting retained browser state resolved both autofill and Enter with iCloud
Passwords enabled. The exact reset step was not identified; do not claim a specific
cache mechanism or a reliable Escape workaround. No keyboard override was needed.
Keep separate login/change-password pages for their independently confirmed
routing benefit. v0.5.7 merges these flows and the paired-row password layout.


Login session reconciliation: retain server-side GET redirects, but also read
/api/me with credentials=same-origin and cache=no-store on login page load,
pageshow and visible visibilitychange. A navigation without its cookie can display
Sign in while a background request recognises the existing session (observed on
iPhone Chrome; exact browser cookie behaviour not confirmed). Route confirmed
sessions via location.replace to the allowlisted dashboard, or the separate mandatory
password-change page; never reinstate the hidden password form. A 401 stays on
Sign in. Bound reconciliation request/JSON to 8s; errors preserve drafts and leave
manual sign-in usable. Coalesce lifecycle checks, ignore checks overtaken by a
credential submission (loginRevision), and never start another restoration during
sign-in/navigation. No cookie-policy or expiry changes, token storage, session
renewal, keyboard handlers or DB migrations. tests/login.test.mjs covers startup,
resume, mandatory changes, unsafe return URLs, duplicate submits, stale reads and
network/HTTP/timeout recovery. Backend tests simulate a cookie-free page load then
a valid API request and verify the fixed 96-hour expiry is never extended.


/api/me includes session_expires_at (Unix timestamp, seconds since epoch) and
session_remaining_seconds (nonnegative whole seconds, rounded down at response
creation). auth.session_user selects the matching session's expires with an alias;
keep public_user's account allowlist unchanged so other/public responses do not
leak session timing. Include the fields for all authenticated roles, including
mandatory-change sessions; expired/anonymous requests still return 401. Reading
expiry never renews the cookie or updates the database. No schema change.


Status section controls group the acknowledged and host visibility toggles in
.status-visibility-controls. At viewport widths <=760px, stack those toggles in
that order and place .status-navigation below, left-aligned with no auto margin.
Keep this breakpoint independent of Show/Hide and Cards/List label widths to
prevent jumping rows. Desktop navigation remains on the right. Preserve IDs,
authenticated-only host access, toggle colours and localStorage preferences.


Stylesheets: app/static/css/base.css centralises shared theme variables and controls,
issue/host components, tables, navigation links and connection indicators. Load it
before dashboard.css/status.css/auth.css, which own only differing page layouts.
Keep readable four-space declarations/comments. Static body widths use .auth-page;
keep truly dynamic toast CSS variables, graph values and popup positioning in JS.
No Bootstrap/CDN/build pipeline is required. STYLESHEETS is a fixed server allowlist;
serve CSS publicly before auth, with text/css, no-store and nosniff. Never turn it
into arbitrary filesystem serving. Update versioned link queries when CSS changes.
Application scripts must remain unchanged by this refactor. Existing UI tests load
CSS explicitly for style assertions. Asset tests cover allowlisting, traversal,
MIME/cache headers and all page links. tools/style_preview.py and tests/style_matrix.html
compare the pre-refactor commit with the working tree using identical deterministic
CSS-only fixtures: eight viewport widths, roles, hosts/issues, panels/dialogs and
account pages. Computed-property/bounding-box equality supplements functional tests;
it does not test authorization or all real-world combinations. Never point the preview
at a live database; it binds loopback only. Coordinate handover for native browser
interaction; prefer the isolated in-app browser for previews.


Restore upload limit is MONITOR_MAX_RESTORE_MB (whole MiB, 1–1024; default 256),
passed through Compose/.env. Reject oversized restore Content-Length with HTTP 413
and an explicit configured-limit message before reading the body. Other payload
limits remain unchanged. Restores still use in-memory upload/SQLite validation;
large limits need spare RAM, so do not remove the bound. Preserve database format,
integrity checks, role/CSRF checks, migrations and paused/session-invalidating restore.
Admin restore confirmation displays server error text or an HTTP/proxy fallback,
not a misleading backup-format message for every failure. Build 103 is a distinct
restore fix after the presentation-only Build 102; its Admin error-handling JS
change is intentional and separately tested. Multiple installations on the same
hostname/IP share cookies across ports; compare using separate browser profiles or
normal/Incognito contexts, not simultaneous logins in one cookie context.


Build 104 replaces in-memory backup/restore with app/backups.py disk workspaces on
DB.parent (0700 directories), 1 MiB HTTP chunks and small SQLite caches/temp files.
GET /api/backup defaults complete; ?kind=configuration copies only allowlisted
configuration rows into fresh schema via read-only ATTACH, never reading history
rows. Retain users/credentials, devices/assignments/aliases, service settings,
defaults/library, provider config and logos. Exclude samples/runs/issues/audits/
measurements/outbox/flap/deletion jobs/sessions/login attempts. Keep durable ID
counters; configuration output has no active/paused deployment. Metadata uses
settings backup_format=network-monitor-1 and backup_kind. Legacy unmarked SQLite
backups are complete. Live DB never gets these metadata keys.
POST /api/restore-preview uploads and validates a private file without changing live
data, returning safe counts/kind/history flags and allowed modes. Session-CSRF-bound
opaque reviews expire after 15 minutes; max two staged files and one active transfer.
POST /api/restore-apply consumes a review once with mode complete/configuration;
configuration files cannot select complete. Cancel uses /api/restore-discard. Retain
the direct binary /api/restore API for compatibility. Validate/migrate private files,
check free disk, FK integrity and Admin authorization again before SQLite backup
replacement under LOCK. Both modes pause monitoring AND notifications, cancel pending
messages and invalidate sessions. Configuration-only replacement removes destination
history too: no merge. Typed failures leave live data intact before replacement;
never automatically retry apply. UI describes content and destructive scope in the
app-styled review dialog, captures the file/token/mode, blocks duplicate writes and
closing while applying, and signs out after success. Legacy account-less backups
retain destination accounts.
MONITOR_MAX_RESTORE_MB now defaults 20480 MiB (20 GiB), allowed 1–1048576; Compose
passes it through. Disk checks reserve upload/candidate/live-journal headroom. Existing
.env values override the new default. Creation/final apply can delay polling/config
writes while holding LOCK; release it before streaming downloads. Private files are
cleaned on success/error/cancel/expiry; crash leftovers older than 24h are swept on
startup. Both shared dashboard guards allow up to two hours for restore requests;
other deadlines remain unchanged and reverse proxies may need separate limits.


Both dashboard Sign out buttons open #signout-confirmation, an app-styled dialog
with explicit Sign out/Cancel and Cancel autofocus. configureSignOut is identical
on both pages: no requests on open/Cancel/Escape, ignore closed/stale confirmation
clicks, block duplicates and cancellation while busy, keep failures inline and
allow retry. Preserve role/temporary-password support and existing CSRF logout.
Admin returns to /login; Status clears private hosts/ack state immediately and
stays public. A post-logout public refresh failure does not make logout fail.
Automatic expiry/authentication redirects never require this manual confirmation.


Sign-out dialogs use the shared .signout-dialog class in base.css, independent of
.acknowledgement-dialog: 340px width, viewport cap, 20px padding, compact heading/
body/action spacing and matching backdrop. Empty feedback occupies no space;
Cancel autofocus and all sign-out behaviour stay unchanged. Keep both dashboards
on this same class; do not resize longer issue/review dialogs to fix sign-out.

Scoped monitoring roles (Build 108): app/access.py resolves active_run, falling back
only when paused to paused_run. Never use an Admin's local configuration selection as
scope. /api/state filters projects/runs/devices/assignments/services/readings/issues,
withholds library/defaults/settings outside the allowlist, and returns access_scope.
Viewer history is fixed to the current run; Operator history/deployment selection
is confined to its project. Bounded history batches each revalidate scope in their
own read transaction; non-Admin project-logo access follows the global project.
Operator writes require expected_scope_run and are checked inside LOCK/transaction.
Global switches invalidate open restricted history/resume dialogs. No deployment
means no scoped data/controls. Managed ping, configuration, host assignment flags,
new/delete deployments, accounts, exports and backups remain Admin-only.

Build 110 extends app/live_updates.py publish_dashboard_change to deployment
activation/resume/deletion, monitoring pause/resume, notification pause/resume,
individual service pause/resume and assignment monitoring/visibility/notification
flags. Publish only after the mutation transaction commits; no-op controls, rejected
requests and rollbacks emit nothing. Keep /api/ack-events and browser handler names
compatible: the stream is now a general dashboard invalidation, still only an opaque
revision. Reuse the existing coalescing, reconnect/focus and 10-second polling fallback.
Do not change metric polling, role scope or Admin local configuration selection.

Build 117 also signals committed polling-driven issue open/close/severity and
flap transitions through live_updates.publish_monitoring_change. Signal only after
the write transaction/monitor lock exits; blocked, unconfirmed, invalidated and
rolled-back reads do not emit issue-change events. Keep existing persistence,
polling cadence, evidence, acknowledgements and provider notification rules.
Existing SSE waiters coalesce monitoring bursts for at most one second, without
timers or new worker threads; capture their pending deadline so sustained changes
cannot postpone delivery. Interactive publish_dashboard_change clears the delay,
and cancellation wakes immediately. Keep ordinary readings quiet and ten-second
polling as fallback; global provider mute never gates dashboard synchronization.

v0.6.3 Build 118 merges the dashboard capacity, duplicate-tab and polling-driven
issue synchronization work into canonical main. The user accepts an occasional
one-second acknowledgement/operational refresh delay when a monitoring event
follows an immediate event before a listener wakes. Preserve that accepted timing
unless asked to change it; committed actions and monitoring data are unaffected.
