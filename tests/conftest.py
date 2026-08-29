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

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPOSITORY = Path(__file__).resolve().parent.parent

# The files install.sh copies. Its own build products (spaces.conf, .venv, the
# git history) are left out: a copy is a fresh machine, not a used one.
COPIED = (
    "bin",
    "config",
    "shell",
    "stats",
    "install.sh",
    "uninstall.sh",
    "spaces.conf.example",
)

STUBS = {
    # `herdr --version` is parsed with awk for the second field; `herdr config
    # check` decides whether the installer reports the config as valid.
    "herdr": (
        "#!/bin/sh\n"
        'case "$1" in\n'
        "  --version) echo 'herdr 0.8.0' ;;\n"
        "  config) exit 0 ;;\n"
        "  *) exit 0 ;;\n"
        "esac\n"
    ),
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
        return sorted(str(p.relative_to(self.home)) for p in self.home.rglob("*") if not p.is_dir())


def load_script(name: str, path):
    """Load one of the repository's standalone scripts as a module.

    They are scripts, not an installed package, and one of them has a dash in
    its file name, so neither is importable by name.
    """
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def badge():
    """bin/github-badge.py loaded as a module."""
    return load_script("cockpit_badge", REPOSITORY / "bin" / "github-badge.py")


@pytest.fixture(scope="session")
def panel():
    """stats/panel.py loaded as a module.

    It is a standalone script, not an installed package, so it is loaded by
    path. Session-scoped because importing it is pure: everything it touches at
    import time is a constant, and the tests that need a different HOME or
    cache location override the module attribute they care about.
    """
    return load_script("cockpit_panel", REPOSITORY / "stats" / "panel.py")


# --- bootstrap.sh -----------------------------------------------------------

# A stand-in for the Herdr server. It keeps its spaces and tabs in a JSON file
# so a test can set the state up, run bootstrap.sh, and read back both what the
# state became and every command that was issued to get there.
HERDR_STUB = """#!/usr/bin/env python3
import json, os, pathlib, sys

log = pathlib.Path(os.environ["HERDR_STUB_LOG"])
state_path = pathlib.Path(os.environ["HERDR_STUB_STATE"])
argv = sys.argv[1:]
with log.open("a") as handle:
    handle.write("\\t".join(argv) + "\\n")

state = json.loads(state_path.read_text()) if state_path.exists() else {}
workspaces = state.setdefault("workspaces", [])
tabs = state.setdefault("tabs", [])


def save():
    state_path.write_text(json.dumps(state))


def option(name, default=None):
    return argv[argv.index(name) + 1] if name in argv else default


if argv[:1] == ["status"]:
    sys.exit(0 if state.get("up", True) else 1)

if argv[:2] == ["workspace", "list"]:
    print(json.dumps({"result": {"workspaces": workspaces}}))
elif argv[:2] == ["workspace", "create"]:
    workspaces.append({
        "workspace_id": "ws-%d" % (len(workspaces) + 1),
        "label": option("--label"),
        "cwd": option("--cwd"),
        "env": [argv[i + 1] for i, a in enumerate(argv) if a == "--env"],
    })
    save()
elif argv[:2] == ["workspace", "close"]:
    state["workspaces"] = [w for w in workspaces if w.get("workspace_id") != argv[2]]
    save()
    sys.exit(0 if len(state["workspaces"]) != len(workspaces) else 1)
elif argv[:2] == ["tab", "list"]:
    wanted = option("--workspace")
    print(json.dumps({"result": {"tabs": [t for t in tabs if t.get("workspace_id") == wanted]}}))
elif argv[:2] == ["tab", "close"]:
    state["tabs"] = [t for t in tabs if t.get("tab_id") != argv[2]]
    save()
elif argv[:1] == ["session"]:
    # `session attach` is what bootstrap.sh execs into with no argument. Dump
    # the environment it was handed, so the marker scrubbing can be observed.
    pathlib.Path(os.environ["HERDR_STUB_ENV"]).write_text(
        "\\n".join("%s=%s" % item for item in sorted(os.environ.items()))
    )
sys.exit(0)
"""


@pytest.fixture
def bootstrap(tmp_path):
    """bin/bootstrap.sh wired to a stub Herdr server."""
    return Bootstrap(tmp_path)


class Bootstrap:
    def __init__(self, root: Path):
        self.root = root
        self.home = root / "home"
        self.home.mkdir()
        self.spaces_conf = root / "spaces.conf"
        self.state = root / "herdr-state.json"
        self.log = root / "herdr-calls.log"
        self.captured_env = root / "attach-env.txt"

        self.herdr = root / "herdr-stub"
        self.herdr.write_text(HERDR_STUB)
        self.herdr.chmod(0o755)

    def write_conf(self, content: str) -> None:
        self.spaces_conf.write_text(content)

    def set_state(self, **state) -> None:
        self.state.write_text(json.dumps(state))

    def read_state(self) -> dict:
        return json.loads(self.state.read_text()) if self.state.exists() else {}

    def calls(self) -> list[list[str]]:
        if not self.log.exists():
            return []
        return [line.split("\t") for line in self.log.read_text().splitlines()]

    def run(self, *arguments, herdr=None, env=None):
        environment = dict(os.environ)
        environment.update(
            {
                "HOME": str(self.home),
                "PATH": f"{Path(sys.executable).parent}:/usr/bin:/bin",
                "COCKPIT_HERDR_BIN": herdr if herdr is not None else str(self.herdr),
                "COCKPIT_SPACES_CONF": str(self.spaces_conf),
                "HERDR_STUB_LOG": str(self.log),
                "HERDR_STUB_STATE": str(self.state),
                "HERDR_STUB_ENV": str(self.captured_env),
            }
        )
        environment.update(env or {})
        return subprocess.run(
            [str(REPOSITORY / "bin" / "bootstrap.sh"), *arguments],
            capture_output=True,
            text=True,
            env=environment,
            timeout=60,
        )
