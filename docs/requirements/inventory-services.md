# Inventory, services and library

Shared devices, independent service copies/defaults, editors and portable imports.

Current requirements. Read [AGENTS.md](../../AGENTS.md) first. The
[migration audit](MIGRATION.md) records the source of each section; anchor IDs
are navigation aids, not priorities.

Related areas: [Access, accounts and acknowledgements](access.md), [Projects and deployments](projects.md), [Monitoring and issue lifecycle](monitoring.md), [History, backup and restore](history-backups.md), [Forms and shared layout](forms-layout.md).
Read the related rules affected by the task; these links do not load documents automatically.

<a id="r029"></a>

## Permanent inventory and assignments

- Permanent inventory; reusable project assignments with per-project aliases.

<a id="r030"></a>

## Inventory editing

- Inventory supports full ID/name, model, IP edits and confirmed permanent deletion.

<a id="r031"></a>

## Permanent device deletion

- Device deletion purges all linked assignments, services, history and issues;
  preserve shared projects/runs and all other equipment.

<a id="r032"></a>

## Shared inventory addresses

- IP addresses belong to inventory devices and are shared across all projects.

<a id="r041"></a>

## Copying services

- Services can be copied between host assignments, including across projects.

<a id="r042"></a>

## Reusable service definitions

- Reusable service library supports creation, saving from a host, editing, deletion
  and applying to a host. Copies/templates materialize independent configurations;
  never copy metric history, issues, acknowledgements or managed host ping.

<a id="r056"></a>

## Inventory-address migration

`migrate_inventory_addresses` moves old assignment addresses to inventory on startup
and restore. Conflicts are preserved in legacy_assignment_addresses; no address
is chosen automatically and those devices are not polled until configured.
SQLite >=3.35 is required for the migration. Do not restore project-specific IPs.

<a id="r059"></a>

## Independent library storage

service_templates stores independent reusable definitions, including credentials.
ensure_service_library runs on startup/restore for backward-compatible backups.
Redact template communities from snapshot, just like normal service credentials.
Deleting a host or library entry must not affect already-materialized copies.

<a id="r072"></a>

## Inventory configuration area

Permanent inventory is its own top-level Admin section, separate from Project
configuration. Keep inventory creation/search/edit/removal there; project assignment
and service configuration remain under Project configuration.

<a id="r098"></a>

## Inventory service defaults

Permanent inventory devices have independent standard service definitions in
`device_service_defaults`. New project assignments materialize copies of these
configs/credentials with monitoring enabled; never link runtime services back to
defaults or copy samples/issues. Existing and reactivated archived assignments
retain their configs. Project duplication copies the project's services, not the
inventory defaults. Defaults have CRUD, library import, and explicit replacement
from a selected project assignment of that same device. Do not infer defaults
from existing projects on migration; offer explicit adoption to avoid conflicts.
Duplicate names are rejected rather than silently losing definitions. Ping stays
managed and is never a default. Redact default communities from snapshots, include
all defaults in backup/restore, and purge only that device's defaults on deletion.

<a id="r105"></a>

## Portable service-library format

Reusable service library import/export is Admin-only. Export versioned JSON of
service definitions including communities, with a host-local timestamp filename.
No database IDs, accounts or runtime/history records travel in the file. Merge
keeps exact case-sensitive name matches; Replace changes only service_templates.
Fully validate all entries before any mutation; import runs in one transaction,
rejecting duplicate file names, unsupported schema/types and invalid service
configs without partial writes. Keep instance services/defaults/history untouched.
Use in-app confirmation for imports, report added/skipped/replaced totals, and
keep errors in the dialog. Bound files to 5 MB and 5000 services. Export files
contain credentials and must be described as sensitive. app/service_library.py
owns the portable format; server.service_details remains the config validator.

<a id="r122"></a>

## Host flap dialog and service-editor layout

Host flap-protection dialog identifies its target with Device ID - project alias
using textContent every time it opens. Reject missing/removed targets. The host
form has no numeric hysteresis control. Service editing uses a responsive wide
three-column grid; .flap-settings spans its own row, with side-by-side settings
that wrap on narrower screens. Use the same horizontal fieldset for library,
inventory defaults and service creation. Keep Save/Cancel together below settings.

<a id="r123"></a>

## Consecutive-reading field order

In the service editor, Consecutive readings follows Critical in the same
Warning / Critical / Consecutive readings row, before the flap settings.

<a id="r124"></a>

## Protocol-field drafts

Service forms disable irrelevant protocol fields on initial load, editor opening,
protocol changes and successful add-form reset. SNMP enables community only;
Modbus enables unit ID only; TCP disables both. Do not clear disabled drafts.
Keep native disabled styling visible. Missing unit on edit preserves the existing
value in service_details, as missing community already preserves the secret.
Apply the shared editor rules to services, library definitions and device defaults.

<a id="r125"></a>

## Service creation location

Project configuration no longer contains the inline Selected services creation
form or its assignment selector. Create definitions in Reusable service library
and apply them with Add to host. Preserve the separate Configured services
filter/management section, service feedback and host actions, existing services,
inventory defaults and history. The shared editor still supports library/default
creation and editing of existing project services.

<a id="r126"></a>

## Assign-equipment choices

Assign-equipment dropdown excludes all non-removed assignments in the selected
project, including hidden/paused hosts. Devices assigned only elsewhere and
removed assignments remain eligible. Recompute on project change and refresh;
preserve eligible selection, clear it after assignment, and explain empty choices.

<a id="r128"></a>

## Soft service-removal dialog

Removing a host service uses the shared styled in-app confirmation, never native
confirm(). Show Device ID - Alias / service name using textContent, explain that
history is retained, and capture the target. Cancel/Escape send no mutation.
Disable controls while saving, keep errors in the dialog, reject unavailable
services and preserve backend Admin/CSRF enforcement and soft-removal semantics.

<a id="r130"></a>

## Configured-service row layout

Configured Services rows separate name/protocol details from right-aligned
Pause/Actions controls with a 24px gap, wrapping safely on small screens.
Project Assignments identifies equipment as Device ID - Alias / Address;
resolve Device ID and IP from permanent inventory and escape all displayed text.

<a id="r169"></a>

## Inventory-default name overrides

Inventory Add from library supports an optional server-side name override for
its independent device_service_defaults copy. Keep missing-name compatibility
(library name), but reject explicit blank/non-text/overlong names and existing
per-device duplicates. Never change the template, credentials or existing projects.
The UI prefills the device name on template selection, preserves custom drafts on
polling/failed saves, and clears selection/name after confirmed success. Do not
clear another device/selection or a newer draft if the save finishes late.

<a id="r171"></a>

## Inventory ordering

Permanent inventory lists sort by the user-facing Device ID/name, case-insensitive
with natural numeric ordering (SW2 before SW10), before applying the display limit.
Apply the same order to search results; sort a filtered copy without mutating state.devices.

<a id="r172"></a>

## Device duplication and unique addresses

Permanent inventory Duplicate opens an Admin-only app-styled dialog with a captured
source ID, blank new Device ID/IP and editable prefilled model. /api/device-duplicate
requires Admin/CSRF, validates a fresh unique name/IP, allocates a durable device ID
and copies every SERVICE_CONFIGURATION_FIELDS value from all source defaults in
the same transaction. Return the new device ID only after commit. Copy no assignments,
project services, readings, issues or runtime state. Preserve rejected drafts and
prevent duplicate submits or Cancel/Escape while saving; distinguish refresh failure
from write failure. Copies and their defaults remain independent of the source.
require_unique_inventory_address runs inside mutate's LOCK/transaction for device
create/edit/address updates/duplication, excluding the edited row. Canonicalize
IPv4/IPv6, compare IPv4-mapped IPv6 equivalently, and return InventoryAddressConflict
as safe HTTP feedback identifying the existing Device ID. Do not expose arbitrary
ValueError messages or credentials. Existing legacy/restored inventory is not
rewritten, and benchmark seeds intentionally insert shared simulator IPs directly;
do not add a global unique index that breaks those datasets. Tests cover clone
ownership/configuration, rollback, concurrency, IP aliases, API roles/CSRF and UI.

<a id="r173"></a>

## Portable inventory transfer

Inventory transfer: app/inventory_transfer.py owns version-1 network-monitor-inventory
JSON (name/model/address/service_defaults per device; no database IDs or projects).
Admin-only /api/inventory-export includes raw default credentials and a host-local
filename timestamp. /api/inventory-preview and /api/inventory-import require Admin/CSRF.
Merge skips existing exact Device IDs; update adds new and updates matched model/IP
and the complete defaults set, retaining default IDs when names match. Never delete
absent inventory or modify assignments, project services/history, accounts or library.
Allow blank imported IPs as unconfigured; ordinary device creation/duplication still
requires an IP. Validate all definitions via the shared service validator, cap 10 MB,
5,000 devices and 10,000 defaults, and reject unknown IDs/fields and duplicate names.
Validate final canonical IP ownership before any writes, permitting atomic swaps;
untouched legacy duplicates are preserved. Bound conflict owner lists. Apply under
mutate's LOCK/transaction and roll back every change on failure. address_key is shared
with normal unique-IP validation, including IPv4-mapped IPv6 normalization.
Preview contains no communities and includes default removals. HMAC binds file/mode
and current inventory/defaults using a process-only random key. Revalidate on confirm;
changed inventory, edited files or restart require re-review. No pending DB jobs or
schema migrations. The in-app dialog captures file/mode/token, prevents double saves
and closing during writes, blocks IP conflicts, preserves rejected inputs and resets
only after success. Export/import does not include project logos or deployment data.
