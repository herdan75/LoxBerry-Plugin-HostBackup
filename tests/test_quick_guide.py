"""Keep the user-facing quick guide consistent with safe setup/restore limits.

These text-contract checks deliberately cover only the quick-guide section, not
matching help elsewhere on the page. They are not a substitute for runtime tests
or a successful restore on a real target device.
"""

import html
import json
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]


def plain_text(markup):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", markup))).strip().casefold()


class QuickGuideTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cgi = (ROOT / "webfrontend" / "htmlauth" / "index.cgi").read_text(encoding="utf-8")
        guide = re.search(
            r'<section\b[^>]*class="[^"]*\bwizard-panel\b[^"]*"[^>]*>'
            r'(?P<body>.*?)</section>',
            cgi,
            re.DOTALL,
        )
        if guide is None or not re.search(r"<summary>\s*Kurzanleitung\s*</summary>", guide["body"]):
            raise AssertionError("The setup quick guide must remain available in its existing disclosure")
        cls.steps = [plain_text(item) for item in re.findall(r"<li\b[^>]*>(.*?)</li>", guide["body"], re.DOTALL)]
        cls.text = plain_text(guide["body"])

    def step_with(self, pattern):
        matches = [step for step in self.steps if re.search(pattern, step)]
        self.assertTrue(matches, f"Quick guide has no step explaining {pattern!r}")
        return " ".join(matches)

    def test_root_includes_normal_directories_while_list_shows_mounts(self):
        source_step = self.step_with(r"datenquell|laufwerke und netzfreigaben")
        self.assertRegex(source_step, r"root|wurzel|systemdateisystem|:\s*/\s")
        self.assertRegex(source_step, r"unterordner|unterverzeichnis|normal\w*.{0,45}(?:ordner|verzeichnis)")
        self.assertRegex(source_step, r"einbindung|einhäng|mount|dateisystem")
        self.assertRegex(source_step, r"nicht (?:jeder|alle|die|sämtliche)|keine (?:vollständige|ordner)|nur (?:die|zusätzliche)")

    def test_new_installation_requires_conscious_stop_selection_or_dumps(self):
        config = json.loads((ROOT / "config" / "config.json").read_text(encoding="utf-8"))
        self.assertEqual(config["stop_targets"], [])
        self.assertFalse(config["stop_docker_before_backup"])
        stop_step = self.step_with(r"dienste und container|container und dienste|stop-ziele")
        self.assertRegex(stop_step, r"neuinstallation|neue[rn]? installation|anfangs|zunächst")
        self.assertRegex(stop_step, r"nicht automatisch|keine .*ausgewählt|auswahl .*leer|stop-ziele .*leer")
        self.assertRegex(stop_step, r"bewusst|gezielt|selbst.*auswähl")
        self.assertIn("datenbank", stop_step)
        self.assertRegex(stop_step, r"dump|anwendungsspezifisch|applikationsspezifisch")

    def test_target_directory_protection_does_not_imply_whole_disk_exclusion(self):
        exclusion_step = self.step_with(r"backup-zielordner|automatisch ausgeschlossen|doppelte backups")
        self.assertIn("automatisch", exclusion_step)
        self.assertRegex(exclusion_step, r"backup-(?:ziel|verzeichnis|ordner)")
        self.assertRegex(exclusion_step, r"datenträger|laufwerk")
        self.assertRegex(exclusion_step, r"nicht.{0,35}(?:automatisch|ganze|gesamte)|weitere backups|gesondert|ganzen .*ausschliess")

    def test_save_precedes_preview_and_automatic_schedule_uses_saved_settings(self):
        preview_step = self.step_with(r"nächstes backup prüfen|vorprüfung")
        self.assertRegex(preview_step, r"speicher\w*.{0,260}(?:nächstes backup prüfen|vorprüfung)")
        schedule_step = self.step_with(r"zeitplan|zeitgesteuert")
        self.assertRegex(schedule_step, r"speicher|gespeichert")

    def test_restore_is_not_a_disk_image_and_requires_target_mapping_and_test(self):
        restore_step = self.step_with(r"restore|wiederherstellung")
        self.assertRegex(restore_step, r"kein\w*.{0,65}(?:disk-image|diskimage|datenträgerabbild|image|blockabbild)")
        self.assertIn("partition", restore_step)
        self.assertIn("bootloader", restore_step)
        self.assertRegex(restore_step, r"volume-zuordnung|volumes?.{0,80}zuord|datenträger.{0,80}zuord")
        self.assertRegex(restore_step, r"restore-test|restoretest|test-restore|testrestore")
        self.assertRegex(restore_step, r"separat|testdatenträger|offline|rescue")


if __name__ == "__main__":
    unittest.main()
