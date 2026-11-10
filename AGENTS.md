# Network Monitor project instructions

<a id="project-context"></a>

## Project context

Build a local-first equipment monitor for 100–150 network and power devices.
The user requested readable, consistently indented code and explanatory comments.

Python standard-library HTTP server and SQLite; vanilla HTML/CSS/JS. Local use
must remain possible without internet. Exact equipment OIDs/register maps remain
unverified. Do not present guessed mappings as verified profiles.

<a id="required-reading"></a>

## Required reading before work

Read this complete entry point at the start of every chat. Detailed requirements
live in the documents below; links do not automatically load their contents.
Before editing, read the complete documents for the affected areas in bounded
sections, then follow relevant cross-area rules. Read all ten current requirement
documents for broad reviews, architectural changes or uncertain scope. Do not
assume the first automatically supplied excerpt contains the entire specification.

- [Architecture](docs/requirements/architecture.md): scope, runtime, Compose and load tests.
- [Access](docs/requirements/access.md): roles, public data, sessions and acknowledgements.
- [Monitoring](docs/requirements/monitoring.md): ping, alarms, suppression and protocols.
- [Projects](docs/requirements/projects.md): logos, deployments, pause/resume and deletion.
- [Inventory/services](docs/requirements/inventory-services.md): ownership, copies and imports.
- [Notifications](docs/requirements/notifications.md): queues, reminders, mute and formats.
- [History/backups](docs/requirements/history-backups.md): bounded queries and restore.
- [Connections](docs/requirements/connections.md): stream limits, tab identity and reconnects.
- [Dashboards](docs/requirements/dashboards.md): issues, hosts, preferences and responsive views.
- [Forms/layout](docs/requirements/forms-layout.md): drafts, dialogs, accessibility and CSS.

Server/schema/configuration work must include applicable access, monitoring,
ownership and migration rules. Browser work must include applicable access,
recovery, display and form rules. Follow related-area links across file boundaries.

Topic documents are required instructions. Resolve unclear conflicts against user
instructions, code and tests; never silently discard a requirement. CHANGELOG.md
holds history. The [migration audit](docs/requirements/MIGRATION.md) maps all 188
original blocks and consolidations as review evidence, not another rule source.

## Essential invariants

- Enforce roles, project/deployment scope and CSRF on the server. Anonymous status
  shows only allowlisted public issue/branding data; live hosts require a valid
  signed-in session without a forced-password-change restriction.
- Never expose credentials in state/status/configuration GET responses or logs.
  Admin-only portable exports/backups intentionally contain secrets and must be
  handled as sensitive. Never commit runtime data, databases or secrets.
- Inventory is shared; assignment aliases and materialized service copies are
  independent. Preserve IDs/history and other projects when editing ownership.
- Ping gates child checks. Paused, blocked, stale and removed sources must not
  become false recoveries or active child faults. Reject stale in-flight reads.
- Acknowledgement records an actor and does not clear the fault. Recovery takes
  precedence in issue-list membership; preserve evidence and audit history.
- Monitoring, visibility and notification controls are independent. Global provider
  mute does not stop monitoring or dashboard synchronization. Never send live
  notification tests without explicit user instructions; tests mock providers.
- Preserve unfinished forms, filters and browser preferences during refreshes.
  Presentation never pauses polling. Retain legacy API/DOM/storage identifiers.
- Keep backup/restore bounded and consistent. Restore pauses monitoring and
  notifications, cancels pending messages and invalidates sessions. Retain the
  documented startup/restore migrations and durable ID counters.
- Keep relay/public exposure gated until authentication, encrypted transport and
  replay-safe commands exist. Health checks use /api/health.

Use Issue/Issues in all user-facing wording, notifications and help text. Preserve
legacy incident API keys, DOM identifiers, storage keys and database names for compatibility.

<a id="git-workflow"></a>

## New-chat checks and Git publishing

Before changing code or publishing, inspect the working tree, current branch,
HEAD and upstream. Refresh the relevant remote branch refs when network access
is available; origin/main alone can be stale. If remote verification is unavailable,
state that limitation and do not claim the checkout is synchronized or publish
against an unverified branch head. Preserve unrelated local changes.

GitHub's published commit history is canonical. Start new work from the actual
published commit, preserving any unpublished local work separately. If local and
remote histories diverge, inspect commits, parents and trees before proceeding;
identical file trees do not make different commit IDs interchangeable. Do not
blindly merge duplicate histories, reset away work or force-push to reconcile them.

Prefer publishing existing Git commit objects when an authenticated push is
available. When using the connected GitHub app instead, create each commit once
on GitHub against the verified expected parent, then fetch and adopt that exact
commit locally after verifying its tree matches the intended files. Do not create
an equivalent local commit separately: different metadata/parents produce different
IDs. Advance remote refs with an expected-head check and without force; inspect
the new head if the check fails. Reconcile local refs/index without discarding
uncommitted changes or including unrelated files.

After publishing, verify local HEAD and the published branch have the same commit
ID and intended file tree; report any remaining difference explicitly. Tags and
releases point to existing commits and do not rewrite main. Never move/delete an
existing release tag unless explicitly requested. These checks are the agent's
responsibility in every chat, without requiring the user to repeat them.

Repository: https://github.com/camdenyoung/network-monitor (public). Git HTTPS
credentials are not configured locally; use the connected GitHub app when needed.
Use a codex/ branch for new work unless instructed otherwise. Leave review branches
unmerged until the user requests merging.

<a id="release-workflow"></a>

## Documentation and release workflow

Keep build history and release notes in CHANGELOG.md, linked near the top of
README.md. README.md contains setup/usage guidance, not duplicated release logs.

Every displayed version change must update the README title and add concise release
notes in CHANGELOG.md describing that release. Keep both dashboard labels and this version context
in sync; do not add versions to browser tab titles.

Every future update commit must increment the displayed build number on BOTH
dashboards, update the README current build and add a brief build note to
CHANGELOG.md in the same commit. Keep the small inline format vVERSION · Build N. Build numbers
increase monotonically across releases; do not reset them when the version changes.
Do not put version/build numbers in browser tab titles. Build 1 starts this policy;
earlier commits were not numbered.

<a id="current-release"></a>

Current displayed release is v0.6.6, Build 130. Show it after the title on both the main and
status dashboards. Browser page titles omit the version.

Keep this entry point within 8 KiB. Put detailed rules in the indexed topic
documents; consolidate current rules and keep implementation history in CHANGELOG.md.

## Validation

Run `python3 -m unittest discover -s tests -v` and `python3 -m compileall app`.
For UI work run the applicable documented Node suites. Use disposable databases
and mocked providers; never seed/restore live data for tests or infer Pi capacity
from local smoke tests. See README.md, UI_TESTING.md and LOAD_TESTING.md.
