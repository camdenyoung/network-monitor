# Forms and shared layout

Draft preservation, confirmations, accessible configuration, responsive toolbars and shared styles.

Current requirements. Read [AGENTS.md](../../AGENTS.md) first. The
[migration audit](MIGRATION.md) records the source of each section; anchor IDs
are navigation aids, not priorities.

Related areas: [Access, accounts and acknowledgements](access.md), [Projects and deployments](projects.md), [Inventory, services and library](inventory-services.md), [Dashboard connections and synchronization](connections.md), [Dashboard display](dashboards.md).
Read the related rules affected by the task; these links do not load documents automatically.

<a id="r028"></a>

## Add-form feedback

- Successful add forms show inline confirmation and reset; errors preserve input.

<a id="r061"></a>

## Actions menus and history views

Service monitor cards use a compact Actions menu with the viewport-fixed floating
panels and unique restoration keys specified in R127. Retain open menu state
during background refreshes; close on choosing an action.
History supports graph/table views over selected deployment/time ranges (legacy API retains latest 200). Numeric graphs
use lines; states use labeled steps. Preserve explicit/long gaps; never connect
readings from different measurement versions. Alarm-only edits keep compatible graph continuity. No external chart dependencies.
Optional UI logic checks: `node tests/dashboard.test.mjs` (Node 18+).

<a id="r064"></a>

## Project editor and inventory drafts

Edit selected project uses separate responsive panels for name, event logo,
status-page settings and duplication. Keep stable form IDs, inline checkbox
alignment, current-logo preview and consistent bottom-aligned actions. Background
refresh must not replace unfinished form edits.
Permanent inventory is collapsed by default and searchable by ID/name, model or
IP. Searching expands it, with 50 initial results and explicit Show more. Preserve
open/search state during refresh; don't render the whole inventory while collapsed.

<a id="r073"></a>

## Exclusive configuration areas

Main dashboard configuration sections are exclusive. Project configuration has
its own top disclosure button and bordered region above Active issues (R161/R165).
Other areas use lower colour-coded tabs for inventory, library, users, Settings,
providers and backups. Keep the legacy reminder-panel/tab IDs for Settings.
These panels start hidden on page load. Selecting a tab shows only that configuration
area, without hiding issue/live host sections; selection is not persisted.
Issue-list and live-status visibility preferences remain separate. Preserve the
accessible tab keyboard and close/reopen behaviour in R099/R100.

<a id="r091"></a>

## Acknowledgement confirmation

Both dashboards require a confirmation popup before acknowledging an issue.
Cancelling sends no acknowledgement request; confirming preserves existing role,
CSRF and status-project acknowledgement restrictions.

<a id="r093"></a>

## Styled acknowledgement dialog

Acknowledgement confirmation on both dashboards uses a styled in-app dialog,
not window.confirm. Show the target issue, explicit Acknowledge issue and Cancel
buttons, inline errors, and matching dark panel/backdrop styling. Opening or
cancelling sends no request; disable repeat submits while saving.

<a id="r099"></a>

## Accessible configuration tabs

Admin configuration areas are exclusive accessible tabs with arrow/Home/End
navigation and active colour. Keep unfinished forms intact when switching areas.
Status attention uses the new-issue tracking and severity-matched, reduced-motion
rules in R109, including preserving the seen set across pause/resume and excluding
initial load or previously seen/reappearing issues.

<a id="r100"></a>

## Closing a selected configuration tab

Clicking the selected configuration tab closes its panel, allowing all config
areas to be hidden. Other tabs switch areas. Preserve the keyboard tab stop and
unsaved form values when closing/reopening.

<a id="r120"></a>

## Checkboxes, selectors and status sign-out

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

<a id="r121"></a>

## Selector span and Telegram controls

Previous-deployment dropdown spans the logo and project-selector columns so it
starts at the toolbar's left edge and ends at Selected project's right edge.
Keep its action group in the shared next column. Telegram Discover groups sits
inside the settings form between Send recoveries and Save settings; type=button
must prevent accidental saves. Telegram delivery log keeps the newest ten
single-line 40px entries visible (400px maximum), with keyboard-accessible vertical
and horizontal scrolling inside its border for older entries and long text.

<a id="r127"></a>

## Floating Actions menus

Actions menus use viewport-fixed floating panels in Cards, List and configured
services, escaping list scroll clipping without growing rows. One menu may be
open globally; outside clicks, action selection, Escape, page/list scroll and
resize close it. Escape restores trigger focus. Internal menu scrolling remains
usable. Polling restores only a unique location:service key, never both live and
catalogue occurrences; clear it if the target disappears. Keep popup within the
viewport, opening upward near the bottom. Other details elements are unaffected.
The Actions summary uses the same opaque control background and hover colour as
Pause/Resume buttons, including on tinted host cards and in List/catalogue views.
Host flap-protection buttons use the compact Actions sizing in Cards and the shared
service-control sizing in List view; retain their neutral text and existing action.

<a id="r129"></a>

## Administrative confirmations

All destructive/replacement confirmations use app-styled dialogs; no native
confirm/alert/prompt calls remain. The shared administrative confirmation captures
IDs or the actual backup File before approval, uses textContent for target labels,
keeps Cancel focused, blocks duplicate saves/closing in flight and retains API
errors inline. Success refresh failures must not imply the mutation failed.
Covers device deletion, project removal, library deletion, default deletion/adoption,
user deletion and backup restore. Preserve server-side Admin/CSRF/last-admin checks.
Restore invalidates sessions; after success return to login, not authenticated refresh.

<a id="r153"></a>

## Project-toolbar fit measurement

Admin project toolbar measures complete button groups against the shared action
column's available width. If the three project actions do not fit, move the whole
group below Selected project. Independently move both previous-deployment actions
below their dropdown if they do not fit. Keep groups nowrap until moved; allow
narrow-screen wrapping afterward. ResizeObserver watches toolbar/buttons and
refresh/resize also update placement; no fixed desktop breakpoint or DOM moves.
Preserve logo reservation, dropdown edges, button listeners and keyboard order.

<a id="r154"></a>

## Wrapped project-action alignment

When the project action group moves below, span the full toolbar and align its
left edge under the logo. Preserve the previous-deployment action placement.

<a id="r155"></a>

## Account-navigation fit measurement

Account actions stay right-aligned when they fit beside visible user/presence
badges. Otherwise move the complete group to a full-width left-aligned row.
Measure button/badge widths, observe nav and label changes, and handle non-Admin
hidden presence badges. Do not allow auto left margin to right-align a wrapped row.

<a id="r161"></a>

## Project panel, library search and run badges

Admin Project configuration is above Active issues, below its top control button.
Keep its button outside lower-tab arrow-key navigation; coordinate exclusive visibility. Reusable service library mirrors inventory
with collapsed-by-default details, case-insensitive name/protocol/target/units search,
auto-expand on searching and 50-entry Show more. Preserve query/open/limit on refresh,
and retain library create/import/export and row actions. Header status uses separate
green Active/yellow Paused bordered badges before project/deployment text.

<a id="r162"></a>

## Header spacing

Admin body > header reserves 18px bottom padding before account navigation.
Keep project/status badges clear of logged-in user controls when the header wraps.

<a id="r165"></a>

## Project-panel border

Keep the full Admin #project-configuration region inside one rounded border with
16px padding, matching the Live Hosts panel. Preserve the nested section borders.

<a id="r166"></a>

## Independent save-toast timers

Save confirmations stack newest-first in #save-toasts. Insert only the new item;
never rerender existing toasts (which would restart progress animations). Each has
its own timer/ID, close button and CSS countdown tied to SAVE_TOAST_DURATION.
Dismissal/expiry removes only that item and clears its timer; hide the container
when empty. Populate message spans via textContent. Cap the stack viewport height
and allow scrolling; use stepped countdowns under prefers-reduced-motion.

<a id="r167"></a>

## Toast size and unacknowledgement feedback

Toast stacks use a compact 320px width, shrinking to fit narrow viewports.
Unacknowledgement keeps inline issue feedback and list updates without a toast.

## Confirmed action feedback

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

<a id="r180"></a>

## Stylesheet ownership and preview boundaries

Stylesheets: app/static/css/base.css centralises shared theme variables and controls,
issue/host components, tables, navigation links and connection indicators. Load it
before dashboard.css/status.css/auth.css, which own only differing page layouts.
Keep readable four-space declarations/comments. Static body widths use .auth-page;
keep truly dynamic toast CSS variables, graph values and popup positioning in JS.
No Bootstrap/CDN/build pipeline is required. STYLESHEETS is a fixed server allowlist;
serve CSS publicly before auth, with text/css, no-store and nosniff. Never turn it
into arbitrary filesystem serving. Update versioned link queries when CSS changes.
Existing UI tests load
CSS explicitly for style assertions. Asset tests cover allowlisting, traversal,
MIME/cache headers and all page links. tools/style_preview.py and tests/style_matrix.html
compare the pre-refactor commit with the working tree using identical deterministic
CSS-only fixtures: eight viewport widths, roles, hosts/issues, panels/dialogs and
account pages. Computed-property/bounding-box equality supplements functional tests;
it does not test authorization or all real-world combinations. Never point the preview
at a live database; it binds loopback only. Coordinate handover for native browser
interaction; prefer the isolated in-app browser for previews.

Service Pause/Resume, Actions and host flap-protection controls keep the same 13px
text, 18px line height and compact padding in Cards, List and configured-service
views. Centre the Actions label and geometric disclosure marker together; retain
native details/summary keyboard behaviour and open-menu positioning.
