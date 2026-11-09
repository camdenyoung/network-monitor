# Projects and deployments

Project identity, logos, activation/resume, deletion and durable deployment metadata.

Current requirements. Read [AGENTS.md](../../AGENTS.md) first. The
[migration audit](MIGRATION.md) records the source of each section; anchor IDs
are navigation aids, not priorities.

Related areas: [Access, accounts and acknowledgements](access.md), [Monitoring and issue lifecycle](monitoring.md), [Notifications](notifications.md), [History, backup and restore](history-backups.md), [Forms and shared layout](forms-layout.md), [Dashboard display](dashboards.md).
Read the related rules affected by the task; these links do not load documents automatically.

<a id="r010"></a>

## Project aliases

- Project assignment aliases are editable independently; preserve assignment IDs,
  services, history and aliases in other projects.

<a id="r019"></a>

## Project duplication

- Admins can duplicate a project into a uniquely named inactive project, copying
  active assignments, current service configs/flags, logo and status settings against
  shared inventory. Never copy runs, samples, issues, sessions or outbox messages.

<a id="r022"></a>

## Project names and event logos

- Admins can rename projects and upload/replace/remove PNG/JPEG event logos.
  Logo blobs live in project_logos and are included in backups. Limit 2 MB and
  4096 pixels per side; disallow SVG/active formats. Public logo access permits the active project, or the paused project when
  no run is active (R082). Renaming preserves identity, assignments and history.

<a id="r040"></a>

## Active project and deployments

- Exactly one active project. Each activation creates a deployment run; retain history.

<a id="r080"></a>

## Quick pause and resume

Pause all monitoring retains paused_run. Resume all monitoring continues that same
deployment for the selected paused project; it never creates a run or resets history,
issues or per-service pause flags. New deployment remains a separate action and
selects its new run in paused_run with active_run=0. Resume requires fresh reads and invalidates pre-pause in-flight
results. Paused deployment survives restart; restore remains paused but resumable.

<a id="r081"></a>

## Monitoring toggle appearance

Pause/Resume all monitoring is one toggle button. Running uses the active green
background; paused uses a slow flashing amber background (static amber when reduced
motion is requested). Resuming retains the paused deployment and still requires
selecting its project. No existing deployment means Resume is disabled.

<a id="r082"></a>

## Paused branding and public logo access

Pausing all monitoring preserves the current event name and logo on public status.
Public logo access permits the active run, or paused_run when no run is active;
other project logos remain private. The status summary explicitly says Monitoring
paused and does not present live readings or enable acknowledgements while paused.

<a id="r083"></a>

## Starting a deployment confirmation

Activate / start new deployment opens a confirmation dialog with Continue and
Cancel before sending any activation request. Explain that the new run starts a
fresh current history/issue list while prior data remains stored. Resume continues
a paused run. Capture the selected project on opening and retain errors in the dialog.

<a id="r096"></a>

## Per-deployment issue numbering

Displayed issue numbers start at #1 for every deployment. Keep incidents.id as
the internal globally unique API/acknowledgement key; use incidents.number for
UI and notification labels. runs.issue_counter is durable across deletions and
pause/resume. Startup/restore number legacy issues by ID order within each run,
without changing their IDs. Notifications include the deployment ID for context.

<a id="r097"></a>

## Deployment descriptions

Starting a deployment requires a 1–500 character description in the confirmation
dialog, validated on the server. runs stores the description and original start
timestamp. The main dashboard shows both for the active or paused run. Pause/Resume
preserves them; older runs retain an empty description rather than invented text.
Deployment descriptions are included in SQLite backups but not public status APIs.

<a id="r104"></a>

## Reusing a project logo

The new-project form can reuse a logo from any existing project with a preview.
Copy project_logos image/mime/digest into an independent new-project row in the
same transaction as project creation. Invalid/deleted choices reject creation
without leaving a partial project. Blank means no logo; refresh preserves drafts.

<a id="r107"></a>

## Resuming a selected deployment

Admins and scoped Operators can select previous deployments for the selected
project and resume one through an in-app confirmation. Show run number, original
start time and description; clearly disclose stopping any current run, current
project config, fresh checks and paused monitoring/notifications.
/api/resume-deployment requires Admin or scoped Operator access plus CSRF (R185).
Validate run ownership and an expected_active_run lease before changes; preserve
run metadata/history/issue counters/service flags and invalidate stale in-flight
reads via monitoring_since. Select the run with active_run=0 and paused_run set,
pause notifications and cancel pending messages (R143). Only explicit global
Resume starts checks; do not automatically resume monitoring.
Never create a run or restore old service configs when resuming an existing run.
The quick Pause/Resume monitoring toggle keeps its existing behavior.

<a id="r108"></a>

## Deleting a deployment

Delete selected deployment is Admin/CSRF-protected and requires explicit in-app
confirmation describing permanent deletion of run/readings/issues/acknowledgements/
related outbox rows. Require inactive target, project ownership and expected active
run before changes. Purge only the chosen run, transactionally; preserve configs,
other runs and inventory. Clear paused_run only when it references the target.
Durable last_id_runs and last_id_incidents counters prevent ID reuse after deletion,
protecting delayed polling and stale acknowledgement/resume dialogs. Migrate these
counters on startup/restore and allocate both IDs through next_record_id.

<a id="r143"></a>

## Paused deployment selection

Deployment selection defaults to paused monitoring and notifications: activate and
resume-deployment set active_run=0 and paused_run to the selected run. Only global
resume starts checks (without unpausing notifications). Retain per-service/host
flags, metadata, history and counters; invalidate in-flight reads when switching.
Both pause buttons pulse while paused, with prefers-reduced-motion disabling the
animation. Confirmations explain the two explicit resume steps. Benchmark seeding
opts into global resume after activation so the harness still measures polling.

<a id="r149"></a>

## Initial project selection

Initial Admin project selection follows active_run's project, then paused_run's
project, then the first available project. Validate that the project still exists.
Never overwrite a valid manual selection on polling/focus/SSE refresh. Use the
same fallback if a selected project becomes unavailable; handle empty inventory.

<a id="r150"></a>

## Empty-logo placeholder

Admin project toolbar's fixed logo slot shows a themed network-icon placeholder
when the selected project has no logo; hide it when an image is present. With no
project, label it Select a project. Keep toolbar dimensions/alignment unchanged.

<a id="r151"></a>

## Durable project deletion

Project deletion: app/project_deletion.py owns a durable project_deletions job table.
Admin/CSRF project-delete queues a named/captured project, rejects a running target,
quarantines assignments/services and clears a matching paused_run. Worker batches
1,000 samples per transaction, purges service-owned issues/outbox/audit/stability,
then scans a captured row-ID horizon in bounded chunks for legacy orphan readings
owned by the project's deployments. Finally remove runs/assignments/logo/project.
Preserve devices, defaults, library, accounts and other projects. Keep completed
job metadata. Persist project ID counters through next_record_id to prevent reuse.
Resume queued/running jobs on startup; failed jobs require explicit retry. While
unfinished, reject configuration changes and backup downloads. Block restore
while queued/running; allow restoring a prior backup as recovery from a failed job. Operational pause,
notification pause and acknowledgement remain available. Status/progress is Admin-only
in /api/state. Restore migrates the job table; never delete shared inventory.

<a id="r164"></a>

## New-project selection and save feedback

New project creation returns its ID after commit; the Admin form selects it without
activation. pendingCreatedProject holds that choice across stale in-flight refreshes
until the project appears; a manual project selection clears the pending choice.
Project assignments use collapsed-by-default native details/summary and retain their
open state through refreshes, without changing host monitoring/visibility flags.
Successful notify calls add a top-right, dismissible six-second save toast using
textContent and a polite live region, alongside the existing inline feedback.
Project name/status/logo saves explicitly notify after a confirmed write. Error
responses do not reset forms or produce success toasts. Paused monitoring button
text stays white; the separate Paused header badge remains yellow.
