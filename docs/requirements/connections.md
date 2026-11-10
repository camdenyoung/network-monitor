# Dashboard connections and synchronization

Stream admission, duplicate tabs, coalescing, lifecycle and connection recovery.

Current requirements. Read [AGENTS.md](../../AGENTS.md) first. The
[migration audit](MIGRATION.md) records the source of each section; anchor IDs
are navigation aids, not priorities.

Related areas: [Access, accounts and acknowledgements](access.md), [Monitoring and issue lifecycle](monitoring.md), [History, backup and restore](history-backups.md), [Forms and shared layout](forms-layout.md), [Dashboard display](dashboards.md).
Read the related rules affected by the task; these links do not load documents automatically.

<a id="r132"></a>

## Public invalidation stream

Issue acknowledgements and committed operational changes publish an opaque revision through /api/ack-events SSE
only after mutate commits; rejected actions and duplicate no-op acknowledgements
do not emit. No issue/actor/account data travels over this public stream. Each
browser fetches its existing role-filtered API data. Connect on load/reconnect,
refresh on visibility/focus, close on pagehide and reconnect on cached pageshow.
Keep 10-second polling fallback. Coalesce/serialize refreshes and fetch once more
when an event arrives in flight, preventing stale responses overwriting changes.
Condition waits hold no SQLite connection or monitor lock; heartbeat every 15s,
flush events immediately and disable reverse-proxy buffering via response header.

<a id="r138"></a>

## Account presence and actual stream capacity

Dashboard presence lives in app/presence.py. Main and public status polling carry
an opaque per-tab X-Dashboard-Connection ID. Presence entries distinguish tabs,
including anonymous viewers, from distinct active authenticated accounts. Expire
entries at 60 seconds using monotonic time; cap at 4,096. Validate session CSRF IDs
against current nonexpired sessions before counting users. Never expose IDs/tokens
or counts on public/status or non-Admin state responses. No new DB writes or
session-lifetime extension. Presence rebuilds after restart and supplies the
approximate distinct active-account count and Admin-only User management Online badges.
/api/users includes only an online boolean per account, based on the same 60-second
window and current valid sessions; never expose session tokens or connection IDs.
Refresh badges through existing polling; preserve account editor drafts. Absence of
a badge means no recent dashboard activity, not necessarily that no session exists.

The Admin top-navigation badge shows actual admitted live-update streams from
app/connections.py as current/limit, separately from active accounts. Polling-only
tabs do not count as admitted streams. Default dashboard_connection_limit=20,
Admin/CSRF configurable 1–200 in Settings (legacy reminder-panel/tab IDs), alongside
issue reminders. Preserve drafts and the setting on restart and backup/restore;
legacy databases get the default. Lowering the limit retains existing streams.
Overflow receives 503; both dashboards close failed EventSources and retry via
normal refresh/focus after 30 seconds, retaining ten-second polling. Stream slots
always release in finally. Ordinary requests have a separate pre-thread limit of
32 and 30-second socket inactivity timeout, preserving sign-in/Admin capacity even
with full stream slots. Counts and settings remain Admin-only; anonymous streams
consume capacity normally.

<a id="r139"></a>

## Refresh-safe stream handover

Key /api/ack-events streams by the validated optional connection query
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

<a id="r140"></a>

## Duplicate-tab coordination

Resolve BroadcastChannel conflicts throughout the document lifetime,
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
limit and leave browser-level stream sharing outside the current implementation scope.

<a id="r141"></a>

## Per-tab connection identity

Store dashboard connection identity under network-monitor.dashboard-connection
in sessionStorage on both dashboards. Reuse it on reload/navigation, validate
stored values, and fall back to a temporary ID if storage is unavailable. Do not
use shared localStorage (which would merge separate tabs).

<a id="r144"></a>

## Connection recovery guard

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

<a id="r145"></a>

## Reconnecting indicator

Both disconnect dialogs show three softly pulsing teal dots next to Reconnecting
automatically, using the app accent colour. Animate only while the dialog is open;
show static dots under reduced motion. Keep decorative dots aria-hidden and retain
accessible status text.

<a id="r146"></a>

## Status connection-notice position

Status Dashboard connection-notice sits immediately below summary near the top,
so the initial retry notice appears beneath Failed to fetch before issue/host lists.

<a id="r147"></a>

## Connection error annotation

Admin report appends — Server connection lost only for errors recorded by the
connection guard. Recovery clears both the original and annotated error messages.

<a id="r186"></a>

## Operational update signals

Use app/live_updates.py publish_dashboard_change for deployment
activation/resume/renaming/deletion, monitoring pause/resume, notification pause/resume,
individual service pause/resume and assignment monitoring/visibility/notification
flags. Publish only after the mutation transaction commits; no-op controls, rejected
requests and rollbacks emit nothing. Keep /api/ack-events and browser handler names
compatible: the stream is now a general dashboard invalidation, still only an opaque
revision. Reuse the existing coalescing, reconnect/focus and 10-second polling fallback.
Do not change metric polling, role scope or Admin local configuration selection.

<a id="r187"></a>

## Polling-driven issue signals

Also signal committed polling-driven issue open/close/severity and
flap transitions through live_updates.publish_monitoring_change. Signal only after
the write transaction/monitor lock exits; blocked, unconfirmed, invalidated and
rolled-back reads do not emit issue-change events. Keep existing persistence,
polling cadence, evidence, acknowledgements and provider notification rules.
Existing SSE waiters coalesce monitoring bursts for at most one second, without
timers or new worker threads; capture their pending deadline so sustained changes
cannot postpone delivery. Interactive publish_dashboard_change clears the delay,
and cancellation wakes immediately. Keep ordinary readings quiet and ten-second
polling as fallback; global provider mute never gates dashboard synchronization.

<a id="r188"></a>

## Accepted synchronization timing

The user accepts an occasional one-second acknowledgement/operational refresh delay when a monitoring event
follows an immediate event before a listener wakes. Preserve that accepted timing
unless asked to change it; committed actions and monitoring data are unaffected.
