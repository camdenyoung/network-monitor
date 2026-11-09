# Monitoring and issue lifecycle

Managed ping, persistence, revisions, pause/suppression, protocols and issue membership.

Current requirements. Read [AGENTS.md](../../AGENTS.md) first. The
[migration audit](MIGRATION.md) records the source of each section; anchor IDs
are navigation aids, not priorities.

Related areas: [Projects and deployments](projects.md), [Inventory, services and library](inventory-services.md), [History, backup and restore](history-backups.md), [Notifications](notifications.md), [Dashboard connections and synchronization](connections.md), [Dashboard display](dashboards.md).
Read the related rules affected by the task; these links do not load documents automatically.

<a id="r025"></a>

## Fresh host-ping dependency

- Services depend on a fresh healthy host ping. Poll ping first; suppress child
  polling/failure reports for offline, stale or unknown hosts. Preserve existing
  child issues as suppressed, without claiming recovery; resume on fresh reads.

<a id="r026"></a>

## Numeric metrics and state maps

- Services and library entries support numeric metrics or numeric state maps.
  State codes map to labels and healthy/warning/critical; unmapped codes warn.

<a id="r027"></a>

## Managed automatic ping

- Every assigned host gets automatic ICMP ping; no manually added service needed.

<a id="r043"></a>

## In-place service editing

- Services can be edited in place; retain identity/history and keep blank edited
  SNMP credentials unchanged. Built-in host ping stays managed by the application.

<a id="r044"></a>

## Issue list membership

- Active issues are open and unacknowledged; Acknowledged issues are open and
  acknowledged; Resolved issues are closed regardless of acknowledgement. An
  acknowledgement does not clear a fault and stays recorded after recovery.
  Apply the full list and dialog rules in R142.

<a id="r046"></a>

## Alarm behaviour

- Warning/critical thresholds, persistence, recovery, acknowledgement, retention.

<a id="r047"></a>

## Independent control flags

- Independent monitoring, visibility, notification controls.

<a id="r057"></a>

## Soft removal and durable IDs

Service removal disables the service and preserves ownership/history. Poll only
enabled services. Device deletion purges both active and disabled services.
Persistent ID counters in settings prevent ID reuse after deletion; use
next_record_id for device, assignment and service creation, including built-in ping.
The editor must retain failed edits and must not be overwritten by dashboard refresh.

<a id="r058"></a>

## Configuration revisions and secrets

Service configuration revisions isolate in-flight reads and persistence counts
when edited. Migrate revision fields on services/samples at startup and restore.
Never expose stored communities in state or service edit responses.

<a id="r060"></a>

## Value-type migration

migrate_value_types runs at startup/restore after ensuring the template table.
Keep value_type/state_map in every service/template create/edit/copy/apply path.
Samples retain numeric values and display labels as read. State modes use raw
codes (scale=1) and mapped severity, not numeric thresholds. SNMP uses -Oeqv to
request numeric enum codes. Use incident_lists for current reporting; issues
contains historical records which can include currently suppressed child faults.

<a id="r063"></a>

## Service pause, archived assignments and catalogue limits

Admin/Operator Pause/Resume is per-host service monitoring, separate from soft service
removal. monitoring_since invalidates queued reads and resets persistence without
changing the configuration revision. Log explicit paused/unknown gaps. Paused
services do not poll, colour hosts, report active faults, or send notifications.
Existing issues stay suppressed, not recovered. Copy/template instances start
independent and enabled.
Removing a device from a project sets assignments.removed=1 and disables its host
monitoring/display. Preserve inventory, other projects, configuration and history.
Exclude archived assignments from polling, current issue lists, selectors and
service targets. Reassign restores the original assignment and invalidates stale
readings. Permanent inventory deletion still purges archived records too.
The configured-service manager starts with no host selected. Filter by host (or
All hosts), name/OID, protocol and monitoring state. Render at most 20 initially
with an explicit Show more; preserve filter choices during background refreshes.

<a id="r110"></a>

## Flap protection and immutable opening evidence

Flap protection lives in app/stability.py. Per-check settings travel through library,
inventory defaults, copies and project duplication. Defaults: enabled, four confirmed
changes within five minutes, five continuous stable minutes to clear; hysteresis zero.
Runtime is durable and scoped to run/service/revision/monitoring_since. Gaps and blocked
reads cannot count as stable. Suppress ordinary alerts/reminders while flapping;
unique episode start/end events use the durable outbox and obey global notification pause.
Opening issues store immutable trigger_value/display/units/timestamp/error. Show these
on both dashboards and use them in opening notifications. Never replace historical
cause with a later sample or edited state mapping. Legacy missing evidence stays unknown.

<a id="r111"></a>

## Readable saved issue values

Display recorded issue values without a Triggered by prefix. Ping failures display
Host unreachable on both dashboards and notifications, including older saved issues;
retain internal exception classes for diagnostics, not the host-facing state.

<a id="r142"></a>

## Recovery precedence and stale dialogs

Recovery takes precedence over acknowledgement for issue list membership:
Active = open/unacknowledged; Acknowledged = open/acknowledged; Resolved = closed,
regardless of acknowledgement. Retain acknowledgement attribution, revision and
audit history on recovery. Public status consumes the same open-only acknowledged
list; recovered entries disappear there (no new public history section). No data
migration is needed: existing recovered/acknowledged records route to Resolved.
Resolved issues display acknowledgement attribution but no Unacknowledge button.
Only unresolved acknowledged issues can open/confirm that dashboard dialog. If
recovery arrives while the dialog is open, reject submission and request review.

<a id="r159"></a>

## Modbus function and protocol validation

Modbus TCP services have a separate modbus_function field, limited to 3 or 4.
The shared editor reuses the community slot: SNMP shows the community password,
Modbus shows Holding (03)/Input (04), TCP hides both. Disable irrelevant controls
without clearing drafts. Persist the function through all shared configuration
paths. migrate_modbus_functions defaults legacy service/template/device-default
rows to 3 on startup/restore. Library format v3 exports it; import v1/v2 remains
accepted with default 3. Validate MBAP identity, unit, length, function and byte
count; handle exception/truncated responses without treating them as readings.
Keep the TCP-to-RTU gateway transport on port 502 and existing unsigned single
16-bit scaling. Test protocol framing and migration in tests/test_modbus.py.

<a id="r160"></a>

## Numeric display precision

Numeric display_value uses 15 significant digits to remove binary scaling residue.
Keep raw sample values and threshold/persistence calculations unchanged; state labels
remain authoritative. Existing recorded history/evidence is not rewritten.
