#!/usr/bin/env python3
import pathlib
import json
import re
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
CGI = (ROOT / "webfrontend" / "htmlauth" / "index.cgi").read_text(encoding="utf-8")
JS = (ROOT / "webfrontend" / "htmlauth" / "assets" / "hostbackup.js").read_text(encoding="utf-8")
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
            self.assertRegex(form, r"\$(?:csrf|csrf_html|native_csrf)\b")

    def test_dynamic_delete_form_contains_csrf(self) -> None:
        self.assertIn("input.name = 'csrf_token'", JS)
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
            self.assertIn(marker.replace("window.innerWidth", "root.innerWidth"), JS)

    def test_source_policy_labels_describe_scope_without_changing_stored_values(self) -> None:
        self.assertIn('<option value="local">Lokale Laufwerke; Netzfreigaben einzeln (empfohlen)</option>', CGI)
        self.assertIn('<option value="legacy">Alle eingebundenen Laufwerke und Netzfreigaben</option>', CGI)
        self.assertNotIn('Bisheriges Verhalten beibehalten: alle eingebundenen Datenquellen', CGI)
        self.assertNotIn("'Bisherige Grundregel'", JS)
        self.assertNotIn("'· bisherige Grundregel'", JS)
        config = json.loads((ROOT / "config" / "config.json").read_text(encoding="utf-8"))
        self.assertEqual(config["source_selection"], {"policy": "local", "overrides": {}})

    def test_source_help_uses_existing_tooltip_without_form_actions(self) -> None:
        legend = re.search(r'<legend\b[^>]*id="source-selection-legend"[^>]*>(.*?)</legend>', CGI, re.DOTALL)
        self.assertIsNotNone(legend)
        self.assertIn("Datenquellen", legend.group(1))
        self.assertRegex(legend.group(1), r"\$info_\w+")
        self.assertIn('#hostbackup-app .info-bubble', STYLE)

    def test_context_help_is_escaped_accessible_and_not_a_submit_control(self) -> None:
        helper = re.search(r"sub info_button \{(?P<body>.*?)\n\}", CGI, re.DOTALL)
        self.assertIsNotNone(helper)
        body = helper.group("body")
        for value in ("$text", "$tooltip_id", "$label"):
            self.assertRegex(body, r"escapeHTML\(" + re.escape(value))
        for attribute in ('type="button"', 'aria-label=', 'aria-describedby=', 'role="tooltip"', 'tabindex="0"'):
            self.assertIn(attribute, body)
        self.assertNotRegex(body, r"\bon(?:click|submit|change)\s*=")

    def test_action_help_has_shared_catalog_for_checks_protection_and_restore(self) -> None:
        helper = re.search(r"sub action_info \{(?P<body>.*?)\n\}", CGI, re.DOTALL)
        self.assertIsNotNone(helper)
        body = helper.group("body")
        for action in (
            "inspect-backup", "verify-backup", "verification-report", "recovery-sheet",
            "protect-backup", "record-restore-test", "backup-preview", "storage-info",
            "runtime-cleanup-preview", "diagnostics", "recover-services", "stop-backup",
            "retention-mode", "integrity-enabled", "maintenance-preview", "restore-files",
            "restore-destination", "restore-volumes", "restore-preview", "restore-start",
        ):
            self.assertRegex(body, r"['\"]" + re.escape(action) + r"['\"]\s*=>\s*\[")
        self.assertIn("return info_button", body)
        self.assertIn("$instance", body, "Backup-row tooltip IDs must be unique per backup")
        self.assertIn("Vergleichsbasis", body)
        self.assertIn("kein automatischer Nachweis", body)

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

    def test_live_log_keeps_updates_and_scroll_position(self) -> None:
        self.assertIn("function normalizeLogForDisplay(value)", JS)
        self.assertIn("logViewport(log.scrollTop", JS)
        self.assertIn("log.scrollLeft = left", JS)
        self.assertIn("log.scrollTop = atEnd ? log.scrollHeight : top", JS)
        self.assertIn("#hostbackup-app pre.terminal", STYLE)
        self.assertIn("white-space: pre;", STYLE)
        self.assertIn("overflow-wrap: normal;", STYLE)
        self.assertNotIn("redirectWithMessage", JS)

    def test_downloads_are_privileged_streams_not_direct_file_access(self) -> None:
        self.assertIn("sub relay_backend_download", CGI)
        self.assertIn("relay_backend_download($action", CGI)
        self.assertNotIn("open my $fh, '<:raw', $archive", CGI)

    def test_settings_change_popup_tracks_delegated_settings(self) -> None:
        self.assertIn('id="settings-change-popup"', CGI)
        self.assertIn("document.addEventListener('input', onSettingChange)", JS)
        self.assertIn("document.addEventListener('change', onSettingChange)", JS)
        self.assertIn("updateDirty(initial, changed, 'stop_targets'", JS)
        self.assertIn("function requireSaved()", JS)
        self.assertIn("function refreshCSRF()", JS)
        self.assertIn("X-CSRF-Token", JS)
        self.assertIn("updateDirty(initial, changed, name, controlState", JS)
        self.assertIn("Deine Eingaben wurden nicht verworfen.", JS)

    def test_upload_limits_are_set_before_eager_cgi_parsing(self) -> None:
        boundary = CGI.index("$q = CGI->new")
        for marker in ("$CGI::POST_MAX", "CONTENT_LENGTH", "same_origin_request()", "HTTP_X_CSRF_TOKEN", "available_bytes(File::Spec->tmpdir())"):
            self.assertLess(CGI.index(marker), boundary)
        self.assertIn('action="?action=import-config"', CGI)

    def test_manual_restore_history_is_explicitly_not_automatic_proof(self) -> None:
        self.assertIn('name="action" value="record-restore-test"', CGI)
        self.assertIn('type="datetime-local" name="tested_at" required', CGI)
        self.assertIn('name="note" maxlength="2000"', CGI)
        self.assertIn("testDate.toISOString()", JS)
        self.assertIn("Vom Plugin nicht überprüft.", JS)
        self.assertIn("Persönliche Testeinträge ändern keine Restore-Freigaben.", JS)

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
