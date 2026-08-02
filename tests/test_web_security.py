#!/usr/bin/env python3
import pathlib
import re
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
CGI = (ROOT / "webfrontend" / "htmlauth" / "index.cgi").read_text(encoding="utf-8")
BACKEND = (ROOT / "bin" / "hostbackup.sh").read_text(encoding="utf-8")
STYLE = (ROOT / "webfrontend" / "htmlauth" / "assets" / "style.css").read_text(
    encoding="utf-8"
)


class WebSecurityTests(unittest.TestCase):
    def test_every_literal_post_form_contains_csrf_field(self) -> None:
        forms = re.findall(
            r'<form\b[^>]*method="post"[^>]*>.*?</form>', CGI, flags=re.IGNORECASE | re.DOTALL
        )
        self.assertGreaterEqual(len(forms), 10)
        for form in forms:
            self.assertRegex(form, r"\$(?:csrf|csrf_html)\b")

    def test_dynamic_delete_form_contains_csrf(self) -> None:
        self.assertIn("csrf.name = 'csrf_token'", CGI)
        self.assertIn("data-csrf-token=", CGI)

    def test_restore_has_typed_challenge_and_degraded_gate(self) -> None:
        self.assertIn('name="restore_challenge"', CGI)
        self.assertIn('name="confirm_degraded"', CGI)
        self.assertIn("requires_degraded_confirmation", CGI)
        self.assertIn("requires_offline_restore", CGI)

    def test_all_metadata_profiles_are_exposed(self) -> None:
        for mode in ("native-strict", "network-compatible", "fake-super", "portable-archive"):
            self.assertIn(f'value="{mode}"', CGI)
        for helper in (
            "$info_metadata_native",
            "$info_metadata_network",
            "$info_metadata_fake_super",
            "$info_metadata_portable",
        ):
            self.assertIn(helper, CGI)
        self.assertIn("Standardeinstellung:</strong> Native Strict", CGI)
        self.assertIn('class="metadata-default-badge">Standard', CGI)

    def test_network_compatible_is_informational_for_backup(self) -> None:
        target_info = re.search(
            r"backup_target_info\(\) \{(?P<body>.*?)\n\}\n\ninstall_schedule",
            BACKEND,
            flags=re.DOTALL,
        )
        preflight = re.search(
            r"preflight_backup\(\) \{(?P<body>.*?)\n\}\n\nrestore_eligibility",
            BACKEND,
            flags=re.DOTALL,
        )
        validation = re.search(
            r"validate_completed_backup\(\) \{(?P<body>.*?)\n\}\n\nmanifest_started_at",
            BACKEND,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(target_info)
        self.assertIsNotNone(preflight)
        self.assertIsNotNone(validation)
        self.assertRegex(
            target_info.group("body"),
            r'(?s)\[ "\$mode" = "network-compatible" \].*?status="info"',
        )
        self.assertIn('"notices": $notices_json', preflight.group("body"))
        self.assertNotRegex(
            preflight.group("body"),
            r'(?s)\[ "\$mode" = "network-compatible" \].*?status="warning"',
        )
        network_validation = re.search(
            r'if \[ "\$metadata_mode_value" = "network-compatible" \]; then(?P<body>.*?)\n  fi',
            validation.group("body"),
            flags=re.DOTALL,
        )
        self.assertIsNotNone(network_validation)
        self.assertNotIn("metadata_ok=false", network_validation.group("body"))
        self.assertIn("metadata_informational=true", network_validation.group("body"))

    def test_empty_backup_target_is_an_informational_state(self) -> None:
        target_info = re.search(
            r"backup_target_info\(\) \{(?P<body>.*?)\n\}\n\ninstall_schedule",
            BACKEND,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(target_info)
        self.assertIn('"configured": false', target_info.group("body"))
        self.assertIn('"status": "info"', target_info.group("body"))
        self.assertIn("exists $target_info->{configured}", CGI)

    def test_info_bubbles_are_kept_inside_the_viewport(self) -> None:
        for marker in (
            "positionInfoBubble",
            "getBoundingClientRect",
            "window.innerWidth",
            "info-bubble-above",
        ):
            self.assertIn(marker, CGI)

    def test_preflight_confirmation_only_appears_after_a_warning(self) -> None:
        self.assertIn("my $preflight_warning = '';", CGI)
        self.assertIn("if (length $preflight_warning)", CGI)
        self.assertIn("$preflight_accept_control", CGI)
        self.assertIn("Backup trotz dieser Warnhinweise starten", CGI)
        self.assertNotIn("Preflight-Warnungen für diesen Start akzeptieren", CGI)

    def test_full_baseline_preflight_requires_estimated_free_space(self) -> None:
        preflight = re.search(
            r"preflight_backup\(\) \{(?P<body>.*?)\n\}\n\nrestore_eligibility",
            BACKEND,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(preflight)
        body = preflight.group("body")
        self.assertIn('baseline_reference="$(latest_complete_backup "$root")"', body)
        self.assertIn('estimate_backup="$(latest_sized_complete_backup "$root")"', body)
        self.assertIn('baseline_space_requirement_mb "$estimate_bytes"', body)
        self.assertRegex(
            body,
            r'(?s)\[ "\$available_mb" -lt "\$baseline_required_mb" \].*?baseline_space_ok=false',
        )
        self.assertIn('elif [ "$baseline_space_ok" != "true" ]; then', body)
        self.assertIn('"full_baseline_required": $full_baseline_required', body)

    def test_live_log_keeps_all_updates_without_wrapping_lines(self) -> None:
        self.assertIn("function normalizeLogForDisplay(value)", CGI)
        self.assertIn("String.fromCharCode(13, 10)", CGI)
        self.assertIn("String.fromCharCode(13)", CGI)
        self.assertIn("String.fromCharCode(27)", CGI)
        self.assertIn("normalizeLogForDisplay(decodeLog(data.content_b64))", CGI)
        terminal = re.search(r"\.terminal\s*\{(?P<body>.*?)\n\}", STYLE, flags=re.DOTALL)
        self.assertIsNotNone(terminal)
        self.assertIn("overflow: auto", terminal.group("body"))
        self.assertIn("overflow-wrap: normal", terminal.group("body"))
        self.assertIn("white-space: pre", terminal.group("body"))
        self.assertIn("word-break: normal", terminal.group("body"))

    def test_export_download_rejects_symlinks(self) -> None:
        self.assertRegex(CGI, r"!-f \$archive \|\| -l \$archive")

    def test_settings_change_popup_tracks_all_setting_types(self) -> None:
        self.assertIn('id="settings-change-popup"', CGI)
        self.assertIn('aria-hidden="true"', CGI)
        self.assertIn(
            'form="settings-save-form"$config_action_disabled>Änderungen speichern', CGI
        )
        self.assertIn("form.addEventListener('input'", CGI)
        self.assertIn("form.addEventListener('change'", CGI)
        for name in (
            "backup_root",
            "keep_backups",
            "metadata_mode",
            "backup_mode",
            "schedule_enabled",
            "schedule_mode",
            "schedule_time",
            "schedule_weekdays",
            "schedule_monthdays",
            "schedule_months",
            "pre_backup_hook",
            "post_backup_hook",
            "rsync_extra_excludes",
            "root_permission_ack",
            "mail_notify_enabled",
            "mail_notify_to",
            "mail_notify_success",
            "mail_notify_failure",
            "mail_notify_stopped",
            "mail_notify_restore",
            "stop_targets",
            "create_export_after_backup",
        ):
            self.assertRegex(CGI, rf"\b{re.escape(name)}:\s*'")
        self.assertIn("changedAt[name] = new Date()", CGI)
        self.assertIn("delete changedAt[name]", CGI)
        self.assertIn("refreshName('stop_targets')", CGI)
        self.assertIn("valueSeparator = String.fromCharCode(31)", CGI)
        self.assertIn(r"state.split(/\\r?\\n/)", CGI)

    def test_failed_config_load_cannot_overwrite_saved_settings(self) -> None:
        self.assertIn("my $config_loaded = 0;", CGI)
        self.assertIn("$config_loaded = 1;", CGI)
        self.assertIn('class="settings-load-guard"$config_action_disabled', CGI)
        self.assertIn("Gespeicherte Einstellungen wurden nicht geladen.", CGI)
        self.assertIn("Speichern und Backup-Start bleiben gesperrt", CGI)
        self.assertIn("type=\"submit\"$config_action_disabled>Backup starten", CGI)

    def test_csrf_secret_rejects_unsafe_types(self) -> None:
        self.assertIn('die "Unsicheres Plugin-Datenverzeichnis" if -l $datadir', CGI)
        self.assertIn("if (-e $path && (!-f $path || -l $path))", CGI)


if __name__ == "__main__":
    unittest.main()
