# Dashboard display

Issue/host ordering, presentation preferences, severity colours and responsive host views.

Current requirements. Read [AGENTS.md](../../AGENTS.md) first. The
[migration audit](MIGRATION.md) records the source of each section; anchor IDs
are navigation aids, not priorities.

Related areas: [Access, accounts and acknowledgements](access.md), [Monitoring and issue lifecycle](monitoring.md), [Dashboard connections and synchronization](connections.md), [Forms and shared layout](forms-layout.md), [Projects and deployments](projects.md).
Read the related rules affected by the task; these links do not load documents automatically.

<a id="r011"></a>

## Severity labels and host colours

- Display Healthy, Warning and Critical with initial capitals; keep stored status
  codes lowercase. Confirmed unresolved issues tint host cards by highest
  severity on both dashboards; acknowledged faults retain colour until recovery.
  Ignore suppressed child faults, stale checks and paused monitoring for card colour.

<a id="r012"></a>

## Host-only views

- Both dashboards can hide/show services for host-only Cards/List views. Persist
  this separately per dashboard in localStorage. Keep host details, issue
  severity colours and complete issue lists; presentation does not pause polling.

<a id="r013"></a>

## Views and service filters

- Both dashboards have Cards/List views and a case-insensitive substring service
  name filter (e.g. RSSI). Hide hosts without matching enabled services. Persist
  each dashboard's view/filter separately in localStorage; retain public show/hide.
  Filters affect host readings only; issue lists and severity rollups stay complete.
  Preserve role restrictions, history/actions, dependency states and row colours.

<a id="r014"></a>

## Main host-control position

- Main dashboard host display controls (Cards/List, service filter, All services
  and host count) sit after Resolved issues, immediately before the hosts.

<a id="r015"></a>

## Main issue-list order

- Both dashboards place active issues above hosts; on the main dashboard,
  acknowledged/suppressed/resolved sections also precede hosts.

<a id="r016"></a>

## Signed-in badge

- Keep the signed-in user label in its existing top-left navigation position;
  style it as a bordered, rounded badge without adding a fake button action.

<a id="r017"></a>

## Project-control alignment

- Align the main project dropdown with activation/pause buttons along the bottom;
  keep the polling note on its own line.

<a id="r018"></a>

## Logo reservation and status branding

- Reserve a fixed logo slot on the main project toolbar, including when no logo
  is assigned, so project controls stay in place. Public status stacks the project
  logo above the project name in the centre, with Network Status on the left.
  Stack branding beneath on narrow screens. Status navigation follows the control-row
  placement and mobile breakpoint rules below.

<a id="r020"></a>

## Public host sorting

- Public status supports persisted hostname/alias/host-status/severity sorting.

<a id="r023"></a>

## Issue order and shared button styling

- Both dashboards place active issues above hosts. List rows retain rounded
  card-like outlines, spacing and severity colours. Navigation/download anchors
  use the shared button-link appearance on login, main and public pages.

<a id="r024"></a>

## Host headings

- Monitor card headings use `Device ID - Alias`.

<a id="r067"></a>

## Visibility-button active state

Main dashboard section visibility buttons use the shared aria-pressed active
colour while their section is visible, including after restoring browser preferences.

<a id="r075"></a>

## Status host-control position

Status dashboard host display controls (Cards/List, sorting, services and filters)
sit immediately above hosts, below issue lists, and hide when hosts are hidden.
The Show/Hide hosts button stays accessible above the issue lists.

<a id="r076"></a>

## Status host-toggle state

The status Show/Hide hosts button sets aria-pressed to host visibility so the
shared active background follows toggles and restored browser preferences.

<a id="r079"></a>

## Inline version styling

Dashboard version labels use a muted 13px inline small.app-version beside the
main heading, following the AxisPy reference; do not render them at heading size.

<a id="r084"></a>

## Main Live Hosts panel

Main dashboard live hosts and all their display controls sit together inside a
rounded bordered panel, separate from issue lists. Edit alias sits in the host heading beside Device ID - Alias in Cards and
List views. List services use shared grid columns and fixed-width Pause/Resume
and Actions controls so varying names, values and labels do not shift buttons.

<a id="r085"></a>

## Main account navigation

Main account navigation keeps the signed-in badge left and groups Status Dashboard
and Sign out on the right, wrapping the action group on narrow screens. Do not
show a separate Change password link in the Admin Dashboard top navigation.

<a id="r088"></a>

## Status Live Hosts border

The status dashboard groups live hosts, display controls and filter helper text
inside a single padded rounded border, matching the Admin dashboard. Card grids
have 16px spacing below the helper text. Show/Hide hosts hides the entire bordered
panel; issue lists, their controls and the update timestamp remain outside it.

<a id="r089"></a>

## Live Hosts headings

Both dashboard live host panels have a Live Hosts heading above their controls,
inside the border, and it hides together with the panel.

<a id="r090"></a>

## Issue-row spacing

Admin issue lists use the shared metric row spacing and top separator border,
matching public status for active, acknowledged, suppressed and resolved issues.

<a id="r094"></a>

## Displayed issue numbers

Both dashboards display deployment-specific issue numbers on rows and acknowledgement
dialogs, matching Telegram/WhatsApp notifications. Internal IDs remain API keys.

<a id="r103"></a>

## Status navigation row

Status navigation (Admin Dashboard / Sign in / Change password) sits on the
same control row as acknowledged-issue and host visibility toggles, aligned
right with auto margin. The logged-in badge remains at the header top right.

<a id="r106"></a>

## Dashboard subtitle

The Admin dashboard subtitle is Project based network monitoring.

<a id="r109"></a>

## Attention-pulse eligibility and severity

Status attention pulses use yellow for new Warning issues and red for new
Critical/Unreachable issues, three cycles. Critical wins mixed arrivals and is
not downgraded by a warning arriving mid-pulse. Both visuals remain independent
of global notification pause; reduced-motion highlights use the same severity colour.
Trigger only for new active issues, not initial load or reappearing previously seen
issues. Track internal IDs/labels per deployment and preserve the seen set across
pause/resume. Reduced-motion mode uses a brief static highlight instead of animation.

<a id="r114"></a>

## Issue reading typography

Both dashboards use span.issue-value with identical 16px regular text for saved
issue readings, outside small metadata. Severity labels use normal-weight spans;
timestamps, recovery and acknowledgement details use small on both dashboards.

<a id="r133"></a>

## Issue-action styling

Row-level acknowledgement controls use class issue-action on both dashboards
with explicit 15px font, 20px line height and 4px/8px padding, including inside small metadata.

<a id="r148"></a>

## Admin host sorting

Admin Live Hosts has the same six sorting choices as public status. Persist under
field-monitor.main.host-sort independently from field-monitor.status.host-sort.
Use fresh ping status via readingStatus for ordering and server incident_status
for severity; numeric, case-insensitive hostname comparison breaks ties. Sorting
applies after filtering to both Cards/List and never changes issue/config lists.

<a id="r156"></a>

## Responsive host-view fallback

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

<a id="r157"></a>

## Host-control wrapping

Live host card controls must never break Pause/Resume labels letter-by-letter.
Use non-shrinking nowrap buttons and a wrap-reverse service-controls group so
Pause/Resume moves below Actions when space runs out. Keep list/catalogue layout
rules unchanged; use matching defensive card styles on both dashboard pages.

<a id="r158"></a>

## Main card-column limit

Admin #dashboard.grid is capped at three card columns using its minimum track
width, while auto-fit still reduces to two/one and fills space for fewer hosts.
Do not apply this three-column cap to the public Status Dashboard.

<a id="r179"></a>

## Narrow status controls

Status section controls group the acknowledged and host visibility toggles in
.status-visibility-controls. At viewport widths <=760px, stack those toggles in
that order and place .status-navigation below, left-aligned with no auto margin.
Keep this breakpoint independent of Show/Hide and Cards/List label widths to
prevent jumping rows. Desktop navigation remains on the right. Preserve IDs,
authenticated-only host access, toggle colours and localStorage preferences.
