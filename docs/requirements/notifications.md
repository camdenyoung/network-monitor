# Notifications

Provider roles, reminders, global mute, message formats and safe sample sends.

Current requirements. Read [AGENTS.md](../../AGENTS.md) first. The
[migration audit](MIGRATION.md) records the source of each section; anchor IDs
are navigation aids, not priorities.

Related areas: [Monitoring and issue lifecycle](monitoring.md), [Projects and deployments](projects.md), [Access, accounts and acknowledgements](access.md), [Forms and shared layout](forms-layout.md).
Read the related rules affected by the task; these links do not load documents automatically.

<a id="r039"></a>

## Provider scope

- Telegram group notifications and optional WhatsApp Business Cloud API templates.
  WhatsApp Business does not connect ordinary app-created groups; Telegram is the
  intended shared group route. Both providers have separate settings and queues.

<a id="r092"></a>

## Issue reminder cadence

Admins configure a shared Telegram/WhatsApp issue reminder interval under Settings → Issue
reminders (0 disables, default 0; otherwise 1–10080 whole minutes). Repeat only
active, unacknowledged issues with fresh matching fault readings. Respect project
activation, host dependency, monitoring/removal and notification flags. Recheck
eligibility before delivery. The durable outbox tracks per-channel cadence, with
at most one pending/in-flight reminder per issue/channel and no restart catch-up
bursts. Reminder settings are included in database backups.

<a id="r095"></a>

## Notification severity icons

Telegram and WhatsApp Business issue notifications start with severity icons:
✅ recovered, ❌ critical/unreachable, ⚠️ warning. Reminders retain the severity
icon and explicit REMINDER label; keep the text status for clarity.

<a id="r101"></a>

## Global notification pause

Admin Pause/Resume notifications is a separate global toggle beside monitoring.
It gates both providers, tests, retries, initial/recovery alerts and reminders,
without modifying provider/host configuration, polling or issues. Persist the
mute setting in SQLite. Cancel pending alerts on pause and do not queue events
while muted. Resume restarts reminder cadence without replaying a backlog.
An HTTP send already in flight at the time of pause cannot be recalled.

<a id="r102"></a>

## New-deployment notification state

Starting any new deployment always pauses global notifications and cancels pending
alerts in the same transaction. Explain this in the start confirmation dialog.
Admins must explicitly Resume notifications for the new deployment. Resuming an
existing deployment preserves the current global notification state.

<a id="r112"></a>

## Telegram delivery-log visibility

Telegram delivery log is wrapped in its own bordered section. Show/Hide log
starts hidden on every page load; reflect visibility with aria-expanded and
aria-pressed plus the standard green active button. Data refresh preserves visibility.

<a id="r113"></a>

## Recovery message readings

Recovery notifications include only the current reading/state, never the original
triggering value. Opening evidence remains available in issue records and reminders.

<a id="r115"></a>

## Flap-start message format

Flap-start notifications begin with four lines: ⚠️ FLAPPING - project; host - alias;
service: current value/units; Issue #n - Deployment #n. Omit the momentary severity
and historical opening value from that notification.

<a id="r116"></a>

## Flap suppression explanation

Append Notifications for this check are suppressed until it stabilises. to
flap-start notifications, making the scope of temporary suppression clear.

<a id="r118"></a>

## Provider sample notifications

Telegram sample selector sends connectivity, critical, warning, recovery, flapping,
stable, host-unreachable and port-state examples through the existing Admin/CSRF
protected test endpoint and durable outbox. Use sample_notification and the same
format_issue_message renderer as live events; fictitious data never creates issues,
samples or deployments. Respect saved provider settings and global notification
pause. Test outbox rows have no incident and bypass real-check suppression. Reject
unknown sample types before queueing; old callers default to connectivity test.

<a id="r119"></a>

## Stable message format

STABLE notifications match the four-line flapping layout with icon, project,
host/alias, current service reading and issue/deployment numbers. Do not append
HEALTHY or other severity to the heading, or the historical opening value.
