#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Exercise setup safety with fake tools and synthetic files, never firmware.

Run in Linux or WSL: python3 tools/test_setup.py
"""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "setup.sh"


@unittest.skipUnless(os.name == "posix", "needs Linux shell tools")
class Setup(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="djs-setup-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.destination = self.root / "installation"
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.key = self.root / "synthetic.key"
        self.update = self.root / "synthetic.UPD"
        self.key.write_text("synthetic test fixture, not a key")
        self.update.write_text("synthetic test fixture, not firmware")
        self.env = dict(os.environ, DJS_HOME=str(self.destination),
                        PATH=str(self.bin) + os.pathsep + os.environ["PATH"])
        self.tool("python3", "touch update.iso\n")
        self.tool("7z", "mkdir -p iso/images\nprintf test > iso/images/release.txt\n")
        self.tool("unsquashfs", 'mkdir -p "$4"\n')
        self.tool("qemu-arm-static", "exit 0\n")
        self.tool("arm-linux-gnueabihf-gcc", "exit 0\n")
        self.tool("openssl", "exit 0\n")
        self.tool("tar", '''case "$2" in
    *pdj.tar.gz)
        mkdir -p "$4/pdj"
        touch "$4/pdj/EP113_Main_R"
        chmod +x "$4/pdj/EP113_Main_R"
        exit 0
        ;;
esac
if [ "${FAIL_TAR:-}" = corrupt ]; then
    echo 'tar: unexpected end of file' >&2
    exit 2
fi
if [ "${FAIL_TAR:-}" = node ]; then
    echo 'tar: dev/test: Cannot mknod: Operation not permitted' >&2
    echo 'tar: Exiting with failure status due to previous errors' >&2
    exit 2
fi
''')

    def tool(self, name, body):
        path = self.bin / name
        path.write_text("#!/bin/bash\nset -eu\n" + body)
        path.chmod(0o755)

    def run_setup(self, rebuild=False):
        command = ["bash", str(SCRIPT)] + (["--rebuild"] if rebuild else [])
        return subprocess.run(command + [str(self.update), str(self.key)], env=self.env,
                              capture_output=True, text=True, timeout=15)

    def existing(self):
        app = self.destination / "root" / "root" / "pdj"
        app.mkdir(parents=True)
        (app / "EP113_Main_R").write_text("old application")
        data = self.destination / "root" / "data"
        data.mkdir()
        (data / "settings").write_text("keep me")
        (self.destination / "usb").mkdir()
        (self.destination / "usb" / "project").write_text("project")

    def test_rejects_home_and_repository_roots(self):
        for target in ("/", str(Path.home()), str(SCRIPT.parents[1])):
            self.env["DJS_HOME"] = target
            run = self.run_setup(rebuild=True)
            self.assertNotEqual(run.returncode, 0)
            self.assertIn("unsafe DJS_HOME", run.stderr)

    def test_existing_installation_requires_rebuild(self):
        self.existing()
        run = self.run_setup()
        self.assertNotEqual(run.returncode, 0)
        self.assertIn("--rebuild", run.stderr)
        self.assertEqual((self.destination / "root/data/settings").read_text(), "keep me")

    def test_rebuild_refuses_unrelated_nonempty_folder(self):
        self.destination.mkdir()
        (self.destination / "unrelated").touch()
        run = self.run_setup(rebuild=True)
        self.assertNotEqual(run.returncode, 0)
        self.assertIn("not a recognised installation", run.stderr)

    def test_corrupt_archive_does_not_replace_existing_root(self):
        self.existing()
        self.env["FAIL_TAR"] = "corrupt"
        run = self.run_setup(rebuild=True)
        self.assertNotEqual(run.returncode, 0, run.stdout)
        self.assertIn("unexpected end", run.stderr)
        self.assertEqual((self.destination / "root/data/settings").read_text(), "keep me")
        self.assertFalse((self.destination / ".setup-lock").exists())

    def test_rebuild_keeps_old_settings_and_usb(self):
        self.existing()
        run = self.run_setup(rebuild=True)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        backups = list(self.destination.glob("previous.*"))
        self.assertEqual(len(backups), 1)
        self.assertEqual((backups[0] / "root/data/settings").read_text(), "keep me")
        self.assertEqual((self.destination / "usb/project").read_text(), "project")
        self.assertTrue((self.destination / ".djs1000-emu").exists())

    def test_expected_unprivileged_device_node_errors_are_allowed(self):
        self.env["FAIL_TAR"] = "node"
        run = self.run_setup()
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
