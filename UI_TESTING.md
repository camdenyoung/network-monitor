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
node tests/host_view.test.mjs
```

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
