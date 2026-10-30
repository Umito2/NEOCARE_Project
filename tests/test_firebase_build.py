"""Exercise the Hosting publish boundary using synthetic files only."""

from pathlib import Path
import os
import subprocess
import tempfile
import unittest

import build_firebase


class FirebaseBuildTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory(prefix="neocare-firebase-test-")))
        (self.root / "index.html").write_bytes(b"<html>synthetic interface</html>\n")
        (self.root / "neocare-i18n.js").write_bytes(b"window.syntheticTranslations = {};\n")
        self.output = self.root / build_firebase.PUBLIC_DIRECTORY

    def public_files(self):
        return {path.relative_to(self.output).as_posix() for path in self.output.rglob("*") if path.is_file()}

    def make_link(self, link, target, *, directory=False):
        try:
            link.symlink_to(target, target_is_directory=directory)
        except (NotImplementedError, OSError) as error:
            self.skipTest(f"This environment cannot create symbolic links: {error}")

    def test_build_publishes_only_ui_and_can_update_it(self):
        for name in ("serviceAccountKey.json", ".openai_api_key", "neocare_auth.sqlite3", "patient-report.pdf"):
            (self.root / name).write_bytes(b"SYNTHETIC PRIVATE CONTENT")
        (self.root / ".local-ai").mkdir()
        (self.root / ".local-ai" / "model.bin").write_bytes(b"SYNTHETIC MODEL")

        self.assertEqual(build_firebase.build(self.root), self.output)
        self.assertEqual(self.public_files(), build_firebase.PUBLIC_FILES)
        self.assertEqual((self.output / "index.html").read_bytes(), (self.root / "index.html").read_bytes())
        self.assertEqual((self.output / "assets/neocare-i18n.js").read_bytes(), (self.root / "neocare-i18n.js").read_bytes())
        self.assertEqual(
            (self.output / "assets/hosting-config.js").read_text(encoding="utf-8"),
            'window.NEOCARE_HOSTING_CONFIG = Object.freeze({apiOrigin: "https://umito.pythonanywhere.com"});\n',
        )
        (self.root / "index.html").write_bytes(b"updated synthetic UI")
        build_firebase.build(self.root)
        self.assertEqual((self.output / "index.html").read_bytes(), b"updated synthetic UI")
        self.assertEqual(self.public_files(), build_firebase.PUBLIC_FILES)
        self.assertTrue((self.root / ".local-ai/model.bin").exists())

    def test_unexpected_files_and_directories_stop_before_any_replacement(self):
        for entry, is_directory in (("private.sqlite3", False), ("assets/secret.json", False), (".hidden", False), ("models", True)):
            with self.subTest(entry=entry):
                case_root = self.root / ("case-" + entry.replace("/", "-"))
                case_root.mkdir()
                (case_root / "index.html").write_bytes(b"new UI")
                (case_root / "neocare-i18n.js").write_bytes(b"new JS")
                output = case_root / build_firebase.PUBLIC_DIRECTORY
                (output / "assets").mkdir(parents=True)
                (output / "index.html").write_bytes(b"previous public UI")
                unexpected = output / entry
                if is_directory:
                    unexpected.mkdir()
                else:
                    unexpected.write_bytes(b"must not delete")
                with self.assertRaises(build_firebase.FirebaseBuildError):
                    build_firebase.build(case_root)
                self.assertEqual((output / "index.html").read_bytes(), b"previous public UI")
                self.assertTrue(unexpected.exists())

    def test_source_link_is_rejected_without_creating_output(self):
        source = self.root / "index.html"
        source.unlink()
        private = self.root / "private.txt"
        private.write_bytes(b"synthetic private data")
        self.make_link(source, private)
        with self.assertRaises(build_firebase.FirebaseBuildError):
            build_firebase.build(self.root)
        self.assertFalse(self.output.exists())

    def test_output_ancestor_link_cannot_write_outside_project(self):
        outside = Path(self.enterContext(tempfile.TemporaryDirectory(prefix="neocare-outside-test-")))
        sentinel = outside / "sentinel.txt"
        sentinel.write_bytes(b"preserve")
        self.make_link(self.root / "deployment-artifacts", outside, directory=True)
        with self.assertRaises(build_firebase.FirebaseBuildError):
            build_firebase.build(self.root)
        self.assertEqual(list(outside.iterdir()), [sentinel])
        self.assertEqual(sentinel.read_bytes(), b"preserve")

    def test_existing_output_file_link_is_rejected(self):
        build_firebase.build(self.root)
        output_index = self.output / "index.html"
        output_index.unlink()
        target = self.root / "private.txt"
        target.write_bytes(b"preserve private file")
        self.make_link(output_index, target)
        with self.assertRaises(build_firebase.FirebaseBuildError):
            build_firebase.build(self.root)
        self.assertEqual(target.read_bytes(), b"preserve private file")

    def test_existing_hard_link_is_replaced_without_modifying_target(self):
        build_firebase.build(self.root)
        output_index = self.output / "index.html"
        output_index.unlink()
        target = self.root / "private.txt"
        target.write_bytes(b"preserve hard-link target")
        try:
            os.link(target, output_index)
        except (NotImplementedError, OSError) as error:
            self.skipTest(f"This environment cannot create hard links: {error}")
        build_firebase.build(self.root)
        self.assertEqual(target.read_bytes(), b"preserve hard-link target")
        self.assertEqual(output_index.read_bytes(), (self.root / "index.html").read_bytes())

    @unittest.skipUnless(os.name == "nt", "Windows junction boundary")
    def test_windows_junction_cannot_redirect_public_output(self):
        outside = Path(self.enterContext(tempfile.TemporaryDirectory(prefix="neocare-junction-target-")))
        sentinel = outside / "sentinel.txt"
        sentinel.write_bytes(b"preserve junction target")
        junction = self.root / "deployment-artifacts"
        result = subprocess.run(
            [
                "powershell", "-NoProfile", "-NonInteractive", "-Command",
                "$ErrorActionPreference = 'Stop'; New-Item -ItemType Junction "
                "-Path $env:NEOCARE_TEST_JUNCTION -Target $env:NEOCARE_TEST_TARGET | Out-Null",
            ],
            env={**os.environ, "NEOCARE_TEST_JUNCTION": str(junction), "NEOCARE_TEST_TARGET": str(outside)},
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        try:
            with self.assertRaises(build_firebase.FirebaseBuildError):
                build_firebase.build(self.root)
            self.assertEqual(list(outside.iterdir()), [sentinel])
            self.assertEqual(sentinel.read_bytes(), b"preserve junction target")
        finally:
            # Remove only the directory junction, without traversing its target.
            os.rmdir(junction)


if __name__ == "__main__":
    unittest.main()
