"""Exercise the actual CGI renderer for saved backup-completion checks.

Only extracted display helpers run: no backend, privileged operation or backup
is invoked. Browser tests cover their integration in the real page.
"""
import json
from html import unescape
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


@unittest.skipUnless(BASH and Path(BASH).exists(), "Bash/Perl required for CGI renderer")
class ValidationDisplayTests(unittest.TestCase):
    def render(self, validation, backup_id="fixture-warning"):
        program = r'''
use strict; use warnings; use JSON::PP;
sub escapeHTML {
    my $value = defined $_[0] ? $_[0] : '';
    $value =~ s/&/&amp;/g;
    $value =~ s/</&lt;/g;
    $value =~ s/>/&gt;/g;
    $value =~ s/"/&quot;/g;
    return $value;
}
'''
        program += "\n".join(cgi_function(name) for name in
                            ("validation_display_text", "render_validation_details"))
        program += "\nmy $input = decode_json($ENV{VALIDATION_DISPLAY_INPUT});\n"
        program += "print render_validation_details($input->{validation}, $input->{id});\n"
        env = os.environ.copy()
        env["VALIDATION_DISPLAY_INPUT"] = json.dumps(dict(validation=validation, id=backup_id))
        result = subprocess.run([BASH, "--noprofile", "--norc", "-s"], cwd=ROOT, env=env,
                                input="perl -e " + shlex.quote(program) + "\n",
                                text=True, capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        return result.stdout

    def test_warning_shows_original_check_date_and_separates_content_report(self):
        result = self.render(dict(status="warning", checked_at="Fri Oct 15 10:15:00 2026", checks=[
            dict(name="Backup-Groesse plausibel", ok=False, value=0),
            dict(name="manifest.json vorhanden", ok=True),
        ]))
        self.assertIn('class="backup-validation-details" data-backup-id="fixture-warning"', result)
        self.assertIn("<summary>Hinweise ansehen</summary>", result)
        self.assertIn("Fri Oct 15 10:15:00 2026", result)
        self.assertIn("Dateiinhaltspr&uuml;fung und kein Restore-Test", result)
        self.assertIn('class="validation-check error"', result)
        self.assertIn('class="validation-check-value">0</p>', result)
        self.assertIn('class="validation-check ok"', result)

    def test_ok_and_error_have_clear_native_collapsible_summaries(self):
        for status, summary in (("ok", "Pr&uuml;fdetails"), ("error", "Hinweise ansehen")):
            with self.subTest(status=status):
                result = self.render(dict(status=status, checks=[]))
                self.assertIn(f"<summary>{summary}</summary>", result)
                self.assertNotIn(" open", result)
                self.assertNotIn("<form", result)
                self.assertNotIn("data-load-action", result)
                self.assertIn("Keine lesbaren Einzelpr&uuml;fungen", result)

    def test_optional_and_informational_results_are_not_labelled_hard_errors(self):
        result = self.render(dict(status="warning", checks=[
            dict(name="Docker absent", ok=False, optional=True),
            dict(name="Metadata limitation", ok=False, informational=True),
            dict(name="Hardlink statistics", ok=True, optional=True, informational=True),
        ]))
        self.assertIn("Hinweis (optional)", result)
        self.assertIn("Hinweis (Information)", result)
        self.assertIn("OK (optional) (Information)", result)
        self.assertNotIn('class="validation-check error"', result)

    def test_check_names_values_details_timestamp_and_id_are_html_escaped(self):
        payload = '<img src=x onerror="alert(1)"><script>bad()</script>&'
        result = self.render(dict(status="warning", checked_at=payload, checks=[
            dict(name=payload, ok=False, value=payload, details=payload),
        ]), backup_id='id" onclick="bad()')
        self.assertNotIn("<img", result)
        self.assertNotIn("<script", result)
        self.assertNotIn('data-backup-id="id" onclick=', result)
        self.assertIn("&lt;img", result)
        self.assertIn('data-backup-id="id&quot; onclick=&quot;bad()"', result)

    def test_unicode_json_fields_survive_mixed_cgi_byte_output(self):
        value = 'Grösse geprüft – 日本語 😀 <script>nicht ausführen</script>'
        result = self.render(dict(status="warning", checked_at=value, checks=[
            dict(name=value, ok=False, value=value, details=value),
        ]))
        self.assertTrue(result.isascii(), result)
        self.assertIn("&#246;", result)
        self.assertIn("&#128512;", result)
        self.assertNotIn("<script>", result)
        self.assertIn(value, unescape(result))
        self.assertNotIn("\ufffd", result)

    def test_malformed_json_shapes_never_become_success_or_crash(self):
        for validation in (None, True, 1, "bad", [], {}):
            with self.subTest(validation=validation):
                self.assertEqual(self.render(validation), "")
        result = self.render(dict(status={}, checked_at=[], checks=[None, [], "bad", {},
            dict(name={}, value=[], details={}, ok="false", optional="true", informational=1),
            dict(name="strict false", ok=False, optional="true", informational="true"),
        ]))
        self.assertIn("nicht lesbar", result)
        self.assertIn("Ergebnis nicht lesbar", result)
        self.assertNotIn('class="validation-check ok"', result)
        self.assertIn('class="validation-check error"', result)
        self.assertNotIn("HASH(", result)
        self.assertNotIn("ARRAY(", result)
        self.assertIn("Gepr&uuml;ft: nicht gespeichert", result)
        self.assertIn("Keine lesbaren Einzelpr&uuml;fungen", self.render(dict(status="warning", checks={})))

    def test_large_saved_fields_and_check_lists_are_bounded_with_explicit_notice(self):
        result = self.render(dict(status="warning", checked_at="D" * 500, checks=[
            dict(name="N" * 800, ok=False, value="V" * 9000, details="T" * 9000)
        ]))
        self.assertIn("[gek&uuml;rzt]", result)
        self.assertNotIn("N" * 257, result)
        self.assertNotIn("V" * 4097, result)
        self.assertNotIn("T" * 4097, result)
        self.assertNotIn("D" * 161, result)
        result = self.render(dict(status="warning", checks=[dict(name=str(i), ok=True) for i in range(120)]))
        self.assertEqual(result.count('class="validation-check ok"'), 100)
        self.assertIn("Weitere Pr&uuml;fpunkte sind ausgeblendet", result)


class ClosablePanelMarkupTests(unittest.TestCase):
    def test_result_and_monitor_have_dedicated_accessible_view_controls(self):
        self.assertRegex(SOURCE, r'id="operation-result-toggle"[^>]*aria-controls="operation-result"')
        self.assertRegex(SOURCE, r'id="operation-result"[^>]*role="region"')
        self.assertRegex(SOURCE, r'id="task-monitor-toggle"[^>]*aria-controls="task-monitor-content"')
        self.assertIn('data-close-view="task-monitor"', SOURCE)
        monitor = SOURCE.split('<section class="panel task-monitor"', 1)[1].split('</section>', 1)[0]
        self.assertLess(monitor.index('id="task-state"'), monitor.index('id="task-monitor-content"'))

    def test_browser_restore_close_links_keep_non_javascript_fallback(self):
        for panel in ("backup-browser", "restore-panel"):
            self.assertRegex(SOURCE, rf'<a [^>]*data-close-view="{panel}"[^>]*href="[^\"]+"')
            self.assertRegex(SOURCE, rf'<button [^>]*data-show-view="{panel}"[^>]*hidden>')
        self.assertRegex(SOURCE, r'<details id="restore-plan-details"[^>]*hidden><summary>Restore-Vorschau</summary><pre id="restore-plan-output"')

    def test_rows_include_completion_details_without_changing_backend_actions(self):
        self.assertIn('render_validation_details($validation, $raw_id)', cgi_function("render_backup_rows"))
        self.assertNotIn("backend_cmd", cgi_function("render_validation_details"))


@unittest.skipUnless(BASH and Path(BASH).exists(), "Bash/Perl required for CGI busy handling")
class BusyOperationWebTests(unittest.TestCase):
    def request(self, status, output, action=None):
        program = r'''
use strict; use warnings; use JSON::PP;
BEGIN {
  *CORE::GLOBAL::readpipe = sub {
    die "Unexpected command: $_[0]" unless $_[0] eq 'fixture-command 2>&1';
    $? = int($ENV{BUSY_WEB_STATUS}) << 8;
    return $ENV{BUSY_WEB_OUTPUT};
  };
}
'''
        program += cgi_function("run_shell") + "\n"
        if action is None:
            program += 'my ($status, $output) = run_shell("fixture-command"); print encode_json({status => $status, output => $output});\n'
        else:
            program += r'''
my $action = $ENV{BUSY_WEB_ACTION};
my $backup_id = 'fixture-backup';
my $q = bless {}, 'FixtureQuery';
sub FixtureQuery::param { return undef; }
sub backend_cmd { return 'fixture-command'; }
sub reject_request { print encode_json({status => $_[0], output => $_[1]}); exit; }
sub json_response { print encode_json({status => '200 OK', data => $_[0]}); exit; }
'''
            if action == "restore-plan":
                pattern = r"^if \(\$action eq 'restore-plan'\) \{\n.*?^\}"
            else:
                pattern = r"^if \(\$action =~ /\^\(\?:task-overview\|.*?^\}"
            handler = re.search(pattern, SOURCE, re.M | re.S)
            self.assertIsNotNone(handler)
            program += handler.group(0)
        result = subprocess.run([BASH, "--noprofile", "--norc", "-s"], cwd=ROOT,
                                env={**os.environ, "BUSY_WEB_STATUS": str(status),
                                     "BUSY_WEB_OUTPUT": output, "BUSY_WEB_ACTION": action or ""},
                                input="perl -e " + shlex.quote(program) + "\n",
                                text=True, capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        return json.loads(result.stdout)

    def test_only_exact_contention_messages_with_exit_five_are_translated(self):
        for output in ("Another HostBackup operation is active.\n", "Backup is busy: backup-20261015\n"):
            with self.subTest(output=output):
                result = self.request(5, output)
                self.assertEqual(result["status"], 5)
                self.assertIn("Diese Aktion ist waehrend", result["output"])
                self.assertIn("Live-Status und gespeicherte Hinweise bleiben erreichbar", result["output"])
                self.assertIn("nicht unterbrochen", result["output"])

    def test_unrelated_exit_five_and_other_exit_codes_keep_original_diagnostics(self):
        for status, output in ((5, "Some different error"), (5, "Prefix\nAnother HostBackup operation is active.\n"),
                               (5, "Backup is busy: bad/id\n"), (13, "Another HostBackup operation is active.\n"),
                               (0, "Another HostBackup operation is active.\n"), (64, "flock: permission denied\n")):
            with self.subTest(status=status, output=output):
                self.assertEqual(self.request(status, output), dict(status=status, output=output))

    def test_busy_get_endpoints_return_conflict_and_readable_reason(self):
        for action in ("backup-preview", "storage-info", "inspect-backup", "verification-report", "restore-plan"):
            with self.subTest(action=action):
                result = self.request(5, "Another HostBackup operation is active.\n", action)
                self.assertEqual(result["status"], "409 Conflict")
                self.assertIn("Diese Aktion ist waehrend", result["output"])

    def test_nonbusy_get_errors_keep_existing_error_status_and_diagnostics(self):
        for action, status in (("backup-preview", "500 Internal Server Error"), ("restore-plan", "400 Bad Request")):
            with self.subTest(action=action):
                result = self.request(13, "Fixture permission denied", action)
                self.assertEqual(result, dict(status=status, output="Fixture permission denied"))


if __name__ == "__main__":
    unittest.main()
