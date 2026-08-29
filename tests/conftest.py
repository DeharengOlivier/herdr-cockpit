"""Shared scaffolding for the installer tests.

Every test that runs install.sh or uninstall.sh does it against a throwaway
HOME and a copy of the repository, never against the machine running the suite.
Two reasons, and both matter: the installer writes to ~/.zshrc and symlinks
into ~/.local/bin, and it copies spaces.conf.example into the repository it is
run from.

The external commands it looks for are replaced by stubs on PATH. herdr and
wezterm are not installed on a CI runner, and the point of these tests is what
the installer does to a filesystem, not whether a terminal emulator is present.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPOSITORY = Path(__file__).resolve().parent.parent

# The files install.sh copies. Its own build products (spaces.conf, .venv, the
# git history) are left out: a copy is a fresh machine, not a used one.
COPIED = ("bin", "config", "shell", "stats", "install.sh", "uninstall.sh", "spaces.conf.example")

STUBS = {
    # `herdr --version` is parsed with awk for the second field; `herdr config
    # check` decides whether the installer reports the config as valid.
    "herdr": "#!/bin/sh\ncase \"$1\" in\n  --version) echo 'herdr 0.8.0' ;;\n  config) exit 0 ;;\n  *) exit 0 ;;\nesac\n",
    "wezterm": "#!/bin/sh\necho 'wezterm 20260101'\n",
}


@pytest.fixture
def cockpit(tmp_path):
    """A copy of the repository, a throwaway HOME, and stubbed dependencies."""
    return Cockpit(tmp_path)


class Cockpit:
    """One isolated installation: run it, then look at what it did."""

    def __init__(self, root: Path):
        self.root = root
        self.home = root / "home"
        self.repository = root / "repo"
        self.stubs = root / "stubs"

        self.home.mkdir()
        self.stubs.mkdir()
        self.repository.mkdir()
        for name in COPIED:
            source = REPOSITORY / name
            destination = self.repository / name
            if source.is_dir():
                shutil.copytree(source, destination)
            else:
                shutil.copy2(source, destination)

        for name, body in STUBS.items():
            stub = self.stubs / name
            stub.write_text(body)
            stub.chmod(0o755)

    # -- running ---------------------------------------------------------
    def run(self, script, *arguments, expect_success=True):
        """Run install.sh or uninstall.sh inside the sandbox."""
        environment = dict(os.environ)
        environment["HOME"] = str(self.home)
        environment["PATH"] = f"{self.stubs}:{Path(sys.executable).parent}:/usr/bin:/bin"
        result = subprocess.run(
            [str(self.repository / script), *arguments],
            capture_output=True,
            text=True,
            env=environment,
            cwd=self.repository,
            timeout=120,
        )
        if expect_success:
            assert result.returncode == 0, (
                f"{script} {' '.join(arguments)} exited {result.returncode}\n"
                f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
            )
        return result

    def install(self, *arguments, **kwargs):
        return self.run("install.sh", "--yes", *arguments, **kwargs)

    def uninstall(self, *arguments, **kwargs):
        return self.run("uninstall.sh", "--yes", *arguments, **kwargs)

    # -- looking at the result -------------------------------------------
    def home_path(self, *parts) -> Path:
        return self.home.joinpath(*parts)

    @property
    def zshrc(self) -> Path:
        return self.home / ".zshrc"

    @property
    def manifest(self) -> Path:
        return self.home / ".config" / "herdr-cockpit" / "install-manifest"

    @property
    def wezterm_config(self) -> Path:
        return self.home / ".config" / "wezterm" / "wezterm.lua"

    @property
    def herdr_config(self) -> Path:
        return self.home / ".config" / "herdr" / "config.toml"

    def backups_of(self, path: Path):
        """Every <name>.bak-<stamp> sitting next to `path`."""
        return sorted(path.parent.glob(path.name + ".bak-*"))

    def tree(self):
        """Every path under HOME, relative and sorted: the state to compare."""
        return sorted(
            str(p.relative_to(self.home)) for p in self.home.rglob("*") if not p.is_dir()
        )
