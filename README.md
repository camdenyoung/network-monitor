# Network Monitor v0.6.6 · Build 128

Local-first equipment monitoring for a single server and roughly 100–150 devices.
This is a runnable development foundation, not the completed production system.

See [CHANGELOG.md](CHANGELOG.md) for build history and release notes.

User management shows an Online badge for accounts with dashboard activity in the
last 60 seconds. This is an approximate presence indicator; closing a browser or
losing connectivity can leave it visible until the window expires.

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
backups and restore. **Operators** follow the globally active or paused project.
They can inspect its history, acknowledge/unacknowledge issues, select/resume its
existing deployments, pause/resume all monitoring and notifications, and pause/resume
individual additional services. They cannot switch projects, create/delete deployments
or edit configuration. **View Only** users follow the globally selected project AND
deployment, including history; they cannot select another deployment, change
monitoring/notifications or acknowledge issues. If no deployment is selected,
restricted accounts see no project data. An Admin's local project dropdown does
not change this global scope. All three roles can change their own
password. User edits, password resets and deletion revoke that user's sessions.
Sessions default to 12 hours (Admin configurable), use HttpOnly/SameSite cookies, and mutations require CSRF
protection. Sign-in attempts are rate-limited by client address and username.

The `/status` dashboard is available locally without login for event branding,
active issues and the optional acknowledged-issue list. Anonymous visitors cannot
access Live Hosts, its display controls or live host/service readings; the API
returns no live devices for them. Public issue details still identify affected
hosts/services and their recorded opening values.

Live Hosts and its Show/Hide control require a signed-in Admin, Operator or View
Only user who has completed any required password change. Existing host display
preferences are preserved for signed-in users. Logout/session expiry clears host
cards, readings and cached layout markup. The Status Dashboard still excludes IP
addresses, credentials, OIDs, other projects' inventory, history, account lists and
configuration. This does not create the future public-facing relay.

## Dashboard updates and connection limits

Admins can set **Settings → Dashboard connections → Maximum live connections**
from 1–200 (default 20). The navigation badge shows current live connections and
the configured maximum. Logged-in users is a separate count of distinct accounts
active within the last 60 seconds.

Connected dashboards receive confirmed issue changes promptly, with up to one
second of update batching. Ordinary readings refresh every ten seconds. Tabs that
cannot establish a live connection also use ten-second polling; this does not
pause device monitoring or prevent authorized actions.

Reducing the limit leaves existing connections open until they close, so the
count can temporarily exceed the new maximum. The setting applies without restart
and is included in backups.

For direct HTTP/1 access, keep four or fewer dashboard tabs open per browser to
leave connections available for readings and actions. The global server limit
applies across browsers and machines. Browser-to-proxy HTTP/2 avoids this particular
HTTP/1 restriction; see the [browser connection-limit documentation](https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events/Using_server-sent_events#listening_for_custom_events).

## Initial workflow

1. Expand inventory/configuration and create a project.
2. Add permanent equipment with its IP address, then assign it to the selected
   project with its project-specific alias. The IP belongs to inventory and is
   shared by every project; change it using the inventory Edit button. A device
   may appear in multiple saved projects.
3. Host ping is configured automatically on assignment. Add any additional services
   using verified OIDs or register addresses.
4. Activate the project. Activation creates a new deployment run with monitoring and notifications paused.
   Choose Resume all monitoring to begin checks and Resume notifications when ready. Pausing stops collection without deleting configuration.
5. Read current metrics, recent readings, and issues in the dashboard.

Numeric thresholds may be above or below a value. Critical is evaluated first;
a configurable number of consecutive identical statuses open or recover an issue
(default two). Acknowledgement
records a timestamp without clearing the issue and moves it into the acknowledged
list while the fault is open. All recovered issues appear in the resolved
list. All three lists are scoped to the active deployment. The three assignment controls
are independent; notification flags enable or mute outbound messages per host.

The Admin **Resolved issues** section shows the ten most recently recovered
issues by default. Search by issue number, device ID/IP, alias, service, status or
recorded value to find matches across all resolved issues in the current deployment.
Results use ten-item pages with Older matches/Newest matches controls. Clear search
to return to the latest ten; search text and the current page survive live refreshes.

## Implemented

- Permanent inventory with full ID/name, model and IP editing; confirmed permanent
  deletion removes the device and its assignments, services, readings, issues,
  and legacy address records across all projects. Shared projects/runs survive.
- Shared device IP; saved project assignments with
  per-project aliases. Inventory IP edits apply to all projects.
- One active project, separate deployment runs, retained historical records,
  project duplication and confirmed project deletion.
- Independent monitoring and visibility controls.
- Bounded concurrent polling (24 workers), 15-second cycle delay.
- Host-first dependency checks: child services are suppressed while the host ping
  is failed, stale or missing. Existing child issues stay recorded in a suppressed
  list, without being falsely recovered. Fresh service reads resume after host recovery.
- Numeric metrics with units/thresholds or numeric state codes with per-value labels
  and healthy/warning/critical severity. Unmapped state codes produce warnings.
- Monitor card headings use `Device ID - Alias`.
- Automatic ICMP host ping (including existing/restored assignments); numeric
  SNMP v2c GET; TCP port reachability; Modbus TCP Holding (03) and Input (04) register reads.
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
- Warning/critical thresholds, configurable persistence, recovery hysteresis and
  flap protection. Issue recovery, acknowledgement/unacknowledgement and configurable
  reminders; unknown/stale status after 60 seconds without a reading.
- Service history with time presets/custom dates, deployment selection, bounded graphs and exact-reading table pages; retention in days.
- Consistent SQLite backup and validated restore with polling paused afterwards.
- Local web UI, Compose health check, non-root container, persistent volume.

## Backup and restore

The Admin **Backup and restore** panel offers two downloads:

- **Complete backup:** configuration, accounts, credentials, inventory, service
  definitions/defaults/library, projects, logos, deployments, readings, issues,
  acknowledgements and delivery history.
- **Configuration only:** the same configuration and accounts, without deployments,
  readings, issues/acknowledgements, delivery logs or monitoring runtime state.

Both are SQLite files containing secrets; protect them and copy them off the server.
Sessions and login attempts are excluded. Configuration copies do not scan/copy
history rows, so they stay small even when retained history is large.

To restore, choose a file and click **Upload and review backup**. The file is streamed
to a private workspace on the data volume, validated and summarised before any live
changes. Complete backups offer **Everything, including history** or **Configuration
only**; configuration backups allow only the latter. Reviews expire after 15 minutes.
Cancel discards the staged file. Review and restore require the same Admin session.

Restore **replaces**, rather than merges, destination configuration/accounts/data.
Configuration-only restore removes destination history and imports none from the
file. All restores pause monitoring and notifications, cancel pending messages and
invalidate sessions; sign in with the backed-up accounts afterwards. Unmarked older
SQLite backups are accepted; account-less legacy backups retain current accounts.
Keep a destination backup before replacing it. Durable ID counters remain preserved.

Transfers use disk files and 1 MiB HTTP chunks instead of loading the whole database
into Python memory. One transfer runs at a time, with up to two files awaiting review.
Download streaming releases the monitoring lock after snapshot creation. Snapshot
creation and final database replacement may temporarily delay polling/configuration
writes. Temporary files are removed on completion, cancellation, failure and review
expiry; abandoned files older than 24 hours are cleaned on startup.

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

- No public relay or notification-link remote acknowledgement yet. Telegram and
  WhatsApp Business notifications are sent directly from the local server;
  acknowledgements are available on the local dashboards for authorised users.
- Built-in TLS and credential encryption remain pending. Account passwords are
  hashed; network/provider credentials in the database and backups remain plaintext.
- No built-in verified manufacturer profiles. Configure OIDs/registers against the
  relevant equipment documentation; reusable services and inventory defaults are supported.
- SNMP v2c only. Counter-rate calculation, rollover handling and SNMPv3 remain
  unimplemented; raw counter readings are not throughput rates.
- Modbus supports TCP port 502, configurable unit ID, unsigned single 16-bit
  Holding (03)/Input (04) registers and scaling. TCP-to-RTU converting gateways
  can provide access to RTU devices. Direct serial RTU, raw RTU-over-TCP transports,
  signed/multi-register values, bitfield extraction and built-in manufacturer fault
  decoding are not implemented.
- Host online/offline status uses ICMP. Service issues appear separately and tint
  host cards by severity. Paired-radio/topology views, upstream network dependencies
  and alternatives to ICMP host checks remain unimplemented. Blocking ICMP causes
  the host to appear offline and suppresses its child services.
- Inventory CRUD, per-device service defaults, project duplication and project
  deletion are implemented. Named multi-service device profiles and project
  readiness checks remain unimplemented.
- History supports up to 31 days per request. Long graphs are summarised; exact
  readings remain available through table pages. Requests have bounded work and
  concurrency; choose a shorter range if a slow-storage query reaches its time budget.
- Recovery hysteresis, flap protection and configurable issue reminders are
  implemented. Scheduled maintenance windows and configurable polling intervals
  remain unimplemented.
- Automatic startup/restore migrations and full database backup/restore are
  implemented. Scheduled/off-site/encrypted backups, pre-upgrade backup automation,
  standalone migration tooling and downgrade support remain unimplemented.
- Polling is a cycle, not a precise interval: slow endpoints lengthen the cycle.
  A repeatable synthetic capacity harness is provided in [LOAD_TESTING.md](LOAD_TESTING.md).
  Results depend on hardware, storage, network conditions and device behaviour;
  the harness does not measure browser rendering or reproduce every real-device fault.

## Verification

```sh
python3 -m unittest discover -s tests -v
python3 -m compileall app
```

Tests cover threshold persistence/recovery, acknowledgement, deployment isolation,
credential redaction, OID validation, backup preservation, full inventory edits,
transactional deletion and isolation from delayed polling results. Hardware polling
requires validation with real equipment. See AGENTS.md for full agent context.

Removing a service disables it and preserves its history. Permanently deleting
its inventory device also removes the linked service history.
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

Service cards keep actions in a compact **Actions** menu. Use **History**
to switch between an SVG graph and exact readings. Numeric metrics use lines;
state codes use labeled steps. Missing/suppressed readings and gaps over 60 seconds
break the line. Graphs group compatible readings by measurement version; the table preserves
older configurations. Graphs are local and do not depend on a CDN or chart service.

Optional dashboard logic tests (Node.js 18+): `node tests/dashboard.test.mjs`,
`node tests/connection.test.mjs` and `node tests/host_view.test.mjs`.
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

## Recovery hysteresis and flap protection

Numeric services can set **Recovery hysteresis (metric units)** in the service
editor. A zero margin disables hysteresis. Escalation uses the configured Warning
and Critical thresholds; recovery must also clear the margin, for the configured
number of consecutive readings. For example, Warning below -65 dBm with a margin
of 3 requires -62 dBm or better to recover. State-code services do not use hysteresis.

Flap protection detects repeated confirmed status changes within its configured
window, suppresses repeated issue notifications during flapping and requires a
continuous stable period before ending the flap episode. Monitoring and dashboard
updates continue. Flap settings are available for automatic host checks and services.

## Delivery behaviour

New confirmed issues and optional recoveries are queued independently for each
enabled provider. Per-host notification flags and host dependencies are respected.
Enabling a provider does not replay old issues. Each event is queued once per
provider. Configurable reminders repeat for eligible open, unacknowledged issues;
acknowledgement, notification pauses, dependency suppression and flap protection
prevent inappropriate reminders. Notification-link remote acknowledgement through
an external relay remains unimplemented.

Queues survive restarts. Transient failures retry with backoff, up to five attempts;
permanent errors stop immediately. Admins see pending/sent/failed/cancelled states
and can retry failed messages for the current configuration. Changing provider
settings cancels pending messages so they cannot move to a different destination.
Restoring a backup cancels unsent messages and pauses polling.

“Sent” means accepted by the provider, not a verified read/delivery receipt. A
network timeout after provider acceptance can cause a duplicate on retry. Use
Send test to verify provider delivery in your environment. Tokens are hidden in
the UI and logs, but remain in admin backups; protect those backups.

Admins can select **Operator** when adding or editing a user. Operators can view
monitoring/history and acknowledge issues within the current project, plus
use its operational controls as described under Login and roles. Configuration remains
Admin-only. **Healthy**, **Warning**, and **Critical** use capitalised labels.
Host cards use amber/red backgrounds for confirmed Warning/Critical issues;
the highest open severity wins. Acknowledgement does not remove the colour until
the fault recovers. Suppressed child faults do not add a second fault indication.

Signed-in users of the Status Dashboard have a **Hide host cards / Show host cards**
button. Anonymous visitors see no Live Hosts section or host controls.
Hide cards for an issue-only view. The choice is stored in that browser and
is preserved during live updates and page reloads.

When a host list cannot fit the available width, either dashboard temporarily
shows Cards and disables List with an explanation. The saved List preference is
preserved and restored when sufficient space returns. Hiding services or narrowing
the service filter can make List available again. An explicit Cards selection
still becomes the user's saved preference.

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

Under **Project configuration → Edit selected project**, Admins can
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

For signed-in users, Status Dashboard **Sort hosts** offers hostname A–Z/Z–A, alias, host status in either
priority order, and issue severity. The selection is saved in browser storage
and applies to both Cards and List views.

Admins can enable **Allow status-page acknowledgement** under **Edit selected
project**. New projects default to enabled; existing projects keep their setting.
When enabled, signed-in Admins and Operators
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

Project configuration opens from the top control row, immediately before the
Acknowledged issues control. Its area appears below those buttons and above Active
issues. Other configuration areas use the lower colour-coded tabs. Only one
configuration area can be open at a time; all start closed after a page reload.
The Project assignments device list has a separate collapsed-by-default arrow.
The complete Project configuration area has a shared outer border. Successful
saves show dismissible six-second toasts at the top right, as well as inline
confirmation. Toasts stack with the newest first; each has its own countdown bar
and auto-close timer. The compact stack is 320px wide and shrinks on small screens.
New confirmations do not replace or restart earlier ones. Unacknowledgement uses
inline confirmation and the updated issue lists rather than a toast.
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
unrecognised URLs fall back to /. Return context is kept in the page URL per tab. `/login` contains only sign-in:
already signed-in users return to their dashboard, while accounts requiring a
password change go to `/change-password`. The dedicated change page requires a
session; voluntary changes are available via **Change my password** in User
Management. Changing a password requires the current password and replaces all
existing sessions for that account with a new session for the current browser.
The login page also checks the existing session after loading and when returning
to a backgrounded/restored tab, preserving the selected dashboard and mandatory
password-change flow without extending the configured session lifetime.

Admins can set the fixed session duration in User management → Login sessions
(1–168 whole hours, default 12). Changes apply to new sign-ins, not existing
sessions; activity does not extend expiry. The database setting controls both
server session expiry and cookie Max-Age and is included in backups.
Manual **Sign out** on either dashboard requires confirmation in an app-styled
dialog. Cancel or Escape keeps the session; automatic expiry still occurs normally.
Authenticated `/api/me` responses include `session_expires_at` (Unix timestamp)
and `session_remaining_seconds` (whole seconds remaining when the response was
created), for the requesting session only. Reading them does not extend expiry.

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

Starting a deployment requires a name of 1–40 characters in the confirmation
dialog. The dashboard shows its name and original start time for the active or
paused deployment. Pause/Resume preserves both. Existing longer descriptions are
kept until an Admin explicitly renames them; older unnamed deployments stay unnamed.
Deployment descriptions are included in SQLite backups but not public status APIs.

## Transfer permanent inventory

In **Permanent inventory**, choose **Export inventory** to download versioned JSON
containing every device's Device ID, model, IP and service defaults, including
stored SNMP communities. Protect the file. This is separate from a complete backup:
projects, assignments, aliases, history, issues, accounts and the reusable service
library are not included. The filename uses the server's local date/time.

Choose an inventory JSON file and an import mode, then **Review inventory import**:

- **Merge** adds new Device IDs and skips exact matches without changing them.
- **Update existing** also updates matching devices' model/IP and replaces their
  service-default set with the file's definitions. Defaults with matching names
  retain their internal IDs. Devices absent from the file remain untouched.

Device IDs match exactly, including case. Existing project services, assignments
and history are preserved; defaults apply to future new assignments. Inventory IP
changes still apply to every project using that device. Blank IPs can be transferred
as unconfigured inventory; new devices are never assigned to projects automatically.

The preview shows additions, updates, skips, default names/removals and IP conflicts.
Resolve conflicts before importing. Equivalent IPv6 spellings count as the same IP;
valid IP swaps are applied atomically. The whole file is validated before changes,
and a failed import rolls back every change. If inventory changed after preview or
the server restarted, close the preview and review again. Imports are Admin-only,
with a 10 MB / 5,000-device / 10,000-total-default limit. No Replace-all mode exists.

## Duplicate inventory equipment

In **Permanent inventory**, expand the device list and choose **Duplicate**.
Enter a new unique Device ID and IP address; the model is prefilled and editable.
The new IP starts blank to avoid accidentally monitoring the source equipment.
The duplicate includes all service defaults and their credentials/settings as
independent copies. Project assignments, aliases, service history and issues are
not copied. Assign the new device to a project when ready.

Adding, editing or duplicating inventory rejects an IP already assigned to another
device and identifies that device in the error. Equivalent IPv6 spellings count as
the same address. A device can retain its own address when edited. Existing
inventory is preserved on upgrade/restore; new saves enforce the conflict check.

## Device service defaults

Permanent inventory lists devices alphabetically by Device ID, ignoring case and
using natural numeric order (SW2 before SW10). Search results use the same order.

In **Permanent inventory**, open the device list and choose **Service defaults**
for a device. Add/edit/remove definitions, add one from the reusable library, or
choose an existing project configuration and **Replace defaults from project**.
When adding from the library, choose **Service name on this device** before adding.
It starts with the library name and can be shortened, for example from Siklu EH RSSI
to RSSI. Only the device's copy is renamed; future project assignments use that name,
while the library entry and existing project services remain unchanged.
This explicit adoption copies credentials on the server and leaves the project
untouched. Existing projects are not chosen automatically during upgrade.

Assigning that device to a new project copies its defaults into independent
project services, alongside automatic host ping. Subsequent edits in either place
do not affect the other. Re-adding a removed assignment restores its old setup;
duplicating a project copies that project's configuration. Copies start with
monitoring enabled. Inventory defaults are included in complete backups.

The top Project configuration button and lower configuration tabs are exclusive;
switching areas preserves unfinished forms. They start closed after a page reload.
Creating a project selects it for editing without starting a deployment or changing
the monitored project. New projects allow Status Dashboard acknowledgements by
signed-in Admins/Operators by default. Existing projects retain their settings;
duplicating a project copies its acknowledgement setting. Anonymous users and
View Only users cannot acknowledge issues.
The public status dashboard pulses its background three times when a new active
issue appears after the initial load: red for Critical/Unreachable, yellow for Warning. Existing or reappearing issues do not
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

## Rename a deployment

Admins can choose an active, paused or historical run under **Previous deployments**
and click **Rename selected deployment**, between Resume and Delete. Edit the name
(1–40 characters), then choose **Save deployment name** or **Cancel**. The deployment
number, original start time, readings, issues and monitoring state stay intact.
If another Admin renamed it while the editor was open, close and reopen the editor
to review the new name before saving. Older descriptions longer than 40 characters
must be shortened when renamed; they are never automatically truncated.

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

Status attention pulses reflect severity: three yellow pulses for new Warning
issues, three red pulses for new Critical/Unreachable issues. Red takes priority
if both arrive together or while a critical alert is already pulsing. These
visual alerts do not depend on Telegram/WhatsApp notification settings.


## Unacknowledging issues

Admins and Operators can use **Unacknowledge** in Acknowledged issues on the main
dashboard. The Status Dashboard offers the same action when that project's
acknowledgement setting is enabled and the issue is publicly visible. View Only
and anonymous visitors cannot use it. Both pages require an app-styled confirmation.

The action removes the current acknowledgement without changing the recorded
fault or recovery: open faults return to Active, unavailable child services appear
in Suppressed, and recovered faults move to Resolved. It does not send another
opening notification. Eligible reminders restart after the configured interval;
global pause, host dependencies, service pause and flap protection still apply.

Each acknowledge/unacknowledge records the authenticated actor's ID, username,
full name and timestamp in an immutable audit table in SQLite. The authenticated
state API includes this as `acknowledgement_history`; it is included in complete
backups and is not exposed on anonymous status. Account edits/deletion do not
rewrite the trail. Deleting the corresponding issue/deployment/device purges its
related audit events. Older acknowledgements are migrated using their saved actor
snapshot; missing historical identity remains unknown. Revision checks prevent a
stale confirmation from removing a later acknowledgement.


Dashboard acknowledgements, global project/deployment changes, monitoring and
notification pause/resume controls, host monitoring/visibility/notification toggles,
and individual service pause/resume trigger same-origin
`/api/ack-events` server-sent events after the change is committed. Connected dashboards
refresh promptly rather than waiting for the next ten-second poll. An Admin's local
project dropdown remains a personal configuration selection; it does not switch the
global deployment. Live metric readings still follow their normal check intervals.
The stream carries only an opaque change revision; dashboards
still fetch normal API data with their existing permissions. Reverse proxies must
allow streaming without buffering this path. Ordinary ten-second refresh remains
available if streaming is interrupted, and reconnect/tab-focus refresh catches up.

## Delete a project

Admins can use **Project configuration → Edit selected project → Delete project**.
Pause monitoring first if this is the running project. The app-styled confirmation
names the project and explains the permanent deletion before starting a background
job. Progress appears in Project configuration; interrupted jobs continue after
restart. If a database error stops a job, check storage and use Retry project deletion.

Deletion removes the project's assignments, services, deployments, readings,
issues, acknowledgement audit, notification outbox entries and logo. It preserves
permanent equipment, inventory service defaults, reusable library definitions,
users and other projects. Legacy orphan readings are removed by deployment too.
Completed job metadata remains available to report the result. Physical SQLite
file space is reused; deleting rows does not automatically shrink the file.

Small deletion batches allow monitoring and acknowledgements for other projects
to continue. Configuration changes and complete backup downloads are unavailable
while deletion is unfinished. Restore is blocked while a deletion is running;
a failed job can be retried or replaced by restoring an earlier complete backup. Deletion cannot be cancelled
once confirmed; recover deleted project data by restoring an earlier complete backup.

## Service history periods

Open **History** for a service. Choose its deployment and a preset:
15 minutes, one hour, six hours, 24 hours or seven days. Alternatively choose custom
From/To dates and Apply range. Times use the browser's local timezone. A single
request can cover up to 31 days; retention still applies globally by reading age.
The dialog explains empty ranges and the configured retention period.

Alarm edits (thresholds, direction, persistence and flap settings) keep compatible
readings together on the graph. Changes to the protocol, target, Modbus addressing,
scale, units, value type or state labels start a new measurement version. When there
are multiple versions, use **Graph measurement** to view an earlier segment with its
own units/labels. The table includes all versions and their configuration numbers.
Historical statuses stay as recorded. Threshold lines show current limits only for
the current measurement; earlier versions do not show those limits.

Existing pre-upgrade test history is grouped as measurement 1 without trying to
reconstruct previous definitions. Future changes preserve separate definitions.
Short graphs show up to 2,000 exact points. Longer numeric graphs retain first,
last, minimum and maximum values per time bucket; collection gaps remain
broken. State graphs preserve transitions up to the point limit, then explicitly
warn when a shorter period/table is needed to see every state change. The table
shows exact readings in pages of 200, with Newer/Older controls.

History reads use the existing service/time index in short batches and never
hold the global monitor lock. Up to four range requests run concurrently, with a
20-second graph work budget and a 30-second browser read timeout. These new range
queries have regression coverage but have not been capacity-tested on the Pi.

### Modbus register types

For Modbus TCP services, the shared service editor replaces the SNMP community
field with a register-type selector: **Holding register (03)** or **Input register (04)**.
Existing services and older imported libraries keep Holding (03). The choice is
retained in copies, inventory defaults, library exports and complete backups.

For a TCP-to-RTU gateway, enter the gateway IP in inventory and the downstream
device unit ID in the service. Enter the zero-based register address in decimal
(for example, `0x0062` becomes `98`); selecting Input (04) changes the read function,
not the address. TCP port 502 is used. Confirm the register, scaling and unit ID
against the device documentation; reads currently support one unsigned 16-bit register.


### Stylesheets and UI regression checks

All four HTML pages load local files from `app/static/css/`. `base.css` owns
shared theme variables and components; `dashboard.css`, `status.css` and
`auth.css` contain page-specific layouts. Keep shared button, form, issue,
host-card and connection-dialog styling in the base file. Use classes for static
presentation; inline values are reserved for runtime data such as toast duration,
graph coordinates and popup positioning. No framework or CDN is required.
The server allowlists these four CSS files, serves them before authentication,
and sends `Cache-Control: no-store` plus `nosniff`. Stylesheet links carry a build
query; update it on all affected pages when changing CSS.

See [UI_TESTING.md](UI_TESTING.md) for UI check coverage, limitations and
instructions to run the checks.


### Restore upload size and comparison installations

Disk-backed restore uploads default to **20 GiB**. Set `MONITOR_MAX_RESTORE_MB`
in `.env` (whole MiB, 1–1048576) and recreate the container to change the cap.
Existing `.env` overrides, such as 256, remain in effect until changed. Free-space
checks reserve room for the upload, candidate database and destination journal;
a limit is not a guarantee that sufficient disk space is available.

A reverse proxy may enforce a smaller body size or timeout. The dashboard allows
up to two hours for restore upload/validation/application; adjust proxy limits if
needed. Never blindly retry a replacement after a connection failure—check the
installation's state first. Oversized uploads return HTTP 413, insufficient free
space returns 507, and validation failures leave destination data unchanged.

When comparing two installations on the same hostname/IP with different ports,
use separate browser profiles or a normal window plus an Incognito window. Session
cookies are shared across ports, so signing into one installation can overwrite
the other's cookie and invalidate its open page's CSRF token. This is independent
of backup validity. Restore still replaces the destination database, pauses
monitoring and notifications, and requires signing in again with the backed-up accounts.
