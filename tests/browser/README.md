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
The suite currently emits 15 browser-check receipts, including the readable
retention phase while the task is still running. Dedicated
`overview-desktop.png`, `overview-expanded.png`, `overview-mobile.png` and
`overview-mobile-expanded.png` screenshots supplement the full-page screenshots.
Storage calculation and runtime-check backend behavior are not validated by
these UI fixtures; their known limitations are documented in the
[1.0.0 release notes](../../docs/RELEASE-1.0.0.md). A successful main-branch build
creates a test artifact, not a published release or a plugin-page update.
The generic fixture styles are not a full LoxBerry
theme or a substitute for testing the installed plugin on a real device.
