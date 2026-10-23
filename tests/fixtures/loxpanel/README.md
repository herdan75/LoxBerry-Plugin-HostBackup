# LoxPanel compatibility fixtures

These unmodified controller files are test data, not HostBackup runtime code.
They must never be executed against a real Docker daemon or installed as part
of HostBackup. The integration tests run only the controller's `check` command
and, for v0.9.9, its `boot` route
in a disposable directory with fake `sudo` and `docker` commands.

## Provenance

`manifest.json` pins the download URL, archive SHA-256 (published release
assets), controller SHA-256 and Git blob (source references where available).
The eight published plugin ZIPs available on 2026-10-22, v0.3.0 through v0.7.0,
all contain the same 4,237-byte controller. The source commit described upstream
as v0.2.7 and the v0.2.8/v0.2.9 tags also contain that identical file. They are
recorded as source evidence, not claimed to be available release assets.

That released controller uses `loxpanel_stopped.cfg` for an intentional stop;
it does not implement the newer watchdog flock. The second fixture is the
controller at commit `61bfd1d82e86f6feb06162e11e41e3fca7944bf6`, which implements
both the intentional-stop marker and `.loxpanel-ctl.lock`. It is recorded as
pinned source, not as a released plugin ZIP.

The v0.9.9 release ZIP published on 2026-10-23 contains a distinct 18,272-byte
controller, recorded separately as `loxpanel-controller-v0.9.9.sh`. Its `check`
dispatches to `pruefen()`, which preserves the intentional-stop and flock
checks. Its new `boot` route removes an intentional-stop marker before calling
the same guarded function. Linux tests exercise both routes under the real
HostBackup lock, the marker during normal checks, and restart after lock release.
The ZIP digest is checked against the release asset before adding this fixture;
the untouched controller's digest is checked offline on every regression run.

Fixtures retain the upstream installation placeholders. Tests substitute only
`REPLACELBPCONFIGDIR` and `REPLACELBPDATADIR`, as a LoxBerry installation does.
Byte/hash tests use the untouched fixture before those substitutions. No
network is needed to execute the regression tests; a changed upstream package
requires deliberate re-download, review and a new recorded hash.

## Upstream licence and required notice

Required Notice: Copyright © 2025–2026 Lenardo1 and LoxPanel contributors (https://github.com/Lenardo1/Loxpanel)

The `.sh` fixtures are licensed by their upstream authors under the
[PolyForm Noncommercial License 1.0.0](https://polyformproject.org/licenses/noncommercial/1.0.0).
See the [upstream licence](https://github.com/Lenardo1/Loxpanel/blob/61bfd1d82e86f6feb06162e11e41e3fca7944bf6/LICENSE.md).
This licence applies to those third-party fixtures, not to HostBackup's own code.
They are included solely for noncommercial compatibility research and testing.
