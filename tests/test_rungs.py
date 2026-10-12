"""Tests for rungs: config handling, name matching, prompts, and commands.

Run with:  python3 -m pytest
"""

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

import rungs
from rungs.main import Rungs

SRC = Path(__file__).resolve().parents[1] / "src"
INVALID_INI = "this is not a valid ini file (no section header)\n"


# --------------------------------------------------------------------------- #
# fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture
def home(tmp_path, monkeypatch):
    """Isolate HOME so rungs never touches the real ~/.config/rungs."""
    fake = tmp_path / "home"
    fake.mkdir()
    monkeypatch.setenv("HOME", str(fake))
    return fake


@pytest.fixture
def tool(home):
    """A Rungs instance with parsed-looking opts, on an isolated HOME."""
    instance = Rungs()
    instance.opts = type(
        "Opts", (), {"dry_run": False, "edit": False, "menus": []}
    )()
    return instance


# --------------------------------------------------------------------------- #
# config handling & recovery
# --------------------------------------------------------------------------- #
def test_default_config_is_created(tool, home):
    cfg = home / ".config" / "rungs" / "rungs.ini"
    assert cfg.is_file()
    text = cfg.read_text(encoding="utf-8")
    assert "[edit-rungs-config]" in text
    assert "[example]" in text
    assert Rungs.edit_menu in tool.menus
    assert "example" in tool.menus


def test_good_config_is_backed_up(tool, home):
    backup = home / ".config" / "rungs" / "rungs.ini.bak"
    assert backup.is_file()
    assert tool.corrupt_config is False


def test_corrupt_config_recovers_from_backup(home, capsys):
    Rungs()  # first run writes a good config *and* its backup
    cfg = home / ".config" / "rungs" / "rungs.ini"
    cfg.write_text(INVALID_INI, encoding="utf-8")

    recovered = Rungs()
    assert recovered.corrupt_config is True
    assert Rungs.edit_menu in recovered.menus
    assert "ERROR" in capsys.readouterr().out


# --------------------------------------------------------------------------- #
# prompts
# --------------------------------------------------------------------------- #
def test_build_prompts_single_and_multiline(tool):
    options = {"a": "command-a", "b": "prompt-b\n   command-b"}
    keys, prompts, cmds = tool.build_prompts(options)
    assert keys == ["a", "b"]
    # single-line: menu text == command run
    assert prompts["a"] == "command-a" == cmds["a"]
    # multi-line: first line is the label, the rest is the literal command
    assert prompts["b"] == "prompt-b"
    assert cmds["b"].strip() == "command-b"


# --------------------------------------------------------------------------- #
# name matching
# --------------------------------------------------------------------------- #
def test_ordinary_vs_special():
    assert Rungs.ordinary("example") is True
    assert Rungs.ordinary(">sub") is False
    assert Rungs.ordinary("!deprecated") is False


@pytest.mark.parametrize(
    "spec,expected",
    [
        ("example", "example"),   # exact
        ("EXAMPLE", "example"),   # case-insensitive exact
        ("ex", "example"),        # case-insensitive, word-boundary prefix
        ("EOS-", "eos-update"),   # ditto
        ("date", None),           # not on a word boundary
    ],
)
def test_find_menu(tool, spec, expected):
    tool.menus = {"edit-rungs-config": {}, "example": {}, "eos-update": {}}
    assert tool.find_menu(spec) == expected


def test_find_menu_ambiguous_is_reported(tool, capsys):
    tool.menus = {"edit-rungs-config": {}, "example": {}, "eos-update": {}}
    assert tool.find_menu("e") is None
    assert "multiple" in capsys.readouterr().out


def test_make_section_menu_lists_only_ordinary(tool):
    tool.menus = {"example": {}, "!deprecated": {}, "edit-rungs-config": {}}
    menu = tool.make_section_menu()
    assert menu["x"] == "exit"
    values = list(menu.values())
    assert "rungs 'example'" in values
    assert "rungs 'edit-rungs-config'" in values
    assert all("!deprecated" not in value for value in values)


# --------------------------------------------------------------------------- #
# running commands
# --------------------------------------------------------------------------- #
def test_run_cmd_dry_run_does_not_execute(tool, capsys, monkeypatch):
    called = []
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: called.append(a))
    tool.opts.dry_run = True

    assert tool.run_cmd("echo hi") == 0
    assert called == []
    assert "WOULD RUN" in capsys.readouterr().out


def test_run_cmd_runs_via_shell_and_reports_status(tool, monkeypatch):
    seen = {}

    class Completed:
        returncode = 7

    def fake_run(command, **kwargs):
        seen["command"] = command
        seen.update(kwargs)
        return Completed()

    monkeypatch.setattr(subprocess, "run", fake_run)
    status = tool.run_cmd("false", precmd="echo start")

    assert status == 7
    assert seen["command"] == "echo start\nfalse"
    assert seen["shell"] is True


# --------------------------------------------------------------------------- #
# packaging / version
# --------------------------------------------------------------------------- #
def test_version_is_a_string():
    assert isinstance(rungs.__version__, str)
    assert re.match(r"^\d+\.\d+", rungs.__version__)


def test_cli_version_flag(home):
    env = os.environ.copy()
    env["PYTHONPATH"] = str(SRC)
    result = subprocess.run(
        [sys.executable, "-m", "rungs.main", "--version"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert result.returncode == 0
    assert rungs.__version__ in result.stdout
