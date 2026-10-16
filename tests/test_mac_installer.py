"""Portable installer checks with explicit fake Mac commands, not Mac validation."""

import hashlib
import io
import os
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path

INSTALLER = Path(__file__).resolve().parents[1] / "scripts/install.sh"


class MacInstallerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="music-installer-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        commands = self.root / "commands"
        commands.mkdir()
        for name, script in {
            "uname": 'case "$1" in -s) echo Darwin;; -m) echo arm64;; esac',
            "file": 'echo "Mach-O 64-bit executable arm64"',
        }.items():
            executable = commands / name
            executable.write_text("#!/bin/sh\n" + script + "\n")
            executable.chmod(0o755)
        self.prefix = self.root / "prefix"
        self.env = dict(
            os.environ,
            PATH=f"{commands}:{os.environ['PATH']}",
            MUSIC_INSTALL_PREFIX=str(self.prefix),
        )
        self.archive = self.root / "fest-0.3.0-darwin-arm64.tar.gz"

    def archive_app(self, content=b"#!/bin/sh\nexit 0\n", traversal=False):
        with tarfile.open(self.archive, "w:gz") as archive:
            for name, data, mode in [
                ("fest/fest", content, 0o755),
                ("fest/_internal/runtime/deno", b"test-runtime", 0o755),
            ]:
                entry = tarfile.TarInfo("../outside" if traversal else name)
                entry.size, entry.mode = len(data), mode
                archive.addfile(entry, io.BytesIO(data))
        digest = hashlib.sha256(self.archive.read_bytes()).hexdigest()
        Path(str(self.archive) + ".sha256").write_text(f"{digest}  {self.archive.name}\n")

    def install(self):
        return subprocess.run(
            ["sh", INSTALLER, self.archive],
            env=self.env,
            capture_output=True,
            text=True,
            timeout=15,
        )

    def test_install_and_update_preserve_previous_bundle(self):
        self.archive_app()
        self.assertEqual(self.install().returncode, 0)
        link = self.prefix / "bin/fest"
        previous = link.resolve()
        self.assertTrue(previous.is_file())
        self.archive_app(b"#!/bin/sh\n# updated\nexit 0\n")
        self.assertEqual(self.install().returncode, 0)
        self.assertNotEqual(link.resolve(), previous)
        self.assertTrue(previous.exists())

    def test_checksum_mismatch_does_not_install(self):
        self.archive_app()
        self.archive.write_bytes(b"modified")
        self.assertNotEqual(self.install().returncode, 0)
        self.assertFalse(self.prefix.exists())

    def test_other_command_is_not_overwritten(self):
        self.archive_app()
        command = self.prefix / "bin/fest"
        command.parent.mkdir(parents=True)
        command.write_text("existing-command")
        self.assertNotEqual(self.install().returncode, 0)
        self.assertEqual(command.read_text(), "existing-command")

    def test_archive_traversal_is_rejected(self):
        self.archive_app(traversal=True)
        self.assertNotEqual(self.install().returncode, 0)
        self.assertFalse(self.prefix.exists())
        self.assertFalse((self.root / "outside").exists())

    def test_existing_music_command_is_preserved(self):
        self.archive_app()
        command = self.prefix / "bin/music"
        command.parent.mkdir(parents=True)
        command.write_text("another-music-command")
        self.assertEqual(self.install().returncode, 0)
        self.assertEqual(command.read_text(), "another-music-command")

    def test_unrelated_music_symlink_is_preserved(self):
        self.archive_app()
        target = self.root / "another-player"
        target.touch()
        command = self.prefix / "bin/music"
        command.parent.mkdir(parents=True)
        command.symlink_to(target)
        self.assertEqual(self.install().returncode, 0)
        self.assertEqual(command.resolve(), target)

    def old_installation(self):
        root = self.prefix / "share/music-cli"
        old = root / "bundles/previous/music"
        old.parent.mkdir(parents=True)
        old.touch()
        (root / ".music-cli-install").touch()
        command = self.prefix / "bin/music"
        command.parent.mkdir(parents=True)
        command.symlink_to(old)
        return command, old

    def test_upgrade_removes_only_owned_music_link_and_keeps_old_bundle(self):
        self.archive_app()
        command, previous = self.old_installation()
        self.assertEqual(self.install().returncode, 0)
        self.assertFalse(command.is_symlink())
        self.assertTrue(previous.exists())
        self.assertTrue((self.prefix / "bin/fest").resolve().is_file())

    def test_failed_upgrade_leaves_owned_music_link_intact(self):
        self.archive_app()
        command, previous = self.old_installation()
        (self.prefix / "bin/fest").write_text("another-fest-command")
        self.assertNotEqual(self.install().returncode, 0)
        self.assertEqual(command.resolve(), previous)


if __name__ == "__main__":
    unittest.main()
