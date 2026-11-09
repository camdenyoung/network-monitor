# History, backup and restore

Bounded historical queries, measurement versions and disk-backed backup/restore.

Current requirements. Read [AGENTS.md](../../AGENTS.md) first. The
[migration audit](MIGRATION.md) records the source of each section; anchor IDs
are navigation aids, not priorities.

Related areas: [Access, accounts and acknowledgements](access.md), [Projects and deployments](projects.md), [Monitoring and issue lifecycle](monitoring.md), [Inventory, services and library](inventory-services.md), [Dashboard connections and synchronization](connections.md).
Read the related rules affected by the task; these links do not load documents automatically.

<a id="r077"></a>

## Product identity and backup filenames

The product name is Network Monitor. Retain legacy field-monitor localStorage keys
to preserve browser preferences. Complete backup downloads use a server-generated
network-monitor-backup-YYYY-MM-DD_HH-MM-SS.sqlite3 filename via Content-Disposition,
using the monitoring host local timezone. Compose mounts /etc/localtime read-only
from the host so container time follows the host, including daylight saving.

<a id="r136"></a>

## Current-reading indexes and retention

History performance: ensure_sample_indexes runs through lifecycle migration on startup
and restore. sample_current supports service/run/revision/latest-ID lookups;
sample_expiry supports bounded retention. Snapshot uses one indexed latest-ID lookup
per service, respecting revision and monitoring_since. host_is_up resolves ping first.
Never group all samples for live state. prune_samples removes at most 1,000 expired
rows per polling cycle, so retention reductions drain gradually. First index creation
on large existing databases takes time and disk space; logs identify each build.

<a id="r137"></a>

## Fresh-read lookup bounds

current_samples handles fresh-read gaps after resume: fetch the latest N IDs first,
then fall back to sample_lookup's timestamp range if pre-resume rows are present.
Use it for snapshot, host dependency and persistence checks. Never fill a limit by
scanning all pre-resume history. Keep latest-ID semantics for out-of-order imports.

<a id="r152"></a>

## Bounded range history

History ranges: app/history.py validates service/run project ownership, finite
start/end and a 31-day maximum. Query sample_lookup in timestamp-keyed batches
without LOCK, cap concurrency at four and graph work at 20s. Short graphs <=2,000
points are exact; numeric summaries retain first/last/min/max in 300 buckets.
State transitions are exact until the cap, then explicitly flag summary overflow.
Segment IDs preserve invalid/missing/measurement gaps; aggregated points must not
create false gaps just because points are farther than 60s apart. Table mode uses
200 exact readings per page with timestamp/id cursors. Keep the legacy no-range
API response for older clients. Browser history GET timeout is 30s; other reads
remain 8s. Dialog presets/custom datetime-local ranges use browser timezone and
all project deployments, including paused/previous runs. Request tokens reject
stale/closed-dialog responses; graph and exact table use the same interval.

<a id="r163"></a>

## Measurement revisions and history

Service history uses measurement_revision independently of the existing revision.
Every service edit still increments revision to invalidate in-flight reads and
reset persistence safely. Only kind/target/scale/units/value_type/state code/label
changes (plus unit/function for Modbus) increment measurement_revision. Credentials,
alarm limits/direction, persistence, flap rules and state severities do not.
Samples record both IDs, including pause markers. history.ensure_tables migrates
startup/restore with default 1, without rewriting old samples. Old test history is
intentionally one measurement; no reconstruction of unknown past settings.
Before a measurement change, remember its non-secret definition in service_measurements
(FK cascade with service deletion). Current definition comes from the service row.
Range graph queries filter measurement before aggregation; graph UI offers previous
versions with their stored units/type/maps. Exact table includes every version.
Historical statuses/values remain recorded; current thresholds overlay only the
current version. Keep bounded queries, retention, stale-read guards and backups.

<a id="r168"></a>

## Resolved-issue search

Admin Resolved issues displays the latest 10, ordered by closed DESC/id DESC.
Keep snapshot's bounded 200-row list for compatibility. app/resolved.py supplies
an authenticated /api/resolved search across all eligible resolved issues in the
current active deployment, 10 per page with closed/id cursors, literal Unicode
casefold matching and no monitor LOCK. Scope by active_run, non-removed assignment
and enabled service. Retain display-name enrichment and legacy ping evidence text.
Install the partial resolved_issue_lookup index on startup/restore. Bound query work
to 3s and four concurrent searches. UI retains filter/page on refresh, debounces
input and rejects stale responses when query/deployment changes. Clear returns to
latest 10. No acknowledgement actions or new notifications are introduced.

<a id="r181"></a>

## Restore rejection and error feedback

Reject oversized restore Content-Length with HTTP 413 and an explicit
configured-limit message before reading the body. Use the current disk-based
implementation and MONITOR_MAX_RESTORE_MB limits in R182; other payload limits
remain unchanged. Preserve database format, integrity checks, role/CSRF checks,
migrations and paused/session-invalidating restore. Admin restore confirmation
displays server error text or an HTTP/proxy fallback, not a misleading backup-format
message for every failure. Multiple installations on the same hostname/IP share
cookies across ports; compare using separate browser profiles or normal/Incognito
contexts, not simultaneous logins in one cookie context.

<a id="r182"></a>

## Disk-backed backup and restore

Backup/restore uses app/backups.py disk workspaces on
DB.parent (0700 directories), 1 MiB HTTP chunks and small SQLite caches/temp files.
GET /api/backup defaults complete; ?kind=configuration copies only allowlisted
configuration rows into fresh schema via read-only ATTACH, never reading history
rows. Retain users/credentials, devices/assignments/aliases, service settings,
defaults/library, provider config and logos. Exclude samples/runs/issues/audits/
measurements/outbox/flap/deletion jobs/sessions/login attempts. Keep durable ID
counters; configuration output has no active/paused deployment. Metadata uses
settings backup_format=network-monitor-1 and backup_kind. Legacy unmarked SQLite
backups are complete. Live DB never gets these metadata keys.
POST /api/restore-preview uploads and validates a private file without changing live
data, returning safe counts/kind/history flags and allowed modes. Session-CSRF-bound
opaque reviews expire after 15 minutes; max two staged files and one active transfer.
POST /api/restore-apply consumes a review once with mode complete/configuration;
configuration files cannot select complete. Cancel uses /api/restore-discard. Retain
the direct binary /api/restore API for compatibility. Validate/migrate private files,
check free disk, FK integrity and Admin authorization again before SQLite backup
replacement under LOCK. Both modes pause monitoring AND notifications, cancel pending
messages and invalidate sessions. Configuration-only replacement removes destination
history too: no merge. Typed failures leave live data intact before replacement;
never automatically retry apply. UI describes content and destructive scope in the
app-styled review dialog, captures the file/token/mode, blocks duplicate writes and
closing while applying, and signs out after success. Legacy account-less backups
retain destination accounts.
MONITOR_MAX_RESTORE_MB defaults 20480 MiB (20 GiB), allowed 1–1048576; Compose
passes it through. Disk checks reserve upload/candidate/live-journal headroom. Existing
.env values override the new default. Creation/final apply can delay polling/config
writes while holding LOCK; release it before streaming downloads. Private files are
cleaned on success/error/cancel/expiry; crash leftovers older than 24h are swept on
startup. Both shared dashboard guards allow up to two hours for restore requests;
other deadlines remain unchanged and reverse proxies may need separate limits.
