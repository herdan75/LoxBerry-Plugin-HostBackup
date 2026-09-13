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
responsive layout and keyboard/dynamic tooltips.
