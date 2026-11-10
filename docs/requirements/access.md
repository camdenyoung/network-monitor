# Access, accounts and acknowledgements

Server permissions, public allowlists, sessions, actor history and authentication flows.

Current requirements. Read [AGENTS.md](../../AGENTS.md) first. The
[migration audit](MIGRATION.md) records the source of each section; anchor IDs
are navigation aids, not priorities.

Related areas: [Projects and deployments](projects.md), [Monitoring and issue lifecycle](monitoring.md), [Dashboard connections and synchronization](connections.md), [Forms and shared layout](forms-layout.md), [Dashboard display](dashboards.md).
Read the related rules affected by the task; these links do not load documents automatically.

<a id="r021"></a>

## Status acknowledgement permissions

- Status acknowledgement is a per-project Admin setting, enabled for newly created
  projects. Preserve existing flags on startup/restore and copy the flag on duplication.
  Require a signed-in Admin/Operator and CSRF; enforce the flag/current project,
  visible monitored source and dependency visibility on /api/status-ack. Anonymous
  users and View Only users remain read-only.

<a id="r033"></a>

## Account email and password policy

- Accounts include an optional validated email for future password resets. No reset
  email flow yet. Admins choose must_change_password when creating/editing accounts;
  default true on creation, preserve on edits unless explicitly changed. Bootstrap
  admin always requires an initial change. Migrate old accounts without lockouts.

<a id="r034"></a>

## Role boundaries

- Local accounts: Admin, Operator and View Only roles enforced by the server. Admins manage
  users, all configuration, acknowledgements and backups. Operators follow the globally
  active/paused project, can resume its existing deployments, toggle global monitoring/
  notifications and individual additional services, and acknowledge/unacknowledge issues.
  Viewers follow the global project AND deployment, including history, and inspect only.
  Neither restricted role can switch projects or create/delete deployments; configuration
  stays Admin-only. Scope APIs server-side, not just controls in the UI.

  Renaming an existing deployment is Admin-only; Operators and View Only users
  cannot change its name through either the dashboard or the API.

<a id="r035"></a>

## Bootstrap administrator

- First-run admin password is generated in /data/initial-admin-password.txt or supplied
  via MONITOR_ADMIN_PASSWORD; require change on first login. Never commit defaults.

<a id="r036"></a>

## Signed-in status host toggle

- Signed-in /status users have a show/hide host cards toggle, persisted per browser.
  Anonymous visitors see no Live Hosts or host controls; public issue lists stay available.

<a id="r037"></a>

## Public issue overview

- Public /status overview shows active issues above host cards. Reuse dependency-
  aware active issues, excluding resolved/suppressed faults and
  hidden, paused or inactive equipment. Allowlist display fields only.

<a id="r038"></a>

## Public data allowlist

- Public /status issue overview needs no login; live hosts/readings require an
  authenticated session without a forced-password-change restriction. Never expose
  IP addresses, OIDs, credentials, account details or other project inventory;
  acknowledged issues explicitly expose recorded display names and usernames only.

<a id="r062"></a>

## Authentication and notification security

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

<a id="r065"></a>

## Status identity response

Public status shows Not signed in or the caller's display name/role, with Sign in /
Dashboard navigation. /api/status exposes the caller's identity and recorded
acknowledging display names and usernames, never account lists, email or password/session hashes. Temporary-password users
get Change password navigation and remain unable to acknowledge.

<a id="r066"></a>

## Recorded actors and section visibility

Acknowledgements retain the authenticated account ID and username at the time of
acknowledgement, including after account rename/deletion. Legacy records display
Unknown user (legacy). The main dashboard has independent Show/Hide controls for
acknowledged, suppressed, resolved and live host/service sections, saved in browser
localStorage. Hiding sections does not pause monitoring or hide active issues.

<a id="r068"></a>

## Public acknowledged issues

Public status includes an allowlisted acknowledged-issue list above hosts, with
a colour-coded Show/Hide toggle persisted separately in localStorage. Apply current
project/host/service visibility rules. Show the recorded acknowledging full name (or username fallback),
with Unknown user (legacy) for older records; never expose actor IDs or account details.

<a id="r070"></a>

## Full names and attribution

Accounts have an editable Full Name (up to 150 characters) separate from the login
username. Signed-in labels and acknowledgement attribution prefer the full name,
falling back to username for existing accounts. Acknowledgements snapshot the full
name at acknowledgement time; later profile edits do not rewrite history. Both
startup and restore migrate account/audit fields. Public issue attribution includes
this display name. The main navigation link is labelled Status Dashboard.

<a id="r071"></a>

## Independent user editor

User management keeps the add-user form independent. Edit opens a native dialog
with all account fields and inline errors; Cancel leaves the creation form intact.
Populate the editor only when opened; background refresh must preserve edits.
Keep the must-change-password setting in the account editor, without displaying
assigned-password/change-required text in the user list.

<a id="r074"></a>

## Enriching legacy acknowledgement names

Older username-only acknowledgements display the account Full Name after it is
filled in, matching both recorded account ID and username. This enriches response
data without rewriting stored audit records. A real full name captured at the time
of acknowledgement remains authoritative, even after profile changes/deletion.

<a id="r086"></a>

## Login return destinations

Sign-in from the status dashboard uses /login?next=%2Fstatus and returns there
after login, including any required password change. Admin dashboard sign-in
defaults to /. Only /status and / are allowed return destinations; external or
unrecognised URLs fall back to /. Return context is kept in the login URL per tab.

<a id="r087"></a>

## Fixed login-session duration

Admins can set the fixed session duration in User management → Login sessions
(1–168 whole hours, default 12). Changes apply to new sign-ins, not existing
sessions; activity does not extend expiry. The database setting controls both
server session expiry and cookie Max-Age and is included in backups.

<a id="r131"></a>

## Unacknowledgement revisions and audit

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

<a id="r170"></a>

## Authenticated status host data

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

<a id="r174"></a>

## Separate authentication pages

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

<a id="r175"></a>

## Password-change layout and browser handover

Password-change layout uses a two-column grid: Username/Current password first,
New password/Confirm new password second, then Save password and Cancel in an
independent full-width actions row. Stack fields on very narrow screens. Cancel
returns to the originating dashboard for voluntary changes; keep it hidden for
mandatory changes, whose API restrictions remain enforced.

Do not claim credential saving is fixed or add a blind Enter handler that submits
while choosing a saved credential. Coordinate explicit browser handover before UI
interaction; concurrent user input invalidates tests.

<a id="r176"></a>

## Browser extension uncertainty

Keep separate login/change-password pages for their independently confirmed
routing benefit. Browser extension interoperability requires real-browser verification.
The earlier iCloud observations and user follow-up are historical context in
CHANGELOG.md; do not infer a specific cache mechanism or a reliable Escape workaround.

<a id="r177"></a>

## Login-session reconciliation

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

<a id="r178"></a>

## Session-expiry response

/api/me includes session_expires_at (Unix timestamp, seconds since epoch) and
session_remaining_seconds (nonnegative whole seconds, rounded down at response
creation). auth.session_user selects the matching session's expires with an alias;
keep public_user's account allowlist unchanged so other/public responses do not
leak session timing. Include the fields for all authenticated roles, including
mandatory-change sessions; expired/anonymous requests still return 401. Reading
expiry never renews the cookie or updates the database. No schema change.

<a id="r183"></a>

## Sign-out confirmation behaviour

Both dashboard Sign out buttons open #signout-confirmation, an app-styled dialog
with explicit Sign out/Cancel and Cancel autofocus. configureSignOut is identical
on both pages: no requests on open/Cancel/Escape, ignore closed/stale confirmation
clicks, block duplicates and cancellation while busy, keep failures inline and
allow retry. Preserve role/temporary-password support and existing CSRF logout.
Admin returns to /login; Status clears private hosts/ack state immediately and
stays public. A post-logout public refresh failure does not make logout fail.
Automatic expiry/authentication redirects never require this manual confirmation.

<a id="r184"></a>

## Sign-out dialog styling

Sign-out dialogs use the shared .signout-dialog class in base.css, independent of
.acknowledgement-dialog: 340px width, viewport cap, 20px padding, compact heading/
body/action spacing and matching backdrop. Empty feedback occupies no space;
Cancel autofocus and all sign-out behaviour stay unchanged. Keep both dashboards
on this same class; do not resize longer issue/review dialogs to fix sign-out.

<a id="r185"></a>

## Scoped monitoring roles

Scoped monitoring roles: app/access.py resolves active_run, falling back
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
