# Browser regression tests

The test renders the actual Perl CGI using a deterministic configuration fixture,
then serves the real JavaScript/CSS over an isolated loopback HTTP server. All
application API requests are fixture responses: no real backups, restores,
configuration changes, deletions or privileged backend actions run. The CGI may
perform its normal read-only mount discovery while rendering the target picker.

Run from this directory:

```sh
npm ci --ignore-scripts
npx playwright install chromium
npm test
```

GitHub Actions runs this as a mandatory build gate, with a locked Playwright
version. Windows can instead use an already installed Edge browser by setting
`HOSTBACKUP_BROWSER_EXECUTABLE` to its full executable path; Git Bash/Perl are
required for the CGI renderer. No browser profile or production session is used.

Each run prints a JSON receipt and saves desktop/mobile screenshots under a new
`hostbackup-browser-*` OS temporary directory. These artifacts and dependency
directories are not part of plugin packages. Tests cover actual browser startup,
late-loaded controls, dirty state, failed saves, CSRF refresh and save races,
configuration validation, task discovery/completion, both log scroll axes,
responsive layout and keyboard/dynamic tooltips. The browser-specific LoxBerry
header fixture emits the CGI's actual head additions instead of injecting its
own asset URLs. Tests prime an obsolete unversioned stylesheet in the browser
cache, then verify that content-fingerprinted CSS/JavaScript are loaded. Overview
checks cover matching white content areas, separated titles and values (also
without CSS), four desktop/two tablet/one mobile column and long paths/timestamps.
The compact overview keeps four primary values visible and puts full IDs, target
paths and report actions in a native disclosure. Tests exercise Enter/Space,
initially closed state, preserved state during polling, no report request on
expansion, and visible failure/recovery notices and loaded reports while closed.
The suite currently emits 19 browser-check receipts, including the readable
retention phase while the task is still running, source selection, and detailed
metadata failures with explicit, unsaved-only profile assistance. Dedicated
`overview-desktop.png`, `overview-expanded.png`, `overview-mobile.png` and
`overview-mobile-expanded.png` screenshots supplement the full-page screenshots.
Storage calculation and runtime-check backend behavior are not validated by
these UI fixtures; their known limitations are documented in the
[1.0.0 release notes](../../docs/RELEASE-1.0.0.md). A successful main-branch build
creates a test artifact, not a published release or a plugin-page update.
The header fixture also reproduces the desktop/mobile global `.wide` rules from
[LoxBerry 4.0.0.15 main.css](https://github.com/mschlenstedt/Loxberry/blob/50cfa335c1c8f2282dc8ed503a5af3587547030d/webfrontend/html/system/css/main.css#L244).
That legacy class carries typography, not only layout; its inherited large font,
bold weight, and letter spacing caused oversized text inside the source settings.
Before the fix, the regression failed at a 1440px viewport with 32.72px paragraph
text, font weight 700, and 3.272px letter spacing. Failed typography checks save
`source-typography-reproduction.json` and `source-typography-regression.png`.

Assertions keep source copy at most 14px with normal weight/spacing and summaries
at most 15px with the same bold weight as the existing plugin disclosures.
A separate, temporary late-loaded global `p, summary` rule uses deliberately
oversized synthetic typography to stress isolation; it is removed before other
layout tests and is not represented as an actual LoxBerry theme declaration.

The source fixture includes more than 80 mounts, including system directories,
Docker overlays, USB, NAS, and a selected but unmounted source. Tests keep root,
USB/NAS, and explicit selections outside the initially closed technical group,
bound the primary/technical scrolling areas to 420px/320px, and check compact
desktop/mobile panel height. Opening, refreshing, changing, and resetting a
technical source must preserve disclosure state and exact source-selection JSON.
`source-selection-desktop.png`, `source-selection-mobile.png`, and
`metadata-diagnostics-desktop.png` provide focused visual evidence.

These deliberately narrow fixture styles are not a full LoxBerry theme or a
substitute for testing the installed plugin on a real device. NAS behavior and
privileged source traversal require the separate backend/Linux tests.
