# Instruction reorganisation audit

This is review evidence, not an additional source of current requirements.
The entry point and ten topic documents define the current rules. This audit
records the original documentation-only reorganisation in commit d66a8ba9; no
application code, database, tests, displayed version/build or release tag changed
in that commit. The later v0.6.4 / Build 121 integration also includes Build 120's
application fixes and adds their confirmed-action feedback rules to forms-layout.md.
The block map below remains a record of the original moves; subsequent requirements
and release-context updates are maintained in the current documents.

## Source and method

The published source is [AGENTS.md at Build 119, commit 4baaa629](https://github.com/camdenyoung/network-monitor/blob/4baaa629bafbc602709d6c6026fefa82dfde065f/AGENTS.md).
The working copy also contained the 33-line new-chat/Git publishing draft added in
this chat before branching. That draft is preserved in the root workflow; its
obsolete oversized-file reading paragraph is replaced by explicit topic loading.
The complete input was 80,902 bytes / 1,174 lines with SHA-256
`ae041702a5b6dd620a4a6904d20779dd56f23867aab32414f370660e2d878534`.

All 188 non-heading instruction blocks were assigned exactly once. Blank lines
and the former generic Requirements/Implementation headings are structural only.
“Exact move” means the complete source block matched verbatim at the original
reorganisation commit, including line wrapping. Consolidated/updated wording is listed explicitly; no requirement
was dropped merely because it lacked a test or seemed unimportant. Source line
numbers below refer to the published Build 119 file, except the marked local draft.

## Consolidations to review

- R002: replace the oversized-file loading warning with mandatory reading of the
  concise entry point and the complete relevant topic documents; broad reviews
  must load every current topic document.
- R018/R022/R073/R092: use the later established navigation, paused-logo and
  configuration/Settings placement; retain identity, validation and accessibility.
- R044/R142: recovered issues belong in Resolved even when acknowledged.
- R050/R039 and R117/R115: consolidate two duplicate provider/format rules.
- R061/R127: use current floating Actions menus with unique restoration keys.
- R099/R109: preserve pulse eligibility and use severity-matched reduced-motion colour.
- R107/R143/R185: previous-deployment selection permits the established scoped
  Operator role and leaves monitoring paused until global Resume.
- R138: preserve account presence and bounded storage, while retaining the later
  admitted-stream numerator instead of the superseded approximate tab count.
- R175/R176: retain current layout/submission/browser cautions and move dated,
  qualified iCloud observations to the changelog in chronological order.
- R180: move the completed Build 102 refactor's script-freeze scope to history;
  current stylesheet/security/preview rules remain.
- R181/R182: keep early 413 rejection and safe errors, while using the later
  disk-backed restore workflow and 20 GiB default instead of old RAM/limit rules.
- R139/R140/R182/R185/R186/R187: remove historical introduction wording from
  current requirements, preserving their behaviour and compatibility constraints.
- R188: retain the accepted one-second timing edge and move the merge history.

The root essential invariants and topic links are navigation/safety summaries of
existing rules. The detailed topic requirements remain authoritative for their
area; the summaries do not replace them. The root maximum-size maintenance target
and explicit topic-reading instructions implement this documentation reorganisation.
The original documentation-only commit left displayed Build 119 unchanged as
requested. The later v0.6.4 integration updates the current release context to
Build 121; future update commits retain the existing build/release policy unless
overridden.

## Complete block map

| Block | Build 119 source lines | Destination | Treatment |
| --- | --- | --- | --- |
| R001 | 3–4 | [AGENTS.md](../../AGENTS.md#project-context) | Exact move |
| R002 | Local Git workflow draft | [AGENTS.md](../../AGENTS.md#required-reading) | Replace the oversized-file reading rule with a complete short entry point and mandatory topic-document loading instructions. |
| R003 | Local Git workflow draft | [AGENTS.md](../../AGENTS.md#git-workflow) | Exact move |
| R004 | Local Git workflow draft | [AGENTS.md](../../AGENTS.md#git-workflow) | Exact move |
| R005 | Local Git workflow draft | [AGENTS.md](../../AGENTS.md#git-workflow) | Exact move |
| R006 | Local Git workflow draft | [AGENTS.md](../../AGENTS.md#git-workflow) | Exact move |
| R007 | 8–9 | [AGENTS.md](../../AGENTS.md#release-workflow) | Exact move |
| R008 | 11–13 | [AGENTS.md](../../AGENTS.md#release-workflow) | Exact move |
| R009 | 15–20 | [AGENTS.md](../../AGENTS.md#release-workflow) | Exact move |
| R010 | 23–24 | [projects](projects.md#r010) | Exact move |
| R011 | 25–28 | [dashboards](dashboards.md#r011) | Exact move |
| R012 | 29–31 | [dashboards](dashboards.md#r012) | Exact move |
| R013 | 32–36 | [dashboards](dashboards.md#r013) | Exact move |
| R014 | 37–38 | [dashboards](dashboards.md#r014) | Exact move |
| R015 | 39–40 | [dashboards](dashboards.md#r015) | Exact move |
| R016 | 41–42 | [dashboards](dashboards.md#r016) | Exact move |
| R017 | 43–44 | [dashboards](dashboards.md#r017) | Exact move |
| R018 | 45–48 | [dashboards](dashboards.md#r018) | Keep logo/branding rules; consolidate navigation placement with R103/R179 rather than the superseded header placement. |
| R019 | 49–51 | [projects](projects.md#r019) | Exact move |
| R020 | 52 | [dashboards](dashboards.md#r020) | Exact move |
| R021 | 53–57 | [access](access.md#r021) | Exact move |
| R022 | 58–61 | [projects](projects.md#r022) | Use the paused-project public-logo rule already established by R082; keep format, size, identity and backup requirements. |
| R023 | 62–64 | [dashboards](dashboards.md#r023) | Exact move |
| R024 | 65 | [dashboards](dashboards.md#r024) | Exact move |
| R025 | 66–68 | [monitoring](monitoring.md#r025) | Exact move |
| R026 | 69–70 | [monitoring](monitoring.md#r026) | Exact move |
| R027 | 71 | [monitoring](monitoring.md#r027) | Exact move |
| R028 | 72 | [forms-layout](forms-layout.md#r028) | Exact move |
| R029 | 73 | [inventory-services](inventory-services.md#r029) | Exact move |
| R030 | 74 | [inventory-services](inventory-services.md#r030) | Exact move |
| R031 | 75–76 | [inventory-services](inventory-services.md#r031) | Exact move |
| R032 | 77 | [inventory-services](inventory-services.md#r032) | Exact move |
| R033 | 78–81 | [access](access.md#r033) | Exact move |
| R034 | 82–88 | [access](access.md#r034) | Exact move |
| R035 | 89–90 | [access](access.md#r035) | Exact move |
| R036 | 91–92 | [access](access.md#r036) | Exact move |
| R037 | 93–95 | [access](access.md#r037) | Exact move |
| R038 | 96–99 | [access](access.md#r038) | Exact move |
| R039 | 100–102 | [notifications](notifications.md#r039) | Exact move |
| R040 | 103 | [projects](projects.md#r040) | Exact move |
| R041 | 104 | [inventory-services](inventory-services.md#r041) | Exact move |
| R042 | 105–107 | [inventory-services](inventory-services.md#r042) | Exact move |
| R043 | 108–109 | [monitoring](monitoring.md#r043) | Exact move |
| R044 | 110–111 | [monitoring](monitoring.md#r044) | Consolidate list membership with the later, authoritative recovery precedence in R142. |
| R045 | 112 | [architecture](architecture.md#r045) | Exact move |
| R046 | 113 | [monitoring](monitoring.md#r046) | Exact move |
| R047 | 114 | [monitoring](monitoring.md#r047) | Exact move |
| R048 | 115 | [architecture](architecture.md#r048) | Exact move |
| R049 | 116–117 | [architecture](architecture.md#r049) | Exact move |
| R050 | 118 | [notifications](notifications.md#r039) | Exact provider-route duplicate consolidated with R039; Telegram remains the shared-group route and WhatsApp optional. |
| R051 | 119 | [architecture](architecture.md#r051) | Exact move |
| R052 | 122–125 | [architecture](architecture.md#r052) | Exact move |
| R053 | 128–135 | [architecture](architecture.md#r053) | Exact move |
| R054 | 137–141 | [architecture](architecture.md#r054) | Exact move |
| R055 | 143–144 | [architecture](architecture.md#r055) | Exact move |
| R056 | 146–149 | [inventory-services](inventory-services.md#r056) | Exact move |
| R057 | 151–155 | [monitoring](monitoring.md#r057) | Exact move |
| R058 | 157–159 | [monitoring](monitoring.md#r058) | Exact move |
| R059 | 161–164 | [inventory-services](inventory-services.md#r059) | Exact move |
| R060 | 166–171 | [monitoring](monitoring.md#r060) | Exact move |
| R061 | 173–178 | [forms-layout](forms-layout.md#r061) | Use R127 for the current floating-menu implementation; retain history and menu-state rules. |
| R062 | 180–189 | [access](access.md#r062) | Exact move |
| R063 | 191–204 | [monitoring](monitoring.md#r063) | Exact move |
| R064 | 206–212 | [forms-layout](forms-layout.md#r064) | Exact move |
| R065 | 214–217 | [access](access.md#r065) | Exact move |
| R066 | 219–223 | [access](access.md#r066) | Exact move |
| R067 | 225–226 | [dashboards](dashboards.md#r067) | Exact move |
| R068 | 228–231 | [access](access.md#r068) | Exact move |
| R069 | 233–234 | [AGENTS.md](../../AGENTS.md#essential-invariants) | Exact move |
| R070 | 236–241 | [access](access.md#r070) | Exact move |
| R071 | 243–245 | [access](access.md#r071) | Exact move |
| R072 | 247–249 | [inventory-services](inventory-services.md#r072) | Exact move |
| R073 | 251–256 | [forms-layout](forms-layout.md#r073) | Consolidate current Project configuration position and Settings label with R161/R165/R138; preserve IDs, visibility and keyboard rules. |
| R074 | 258–261 | [access](access.md#r074) | Exact move |
| R075 | 263–265 | [dashboards](dashboards.md#r075) | Exact move |
| R076 | 267–268 | [dashboards](dashboards.md#r076) | Exact move |
| R077 | 270–274 | [history-backups](history-backups.md#r077) | Exact move |
| R078 | 276–277 | [AGENTS.md](../../AGENTS.md#current-release) | Exact move originally; current release context updated to v0.6.4 / Build 121 during integration. |
| R079 | 279–280 | [dashboards](dashboards.md#r079) | Exact move |
| R080 | 282–286 | [projects](projects.md#r080) | Exact move |
| R081 | 288–291 | [projects](projects.md#r081) | Exact move |
| R082 | 293–296 | [projects](projects.md#r082) | Exact move |
| R083 | 298–301 | [projects](projects.md#r083) | Exact move |
| R084 | 303–306 | [dashboards](dashboards.md#r084) | Exact move |
| R085 | 308–310 | [dashboards](dashboards.md#r085) | Exact move |
| R086 | 312–315 | [access](access.md#r086) | Exact move |
| R087 | 317–320 | [access](access.md#r087) | Exact move |
| R088 | 322–325 | [dashboards](dashboards.md#r088) | Exact move |
| R089 | 327–328 | [dashboards](dashboards.md#r089) | Exact move |
| R090 | 330–331 | [dashboards](dashboards.md#r090) | Exact move |
| R091 | 333–335 | [forms-layout](forms-layout.md#r091) | Exact move |
| R092 | 337–343 | [notifications](notifications.md#r092) | Update the location to the existing Settings tab; retain reminder limits and delivery semantics. |
| R093 | 345–348 | [forms-layout](forms-layout.md#r093) | Exact move |
| R094 | 350–351 | [dashboards](dashboards.md#r094) | Exact move |
| R095 | 353–355 | [notifications](notifications.md#r095) | Exact move |
| R096 | 357–361 | [projects](projects.md#r096) | Exact move |
| R097 | 363–367 | [projects](projects.md#r097) | Exact move |
| R098 | 369–379 | [inventory-services](inventory-services.md#r098) | Exact move |
| R099 | 381–386 | [forms-layout](forms-layout.md#r099) | Keep tab accessibility and pulse eligibility; use the later R109 yellow/red rule instead of the old always-red reduced-motion wording. |
| R100 | 388–390 | [forms-layout](forms-layout.md#r100) | Exact move |
| R101 | 392–397 | [notifications](notifications.md#r101) | Exact move |
| R102 | 399–402 | [notifications](notifications.md#r102) | Exact move |
| R103 | 404–406 | [dashboards](dashboards.md#r103) | Exact move |
| R104 | 408–411 | [projects](projects.md#r104) | Exact move |
| R105 | 413–423 | [inventory-services](inventory-services.md#r105) | Exact move |
| R106 | 425 | [dashboards](dashboards.md#r106) | Exact move |
| R107 | 427–435 | [projects](projects.md#r107) | Apply the later scoped-Operator permission (R185) and paused-selection rule (R143); retain ownership, lease, metadata and stale-read safeguards. |
| R108 | 437–444 | [projects](projects.md#r108) | Exact move |
| R109 | 446–449 | [dashboards](dashboards.md#r109) | Consolidate pulse eligibility from R099 with the current severity and priority rules; retain the reduced-motion duration/behaviour. |
| R110 | 452–460 | [monitoring](monitoring.md#r110) | Exact move |
| R111 | 462–464 | [monitoring](monitoring.md#r111) | Exact move |
| R112 | 466–468 | [notifications](notifications.md#r112) | Exact move |
| R113 | 470–471 | [notifications](notifications.md#r113) | Exact move |
| R114 | 473–475 | [dashboards](dashboards.md#r114) | Exact move |
| R115 | 477–479 | [notifications](notifications.md#r115) | Exact move |
| R116 | 481–482 | [notifications](notifications.md#r116) | Exact move |
| R117 | 484 | [notifications](notifications.md#r115) | The warning-icon prefix is already explicitly required by the four-line format in R115. |
| R118 | 486–492 | [notifications](notifications.md#r118) | Exact move |
| R119 | 494–496 | [notifications](notifications.md#r119) | Exact move |
| R120 | 498–508 | [forms-layout](forms-layout.md#r120) | Exact move |
| R121 | 510–516 | [forms-layout](forms-layout.md#r121) | Exact move |
| R122 | 518–523 | [inventory-services](inventory-services.md#r122) | Exact move |
| R123 | 525–526 | [inventory-services](inventory-services.md#r123) | Exact move |
| R124 | 528–533 | [inventory-services](inventory-services.md#r124) | Exact move |
| R125 | 535–540 | [inventory-services](inventory-services.md#r125) | Exact move |
| R126 | 542–545 | [inventory-services](inventory-services.md#r126) | Exact move |
| R127 | 547–553 | [forms-layout](forms-layout.md#r127) | Exact move |
| R128 | 555–559 | [inventory-services](inventory-services.md#r128) | Exact move |
| R129 | 561–568 | [forms-layout](forms-layout.md#r129) | Exact move |
| R130 | 570–573 | [inventory-services](inventory-services.md#r130) | Exact move |
| R131 | 575–589 | [access](access.md#r131) | Exact move |
| R132 | 591–599 | [connections](connections.md#r132) | Exact move |
| R133 | 601–602 | [dashboards](dashboards.md#r133) | Exact move |
| R134 | 604–616 | [architecture](architecture.md#r134) | Exact move |
| R135 | 618–619 | [architecture](architecture.md#r135) | Exact move |
| R136 | 621–627 | [history-backups](history-backups.md#r136) | Exact move |
| R137 | 629–632 | [history-backups](history-backups.md#r137) | Exact move |
| R138 | 634–653 | [connections](connections.md#r138) | Replace the explicitly superseded approximate connection badge with the current admitted-stream count, retaining the separate bounded presence/account tracker and all admission rules. |
| R139 | 655–668 | [connections](connections.md#r139) | Remove a historical build prefix; retain handover, cleanup, legacy-client and test requirements. |
| R140 | 670–681 | [connections](connections.md#r140) | Describe current lifetime arbitration without a historical introduction; retain Build 115 wire compatibility and the browser limit. |
| R141 | 683–686 | [connections](connections.md#r141) | Exact move |
| R142 | 688–696 | [monitoring](monitoring.md#r142) | Exact move |
| R143 | 698–704 | [projects](projects.md#r143) | Exact move |
| R144 | 706–716 | [connections](connections.md#r144) | Exact move |
| R145 | 718–721 | [connections](connections.md#r145) | Exact move |
| R146 | 723–724 | [connections](connections.md#r146) | Exact move |
| R147 | 726–727 | [connections](connections.md#r147) | Exact move |
| R148 | 729–733 | [dashboards](dashboards.md#r148) | Exact move |
| R149 | 735–738 | [projects](projects.md#r149) | Exact move |
| R150 | 740–742 | [projects](projects.md#r150) | Exact move |
| R151 | 744–756 | [projects](projects.md#r151) | Exact move |
| R152 | 758–769 | [history-backups](history-backups.md#r152) | Exact move |
| R153 | 771–777 | [forms-layout](forms-layout.md#r153) | Exact move |
| R154 | 779–780 | [forms-layout](forms-layout.md#r154) | Exact move |
| R155 | 782–785 | [forms-layout](forms-layout.md#r155) | Exact move |
| R156 | 787–799 | [dashboards](dashboards.md#r156) | Exact move |
| R157 | 801–804 | [dashboards](dashboards.md#r157) | Exact move |
| R158 | 806–808 | [dashboards](dashboards.md#r158) | Exact move |
| R159 | 810–819 | [monitoring](monitoring.md#r159) | Exact move |
| R160 | 821–823 | [monitoring](monitoring.md#r160) | Exact move |
| R161 | 825–830 | [forms-layout](forms-layout.md#r161) | Exact move |
| R162 | 832–833 | [forms-layout](forms-layout.md#r162) | Exact move |
| R163 | 835–848 | [history-backups](history-backups.md#r163) | Exact move |
| R164 | 850–859 | [projects](projects.md#r164) | Exact move |
| R165 | 861–862 | [forms-layout](forms-layout.md#r165) | Exact move |
| R166 | 864–869 | [forms-layout](forms-layout.md#r166) | Exact move |
| R167 | 871–872 | [forms-layout](forms-layout.md#r167) | Exact move |
| R168 | 874–883 | [history-backups](history-backups.md#r168) | Exact move |
| R169 | 885–891 | [inventory-services](inventory-services.md#r169) | Exact move |
| R170 | 893–903 | [access](access.md#r170) | Exact move |
| R171 | 905–907 | [inventory-services](inventory-services.md#r171) | Exact move |
| R172 | 909–924 | [inventory-services](inventory-services.md#r172) | Exact move |
| R173 | 926–945 | [inventory-services](inventory-services.md#r173) | Exact move |
| R174 | 948–962 | [access](access.md#r174) | Exact move |
| R175 | 965–978 | [access](access.md#r175) | Keep current password layout, native submission and browser-handover cautions; move dated diagnostics to CHANGELOG. Historical portion: [CHANGELOG](../../CHANGELOG.md#instruction-history-r175). |
| R176 | 981–986 | [access](access.md#r176) | Retain the current routing and uncertainty requirements; move the dated user follow-up and release reference to CHANGELOG. Historical portion: [CHANGELOG](../../CHANGELOG.md#instruction-history-r176). |
| R177 | 989–1003 | [access](access.md#r177) | Exact move |
| R178 | 1006–1012 | [access](access.md#r178) | Exact move |
| R179 | 1015–1020 | [dashboards](dashboards.md#r179) | Exact move |
| R180 | 1023–1039 | [forms-layout](forms-layout.md#r180) | Retain current stylesheet boundaries, asset security and preview checks; move the completed CSS-refactor-only script restriction to CHANGELOG. Historical portion: [CHANGELOG](../../CHANGELOG.md#instruction-history-r180). |
| R181 | 1042–1053 | [history-backups](history-backups.md#r181) | Keep early rejection, safe feedback, format/access and browser isolation rules; R182 supersedes the former in-memory implementation and old upload defaults. Historical portion: [CHANGELOG](../../CHANGELOG.md#instruction-history-r181). |
| R182 | 1056–1086 | [history-backups](history-backups.md#r182) | Describe the established disk-backed restore as the current requirement, preserving all limits, lifecycle, configuration-copy and security semantics. |
| R183 | 1089–1096 | [access](access.md#r183) | Exact move |
| R184 | 1099–1103 | [access](access.md#r184) | Exact move |
| R185 | 1105–1115 | [access](access.md#r185) | Remove a historical build prefix; preserve current role scoping. |
| R186 | 1117–1124 | [connections](connections.md#r186) | Remove a historical build prefix; preserve post-commit operational invalidations and quiet no-ops. |
| R187 | 1126–1135 | [connections](connections.md#r187) | Remove a historical build prefix; preserve monitoring event eligibility, coalescing and notification independence. |
| R188 | 1137–1141 | [connections](connections.md#r188) | Keep the explicitly accepted one-second timing edge as a current constraint; move the merge/build history to CHANGELOG. Historical portion: [CHANGELOG](../../CHANGELOG.md#instruction-history-r188). |
