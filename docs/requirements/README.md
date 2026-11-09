# Current requirements index

[AGENTS.md](../../AGENTS.md) is the mandatory entry point. Read it first, then read
complete topic documents before changing their areas. Linked files are not loaded
automatically. For broad reviews or uncertain scope, read all ten topic documents.

| Area | Requirements |
| --- | --- |
| [Architecture and operations](architecture.md) | Equipment scope, runtime, deployment and safe capacity testing. |
| [Access, accounts and acknowledgements](access.md) | Server permissions, public allowlists, sessions, actor history and authentication flows. |
| [Monitoring and issue lifecycle](monitoring.md) | Managed ping, persistence, revisions, pause/suppression, protocols and issue membership. |
| [Projects and deployments](projects.md) | Project identity, logos, activation/resume, deletion and durable deployment metadata. |
| [Inventory, services and library](inventory-services.md) | Shared devices, independent service copies/defaults, editors and portable imports. |
| [Notifications](notifications.md) | Provider roles, reminders, global mute, message formats and safe sample sends. |
| [History, backup and restore](history-backups.md) | Bounded historical queries, measurement versions and disk-backed backup/restore. |
| [Dashboard connections and synchronization](connections.md) | Stream admission, duplicate tabs, coalescing, lifecycle and connection recovery. |
| [Forms and shared layout](forms-layout.md) | Draft preservation, confirmations, accessible configuration, responsive toolbars and shared styles. |
| [Dashboard display](dashboards.md) | Issue/host ordering, presentation preferences, severity colours and responsive host views. |

The documents contain current behaviour and preservation constraints. Root
instructions retain Git publishing, release policy and essential safety invariants.
Detailed UI rules remain requirements even when their corresponding backend lives
in a different module; follow the related-area links for the paths being changed.

[Migration audit](MIGRATION.md) records the source of every original instruction
block, exact moves and explicit consolidations. Historical implementation notes
are retained in [CHANGELOG.md](../../CHANGELOG.md), rather than taking precedence
over current requirements. Requirement IDs are stable navigation aids; future
requirements can use descriptive headings without extending the migration table.
