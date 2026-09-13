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
without CSS), two desktop columns, one mobile column and long paths/timestamps.
Dedicated `overview-desktop.png` and `overview-mobile.png` screenshots supplement
the full-page screenshots. The generic fixture styles are not a full LoxBerry
theme or a substitute for testing the installed plugin on a real device.
