# Stylesheet refactor validation

Build 102 extracts and consolidates styling while preserving existing layouts.
Baseline: v0.5.8 Build 101 (tree `844c9e9ef23a41991e0c92c151f90ee852b33882`).

## Results

- 248 backend tests passed, including authentication, session restoration, monitoring,
  backups, inventory and public/allowlisted stylesheet delivery.
- Dashboard, account-page, connection-recovery and responsive host-view JavaScript
  suites passed. All four application scripts remained byte-for-byte unchanged.
- 696 rendered comparisons passed: 87 deterministic scenarios at 320, 390, 480,
  760, 761, 900, 1280 and 1600 pixels. No differences in the sampled computed
  properties or document-space element bounding boxes.
- The full summary is in [tests/reports/stylesheets-build102.json](tests/reports/stylesheets-build102.json).

## Rendered scenarios

Both dashboards include healthy/warning/critical/blocked/paused equipment, Cards
and List layouts, host-only and hidden-host states, anonymous/Operator/View Only
presentation, logos, long project/host labels, wrapped action groups, open Actions
menus, toast styling, and warning/critical attention indicators. The Admin page
also covers every declared configuration panel, each declared dialog, and SNMP,
Modbus, TCP and state-mapping editor presentations. The Status page covers its
declared dialogs. Login and password-change pages cover ordinary, long-content,
error and mandatory-change presentations. Ten additional scenarios activate the
authored reduced-motion rules for paused monitoring, toasts, attention and reconnect
presentation on both dashboards.

## Repeat the comparison

Use a checkout containing the refactor and a locally available pre-refactor Git
commit. The preview runs without a database, background pollers, credentials,
mutation endpoints, external assets or notification sends.

```bash
python3 -m tools.style_preview --baseline <pre-refactor-commit> --port 18080
```

Open `http://127.0.0.1:18080/matrix` in an ordinary browser, wait for completion,
and use **Download JSON report**. Stop the terminal process with Ctrl+C afterwards.
The server binds only to loopback. The same fixture code is applied to both page
versions; styles are loaded from the baseline HTML and the candidate's CSS files.
Build labels are normalised and animations paused for deterministic comparisons.
Each preview frame is focused immediately before sampling so opening a dialog in
one frame does not create a false focus-outline difference in the other. Reduced-
motion fixtures activate only the existing reduced-motion media rules, without
modifying browser or operating-system preferences.

Run functional verification separately:

```bash
python3 -m unittest discover -s tests -q
python3 -m compileall -q app tools
node tests/dashboard.test.mjs
node tests/connection.test.mjs
node tests/dashboard_stream.test.mjs
node tests/host_view.test.mjs
```

`tests/toasts.test.mjs` is also imported by the dashboard suite and can run on its
own. It checks confirmed-save feedback across Settings, accounts, providers,
imports and operational controls, plus failed refreshes and stale deployment
confirmations. All requests are mocked; it never sends provider messages.

`tests/deployments.test.mjs` checks the Admin-only rename editor, Resume/Rename/Delete
button order, 40-character validation, captured targets, preserved drafts and
Cancel/Escape/duplicate-submit behaviour. It is imported by the dashboard suite.
`tests/test_deployments.py` covers API permissions, optimistic rename conflicts,
unchanged history/state and compatibility with older long deployment descriptions.

## Limits

This is a representative matrix, not every possible cross-product of projects,
roles, content, device sizes and interactions. The fixture server deliberately
populates static page DOM and disables application scripts: it tests CSS/layout,
not real login permissions or monitoring operations. Those are covered separately
by backend tests and the JavaScript suites, whose DOM/network objects are simulated.
The browser comparison samples authored computed CSS properties (excluding new
custom-property declarations) and element bounds, not screenshot pixel equality,
pseudo-element pixels, animation timing or operating-system native controls.
It does not establish identical rendering in every browser, iOS version, zoom level,
font configuration or password-manager extension. Real hardware acceptance testing
remains appropriate before merging this presentation refactor.


## Subsequent restore fix (Build 103)

After the presentation-only Build 102, comparison deployment testing exposed the
pre-existing 64 MiB restore cap. Build 103 raises/configures that limit and changes
the Admin dialog's error handling to report the server's actual failure. This is a
separate functional fix, not part of the byte-identical-script claim above. It adds
backend large-backup/fresh-install and size-limit tests, plus frontend authentication,
CSRF, size and non-JSON proxy error cases. The CSS files and Build 102 layout report
remain unchanged.


## Backup workflow addition (Build 104)

The dedicated backup branch adds a new app-styled review dialog and local CSS rules
for its viewport height/long filenames. It deliberately changes backup workflows;
the presentation-only comparison report remains evidence for Build 102 only. New
backend tests cover complete/config-only exports and restores, data ownership,
credentials/logos/defaults, legacy compatibility, no reads from history during config
copy, bounded I/O, disk failures, review ownership/expiry/cancellation/replay, and
Admin/CSRF enforcement. UI tests cover review mode restrictions, captured uploads,
failed previews/applies, cancellation, busy states and duplicate-submit prevention.


Build 104 validation: all 262 backend tests and dashboard/account/connection/host-view
suites passed. A real local browser run signed into a disposable installation,
uploaded a complete SQLite backup, reviewed its two available modes, selected
configuration only at a 390px viewport (358px dialog, no horizontal overflow), and
applied it. The browser returned to Sign in. Read-only database inspection confirmed
one retained project/device and two accounts, zero deployments/samples/issues/sessions,
active_run=0, paused_run=0 and notifications_paused=1. No live installation, provider
or monitoring database was used. The temporary browser tab/server/database were
closed and cleaned afterwards.


## Manual sign-out confirmations (Build 105)

Both dashboards use the same app-styled confirmation logic. tests/signout.test.mjs
(imported by the dashboard suite) checks no requests on open/Cancel/Escape, rejection
of stale/duplicate confirmations, blocked closing during requests, inline failures
and retry. The Admin binding is checked for one logout request and /login navigation.
Existing public-dashboard tests exercise Admin/Operator/View Only and mandatory-change
accounts, session expiry and stale authenticated responses after confirmed logout.


Build 106 gives sign-out its own shared style. Local browser fixture checks measured
340×176px on a 1280px viewport and 288×176px on a 320px viewport, with no horizontal
overflow and Cancel focused on both dashboards. Sign-out behaviour tests and all
97 API/access tests passed. Other confirmation widths are unchanged.


## Scoped monitoring roles (Build 108)

All 268 backend tests pass, including six new role-boundary tests with multiple
projects/deployments. They verify state collection filtering, empty/paused scope,
Viewer history confinement, Operator history within its project, bounded history
batch revalidation, CSRF, stale deployment controls, managed-ping/archived-source
protection, scoped logos and Admin-only configuration. Existing acknowledgement,
monitoring, notification, backup and retention suites remain passing.

Dashboard/account/sign-out, reconnect and responsive host-view JavaScript suites
pass. New UI scenarios verify fixed project labels, forced Viewer history scope,
Operator controls and stale history/resume-dialog invalidation after a global
switch. Earlier Admin manual-selection tests explicitly use an Admin account.

A real browser check on a disposable loopback installation verified Operator service
pause and confirmed resume of an existing deployment, retaining paused monitoring
and notifications. View Only showed no project/deployment or operational controls
and its history remained usable for the global deployment. Checked at phone and
desktop widths; no live providers, device polling or production database were used.
These checks do not replace testing on the deployed Raspberry Pi or every browser.


## Live operational changes (Build 110)

All 271 backend tests and the dashboard/account/sign-out, connection-recovery and
responsive host-view JavaScript suites pass. New server tests cover committed
activation/project switches, deployment resume/deletion, global monitoring and
notification controls, individual service pause/resume and host flags. Separate
SQLite connections verify that listeners see committed values. No-op/rejected
requests and simulated rollback do not publish. An Operator HTTP action wakes
Admin and Viewer waiters, whose subsequent API reads retain their role scope.
Existing stream tests verify opaque payloads/heartbeats, and UI tests cover separate
dashboard contexts, queued refreshes, reconnects and polling/focus fallback. No new
metric polling or live provider sends are introduced.
