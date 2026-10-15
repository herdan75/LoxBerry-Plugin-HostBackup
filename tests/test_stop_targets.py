"""Exercise the real read-only service discovery with disposable command doubles.

The backend entry point is not sourced. One Linux smoke test additionally uses
the real systemd manager through an inventory/property-read-only adapter. No host
Docker command or service mutation runs. The genuine timeout bounds subprocess
trees; timeout tests only shorten its deadline.
"""

import fnmatch
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "bin" / "hostbackup.sh"
BASH = shutil.which("bash") or (r"C:\Program Files\Git\bin\bash.exe" if os.name == "nt" else None)


def function(name):
    match = re.search(rf"^{re.escape(name)}\(\) \{{\n.*?^\}}\n(?=\n)", SOURCE.read_text(encoding="utf-8"), re.M | re.S)
    if not match:
        raise AssertionError(f"Missing function {name}")
    return match.group(0)


# These are executables rather than shell-function doubles so GNU timeout really
# supervises the Perl discovery process and its child commands.
COMMAND_STUB = r'''#!/usr/bin/perl
use strict;
use warnings;
use JSON::PP;
binmode STDOUT, ":encoding(UTF-8)";
my ($tool) = $0 =~ m{([^/]+)$};
open my $input, "<", "fixture.json" or die $!;
my $fixture = do { local $/; decode_json(<$input>) };
close $input;
open my $calls, ">>", "calls.jsonl" or die $!;
print {$calls} encode_json([$tool, @ARGV]), "\n";
close $calls;
my $operation = "$tool:$ARGV[0]";
if (exists($fixture->{operation_delays}) && exists($fixture->{operation_delays}{$operation})) {
  select undef, undef, undef, $fixture->{operation_delays}{$operation};
}
if (($fixture->{delay_operation} // "") eq $operation) {
  select undef, undef, undef, ($fixture->{delay_seconds} // 5);
}
if (($fixture->{fail_operation} // "") eq $operation) {
  print "partial-untrusted-output\n";
  print STDERR "controlled discovery failure\n";
  exit 7;
}
if ($tool eq "docker" && $ARGV[0] eq "ps") {
  print join("\t", @$_), "\n" for @{$fixture->{docker} // []};
  exit 0;
}
my $units = $fixture->{units} // {};
if ($tool eq "systemctl" && $ARGV[0] eq "list-units") {
  for my $name (sort keys %$units) {
    my $unit = $units->{$name};
    next unless ($unit->{ActiveState} // "active") eq "active"
      && ($unit->{SubState} // "running") eq "running";
    print "$name loaded active running ", ($unit->{Description} // $name), "\n";
  }
  exit 0;
}
if ($tool eq "systemctl" && $ARGV[0] eq "list-unit-files") {
  print "$_ enabled enabled\n" for sort keys %$units;
  exit 0;
}
if ($tool eq "systemctl" && $ARGV[0] eq "show") {
  shift @ARGV while @ARGV && $ARGV[0] ne "--";
  shift @ARGV;
  exit 98 unless @ARGV && @ARGV <= 128;
  for my $name (@ARGV) {
    next if ($fixture->{omit_unit} // "") eq $name;
    my $unit = $units->{$name} or exit 97;
    my %properties = (
      Id => $name, Names => $name, LoadState => "loaded",
      ActiveState => "active", SubState => "running", Description => $name,
      ExecStart => "{ path=/usr/bin/example ; argv[]=/usr/bin/example ; }",
      FragmentPath => "/usr/lib/systemd/system/$name", %$unit,
    );
    for my $key (sort keys %properties) {
      next if ($fixture->{omit_property} // "") eq $key;
      next if grep { $_ eq $key } @{$fixture->{omit_properties_by_unit}{$name} // []};
      if ($key eq "ExecStart" && exists $fixture->{execution_commands_by_unit}{$name}) {
        print "ExecStart=$_\n" for @{$fixture->{execution_commands_by_unit}{$name}};
        next;
      }
      print "$key=$properties{$key}\n";
    }
    print "\n";
  }
  exit 0;
}
die "Unexpected command; writes/start/stop are forbidden: $tool @ARGV\n";
'''


@unittest.skipUnless(BASH and Path(BASH).exists(), "Bash is required for shell behavior tests")
class StopTargetDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="hostbackup-stop-targets-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        for name in ("docker", "systemctl"):
            script = self.bin / name
            script.write_text(COMMAND_STUB, encoding="utf-8", newline="\n")
            script.chmod(0o755)

    def run_discovery(self, fixture=None, selected=(), missing=(), expected=0, cap=None, invalid_config=False,
                      real_systemctl=None, timeout_result=None):
        config = self.root / "config.json"
        config.write_text("{broken" if invalid_config else json.dumps({"stop_targets": list(selected)}), encoding="utf-8")
        initial_config = config.read_bytes()
        (self.root / "fixture.json").write_text(json.dumps(fixture or {}), encoding="utf-8")
        (self.root / "calls.jsonl").write_text("", encoding="utf-8")
        source = r'''
set -euo pipefail
cd -- "$DISCOVERY_TEST_DIR"
export PATH="$PWD/bin:$PATH"
CONFIG_FILE="$PWD/config.json"
command() {
  if [ "${1:-}" = -v ]; then
    case " $MISSING_COMMANDS " in *" $2 "*) return 1 ;; esac
  fi
  builtin command "$@"
}
timeout() {
  [ "$1:$2:$3" = '-k:2s:45s' ] || return 99
  shift 3
  if [ -n "$TEST_TIMEOUT_RESULT" ]; then
    printf '{"partial":"not a valid inventory"}\n'
    return "$TEST_TIMEOUT_RESULT"
  fi
  if [ -n "$TEST_TIMEOUT_CAP" ]; then
    builtin command timeout -k 1s "$TEST_TIMEOUT_CAP" "$@"
  else
    builtin command timeout -k 2s 45s "$@"
  fi
}
'''
        source += function("discover_stop_targets") + "\ndiscover_stop_targets\n"
        result = subprocess.run(
            [BASH, "-s"], input=source, text=True, encoding="utf-8", capture_output=True,
            env={**os.environ, "DISCOVERY_TEST_DIR": self.root.as_posix(),
                 "MISSING_COMMANDS": " ".join(missing), "TEST_TIMEOUT_CAP": cap or "",
                 "DISCOVERY_REAL_SYSTEMCTL": real_systemctl or "",
                 "TEST_TIMEOUT_RESULT": str(timeout_result) if timeout_result is not None else ""},
            timeout=60, check=False,
        )
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        self.assertEqual(config.read_bytes(), initial_config, "Read-only discovery changed saved settings")
        self.calls = [json.loads(line) for line in (self.root / "calls.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertTrue(all(call[1] in ("ps", "list-units", "list-unit-files", "show") for call in self.calls))
        return result

    def test_saved_selections_labels_groups_and_real_active_recommendations(self):
        result = self.run_discovery({
            "docker": [["sonn-core", "sonn:latest", "Up 3 hours (healthy)"], ["stopped", "db:1", "Exited (0)"]],
            "units": {
                "mqtt.service": {"Description": "MQTT daemon"},
                "stats4lox.service": {"Description": "Stats4Lox", "ActiveState": "inactive", "SubState": "dead"},
                "plugin-db.service": {"Description": "User data", "ExecStart": "/opt/loxberry/bin/plugins/database/run"},
                "ordinary.service": {"Description": "Ordinary application"},
                "old.service": {"ActiveState": "inactive", "SubState": "dead"},
                "grafana.service": {"Description": "Grafana"},
            },
        }, selected=[{"type": "docker", "name": "sonn-core"}, {"type": "systemd", "name": "stats4lox.service"}])
        items = json.loads(result.stdout)
        by_name = {item["name"]: item for item in items}
        self.assertEqual(len(by_name), 7)
        self.assertNotIn("old.service", by_name)
        self.assertTrue(by_name["sonn-core"]["selected"])
        self.assertTrue(by_name["sonn-core"]["recommended"])
        self.assertFalse(by_name["stopped"]["recommended"])
        self.assertEqual(by_name["mqtt.service"]["label"], "MQTT / ZigbeeMQTT")
        self.assertTrue(by_name["stats4lox.service"]["selected"])
        self.assertFalse(by_name["stats4lox.service"]["recommended"])
        self.assertEqual(by_name["stats4lox.service"]["status"], "inactive/dead")
        self.assertTrue(by_name["plugin-db.service"]["recommended"])
        self.assertEqual(by_name["plugin-db.service"]["group"], "LoxBerry-/Plugin-Dienste")
        self.assertFalse(by_name["ordinary.service"]["recommended"])
        self.assertTrue(by_name["grafana.service"]["recommended"])
        for item in items:
            self.assertEqual(set(item), {"type", "name", "label", "group", "status", "details", "recommended", "selected"})
            self.assertIsInstance(item["selected"], bool)
            self.assertIsInstance(item["recommended"], bool)
        self.assertEqual(items, sorted(items, key=lambda item: (item["group"], item["label"])))

    def test_large_inventory_uses_bounded_batches_not_per_unit_queries(self):
        count = 300
        result = self.run_discovery({"units": {f"plugin-{i}.service": {"ExecStart": "/plugins/test/run"} for i in range(count)}})
        self.assertEqual(len(json.loads(result.stdout)), count)
        calls = [call for call in self.calls if call[0] == "systemctl"]
        shows = [call for call in calls if call[1] == "show"]
        self.assertEqual(len(shows), math.ceil(count / 128))
        self.assertEqual(len(calls), 2 + len(shows))
        self.assertTrue(all(1 <= len(call[call.index("--") + 1:]) <= 128 for call in shows))
        queried = [name for call in shows for name in call[call.index("--") + 1:]]
        self.assertEqual(len(queried), len(set(queried)))

    def test_protected_units_match_shell_safety_predicate_and_are_never_queried(self):
        protected = [
            "loxberry.service", "LoxBerryHostBackup.service", "loxberryhostbackup.service",
            "ssh.service", "sshd.service", "dropbear.service", "cron.service", "crond.service", "anacron.service",
            "dbus.service", "polkit.service", "systemd-journald.service", "systemd-.service", "udev.service",
            "getty@tty1.service", "serial-getty@ttyAMA0.service", "user@1001.service",
            "networking.service", "NetworkManager.service", "docker.service", "containerd.service",
            "apache2.service", "lighttpd.service", "nginx.service", "php-fpm.service", "php8.4-fpm.service",
            "sample.mount", "sample.socket", "sample.timer",
        ]
        allowed = ["ssh-custom.service", "my-docker.service", "systemdbackup.service", "php-worker.service", "user-app.service"]
        predicate = function("protected_systemd_service")
        patterns = [pattern for alternatives in re.findall(r"^[ \t]+([^\n()]+)\) return 0 ;;", predicate, re.M)
                    for pattern in alternatives.split("|")]
        self.assertTrue(patterns)
        for pattern in patterns:
            self.assertTrue(any(fnmatch.fnmatchcase(name, pattern) for name in protected),
                            f"Missing discovery parity fixture for shell protection pattern {pattern}")
        source = predicate + "\nfor unit in \"$@\"; do if protected_systemd_service \"$unit\"; then printf '%s\\n' \"$unit\"; fi; done\n"
        result = subprocess.run([BASH, "-c", source, "--", *protected, *allowed], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), protected)
        response = self.run_discovery({"units": {name: {} for name in protected + allowed}})
        self.assertEqual({item["name"] for item in json.loads(response.stdout)}, set(allowed))
        shows = [call for call in self.calls if call[1] == "show"]
        queried = {name for call in shows for name in call[call.index("--") + 1:]}
        self.assertFalse(queried.intersection(protected))

    def test_template_and_unsaveable_names_excluded_but_instance_preserved(self):
        response = self.run_discovery({"units": {
            "mqtt@.service": {}, "mqtt@main.service": {}, "mnt\\x2ddata.service": {},
        }})
        self.assertEqual([item["name"] for item in json.loads(response.stdout)], ["mqtt@main.service"])

    def test_systemd_alias_matches_names_without_duplicate_requested_rows(self):
        response = self.run_discovery({"units": {
            "mqtt-alias.service": {"Id": "mqtt-real.service", "Names": "mqtt-real.service mqtt-alias.service"},
        }}, selected=[{"type": "systemd", "name": "mqtt-alias.service"}])
        item, = json.loads(response.stdout)
        self.assertEqual(item["name"], "mqtt-alias.service")
        self.assertTrue(item["selected"])

    def test_aliases_cannot_expose_protected_canonical_or_alternative_names(self):
        response = self.run_discovery({"units": {
            "dbus-org.freedesktop.resolve1.service": {
                "Id": "systemd-resolved.service", "Names": "systemd-resolved.service dbus-org.freedesktop.resolve1.service"},
            "network-alias.service": {"Id": "NetworkManager.service", "Names": "NetworkManager.service network-alias.service"},
            "ssh-alias.service": {"Id": "sshd.service", "Names": "sshd.service ssh-alias.service"},
            "canonical.service": {"Id": "canonical.service", "Names": "canonical.service docker.service"},
            "mqtt.service": {},
        }})
        self.assertEqual([item["name"] for item in json.loads(response.stdout)], ["mqtt.service"])

    def test_missing_optional_tools_and_valid_empty_inventory(self):
        for missing in ((), ("docker",), ("systemctl",), ("docker", "systemctl")):
            with self.subTest(missing=missing):
                response = self.run_discovery(missing=missing)
                self.assertEqual(json.loads(response.stdout), [])
                self.assertTrue(all(call[0] not in missing for call in self.calls))

    def test_missing_timeout_is_failure_not_empty_success(self):
        response = self.run_discovery(missing=("timeout",), expected=1)
        self.assertEqual(response.stdout, "")
        self.assertIn("requires timeout", response.stderr)
        self.assertEqual(self.calls, [])

    def test_command_failures_never_publish_partial_docker_or_systemd_results(self):
        for operation in ("docker:ps", "systemctl:list-units", "systemctl:list-unit-files", "systemctl:show"):
            with self.subTest(operation=operation):
                response = self.run_discovery({
                    "docker": [["sonn-core", "sonn:latest", "Up 1 hour"]],
                    "units": {"mqtt.service": {}}, "fail_operation": operation,
                }, expected=7)
                self.assertEqual(response.stdout, "")
                self.assertIn("Service discovery query failed", response.stderr)

    def test_incomplete_metadata_or_disappeared_service_is_failure(self):
        for update in ({"omit_unit": "mqtt.service"}, {"omit_property": "Description"},
                       {"units": {"mqtt.service": {"LoadState": "not-found"}}}):
            with self.subTest(update=update):
                response = self.run_discovery({"units": {"mqtt.service": {}}, **update}, expected=255)
                self.assertEqual(response.stdout, "")
                self.assertTrue("properties" in response.stderr or "disappeared" in response.stderr)

    def test_empty_execution_array_is_optional_for_loaded_and_masked_units(self):
        response = self.run_discovery({"units": {
            "mqtt-masked.service": {"LoadState": "masked", "ActiveState": "inactive", "SubState": "dead"},
            "mqtt-stop-only.service": {"LoadState": "loaded", "ActiveState": "active", "SubState": "exited"},
        }, "omit_properties_by_unit": {
            "mqtt-masked.service": ["ExecStart"], "mqtt-stop-only.service": ["ExecStart"],
        }})
        by_name = {item["name"]: item for item in json.loads(response.stdout)}
        self.assertEqual(set(by_name), {"mqtt-masked.service", "mqtt-stop-only.service"})
        self.assertFalse(by_name["mqtt-masked.service"]["recommended"])
        self.assertTrue(by_name["mqtt-stop-only.service"]["recommended"])

    def test_all_repeated_execution_commands_contribute_to_plugin_classification(self):
        units = {"first.service": {"ActiveState": "active", "SubState": "exited"},
                 "second.service": {"ActiveState": "inactive", "SubState": "dead"}}
        commands = ["{ path=/opt/loxberry/bin/plugins/example/start ; }", "{ path=/usr/bin/true ; }"]
        response = self.run_discovery({"units": units,
            "execution_commands_by_unit": {name: commands for name in units}})
        by_name = {item["name"]: item for item in json.loads(response.stdout)}
        self.assertEqual(set(by_name), set(units))
        self.assertTrue(all(item["group"] == "LoxBerry-/Plugin-Dienste" for item in by_name.values()))
        self.assertTrue(by_name["first.service"]["recommended"])
        self.assertFalse(by_name["second.service"]["recommended"])

    def test_invalid_configuration_fails_before_discovery_and_does_not_change_it(self):
        response = self.run_discovery(invalid_config=True, expected=255)
        self.assertEqual(response.stdout, "")
        self.assertIn("Invalid service selection configuration", response.stderr)
        self.assertEqual(self.calls, [])

    def test_timeout_status_and_partial_output_are_handled_safely(self):
        for code in (124, 137):
            with self.subTest(code=code):
                response = self.run_discovery(timeout_result=code, expected=124)
                self.assertEqual(response.stdout, "")
                self.assertIn("timed out", response.stderr)
                self.assertEqual(self.calls, [])

    @unittest.skipUnless(sys.platform == "linux", "Process-group deadline behavior requires native Linux")
    def test_shared_deadline_covers_slow_child_and_emits_no_partial_json(self):
        for operation in ("docker:ps", "systemctl:show"):
            with self.subTest(operation=operation):
                started = time.monotonic()
                response = self.run_discovery({"units": {"mqtt.service": {}},
                    "delay_operation": operation, "delay_seconds": 10}, cap="1s", expected=124)
                self.assertLess(time.monotonic() - started, 8)
                self.assertEqual(response.stdout, "")
                self.assertIn("timed out", response.stderr)

    def test_shared_budget_is_not_restarted_for_each_command(self):
        response = self.run_discovery({"operation_delays": {
            "docker:ps": 0.6, "systemctl:list-units": 0.6, "systemctl:list-unit-files": 0.6,
        }}, cap="1.5s", expected=124)
        self.assertEqual(response.stdout, "")
        self.assertIn("timed out", response.stderr)

    def test_response_slower_than_previous_twenty_second_ui_limit_succeeds(self):
        started = time.monotonic()
        response = self.run_discovery({"delay_operation": "docker:ps", "delay_seconds": 21.9,
            "docker": [["sonn-core", "sonn:latest", "Up 1 hour"]]})
        self.assertGreaterEqual(time.monotonic() - started, 21)
        item, = json.loads(response.stdout)
        self.assertEqual(item["name"], "sonn-core")

    def test_descriptions_are_json_data_not_commands(self):
        description = "Überwachung; $(touch forbidden) <script>\"quoted\"</script>"
        response = self.run_discovery({"units": {"ordinary.service": {"Description": description}}})
        item, = json.loads(response.stdout)
        self.assertEqual(item["label"], description)
        self.assertFalse((self.root / "forbidden").exists())

    @unittest.skipUnless(sys.platform == "linux", "Real systemd discovery smoke test requires Linux")
    def test_real_systemctl_properties_are_parsed_without_service_mutations(self):
        required = os.environ.get("HOSTBACKUP_REQUIRE_LINUX_INTEGRATION") == "1"
        executable = shutil.which("systemctl")
        if not executable or not Path("/run/systemd/system").is_dir():
            if required:
                self.fail("Mandatory Linux discovery smoke test requires a running systemd manager")
            self.skipTest("No running systemd manager available")
        # Only inventory/property reads can reach the real service manager, even
        # if the discovery implementation accidentally adds a different command.
        (self.bin / "systemctl").write_text(r'''#!/usr/bin/perl
use strict;
use warnings;
use JSON::PP;
die "Only read-only systemctl queries allowed\n"
  unless @ARGV && $ARGV[0] =~ /\A(?:list-units|list-unit-files|show)\z/;
open my $calls, ">>", "calls.jsonl" or die $!;
print {$calls} encode_json(["systemctl", @ARGV]), "\n";
close $calls;
exec $ENV{DISCOVERY_REAL_SYSTEMCTL}, @ARGV;
die "Cannot execute real systemctl: $!\n";
''', encoding="utf-8", newline="\n")
        response = self.run_discovery(real_systemctl=executable)
        items = json.loads(response.stdout)
        self.assertIsInstance(items, list)
        self.assertTrue(any(call[1] == "show" for call in self.calls), "Real systemd property query was not exercised")
        self.assertTrue(all(item["type"] == "systemd" for item in items))
        self.assertTrue(all(isinstance(item["recommended"], bool) for item in items))


if __name__ == "__main__":
    unittest.main()
