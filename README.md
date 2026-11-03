# Network Monitor v0.2.2 · Build 13

Local-first equipment monitoring for a single server and roughly 100–150 devices.
This is a runnable development foundation, not the completed production system.

## Build history

### Build 13 — v0.2.2

- Added confirmed deletion of an inactive selected deployment and its stored history, issues, acknowledgements and notification records.
- Preserve project/device/service configuration and other deployments; prevent deleted deployment and internal issue IDs from being reused.


### Build 12 — v0.2.2

- Added project-scoped previous-deployment selection with start times and descriptions.
- Added confirmed resumption of existing deployments, preserving history and issue numbering while requiring fresh checks and pausing notifications.


### Build 11 — v0.2.2

- Merged reusable service library transfer and updated dashboard branding into main.


### Build 10 — v0.2.1

- Added Admin-only reusable service library export/import as portable versioned JSON.
- Added reviewed Merge and Replace imports with full validation and atomic database updates.
- Updated the Admin dashboard subtitle to Project based network monitoring.


### Build 9 — v0.2.1

- Merged inventory service defaults, configuration navigation, notification controls and status attention improvements into main.


### Build 8 — v0.2

- New projects can reuse an already-uploaded project logo, with an optional selection and preview.
- Logos are copied independently so replacing/removing the original does not affect the new project.


### Build 7 — v0.2

- Moved status-page Admin Dashboard / Sign in navigation to the right of the issue and host visibility controls.
- Kept the login-status badge in the header.


### Build 6 — v0.2

- New deployments start with global notifications paused, requiring an explicit Resume notifications action.
- Added this behavior to the deployment confirmation dialog; ordinary monitoring Resume preserves the notification setting.


### Build 5 — v0.2

- Added a global Pause/Resume notifications toggle beside Pause/Resume monitoring.
- Continue polling and displaying issues while Telegram and WhatsApp notifications are muted.
- Discard pending/muted alerts and restart reminder timing on resume to avoid backlog replay.


### Build 4 — v0.2

- Clicking the selected configuration tab closes its area, allowing all configuration areas to be hidden.


### Build 3 — v0.2

- Added permanent per-device service defaults that seed independent services for new project assignments.
- Added defaults editing, library import and explicit adoption from an existing project configuration.
- Changed Admin configuration controls into exclusive tabs that preserve unfinished forms.
- Added three red status-page background pulses for newly appearing active issues, with a reduced-motion alternative.


### Build 2 — v0.2

- Merged the status dashboard UI, acknowledgement, reminder and deployment-record improvements into main.

### Build 1

- Added a small build number beside the version on both dashboards.
- Build numbering starts here. Every subsequent update commit increments the build
  on both dashboards, including updates within the same version. Build numbers
  continue increasing across version releases.

## Release notes

### v0.2.2

- Added Admin-only reusable service library JSON export/import for transferring definitions between installations.
- Added reviewed Merge imports that keep existing matching names, and Replace imports that affect only the library.
- Validate complete files before applying atomic changes; project services, inventory defaults and monitoring history are preserved.
- Include stored SNMP communities in portable exports, with credential-handling guidance and host-local timestamp filenames.
- Updated the Admin dashboard subtitle to Project based network monitoring.


### v0.2.1

- Added per-device service defaults for new project assignments, with independent event configurations, library import and explicit adoption from existing projects.
- Changed Admin configuration controls into exclusive tabs; click the selected tab to close it.
- Added three red status-page background pulses when a new active issue appears, respecting reduced-motion preferences.
- Added an independent global Pause/Resume notifications control while monitoring and dashboard issues continue.
- New deployments start with notifications paused until an Admin explicitly resumes delivery.
- Moved status-page Admin Dashboard / Sign in navigation onto the right of the issue/host visibility row.
- Added reusable uploaded logos and previews when creating projects.


### v0.2

- Matched the status dashboard's bordered Live Hosts panel and card spacing to the Admin dashboard; added Live Hosts headings to both.
- Added consistent issue separator rows and displayed issue numbers on both dashboards.
- Added styled in-app acknowledgement confirmation dialogs with Cancel and inline errors.
- Added configurable reminders for active, unacknowledged issues through enabled Telegram/WhatsApp channels, respecting paused and suppressed checks.
- Added notification icons for recovery, critical/unreachable and warning states.
- Numbered issues from #1 within each deployment while preserving internal IDs and existing history.
- Required a description when starting a deployment and displayed its start time and description on the Admin dashboard.
- Added dashboard build labels and documented build increments for future update commits.

### v0.1.3

- Return users to the dashboard where sign-in started, including after required password changes.
- Restrict login return destinations to the local Status and Admin dashboards.
- Added Admin-configurable session duration under User management → Login sessions (1–168 hours, default 12).
- Apply session-duration changes to new sign-ins, keeping existing session expiry unchanged.

### v0.1.2

- Enclosed live hosts and their display controls in a bordered panel, with spacing above cards.
- Moved Edit alias beside the host heading in Cards and List views.
- Aligned service Pause/Resume and Actions controls in List view.
- Grouped Status Dashboard, Change password and Sign out on the right, keeping the user badge on the left.
- Renamed the status page navigation button to Admin Dashboard.

### v0.1.1

- Added a Continue/Cancel confirmation before starting a new deployment.
- Explained that a new deployment starts a fresh current view while previous history remains stored, subject to retention.
- Kept Resume all monitoring separate from starting a new deployment.

### v0.1

- Initial tagged baseline: SNMP/Modbus monitoring, reusable project inventory and services,
  thresholds, issue acknowledgement, dashboards, user roles, notifications and SQLite backup/restore.

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
The main dashboard requires login. The `/status` overview is intentionally accessible without credentials and remains
read-only for anonymous visitors. Use an HTTPS reverse proxy before sending passwords
across untrusted networks; set `MONITOR_SECURE_COOKIE=true` when using HTTPS.

The `monitor-data` named volume holds the SQLite database, including configuration,
metrics, issues, and SNMP communities. Container replacement preserves it.
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

## Login and roles

The initial username is **admin**. On first startup (including upgrades without
accounts), a random temporary password is written to the persistent volume:

```sh
docker compose exec monitor cat /data/initial-admin-password.txt
```

Alternatively, set `MONITOR_ADMIN_PASSWORD` in `.env` before the first startup.
This variable never resets an existing account. Sign in at `/login` and change the
temporary password before configuring the system. Passwords require 10–256
characters. Admins can add, edit, reset or remove users in **User management**.
Accounts have an optional email field for a future reset flow; no email is sent yet.
The **Require password change on next login** checkbox is selected by default for
new users. Leave it selected for a temporary password, or clear it to let the user
keep the assigned password. Editing a user loads their current setting, which can
also be changed without replacing their password. Blank edited passwords keep
the existing password. Existing accounts migrate with a blank email while keeping
their current password and password-change setting. The last Admin cannot be demoted, and self-deletion is blocked.

**Admins** configure equipment, acknowledge issues, manage users, notifications,
backups and restore. **Operators** can inspect status/history and acknowledge
issues but cannot edit projects, equipment, services or any other configuration.
**View Only** users can inspect monitoring data and history but
cannot mutate configuration or acknowledge issues. All three roles can change their own
password. User edits, password resets and deletion revoke that user's sessions.
Sessions default to 12 hours (Admin configurable), use HttpOnly/SameSite cookies, and mutations require CSRF
protection. Sign-in attempts are rate-limited by client address and username.

The public `/status` dashboard shows active issues above the active project's visible hosts and
current service values. Issues for hidden, paused or inactive equipment are
excluded, as are acknowledged, resolved and dependency-suppressed issues. It excludes IP addresses, credentials, OIDs, inventory of
other projects, history, user accounts, and configuration. It is available locally
without login; this does not create the future public-facing relay.

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
5. Read current metrics, recent readings, and issues in the dashboard.

Numeric thresholds may be above or below a value. Critical is evaluated first;
a configurable number of consecutive identical statuses open or recover an issue
(default two). Acknowledgement
records a timestamp without clearing the issue and moves it into the acknowledged
list. It stays there after recovery. Unacknowledged recoveries appear in the resolved
list. All three lists are scoped to the active deployment. The three assignment controls
are independent; notification flags enable or mute outbound messages per host.

## Implemented

- Permanent inventory with full ID/name, model and IP editing; confirmed permanent
  deletion removes the device and its assignments, services, readings, issues,
  and legacy address records across all projects. Shared projects/runs survive.
- Shared device IP; saved project assignments with
  per-project aliases. Inventory IP edits apply to all projects.
- One active project, separate deployment runs, retained historical records.
- Independent monitoring and visibility controls.
- Bounded concurrent polling (24 workers), 15-second cycle delay.
- Host-first dependency checks: child services are suppressed while the host ping
  is failed, stale or missing. Existing child issues stay recorded in a suppressed
  list, without being falsely recovered. Fresh service reads resume after host recovery.
- Numeric metrics with units/thresholds or numeric state codes with per-value labels
  and healthy/warning/critical severity. Unmapped state codes produce warnings.
- Monitor card headings use `Device ID - Alias`.
- Automatic ICMP host ping (including existing/restored assignments); numeric
  SNMP v2c GET; TCP port reachability; basic Modbus TCP function 03.
- Inline success confirmations and cleared add forms; failed submissions preserve
  input and background refreshes preserve unfinished selections.
- Copy services to hosts in any saved project, with optional name/community overrides.
- Reusable service library: create definitions directly, save existing services,
  edit/delete entries, and apply them to hosts. Copies are independent, with fresh
  history and issues; template edits/deletion do not modify existing services.
  Templates retain credentials and are included in database backups. Credentials
  are hidden from the UI; blank overrides reuse the source credential.
- In-place service editing from host cards or the configuration catalogue, including
  protocol, OID/register/port, thresholds, scaling, units, Modbus unit ID, persistence,
  and optional credential replacement. Blank edited credentials stay unchanged.
- Warning/critical thresholds, configurable persistence, issue recovery and local
  acknowledgement; unknown/stale status after 60 seconds without a reading.
- Recent metric table (latest 200 readings per service/run), retention in days.
- Consistent SQLite backup and validated restore with polling paused afterwards.
- Local web UI, Compose health check, non-root container, persistent volume.

## Backup and restore

Use the UI's download link to produce a consistent full database snapshot while
monitoring continues. The file includes credentials in plaintext: protect it as a
secret. Copy backups off the monitoring server. Restore accepts this application's
SQLite backup, checks database integrity/table presence, replaces the database,
and sets monitoring to paused. Users and notification settings are included; active
sessions are excluded from downloads and invalidated on restore. Queued messages
are cancelled on restore to prevent replay. Older backups without accounts retain
the current account list. Download a backup before replacing current state.
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

- No public relay or chat-based remote acknowledgement yet. Outbound Telegram and WhatsApp
  Business notifications are supported directly from the local server.
- Built-in TLS and credential encryption remain pending.
  Account passwords are hashed; network/provider credentials in backups remain plaintext.
- No verified manufacturer profiles: do not invent OIDs or Mean Well registers.
- SNMP v2c only. Raw counters are not throughput; counter-rate calculation, counter
  rollover handling, SNMPv3 and vendor profiles are required next.
- Modbus TCP port 502 with configurable unit ID, unsigned 16-bit holding registers with scale.
  RTU/gateways, signed/multi-register values, bitfields and
  manufacturer fault decoding are pending confirmation of the actual DRS interface.
- Host cards show ICMP online/offline/unknown independently of additional services.
  Paired-radio views and a combined host/service health rollup remain pending.
  Networks that block ICMP will show hosts as offline and suppress their child services.
- Inventory creation/editing/deletion and service creation/editing/removal are present; multi-service device profiles, project cloning, and project readiness
  checks remain to be added.
- History graphs cover the latest 200 readings in the active deployment. A full
  historical run selector and longer-range graph queries remain to be added.
- No hysteresis, upstream network dependencies, maintenance windows, configurable polling intervals,
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

Editing a service keeps earlier samples for history, discards any in-flight reads
using the old configuration, and awaits fresh readings before showing current
values. Alert persistence restarts for the new configuration. Existing issues
remain recorded and are reconciled by subsequent confirmed readings.

Service library entries are user-defined. No unverified manufacturer OIDs or
registers are preloaded. Older backups get an empty library on restore. Applying
a library service requires a device already assigned to the target project.

## State services and host dependencies

Choose **Numeric metric** for scaled readings such as percent, voltage, RSSI or
degrees; set units and numeric thresholds. Choose **Numeric state codes** for
values such as switch port status, then enter one mapping per line:

```text
1 | Up | healthy
2 | Down | critical
3 | Testing | warning
```

The dashboard and history show the assigned label. Raw numeric readings remain in
the database. State codes bypass scaling and numeric thresholds; unmapped codes
warn. Mappings travel with copied services, library entries and backups.
SNMP enum values are requested numerically using Net-SNMP's
[output options](https://www.net-snmp.org/docs/man/snmpcmd.html).

Each host is pinged before its child checks. A failed/missing ping or a ping older
than 60 seconds blocks child polling and records a suppressed sample instead of a
service-down event. Confirmed host failures still create host issues. Existing
child issues move to the suppressed list and keep their original history and
acknowledgements. After host recovery, service persistence starts again from fresh
readings; recovery is recorded only after confirmed healthy readings.

To rename a project alias, select the project, expand **Inventory and project
configuration**, and use **Edit alias** in **Project assignments**, or click
**Edit alias** directly on its monitor card. This changes
only that assignment; inventory IDs and aliases in other projects are preserved.

Service cards keep actions in a compact **Actions** menu. Use **History / graph**
to switch between an SVG graph and exact readings. Numeric metrics use lines;
state codes use labeled steps. Missing/suppressed readings and gaps over 60 seconds
break the line. Graphs use the current configuration revision; the table preserves
older configurations. Graphs are local and do not depend on a CDN or chart service.

Optional dashboard logic tests (Node.js 18+): `node tests/dashboard.test.mjs`.
These use a minimal DOM stub; a full browser layout check remains separate.

## Telegram notifications

1. Create a bot using [BotFather](https://core.telegram.org/bots/features#botfather).
2. Add the bot to your Telegram group and allow it to send messages.
3. In **Telegram notifications**, save the token while notifications are disabled.
4. Send a command addressed to the bot in the group, then use **Discover groups**
   and select your group, or enter its numeric chat ID directly.
5. Optionally enter a topic ID, enable notifications, save and send a test message.

The monitor uses outbound HTTPS to Telegram's
[sendMessage API](https://core.telegram.org/bots/api#sendmessage). No inbound port
forwarding is required. Discovery inspects recent bot updates without retaining
message text. Use a dedicated bot so other consumers do not consume those updates.

## WhatsApp Business notifications

This optional provider uses Meta's [Cloud API](https://developers.facebook.com/documentation/business-messaging/whatsapp/messages/template-messages),
not WhatsApp Web. Configure the sender phone-number ID, access token, Graph API
version from your Meta app, approved template name and language, and recipient.
Individual recipients use an international phone number without `+`. Group mode
requires a Business API group and appropriate Meta eligibility; it cannot target
an ordinary app-created WhatsApp group. Use Telegram for that shared-team workflow.

Create an approved template with **three positional body text parameters**:
`{{1}}` device, `{{2}}` status/project, `{{3}}` service reading and issue details.
Enable the provider, save and send a test. Provider approval, sender provisioning,
API permissions, billing and group eligibility are managed in Meta, outside this app.

## Delivery behaviour

New confirmed issues and optional recoveries are queued independently for each
enabled provider. Per-host notification flags and host dependencies are respected.
Enabling a provider does not replay old issues. Each event is queued once per
provider; reminders and remote acknowledgement are not implemented yet.

Queues survive restarts. Transient failures retry with backoff, up to five attempts;
permanent errors stop immediately. Admins see pending/sent/failed/cancelled states
and can retry failed messages for the current configuration. Changing provider
settings cancels pending messages so they cannot move to a different destination.
Restoring a backup cancels unsent messages and pauses polling.

“Sent” means accepted by the provider, not a verified read/delivery receipt. A
network timeout after provider acceptance can cause a duplicate on retry. No real
provider delivery has been verified without credentials. Tokens are hidden in the
UI and logs, but remain in admin backups; protect those backups.

Admins can select **Operator** when adding or editing a user. Operators can view
monitoring/history and acknowledge issues, but all configuration remains
Admin-only. **Healthy**, **Warning**, and **Critical** use capitalised labels.
Host cards use amber/red backgrounds for confirmed Warning/Critical issues;
the highest open severity wins. Acknowledgement does not remove the colour until
the fault recovers. Suppressed child faults do not add a second fault indication.

The public status overview has a **Hide host cards / Show host cards** button.
Hide cards for an issue-only view. The choice is stored in that browser and
is preserved during live updates and page reloads.

Both dashboards offer **Cards** and **List** views. **Service filter** matches part
of a service name, ignoring case: `RSSI` displays readings such as Local RSSI and
Remote RSSI and hides hosts without a matching enabled service. **All services**
clears the filter. Issue lists remain complete and host severity colours still
reflect all confirmed faults. View and filter preferences are saved separately
for each dashboard in browser storage and survive live updates/page reloads. The
public show/hide control hides either layout for an issue-only display.

Both dashboards place **Active issues** above hosts. List rows have rounded
card-style borders and spacing with the same severity colours as cards. Navigation
and download links use consistent button styling across the app.

Under **Inventory and project configuration → Edit selected project**, Admins can
rename the selected project and upload, replace, or remove its event logo. Logos
accept PNG/JPEG up to 2 MB and 4096 pixels per side. The selected project logo is
shown on the main dashboard; the active project logo is shown on public status.
Images are stored inside the database and included in backup/restore. Project
renaming preserves assignments and history. The main dashboard keeps all issue
sections—active, acknowledged, suppressed and resolved—above the host display.

Admins can **Pause / Resume** a service directly on its host or in the filtered
service manager. This stops polling and suppresses its issues/messages while
keeping configuration and history. Resuming waits for fresh readings and restarts
threshold persistence. Built-in host ping is controlled through host monitoring.

**Project assignments → Remove from project** stops monitoring and hides that
assignment. Inventory, other projects and historical data remain. Assigning the
same inventory device back to the project restores its previous configuration.

The configured-service manager shows nothing until a host (or **All hosts**) is
selected. Filter by service name/OID, protocol, and enabled/paused monitoring.
Results start at 20; **Show 20 more** expands the list intentionally.

Both dashboards have **Hide services / Show services** for a host-only Cards or
List display. Host details, issue badges/colours, and issue lists remain.
This is a display preference, not a monitoring pause. It is saved per dashboard
in browser storage and restored after refresh.

**Edit selected project → Duplicate selected project** creates a new inactive
project with a unique name. It copies the logo, current device assignments and
aliases, services, monitoring/visibility/notification flags and status settings.
Inventory records remain shared. History, issues and deployment runs stay with
the original project; review the copy before activating it. Removed assignments
and removed services are excluded.

Public status **Sort hosts** offers hostname A–Z/Z–A, alias, host status in either
priority order, and issue severity. The selection is saved in browser storage
and applies to both Cards and List views.

Admins can enable **Allow status-page acknowledgement** under **Edit selected
project**. It defaults off per project. When enabled, signed-in Admins and Operators
see Acknowledge buttons on active public-status issues. Anonymous visitors and
View Only users stay read-only. Disabling the setting removes that ability from
the status page; normal authorised acknowledgement on the main dashboard remains.

Project settings are grouped into Name, Event logo, Status dashboard and Duplicate
project panels. Permanent inventory has a collapsible device list and search by
device ID/name, model, or IP. Searches expand the list, showing 50 results initially
with a Show more button for larger inventories.

The status dashboard shows whether the current browser is signed in and displays
that user's name/role. Its navigation changes to Sign in, Dashboard, or Change
password as appropriate. Anonymous responses include recorded acknowledging names but no other account details.

Acknowledgements retain the authenticated account ID and username at the time of
acknowledgement, including after account rename/deletion. Legacy records display
Unknown user (legacy). The main dashboard has independent Show/Hide controls for
acknowledged, suppressed, resolved and live host/service sections, saved in browser
localStorage. Hiding sections does not pause monitoring or hide active issues.

The public status dashboard also has a separate acknowledged-issues section
with a colour-coded Show/Hide button, saved in browser storage. It shows
acknowledgement/recovery times and the recorded acknowledging full name (or username fallback). Legacy
records display Unknown user (legacy); account IDs and other details stay private.

Accounts have an editable Full Name (up to 150 characters) separate from the login
username. Signed-in labels and acknowledgement attribution prefer the full name,
falling back to username for existing accounts. Acknowledgements snapshot the full
name at acknowledgement time; later profile edits do not rewrite history. Both
startup and restore migrate account/audit fields. Public issue attribution includes
this display name. The main navigation link is labelled Status Dashboard.

User editing opens a separate dialog with Save changes and Cancel. The inline
user form is dedicated to adding accounts and is not overwritten by editing.

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

The product name is Network Monitor. Retain legacy field-monitor localStorage keys
to preserve browser preferences. Complete backup downloads use a server-generated
network-monitor-backup-YYYY-MM-DD_HH-MM-SS.sqlite3 filename via Content-Disposition,
using the monitoring host local timezone. Compose mounts /etc/localtime read-only
from the host so container time follows the host, including daylight saving.

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

## Device service defaults

In **Permanent inventory**, open the device list and choose **Service defaults**
for a device. Add/edit/remove definitions, add one from the reusable library, or
choose an existing project configuration and **Replace defaults from project**.
This explicit adoption copies credentials on the server and leaves the project
untouched. Existing projects are not chosen automatically during upgrade.

Assigning that device to a new project copies its defaults into independent
project services, alongside automatic host ping. Subsequent edits in either place
do not affect the other. Re-adding a removed assignment restores its old setup;
duplicating a project copies that project's configuration. Copies start with
monitoring enabled. Inventory defaults are included in complete backups.

Admin configuration areas now act as tabs: only one is visible at a time, and
switching tabs preserves unfinished forms. They start closed after a page reload.
The public status dashboard pulses its background red three times when a new
active issue appears after the initial load. Existing or reappearing issues do not
retrigger it; reduced-motion browsers receive a brief static red highlight.

## Temporarily pause notifications

Admins can use **Pause notifications** beside the monitoring toggle. It turns
amber and becomes **Resume notifications** while muted. Device checks, issue
creation/recovery, history and dashboard updates continue normally. The mute
survives restart and applies to both providers, including test sends and retries.

Pending alerts are cancelled and events during the pause are not queued. On
resume, fresh events can send normally, and enabled reminders wait one full
configured interval before repeating eligible active issues. Existing provider
settings and per-host notification flags are preserved. A send already in flight
when Pause is clicked can still complete.

Every new deployment starts with notifications paused, even if delivery was enabled
for the previous deployment. Check the setup, then click **Resume notifications**
when ready. Pause/Resume monitoring within an existing deployment does not change
its notification setting.

## Transfer the reusable service library

Open **Reusable service library → Export library** to download a JSON file. On
another installation, choose that file, select an import mode, click **Review
import**, then confirm **Import library**:

- **Merge** adds new names and keeps existing services with exactly matching,
  case-sensitive names. It does not overwrite existing definitions.
- **Replace** replaces the reusable library only. Project services, inventory
  device defaults, issues and history remain unchanged.

All definitions are validated before the database is changed. Invalid files are
rejected as a whole; there are no partial imports. Duplicate service names in one
file are rejected. Files are limited to 5 MB and 5000 services. An empty Replace
file intentionally clears the reusable library after confirmation.

Exports include service definitions, units/thresholds/state mappings and stored
SNMP communities, so protect the files as credentials. They contain no project
assignments, readings, user accounts or database IDs. This is a library transfer,
not a complete database backup. The filename uses the monitoring host's local
date and time; the JSON format has its own version for compatibility checks.

## Resume a previous deployment

Select the project on the Admin dashboard, choose a run under **Previous
deployments**, then click **Resume selected deployment**. The list shows each
run's number, original start date/time and description. Review the confirmation
and click **Resume deployment** to continue that run rather than create a new one.

Any currently active deployment stops monitoring. All retained readings, issues,
acknowledgements and issue numbering stay associated with their original runs;
the resumed deployment continues its existing issue sequence. It uses the
project's **current** inventory assignments and service definitions, rather than
restoring a historical configuration. Expired readings cannot be recovered.
Fresh checks are required, and notifications start paused until explicitly resumed.

The normal Pause/Resume monitoring button still resumes the most recently paused
run without changing its notification setting. The new selector can instead
resume any existing run belonging to the selected project. Only Admins can do so.

## Delete a deployment

Choose a run under **Previous deployments**, then **Delete selected deployment**.
The in-app confirmation identifies the run and explains what will be removed.
An active deployment must be paused first. Only Admins can delete deployments.

Deletion permanently removes that run, its metric readings, issues (including
acknowledgements), and related notification records from SQLite. The project,
inventory, service definitions, library and other deployments are preserved.
Deleting the most recently paused deployment clears the quick-resume target.
A complete backup is required to recover deleted history. Deployment IDs and
internal issue IDs are never reused after deletion.
