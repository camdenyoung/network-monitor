# Network Monitor changelog

Build history and release notes for Network Monitor. See [README.md](README.md) for setup and usage.

## Build history

### Build 115 — v0.6.2

- Reuse a dashboard tab's live connection slot on refresh, including at full capacity. Cancel the previous stream immediately and wait for its real worker to exit before replacement.
- Keep stalled handovers bounded, retain their capacity until cleanup, and prevent delayed cleanup from removing a newer stream. Keep legacy clients and polling fallback available.
- Separate duplicated tabs through browser identity arbitration; clean up claims on navigation and recheck them after cached-page restoration.
- Verify rapid refreshes at twenty-stream capacity with normal heartbeats and retained upstream sockets, plus thread termination, stalled cleanup and dashboard lifecycle regressions.

### Build 114 — v0.6.2

- Default live dashboard streams to 20, with an Admin-configurable 1–200 limit in the renamed Settings tab alongside issue reminders; preserve the setting in backups.
- Show actual live connections/configured maximum in the Admin badge. Keep polling available above capacity and back off stream retries for 30 seconds.
- Bound ordinary HTTP request threads separately, add socket inactivity timeouts, and release connection slots on disconnects and response errors.

### Build 113 — v0.6.2

- Merge the Host flap protection button colour fix: keep the standard white label in Cards and List views, independently of host status.
- Update dashboard release labels and documentation; retain existing monitoring behaviour and permissions.

### Build 112 — v0.6.1 (host flap button colour)

- Keep Host flap protection button text in the standard white colour in Cards and List views, independently of the host status colour.

### Build 111 — v0.6.1

- Merge scoped roles: View Only follows the global project/deployment; Operators stay within its project with existing-deployment resume and monitoring/notification controls. Keep configuration and deployment creation/deletion Admin-only.
- Refresh other connected dashboards promptly after committed operational changes, with opaque events, role-scoped reads and the ten-second polling fallback.
- Shorten each service action to **History**, preserving graph/table functionality.
- Verify with 271 backend tests and dashboard/account, connection-recovery and responsive host-view suites. See UI_TESTING.md for coverage and limits.

### Build 110 — v0.6.0 (live operational updates)

- Refresh other connected dashboards promptly after global project/deployment changes and monitoring/notification or host/service control changes, using the existing opaque event stream.
- Publish after commit only; skip no-op/rejected/rolled-back controls. Preserve role-scoped reads, reconnect/coalescing and the ten-second polling fallback.

### Build 109 — v0.6.0 (service history label)

- Rename each service action from “History / graph” to “History”; retain graph/table functionality and role permissions.

### Build 108 — v0.6.0 (scoped monitoring roles)

- Fix View Only accounts to the globally selected project/deployment, including history; follow active and paused deployments without project selectors.
- Fix Operators to that project, with existing-deployment selection/resume, global monitoring/notification toggles and individual service pause/resume.
- Enforce scope in state, logo and history reads and transactional mutations; reject stale Operator controls across deployment changes. Keep configuration, inventory, deployment creation/deletion, users and backups Admin-only.

### Build 107 — v0.6.0

- Merge shared local stylesheets and theme variables across all pages, with before/after layout validation and retained offline operation.
- Include disk-backed complete/configuration-only backups and reviewed selective restores, with bounded streaming, disk-space checks, legacy compatibility and a configurable 20 GiB default upload cap.
- Include compact app-styled sign-out confirmations on both dashboards, preserving logout destinations, cancellation and automatic session expiry.
- Verify with all 262 backend tests and dashboard, account, sign-out, connection-recovery and responsive host-view suites. See UI_TESTING.md for browser checks and coverage limits.

### Build 106 — v0.5.8 (compact sign-out styling)

- Give both sign-out confirmations a dedicated shared 340px responsive style with compact spacing and no empty error area.
- Preserve wider issue/review dialogs, Cancel autofocus and existing sign-out behaviour; version stylesheet references for the update.

### Build 105 — v0.5.8 (sign-out confirmations)

- Add matching app-styled Sign out/Cancel confirmations to both dashboards, with Cancel focused initially.
- Opening/cancelling sends no logout; guard duplicate submissions and closing during requests, and retain failures inline for retry.
- Preserve manual logout destinations, public host-data cleanup, role support and automatic session expiry.

### Build 104 — v0.5.8 (disk-backed backup and selective restore branch)

- Stream backup downloads and restore uploads through private on-disk SQLite files with bounded buffers, disk-space checks and a configurable 20 GiB default cap.
- Add compact configuration-only backups, preserving accounts, equipment, assignments, service definitions/defaults/library, credentials and logos while excluding history/runtime data.
- Review uploaded content before replacement; select complete or configuration-only restore where available. Add session-bound, expiring, single-use reviews and cancellation cleanup.
- Preserve legacy SQLite restore support and migration checks. Both restore modes pause monitoring/notifications and invalidate sessions; configuration-only replacement removes destination history.
- Verify with 262 backend tests, functional UI suites and a real browser upload/review/configuration-only restore on a disposable database, including phone-width dialog checks.

### Build 103 — v0.5.8 (restore upload fix)

- Fix complete backups over the old 64 MiB upload cap being rejected. Default to 256 MiB, configurable with MONITOR_MAX_RESTORE_MB (1–1024 MiB).
- Reject oversized uploads before reading their bodies and show the actual authentication, request-token or size error in the restore dialog.
- Preserve database validation and restore semantics. Test a real backup over 64 MiB into a fresh installation, bounded limits and frontend error handling.

### Build 102 — v0.5.8 (shared stylesheets branch)

- Extract embedded CSS from all pages into local shared and page-specific stylesheets, with readable formatting and common colour/spacing variables.
- Centralise shared controls, issues, host cards and connection indicators; keep existing page layouts, dynamic rendering and account workflows.
- Serve only four allowlisted CSS assets with versioned links, no-store caching and nosniff headers. Keep all assets local for offline deployments.
- Add repeatable before/after CSS layout fixtures: all 696 comparisons passed (87 scenarios × eight widths), with no sampled style/layout differences. All 248 backend tests and functional UI suites passed. See UI_TESTING.md for coverage and limits.

### Build 101 — v0.5.8

- Merge login session rechecks on load and mobile-tab restoration while preserving dashboard destinations, separate mandatory password changes and fixed session expiry.
- Include the requesting session's expiry timestamp and remaining seconds in `/api/me`, without extending its lifetime or exposing other sessions.
- Stabilise narrow-screen Status Dashboard controls: host visibility stays below acknowledged issues, with navigation left-aligned underneath.
- Verify with all 247 backend tests and dashboard, authentication, connection-recovery and responsive host-view checks.

### Build 100 — v0.5.7 (mobile Status Dashboard controls)

- Keep host visibility below acknowledged-issue visibility on narrow screens, with dashboard/sign-out navigation left-aligned beneath them.
- Use a stable responsive layout so Show/Hide and Cards/List label changes do not move controls between rows; preserve desktop alignment and access restrictions.

### Build 99 — v0.5.7 (session expiry information branch update)

- Add the requesting session's Unix expiry timestamp and whole seconds remaining to authenticated `/api/me` responses.
- Keep expiry out of account lists/public responses, preserve expired-session rejection and verify that inspection never renews the session.

### Build 98 — v0.5.7 (login session recheck branch)

- Recheck existing sessions from the loaded login page and when a mobile tab resumes, so an authenticated API session can return to its dashboard without another sign-in.
- Preserve separate mandatory password changes, safe per-tab return destinations and fixed session expiry. Use replacement navigation, bounded/coalesced checks and stale-response protection during sign-in.
- Preserve rejected drafts and usable sign-in on connectivity failures. Keep existing cookie security and add regression coverage for session restoration and 96-hour expiry.

### Build 97 — v0.5.7

- Merge separate login and password-change pages, with session-aware redirects and the original dashboard destination preserved through required changes.
- Include the paired-row password form with Save password and Cancel underneath, plus the self-service link in User Management.
- User testing confirmed that resetting retained browser state resolved iCloud autofill and Enter submission; no keyboard workaround was required. The separate forms fix the independently confirmed login redirect issue.
- Verify with all 245 backend tests and dashboard, authentication, connection-recovery and responsive host-view checks.

### Build 96 — v0.5.6 (password-change layout branch update)

- Arrange password-change fields in two paired rows with Save password and Cancel underneath; stack fields on very narrow screens.
- Rename the voluntary return action to Cancel while preserving mandatory-change restrictions and dashboard return context.
- Investigate iCloud Passwords Enter cancellation in its active suggestion-list handler. Escape worked in one diagnostic but was not reliable in user testing; see Build 97 for the subsequent browser-state resolution. No keyboard override was added.

### Build 95 — v0.5.6 (separate password-change branch)

- Separate sign-in and password-change pages; redirect signed-in visitors away from login and preserve the originating dashboard through mandatory changes.
- Add an explicit self-service password-change link in User Management, with a username field and appropriate autocomplete attributes on the dedicated change form.
- Preserve credential fields until navigation and use explicit submit buttons. Retain current-password verification, CSRF and session rotation; browser password-manager compatibility still requires real-device verification.

### Build 94 — v0.5.6

- Merge independent inventory device duplication with all service defaults and unique-IP validation into main.
- Include inventory JSON export and reviewed Merge/Update existing imports with atomic changes, IP-conflict checks and stale-preview protection. Preserve project services and history.
- Verify with all 243 backend tests plus dashboard, connection recovery and responsive host-view checks.

### Build 93 — v0.5.5 (inventory duplication and transfer branch)

- Add portable permanent inventory JSON export with all service defaults and credentials, plus Admin-only Merge and Update existing import modes.
- Preview additions, updates, skipped Device IDs, default replacements/removals and IP conflicts before confirmation. Preserve project data and inventory absent from the file.
- Validate final IP ownership and apply atomically, including valid IP swaps; reject stale or modified approvals. Preserve default IDs for matching names and keep imports separate from complete backups.

### Build 92 — v0.5.5 (duplicate inventory device branch)

- Add an Admin-only Duplicate action for permanent inventory, copying all service defaults independently while requiring a new Device ID and IP. Preserve projects, assignments and history.
- Enforce unique canonical IPs on inventory create/edit/address updates/duplication, with clear conflict messages. Preserve existing inventory during upgrade/restore.
- Keep duplication atomic, preserve rejected form values and prevent duplicate submissions or dismissal during a save.

### Build 91 — v0.5.5

- Merge alphabetical Device ID ordering for Permanent inventory and search results into main, with case-insensitive natural numeric sorting before pagination.
- Verify with all 228 backend tests plus dashboard, connection recovery and responsive host-view checks.

### Build 90 — v0.5.4 (inventory Device ID ordering branch)

- Sort Permanent inventory and its search results alphabetically by Device ID, ignoring case and using natural numeric ordering before pagination.

### Build 89 — v0.5.4

- Merge signed-in-only Status Dashboard Live Hosts into main. Anonymous visitors retain public issue lists and branding but receive no live hosts/readings or host controls.
- Preserve signed-in display preferences and clear private host data after session loss/logout, including stale-response protection and cached layout cleanup.
- Verify with all 228 backend tests plus dashboard, connection recovery and responsive host-view checks.

### Build 88 — v0.5.3 (status live-host access branch)

- Restrict Status Dashboard Live Hosts and its controls to signed-in users; omit live devices/readings from anonymous API responses while preserving public issue lists and branding.
- Preserve signed-in display preferences and clear rendered/cached host data after session loss or logout. Reject stale pre-logout responses.
- Retain live-host access for Admin, Operator and View Only accounts after any required password change.

### Build 87 — v0.5.3

- Merge the README corrections and Admin project setup improvements into main, including the bordered top configuration area, automatic selection of new projects, collapsible assignments and acknowledgement defaults for new projects.
- Include compact stacked save toasts with individual countdowns, resolved-issue search with ten-item pages, and per-device names for library services copied into inventory defaults.
- Release as v0.5.3 and advance the displayed build. Verify with all 226 backend tests plus dashboard, connection recovery and responsive host-view checks.

### Build 86 — v0.5.2 (Admin project configuration updates)

- Allow naming a library service's copy when adding it to a permanent inventory device's defaults; future assignments inherit the chosen name without renaming the library or existing project services.
- Prefill the library name, preserve custom drafts during refresh/errors, validate names and reset after a confirmed add.

### Build 85 — v0.5.2 (Admin project configuration updates)

- Show the ten most recently recovered resolved issues by default and add a search field with Clear search.
- Search all resolved issues in the current deployment, including older matches beyond the dashboard snapshot limit, with ten-result pages and recovery-time ordering.
- Preserve search/page during live refreshes, reject stale replies and enforce authenticated, bounded, indexed reads.

### Build 84 — v0.5.2 (Admin project configuration updates)

- Rename the first Project configuration heading from Projects to Add Project.

### Build 83 — v0.5.2 (Admin project configuration updates)

- Narrow save-confirmation toasts to 320px while retaining small-screen fitting, stacking and individual countdowns.
- Remove the unacknowledgement success toast; retain inline confirmation and live issue-list updates.

### Build 82 — v0.5.2 (Admin project configuration updates)

- Stack save-confirmation toasts at the top right, newest first, with independent six-second lifetimes and close buttons.
- Add a countdown progress bar to each toast without restarting existing bars when new confirmations arrive; support reduced-motion preferences.

### Build 81 — v0.5.2 (Admin project configuration updates)

- Move save-confirmation toasts to the top right and add a rounded outer border around the whole Project configuration area, matching the Live Hosts panel.

### Build 80 — v0.5.2 (Admin project configuration updates)

- Move Project configuration to the top controls and display its area above Active issues, coordinated with the lower configuration tabs. Keep paused monitoring button text white.
- Select newly created projects without activating monitoring, preserving the selection through stale refreshes. Default new projects to allowing signed-in Admin/Operator status acknowledgements; retain existing project settings.
- Add a collapsed assignment device list and dismissible save-confirmation toasts while retaining inline messages.

### Build 79 — v0.5.2 (README capability review branch)

- Correct outdated README limitations for hysteresis, flap protection, reminders, project duplication, inventory defaults, Modbus gateways and synthetic load testing.
- Document recovery hysteresis and flap protection; update delivery behaviour to reflect implemented reminders and retain genuine outstanding limitations.

### Build 78 — v0.5.2

- Merge the service-history fix: alarm-setting edits retain graph continuity, while measurement changes create separately selectable versions with their original units/state labels.
- Preserve historical values/statuses and configuration-revision safeguards. Resumed deployments use the latest project service settings for new checks.
- Verify with all 223 backend tests and dashboard, connection recovery and responsive host-view checks.

### Build 77 — v0.5.1 (service history revisions branch)

- Keep graph history visible across alarm-setting edits using a separate measurement revision, while retaining configuration revisions for in-flight read and persistence safety.
- Separate measurement changes and allow selecting previous graph versions with their stored units/state labels. Preserve recorded values/statuses; table history includes all versions.
- Migrate existing test history to measurement 1 without scanning/rebuilding sample data, and include measurement definitions in backups and service deletion cleanup.

### Build 76 — v0.5.1

- Merge project deletion, deployment/date-range history and the subsequent responsive dashboard improvements into main.
- Add Modbus Holding (03)/Input (04) register selection across services, defaults, library transfers and backups, with compatible migration for existing installations.
- Clean scaled numeric display values, add library search/collapse, reorder Admin configuration tabs and improve monitoring-status badges/header spacing.
- Validate with all 217 backend tests plus dashboard, connection recovery and responsive host-view checks.

### Build 75 — v0.4.4 (Modbus register types branch)

- Add bottom padding to the Admin page header so wrapped project/status badges remain clear of the logged-in user and navigation controls on narrow screens.

### Build 74 — v0.4.4 (Modbus register types branch)

- Move Project configuration before Permanent inventory in the Admin configuration tabs and keyboard order.
- Add searchable, collapsed-by-default library services with an expand/collapse arrow, match counts and Show 50 more, matching inventory behaviour. Preserve search and expansion during refreshes.
- Show the Admin header monitoring status as a green Active or yellow Paused bordered badge beside the project/deployment.

### Build 73 — v0.4.4 (Modbus register types branch)

- Format newly captured numeric readings to 15 significant digits for display, removing floating-point tails caused by scales such as 0.1. Both dashboards, history and notifications share the stored display text. Preserve raw numeric samples and threshold comparisons, and keep state labels unchanged.

### Build 72 — v0.4.4 (Modbus register types branch)

- Add Holding (03) and Input (04) register selection in the shared service editor, using the SNMP community field’s space for Modbus. Preserve protocol drafts and disable irrelevant fields.
- Carry the function through project services, inventory defaults, copies, project duplication, library format v3 and complete backups. Keep existing databases and older library imports on Function 03.
- Validate Modbus TCP response framing and exception replies; retain single unsigned 16-bit register reads and scaling.

### Build 71 — v0.4.4 (project deletion and history ranges branch)

- Prevent Pause/Resume card-control labels breaking into vertical letters. When the control pair cannot fit side by side, wrap Pause/Resume below Actions, keeping labels intact and controls right-aligned.
- Cap Admin Live Hosts at three card columns, reducing to two or one on narrower screens; leave Status Dashboard column counts unchanged.


### Build 70 — v0.4.4 (project deletion and history ranges branch)

- Automatically show Cards and temporarily disable List on both dashboards when the host list cannot fit its container. Explain the temporary mode and preserve the user's saved preference.
- Measure an inert copy of the list so List can return after resizing, service visibility/filter changes or content changes. Use a small restoration buffer to avoid flicker; keep narrow Cards within their container.
- Preserve connection-loss feedback during presentation-only status updates and keep measurement menus separate from live actions.


### Build 69 — v0.4.4 (project deletion and history ranges branch)

- Keep account actions right-aligned while they fit beside the user/presence badges; move Status Dashboard and Sign out onto a left-aligned row when space is insufficient.


### Build 68 — v0.4.4 (project deletion and history ranges branch)

- Remove the redundant Change password link from the Admin Dashboard's top navigation; retain Status Dashboard and Sign out.


### Build 67 — v0.4.4 (project deletion and history ranges branch)

- Left-align the wrapped Activate/Monitoring/Notifications group under the logo across the full toolbar width. Keep previous-deployment action placement unchanged.


### Build 66 — v0.4.4 (project deletion and history ranges branch)

- Move each complete deployment action group below its dropdown as soon as the buttons no longer fit alongside it. Re-evaluate on resize and button-label changes; preserve aligned dropdowns and narrow-screen wrapping.


### Build 65 — v0.4.4 (project deletion and history ranges branch)

- Add Admin-only confirmed project deletion with persistent background progress, bounded cleanup, restart/retry support and shared inventory/library preservation.
- Prevent deleting a running project; quarantine queued data and temporarily block configuration/backups while deletion is unfinished and restore while queued/running. Retain completed job metadata and never reuse deleted project IDs.
- Add history deployment selection, time presets and custom local date ranges up to 31 days. Use bounded graph summaries with preserved numeric extremes/gaps, state-transition handling and exact-reading table pagination.
- Keep range queries indexed and separate from the monitor lock, with bounded concurrency/work and stale-response protection. Preserve the legacy latest-200 API for older clients.


### Build 64 — v0.4.4

- Move build history and release notes from README.md into CHANGELOG.md, with a README link and updated release-maintenance instructions.


### Build 63 — v0.4.4

- Merge current-project selection and the Admin Dashboard logo placeholder into main.


### Build 62 — v0.4.3 (current-project selection branch)

- Fill the Admin Dashboard's reserved logo slot with a themed network icon and No project logo placeholder when the selected project has no uploaded image.


### Build 61 — v0.4.3 (current-project selection branch)

- Initially select the active deployment's project, then the paused deployment's project, then the first available project on the Admin Dashboard.
- Preserve valid manual project selections during refreshes; use the same fallback if a selected project becomes unavailable.


### Build 60 — v0.4.3

- Merge Admin Dashboard host sorting into main and release the matching Live Hosts controls.


### Build 59 — v0.4.2 (Admin host sorting branch)

- Add Sort hosts to the Admin Dashboard's Live Hosts controls, matching Status Dashboard choices: hostname in either direction, alias, host status in either direction and issue severity.
- Apply sorting to Cards and List views alongside service filtering; save the choice independently in browser storage for each dashboard.


### Build 58 — v0.4.2

- Merge dashboard connection-loss locking, automatic recovery and the reconnect popup refinements into main.


### Build 57 — v0.4.1 (dashboard connection recovery branch)

- Replace the reconnect spinner with three softly pulsing teal dots matching the app's accent colour, with a static reduced-motion presentation.


### Build 56 — v0.4.1 (dashboard connection recovery branch)

- Append Server connection lost to the Admin Dashboard's connectivity error text, and clear the full message automatically after recovery.


### Build 55 — v0.4.1 (dashboard connection recovery branch)

- Place the Status Dashboard's initial connection-loss notice directly below the top summary/error message.


### Build 54 — v0.4.1 (dashboard connection recovery branch)

- Add a rotating reconnect indicator to both disconnect popups, with a static indicator for reduced-motion preferences.


### Build 53 — v0.4.1 (dashboard connection recovery branch)

- Lock both dashboards with an app-styled connection-loss dialog after 30 seconds without a completed refresh. Existing readings remain visible as stale; controls unlock only after fresh data is rendered.
- Bound read requests and JSON bodies to eight seconds so hung connections cannot block polling retries. Writes have a 60-second deadline and are never automatically retried; new writes are blocked while offline.
- Clear connectivity notices and the Admin Dashboard's Failed to fetch message after recovery, preserving unrelated validation feedback and unsaved forms. Retry session initialization if the first load failed, and reconnect live updates after recovery.
- UI checks: `node tests/dashboard.test.mjs` and `node tests/connection.test.mjs`.


### Build 52 — v0.4.1

- Merge the acknowledged recovery correction and paused deployment defaults into main.
- Release the matching notification-pause pulse and dashboard control updates.


### Build 51 — v0.4 (acknowledged recovery fix branch)

- Pulse Resume notifications while global notification delivery is paused, matching paused monitoring and respecting reduced-motion preferences.
- Creating a deployment or selecting a previous deployment leaves monitoring and notifications paused. Explicitly choose Resume all monitoring to begin checks, then Resume notifications when ready.
- Preserve deployment history and individual host/service monitoring flags. The synthetic seeder explicitly resumes its disposable monitoring deployment for capacity testing.


### Build 50 — v0.4 (acknowledged recovery fix branch)

- Remove Unacknowledge from resolved issues while keeping acknowledgement attribution visible.
- Prevent the dashboard's unacknowledgement dialog submitting an issue that has recovered during review.


### Build 49 — v0.4 (acknowledged recovery fix branch)

- Automatically move recovered issues to Resolved even when acknowledged. Keep acknowledgement names, timestamps and audit history intact.
- Limit Acknowledged to unresolved issues on both dashboards; existing recovered records follow the corrected lists immediately, without a database migration.
- Preserve acknowledgement attribution and audit history in Resolved.


### Build 48 — v0.4

- Merge the verified history/polling performance improvements, synthetic test harness and active user/connection counts into main.
- Release the Raspberry Pi 5 load-tested monitoring changes and refresh-stable tab identity.


### Build 47 — v0.3.2 (load-test improvements branch)

- Keep dashboard connection identity in tab-scoped sessionStorage so refreshing or navigating between dashboards does not temporarily increase the count.
- If browser storage is unavailable, retain the existing per-page fallback and 60-second expiry.


### Build 46 — v0.3.2 (load-test improvements branch)

- Show Admins the number of distinct active logged-in accounts and dashboard connections, including anonymous Status Dashboard tabs.
- Refresh presence through normal dashboard polling; expire connections after 60 seconds without activity. Tabs count separately, while accounts are deduplicated across tabs/devices.
- Counts are approximate, process-local and rebuilt after restart; they are not a list of all unexpired logins. Revoked/expired/logged-out sessions do not count as logged-in users. No additional database writes or heartbeat requests are required.


### Build 45 — v0.3.2 (load-test improvements branch)

- Integrate the history-performance fixes verified on the Raspberry Pi 5: indexed current readings, bounded retention cleanup and efficient first readings after startup/resume.
- Preserve existing data; build missing history indexes once during startup, with progress logs. Large databases require additional free disk space and time for this upgrade.
- Include the isolated SNMP/Modbus simulator, capacity probe and regression tests. See [LOAD_TESTING.md](LOAD_TESTING.md) for setup and the measured results.


### Build 44 — v0.3.2

- Merge confirmed issue unacknowledgement, acknowledgement audit history and live acknowledgement updates into main.
- Match issue action button sizing across both dashboards.


### Build 40 — v0.3.1 (unacknowledgement branch)

- Synchronise acknowledgements between connected dashboards with server-sent invalidations, including separate users, browsers and machines.
- Match Acknowledge/Unacknowledge button sizing on both dashboards.
- Refresh through existing permission-checked APIs; keep polling as a fallback and serialize refresh requests to avoid stale response races.


### Build 39 — v0.3.1 (unacknowledgement branch)

- Admins and Operators can Unacknowledge issues through confirmed actions on both dashboards; the Status Dashboard follows the project's acknowledgement setting.
- Unresolved issues return to Active or Suppressed; recovered issues move to Resolved without reopening. Reminders restart after the configured interval and obey existing suppression settings.
- Preserve an immutable acknowledgement/unacknowledgement audit trail and reject stale confirmations from earlier acknowledgement cycles.


### Build 38 — v0.3.1

- Merge the UI polish branch into main and release the dashboard, editor and confirmation improvements.


### Build 37 — v0.3 (UI polish branch)

- Separate Configured Services details from Pause/Actions controls with more spacing and responsive alignment.
- Show Device ID alongside alias and address in Project Assignments.


### Build 36 — v0.3 (UI polish branch)

- Replace all remaining browser confirmations with app-styled dialogs for inventory/project removal, library/default changes, user deletion and backup restore.
- Show the selected target and consequences before approval; retain errors inline and prevent duplicate submissions.
- Successful backup restoration returns to sign-in because saved sessions are invalidated.


### Build 35 — v0.3 (UI polish branch)

- Replace browser service-removal confirmation with an in-app dialog identifying the host and service, retaining history and displaying errors inline.


### Build 34 — v0.3 (UI polish branch)

- Actions menus float over List rows without expanding or being clipped by them.
- Allow one Actions menu open across the app; close on outside clicks, action selection or Escape, and retain only that menu during polling refreshes.


### Build 33 — v0.3 (UI polish branch)

- Assign equipment lists only devices not already assigned to the selected project; removed devices remain available for reassignment.


### Build 32 — v0.3 (UI polish branch)

- Remove the redundant Selected services creation form from Project configuration; create reusable definitions in the library and apply them to hosts.
- Retain Configured services filters and management actions for existing project services.


### Build 31 — v0.3 (UI polish branch)

- Service forms disable SNMP community outside SNMP, and Modbus Unit ID outside Modbus, including when opening existing definitions.
- Switching protocols preserves unfinished input; saving with an irrelevant field disabled preserves its stored value.


### Build 30 — v0.3 (UI polish branch)

- Move Consecutive readings immediately to the right of Critical in the service editor.


### Build 29 — v0.3 (UI polish branch)

- Identify the host being edited in the flap-protection dialog by device ID and project alias.
- Rework service editing into a responsive grid with horizontal flap settings and grouped action buttons.


### Build 28 — v0.3 (UI polish branch)

- Extend Previous deployments to the toolbar's left edge while retaining its right-edge alignment with Selected project.
- Move Telegram Discover groups between Send recoveries and Save settings.
- Limit the Telegram log viewport to ten entries, with scrolling inside its bordered section.


### Build 27 — v0.3 (UI polish branch)

- Give each listed user a separate rounded border.
- Enlarge checkboxes to 24px across the app and align stacked checkbox headings with other form labels.
- Align project and previous-deployment selectors, with their action groups starting in the same column.
- Restore Sign out beside Admin Dashboard on public status for every signed-in role.


### Build 26 — v0.3

- Merged flap protection, recovery hysteresis, immutable issue readings, notification formatting and Telegram sample notifications into main.


### Build 25 — v0.2.3 (flap-protection branch)

- STABLE notifications match the flapping layout, showing the icon and current reading without a repeated severity or historical opening value.


### Build 24 — v0.2.3 (flap-protection branch)

- Telegram settings can send sample Critical, Warning, Recovered, Flapping, Stable, Host unreachable and Port Down notifications alongside the connectivity test.
- Samples share the live message renderer, use fictitious data, and obey global notification pause without creating real issues or deployments.


### Build 23 — v0.2.3 (flap-protection branch)

- Restore the warning icon at the start of flapping notifications.


### Build 22 — v0.2.3 (flap-protection branch)

- Flapping notifications explain that notifications for the affected check are suppressed until it stabilises.


### Build 21 — v0.2.3 (flap-protection branch)

- Flap-start notifications use four lines for project, host/alias, service/current reading, and issue/deployment numbers, without momentary severity or opening evidence.


### Build 20 — v0.2.3 (flap-protection branch)

- Match issue typography across both dashboards: body-sized values/states, normal-weight severity labels, and smaller timestamp/acknowledgement details.


### Build 19 — v0.2.3 (flap-protection branch)

- Recovery notifications show only the current value/state, omitting the original triggering value.


### Build 18 — v0.2.3 (flap-protection branch)

- Telegram delivery log has its own bordered section with a Show/Hide log button. It starts hidden on each page load and highlights the button while visible.


### Build 17 — v0.2.3 (flap-protection branch)

- Display issue values without the Triggered by prefix.
- Show Host unreachable for failed ping checks, including older issues, instead of internal exception names.


### Build 16 — v0.2.3 (flap-protection branch)

- Configurable host/service flap protection: default four confirmed changes in five minutes, clearing after five stable minutes. Ordinary alerts/reminders are suppressed during flapping; episode start/end notifications summarise the state.
- Optional recovery hysteresis in metric units; zero preserves existing thresholds.
- Issues retain the triggering value/state and units for dashboard display and opening notifications, independently of subsequent readings and retention. Legacy issues are backfilled only from matching retained opening history; otherwise their cause is marked unavailable.
- Service-library format v2 includes stability settings; v1 imports remain supported.


### Build 15 — v0.2.3

- Merged previous-deployment selection/resumption, safe deployment deletion and severity-coloured visual alerts into main.


### Build 14 — v0.2.2

- Status-page attention pulses are yellow for Warning issues and red for Critical/Unreachable issues.
- Critical takes priority for mixed arrivals; visuals remain active while notifications are globally paused.


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

### v0.4.4

- On Admin Dashboard load, select the active deployment's project, then the paused deployment's project, then the first available project. Resume all monitoring is immediately available for the selected paused deployment.
- Preserve valid manual selections during refresh and handle missing or empty project lists.
- Show a themed network-icon placeholder in the existing logo slot when the selected project has no logo, preserving toolbar alignment.


### v0.4.3

- Add the Status Dashboard's six host-sorting options to Admin Live Hosts: hostname in either direction, alias, host status in either direction and issue severity.
- Apply sorting in both Cards and List views alongside service filters, with an independent saved browser preference for each dashboard.


### v0.4.2

- Lock dashboard interaction after 30 seconds without a completed refresh, showing an app-styled reconnect popup while automatic retries continue.
- Bound stalled read requests and JSON bodies so polling can recover. Block new writes while locked and never automatically replay mutations.
- Unlock after fresh data renders, preserve unsaved forms, clear connectivity errors and recover from an initial failed session lookup.
- Clarify Admin Dashboard errors with Server connection lost, position the public status notice beneath the top error, and show softly pulsing teal reconnect dots with reduced-motion support.


### v0.4.1

- Move all recovered issues to Resolved, including acknowledged ones, while preserving acknowledgement attribution and audit history. Existing recovered records follow the corrected lists automatically.
- Remove Unacknowledge from resolved issues and reject dashboard submissions when an issue recovers during confirmation.
- Default new and selected previous deployments to paused monitoring and notifications. Use Resume all monitoring to begin checks, then Resume notifications independently.
- Pulse Resume notifications while delivery is paused, matching the monitoring control and respecting reduced-motion preferences.
- Preserve the v0.4 load-testing improvements; the benchmark seeder explicitly resumes its disposable deployment for measurement.


### v0.4

- Avoid full-history scans when loading dashboards, checking host dependencies and collecting fresh readings after startup/resume. Index retention cleanup and remove expired readings in bounded batches.
- Preserve existing data on upgrade. Missing history indexes are built once at startup with progress logs; large databases need additional disk space and startup time.
- Include an isolated two-machine SNMP/Modbus simulator and capacity harness. Raspberry Pi 5 tests passed for 150 hosts, 750 SNMP services, three HTTP users and seven days of generated history under healthy, timeout and flapping-value scenarios. See [LOAD_TESTING.md](LOAD_TESTING.md) for results and limitations.
- Show Admins distinct active logged-in accounts and dashboard connections, including anonymous status viewers. Normal polling updates counts; inactive connections expire after 60 seconds.
- Preserve connection identity across refreshes and dashboard navigation using tab-scoped storage. Separately opened tabs count individually; browser Duplicate Tab may copy the identity.


### v0.3.2

- Admins and Operators can unacknowledge issues through app-styled confirmation dialogs. Status Dashboard actions follow the project's acknowledgement setting.
- Preserve an acknowledgement/unacknowledgement audit trail, reject stale confirmations and restart reminder timing after unacknowledgement.
- Synchronise acknowledgement changes across dashboards and multiple users through server-sent invalidations, with polling fallback and serialized refreshes.
- Match Acknowledge/Unacknowledge button sizing on both dashboards.


### v0.3.1

- Add bordered user entries, larger consistent checkboxes and aligned project/deployment controls.
- Restore Status Dashboard sign-out for all signed-in roles; add a bounded, scrollable Telegram log and refine notification settings layout.
- Identify hosts in flap-protection dialogs and arrange service editing in a responsive grid. Disable protocol-specific fields when irrelevant while preserving stored values.
- Remove redundant inline service creation; filter equipment assignment choices to devices not already in the project. Improve service-control spacing and show Device ID in assignments.
- Float Actions menus in List view without growing rows; enforce one open menu with outside-click and Escape dismissal.
- Replace all remaining browser confirmations with app-styled dialogs that capture selected targets, retain errors inline and prevent duplicate submissions.
- After backup restoration, return to sign-in because sessions are invalidated.


### v0.3

- Added configurable host/service flap protection with durable detection, suppression of repeated alerts while flapping, and start/stable notifications.
- Added optional numeric recovery hysteresis, including negative readings such as RSSI. Stability settings travel with service libraries, inventory defaults and copied projects.
- Save the value/state that opened an issue independently of later readings or history retention, and display it consistently on both dashboards.
- Use readable Host unreachable messages. Recovery and stable notifications show current readings without the old trigger value; flapping alerts explain notification suppression.
- Added a bordered Show/Hide Telegram delivery log and selectable sample notifications for testing message layouts without creating real issues.
- Service-library exports use format v2; existing v1 library imports remain supported. Database upgrades preserve existing data.


### v0.2.3

- Added project-scoped deployment selection with start dates and descriptions, plus confirmed resumption of older runs.
- Preserve retained history and issue numbering when resuming; use current project configuration, require fresh checks and pause notifications.
- Added confirmed deletion of inactive deployments and their readings, issues, acknowledgements and related notification records while preserving other runs and configuration.
- Prevent reuse of deleted deployment/internal issue IDs to protect stale browser actions and in-flight polling.
- Status-page visual alerts pulse red for Critical/Unreachable issues and yellow for Warning issues, with critical priority and reduced-motion support.


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

