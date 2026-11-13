# DNSmuggle research workbench

## Goal and visual contract

Replace the default Tkinter tabbed landing experience with a local desktop defensive research workbench. The supplied screenshot is the layout reference: narrow left navigation, quiet breadcrumb, strong page title, three equal metric cards, a wide thin-line activity chart, and a restrained recent-activity list. Do not copy its fictional statistics.

Default dark tokens: background #101010, surface #171717, border #2C2C2C, muted #A1A1AA, text #FAFAFA. App-controlled UI is monochrome, including statuses. Light mode uses corresponding neutral tokens. Corners are 8px; thin borders, minimal shadows, generous spacing. Bundle Geist, JetBrains Mono, and Lucide assets locally, with licenses. Technical values use JetBrains Mono. Use native OS window controls rather than fake macOS traffic lights. Honor reduced-motion settings and preserve keyboard focus visibility.

## Architecture decision

Use bundled HTML/CSS/JavaScript in a Python desktop webview. The frontend requires no Node server or Internet access at runtime. A small, explicitly allowlisted Python bridge exposes defensive operations; never expose arbitrary shell execution, arbitrary filesystem reads, or transfer operations. Keep backend computation, SQLite access, monitoring and reports outside the rendering layer. Do not load remote web content into the privileged view. Webview installation adds native runtime dependencies, especially GTK/WebKit on Linux; document them and report launch failures clearly.

Alternatives considered: Tkinter restyling has the smallest dependency footprint but would require extensive custom drawing to match typography, icons, corners and transitions; browser-only local UI is portable but does not retain the standalone desktop experience. Choose the webview for visual fidelity.

Preserve the existing protocol, detector rule thresholds, crypto, compression, CLI tools and transfer history. Preserve the existing Tkinter Lab tools window as a separate launchable process. No sender improvements, new transports, concealment or evasion features.

## Data and observation boundaries

Add a separate SQLite defensive telemetry store. Persist observation timestamp, source, query name, rule evidence, monitoring session, and report metadata. Do not store transferred file contents or passwords. Existing transfer records are not DNS observations and must never inflate dashboard metrics.

Reuse the existing detector and DNS parser. Collect only explicitly started lab observations. A listener receives queries intentionally sent to its configured endpoint; it is not a system-wide packet sniffer or recursive DNS resolver. Backend ownership must prevent two listeners silently competing for the same endpoint. Existing Lab tools retain their receiver behavior; any observation integration is metadata-only and must not interfere with ACKs or file reconstruction. Surface bind failures and monitoring state truthfully.

The Overview query count is the count of observed queries in the selected period. Anomalies count distinct observed queries with recorded rule evidence, not individual rule alerts. The displayed detection rate is that count divided by observed queries, with an explanation that this is a heuristic flag rate, not detection accuracy. Respect the existing alert cooldown in the recorded event semantics and explain it where relevant. With no observations show zero counts and an unavailable percentage, not seeded data. Charts use real time buckets; identify the selected time range and observation gaps.

## Screens and interactions

1. Overview: screenshot-matched metric row, activity chart, recent events, View reports action, explicit local coverage and monitoring state.
2. DNS Detector: configured endpoint, explicit start/stop monitoring, existing length/entropy/rate rule descriptions, incoming query evidence and error state. No automatic transmission or scanning.
3. Traffic Analysis: filter observed queries by time, source, name and rule; display technical query details, measured length/entropy and recorded evidence. Derived summaries use the same filtered observations.
4. Detection History: persistent, filterable flagged-query list and detail panel with timestamp, source, rule and reason; survives restarts.
5. Research Reports: generate and export reports from actual stored observations for the selected time range, list generated reports, include coverage, rule limitations and the lab-only note. No fabricated PDF fallback; text export always works and PDF only when supported.
6. Settings: dark/light appearance, observation endpoint, read-only data location, About and lab-only scope. Preserve existing transfer settings in Lab tools rather than mixing them into defensive settings.

Navigation includes all six screens, an accessible collapse control and a Lab tools action. Command palette opens with Ctrl/Cmd+K; supports navigation, theme switching, report creation and explicit monitor controls. Keyboard navigation, Escape dismissal, focus restoration and clear disabled states are required. Loading, empty, error and populated states use shared components across every screen. No decorative metrics, gradients, glass effects or neon.

## Component boundaries

Frontend: design tokens and typography; application shell/sidebar; command palette/dialog; buttons, fields, cards, tables, badges, state panels and chart; screen renderers; one bridge client and view state layer. Never inject query names as HTML.

Python: observation storage and aggregate queries; detector/monitor controller; report exports; narrow UI bridge; desktop startup and legacy Lab tools launch. Background threads do not call UI widgets directly. Shutdown stops owned workers and closes storage safely.

## Verification and delivery

Exercise real UDP observations and persisted queries; verify counts, deduplication of multi-rule anomalies, time filtering, history after reopening storage, bind errors and report contents. Preserve existing protocol and loopback tests. Inspect actual rendered desktop surfaces in dark and light mode, collapsed navigation, palette, all six screens and empty/error states. Check layout at the reference proportions and typical desktop size. Package local assets into the wheel and verify an installed build outside the source directory.

Update user documentation and the knowledge graph after implementation. Following the user's release preference, commit/push verified changes and publish a new version after local package verification. Never stage credentials or generated local telemetry. Release notes must identify native webview dependencies and the preserved Lab tools entry point.
