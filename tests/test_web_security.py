#!/usr/bin/env python3
import pathlib
import re
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
CGI = (ROOT / "webfrontend" / "htmlauth" / "index.cgi").read_text(encoding="utf-8")
BACKEND = (ROOT / "bin" / "hostbackup.sh").read_text(encoding="utf-8")


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

    def test_network_compatible_is_informational_for_backup(self) -> None:
        target_info = re.search(
            r"backup_target_info\(\) \{(?P<body>.*?)\n\}", BACKEND, flags=re.DOTALL
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

    def test_export_download_rejects_symlinks(self) -> None:
        self.assertRegex(CGI, r"!-f \$archive \|\| -l \$archive")

    def test_csrf_secret_rejects_unsafe_types(self) -> None:
        self.assertIn('die "Unsicheres Plugin-Datenverzeichnis" if -l $datadir', CGI)
        self.assertIn("if (-e $path && (!-f $path || -l $path))", CGI)


if __name__ == "__main__":
    unittest.main()
