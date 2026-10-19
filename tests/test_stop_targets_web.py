"""CGI stop-list validation/rendering plus the real POST/save request path.

Extracted functions use deterministic backend replies; the full CGI POST fixture
intercepts every backend command and executes only printf for shell-argument
transport. No privileged entry point or real Docker/systemd command is executed.
The installed CGI parser is replaced with a minimal URL-encoded request parser.
"""
import json
import hashlib
import hmac
import os
from pathlib import Path
import re
import shlex
import subprocess
import tempfile
import time
import unittest
from urllib.parse import urlencode

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
        program += "\n".join(cgi_function(name) for name in ("checked_attr", "valid_stop_target_name", "validated_stop_targets", "render_stop_targets"))
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

    def serialize(self, data, success=True):
        program = "use strict; use warnings; use JSON::PP;\n"
        program += "\n".join(cgi_function(name) for name in (
            "valid_stop_target_name", "valid_stop_target_value", "stop_targets_csv", "shell_quote"))
        program += r'''
my $value = stop_targets_csv(decode_json($ENV{STOP_WEB_JSON}));
my $quoted = shell_quote($value);
my $roundtrip = qx{printf '%s' $quoted};
die "Shell argument changed" unless $? == 0 && $roundtrip eq $value;
print $value;
'''
        result = subprocess.run([BASH, "--noprofile", "--norc", "-s"], cwd=ROOT,
                                env={**os.environ, "STOP_WEB_JSON": json.dumps(data)},
                                input="perl -e " + shlex.quote(program) + "\n",
                                text=True, capture_output=True, timeout=20)
        if success:
            self.assertEqual(result.returncode, 0, result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, "", "Invalid entries must not emit a partial saved selection")
        return result

    def test_all_supported_systemd_names_roundtrip_without_unescaping(self):
        names = ("plain.service", "_worker.service", ":worker.service", "-worker.service", ".worker.service",
                 "worker:zone.service", "worker@zone:one@two.service", "worker@@.service",
                 r"worker@room\x20one.service", r"\x2dworker.service", r"raw\q.service", r"slash\.service",
                 "a" * 247 + ".service")
        records = [self.row(type="systemd", name=name, aliases=[name]) for name in names]
        output = self.request(records)
        self.assertIn("Status: 200 OK", output)
        for name in names:
            self.assertIn('value="systemd:' + name + '"', output)
        values = ["systemd:" + name for name in names] + ["docker:sonn-core"]
        self.assertEqual(self.serialize(values).stdout, ",".join(values))
        hashes = [{"type": "systemd", "name": name} for name in names]
        self.assertEqual(self.serialize(hashes).stdout, ",".join(values[:-1]))
        self.assertEqual(self.serialize(values + [values[0]]).stdout, ",".join(values))

    def test_invalid_names_are_rejected_consistently_by_renderer_and_save_import_helper(self):
        names = ("", ".service", "@worker.service", "worker@.service", "worker.socket",
                 "a" * 248 + ".service", "worker.service\n", "worker.service\r", "worker.service\u2028",
                 "bad name.service", "bad\tname.service", "worker/other.service", "worker*.service",
                 "worker?.service", "worker[one].service", "worker;id.service", "worker$(id).service",
                 "worker`id`.service", "worker'one.service", 'worker"one.service', "worker,one.service",
                 "wörker.service")
        records = [{"type": "systemd", "name": name} for name in names]
        records += [{"type": "docker", "name": name} for name in ("-option", "_leading", "with:colon", "with@at", r"with\slash", "sonn-core\n")]
        for record in records:
            with self.subTest(record=record):
                self.assertIn("Status: 500", self.request([self.row(**record)]))
                self.serialize([{"type": "systemd", "name": "mosquitto.service"}, record], success=False)
        for value in ({}, "invalid", [None], [{"type": [], "name": "demo.service"}], [{"type": "systemd", "name": []}]):
            with self.subTest(value=value):
                self.serialize(value, success=False)

    def test_save_import_and_preserved_selection_use_the_same_validator(self):
        self.assertIn("my $stop_targets = eval { stop_targets_csv($imported->{stop_targets}) };", SOURCE)
        self.assertIn("$stop_targets = eval { stop_targets_csv(\\@stop_targets) };", SOURCE)
        self.assertIn("stop_targets_csv($current->{stop_targets});", SOURCE)
        self.assertIn("grep { valid_stop_target_value($_) } $q->param('stop_targets')", SOURCE)

    def test_actual_cgi_post_preserves_literal_names_through_shell_argument_transport(self):
        values = [r"systemd:-worker@room\x20one@zone.service", r"systemd:_raw\q.service",
                  "systemd::worker.service", "systemd:worker@@.service", "docker:sonn-core"]
        with tempfile.TemporaryDirectory(prefix="hostbackup-cgi-stop-post-") as temporary:
            directory = Path(temporary)
            secret = "a" * 64
            (directory / "csrf-secret").write_text(secret + "\n", encoding="utf-8", newline="\n")
            token = hmac.new(secret.encode(), f"fixture|127.0.0.1|fixture|{int(time.time() / 3600)}".encode(),
                             hashlib.sha256).hexdigest()
            # Run the entire CGI and its real POST/save branch. Only the CGI
            # parser and external backend are doubled; the actual shell_quote
            # and run_shell code hand their command to a real shell/printf.
            # Every non-fixture subprocess is refused before it could execute.
            program = r'''
BEGIN {
    require HostBackupFixture;
    require JSON::PP;
    my %params;
    my $body = '';
    read(STDIN, $body, $ENV{CONTENT_LENGTH}) == $ENV{CONTENT_LENGTH} or die "Incomplete fixture POST";
    for my $pair (split /&/, $body) {
        my ($key, $value) = split /=/, $pair, 2;
        for ($key, $value) { $_ //= ''; tr/+/ /; s/%([0-9a-fA-F]{2})/chr(hex($1))/eg; }
        push @{$params{$key}}, $value;
    }
    no warnings 'redefine';
    *CGI::new = sub { bless {}, 'CGI' };
    *CGI::param = sub { my $values = $params{$_[1]} || []; return wantarray ? @$values : $values->[0]; };
    *CGI::request_method = sub { 'POST' };
    *CGI::cgi_error = sub { '' };
    my $original = \&CORE::GLOBAL::readpipe;
    *CORE::GLOBAL::readpipe = sub {
        my ($command) = @_;
        if ($command =~ /\Asudo -n '[^']+' 'save-config' /) {
            $command =~ s/\Asudo -n '[^']+' /q{printf '%s\0' }/e or die "Unexpected dispatcher";
            my $arguments = CORE::readpipe($command);
            die "Fixture shell failed: " . JSON::PP::encode_json($command) unless $? == 0;
            open my $out, '>', "$ENV{LBPDATADIR}/saved-arguments.json" or die $!;
            print $out JSON::PP::encode_json([split /\0/, $arguments, -1]);
            close $out or die $!;
            $? = 0;
            return '{}';
        }
        return $original->(@_);
    };
}
do './webfrontend/htmlauth/index.cgi';
die $@ if $@;
'''
            environment = {**os.environ, "PERL5LIB": "tests/browser/perl:tests/perl-stub:tests/perl",
                           "LBPDATADIR": directory.as_posix(), "REQUEST_METHOD": "POST",
                           "CONTENT_TYPE": "application/x-www-form-urlencoded",
                           "REMOTE_USER": "fixture", "REMOTE_ADDR": "127.0.0.1", "HTTP_USER_AGENT": "fixture",
                           "HTTP_X_HOSTBACKUP_REQUEST": "1", "HTTP_HOST": "localhost",
                           "HTTP_ORIGIN": "http://localhost", "HTTP_X_CSRF_TOKEN": token}
            parameters = [("action", "save-config"), ("backup_root", "/fixture/backup"),
                          ("stop_targets_loaded", "1"), ("metadata_mode", "native-strict"),
                          *(("stop_targets", value) for value in values)]
            for valid in (True, False):
                with self.subTest(valid=valid):
                    posted = parameters if valid else parameters + [("stop_targets", "systemd:bad;touch nope.service")]
                    body = urlencode(posted)
                    capture = directory / "saved-arguments.json"
                    capture.unlink(missing_ok=True)
                    result = subprocess.run([BASH, "--noprofile", "--norc", "-c", "perl -e " + shlex.quote(program)],
                                            cwd=ROOT, input=body, text=True, capture_output=True, timeout=30,
                                            env={**environment, "CONTENT_LENGTH": str(len(body))})
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    if valid:
                        self.assertIn('"ok":true', result.stdout)
                        arguments = json.loads(capture.read_text())
                        self.assertEqual(arguments[0], "save-config")
                        self.assertEqual(arguments[18], ",".join(values))
                    else:
                        self.assertIn('"ok":false', result.stdout)
                        self.assertFalse(capture.exists(), "Invalid POST must never invoke save-config")
                        self.assertFalse((ROOT / "nope.service").exists())

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
