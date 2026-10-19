"""Actual CGI stop-list validator/renderer/handler with a disposable backend reply.

No privileged entry point is executed; the subprocess runs only extracted Perl
functions with run_shell, HTML escaping and HTTP headers replaced by deterministic
test doubles. The installed CGI module itself is not under test here.
"""
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import unittest

from test_runtime_safety import BASH, ROOT


SOURCE = (ROOT / "webfrontend/htmlauth/index.cgi").read_text(encoding="utf-8")


def cgi_function(name):
    found = re.search(rf"^sub {re.escape(name)} \{{\n.*?^\}}", SOURCE, re.M | re.S)
    if not found:
        raise AssertionError("Missing CGI function " + name)
    return found.group(0)


@unittest.skipUnless(BASH and Path(BASH).exists(), "Bash/Perl required for CGI integration")
class StopTargetsWebTests(unittest.TestCase):
    def row(self, **changes):
        result = dict(type="docker", name="sonn-core", label="sonn-core", group="Docker-Container",
                      status="Up 37 hours", details="fixture:image", selected=True, recommended=True)
        result.update(changes)
        return result

    def request(self, data, status=0, raw=False):
        handler = re.search(r"^if \(\$action eq 'stop-targets'\) \{\n.*?^\}", SOURCE, re.M | re.S).group(0)
        program = "use strict; use warnings; use JSON::PP;\n"
        program += r'''
sub escapeHTML {
    my $value = defined $_[0] ? $_[0] : '';
    $value =~ s/&/&amp;/g;
    $value =~ s/</&lt;/g;
    $value =~ s/>/&gt;/g;
    $value =~ s/"/&quot;/g;
    return $value;
}
'''
        program += "\n".join(cgi_function(name) for name in ("checked_attr", "validated_stop_targets", "render_stop_targets"))
        program += r'''
my $action = 'stop-targets';
sub backend_cmd { die "Unexpected action" unless @_ == 1 && $_[0] eq 'stop-targets'; return 'fixture'; }
sub run_shell { return (int($ENV{STOP_WEB_STATUS}), $ENV{STOP_WEB_JSON}); }
sub header { my %fields = @_; return "Status: $fields{'-status'}\n\n"; }
'''
        program += handler
        env = os.environ.copy()
        env.update(STOP_WEB_STATUS=str(status), STOP_WEB_JSON=data if raw else json.dumps(data))
        command = "perl -e " + shlex.quote(program) + "\n"
        result = subprocess.run([BASH, "--noprofile", "--norc", "-s"], cwd=ROOT, env=env,
                                input=command, text=True, capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def test_complete_valid_list_renders_selected_targets_and_escapes_labels(self):
        output = self.request([self.row(label='<script>alert("fixture")</script>'),
                               self.row(type="systemd", name="squeezelite-lbp@inst_bad.service", selected=False)])
        self.assertIn("Status: 200 OK", output)
        self.assertIn('name="stop_targets_loaded" value="1"', output)
        self.assertRegex(output, r'value="docker:sonn-core"[^>]*checked')
        self.assertIn('value="systemd:squeezelite-lbp@inst_bad.service"', output)
        self.assertNotIn("<script>", output)
        self.assertIn("&lt;script&gt;", output)

    def test_genuine_empty_list_is_distinct_from_failed_discovery(self):
        output = self.request([])
        self.assertIn("Status: 200 OK", output)
        self.assertIn('name="stop_targets_loaded"', output)
        self.assertIn("Keine ausw", output)

    def test_systemd_aliases_render_as_escaped_json_without_duplicate_controls(self):
        output = self.request([self.row(type="systemd", name="mqtt.service",
                                       aliases=["mqtt.service", "mqtt-old.service"]), self.row()])
        self.assertIn("Status: 200 OK", output)
        self.assertIn('data-stop-aliases="[&quot;mqtt.service&quot;,&quot;mqtt-old.service&quot;]"', output)
        self.assertEqual(output.count('name="stop_targets"'), 2)
        self.assertNotIn('value="systemd:mqtt-old.service"', output)

    def test_invalid_alias_payload_or_ambiguous_identity_rejects_entire_list(self):
        bad_aliases = (None, "mqtt.service", {}, [None], [1], [True], [{}], [""],
                       ["bad\nname.service"], ["foo$(id).service"], ["ssh.socket"],
                       ["mqtt@.service"], ["mqtt.service", "mqtt.service"])
        for aliases in bad_aliases:
            with self.subTest(aliases=aliases):
                output = self.request([self.row(type="systemd", name="mqtt.service", aliases=aliases)])
                self.assertIn("Status: 500", output)
                self.assertNotIn('name="stop_targets_loaded"', output)
        for records in (
            [self.row(aliases=[])],
            [self.row(type="systemd", name="template@.service", aliases=[])],
            [self.row(type="systemd", name="mqtt.service", aliases=["other.service"]),
             self.row(type="systemd", name="other.service")],
            [self.row(type="systemd", name="mqtt.service", aliases=["shared.service"]),
             self.row(type="systemd", name="other.service", aliases=["shared.service"])],
        ):
            with self.subTest(records=records):
                self.assertIn("Status: 500", self.request(records))

    def test_invalid_json_and_wrong_container_never_render_empty_success(self):
        for data in ("", "warning\n[]", "{", "null", "{}", "true", '"text"', "[null]"):
            with self.subTest(data=data):
                output = self.request(data, raw=True)
                self.assertIn("Status: 500 Internal Server Error", output)
                self.assertNotIn('name="stop_targets_loaded"', output)

    def test_invalid_or_duplicate_records_reject_the_entire_list(self):
        for bad in (self.row(type="unknown"), self.row(name="bad\nname"), self.row(name=""),
                    self.row(name="foo$(whoami)"), self.row(selected="false"), self.row(recommended=1),
                    self.row(label={"unexpected": "object"}), self.row(details=None)):
            with self.subTest(bad=bad):
                output = self.request([self.row(), bad])
                self.assertIn("Status: 500 Internal Server Error", output)
                self.assertNotIn('name="stop_targets_loaded"', output)
        self.assertIn("Status: 500", self.request([self.row(), self.row()]))

    def test_backend_failure_never_exposes_diagnostics_or_loaded_marker(self):
        output = self.request('<script>PRIVATE-DIAGNOSTIC</script>', status=1, raw=True)
        self.assertIn("Status: 500 Internal Server Error", output)
        self.assertNotIn("PRIVATE-DIAGNOSTIC", output)
        self.assertNotIn('name="stop_targets_loaded"', output)

    def test_backend_deadline_is_a_distinct_gateway_timeout(self):
        output = self.request("Discovery timed out", status=124, raw=True)
        self.assertIn("Status: 504 Gateway Timeout", output)
        self.assertNotIn('name="stop_targets_loaded"', output)


if __name__ == "__main__":
    unittest.main()
