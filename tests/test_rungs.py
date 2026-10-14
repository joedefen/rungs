"""Tests for rungs: config handling, name matching, prompts, and commands.

Run with:  python3 -m pytest
"""

import os
import re
import signal
import subprocess
import sys
from pathlib import Path

import pytest

import rungs
from rungs.main import Rungs, _sigint_targets_child

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
# ad-hoc menu files (any filename, .ini contents)
# --------------------------------------------------------------------------- #
def test_find_menu_quiet_suppresses_diagnostics(tool, capsys):
    tool.menus = {"example": {}}
    assert tool.find_menu("nope", quiet=True) is None
    assert capsys.readouterr().out == ""


def test_make_section_menu_accepts_explicit_menus(tool):
    menu = tool.make_section_menu({"adhoc": {}, "!hidden": {}})
    values = list(menu.values())
    assert "rungs 'adhoc'" in values
    assert all("!hidden" not in value for value in values)


def test_load_menu_file_parses_and_merges(tool, tmp_path):
    menu_file = tmp_path / "MyProcedure"  # deliberately no .ini extension
    menu_file.write_text("[adhoc]\na: echo hi\nx: exit\n", encoding="utf-8")

    file_menus = tool.load_menu_file(str(menu_file))
    assert set(file_menus) == {"adhoc"}
    assert "adhoc" in tool.menus        # merged so sub-menus resolve by name
    assert "adhoc" in tool.file_menus
    assert tool.menu_file == str(menu_file)


def test_load_menu_file_rejects_non_ini(tool, tmp_path, capsys):
    bad = tmp_path / "not-ini"
    bad.write_text(INVALID_INI, encoding="utf-8")
    assert tool.load_menu_file(str(bad)) is None
    assert "ERROR" in capsys.readouterr().out


def test_run_spec_prefers_menu_name(tool, monkeypatch):
    tool.menus = {"example": {"a": "echo hi"}}
    picked = []
    monkeypatch.setattr(tool, "do_menu",
                        lambda name, options=None: picked.append(name))
    assert tool.run_spec("example") is True
    assert picked == ["example"]


def test_run_spec_runs_file_path_without_extension(tool, tmp_path, monkeypatch):
    menu_file = tmp_path / "MyProcedure"  # path contains a '/', no extension
    menu_file.write_text("[solo]\na: echo hi\nx: exit\n", encoding="utf-8")
    picked = []
    monkeypatch.setattr(tool, "do_menu",
                        lambda name, options=None: picked.append(name))
    assert tool.run_spec(str(menu_file)) is True
    assert picked == ["solo"]


def test_run_spec_runs_bare_filename(tool, tmp_path, monkeypatch):
    menu_file = tmp_path / "adhoc"
    menu_file.write_text("[solo]\na: echo hi\nx: exit\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    picked = []
    monkeypatch.setattr(tool, "do_menu",
                        lambda name, options=None: picked.append(name))
    assert tool.run_spec("adhoc") is True   # no '/' in the spec
    assert picked == ["solo"]


def test_run_spec_misuse_returns_false(tool, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert tool.run_spec("no-such-menu-or-file") is False
    assert tool.run_spec("some/path/that/does/not/exist") is False


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
# Ctrl-C / signal handling
# --------------------------------------------------------------------------- #
def test_shell_status_maps_signals_like_a_shell(tool):
    assert tool.shell_status(0) == 0
    assert tool.shell_status(7) == 7
    assert tool.shell_status(-signal.SIGINT) == 130   # Ctrl-C -> 128 + 2


def test_sigint_targets_child_ignores_then_restores():
    before = signal.getsignal(signal.SIGINT)
    with _sigint_targets_child():
        during = signal.getsignal(signal.SIGINT)
        assert callable(during)
        assert during is not before          # a no-op handler is installed
    assert signal.getsignal(signal.SIGINT) is before


def test_run_cmd_lets_the_child_own_ctrl_c(tool, monkeypatch):
    seen = {}

    class Completed:
        returncode = 0

    def fake_run(command, **kwargs):
        # While the command runs, rungs must NOT be using the default
        # (KeyboardInterrupt-raising) SIGINT handler ...
        seen["handler"] = signal.getsignal(signal.SIGINT)
        return Completed()

    monkeypatch.setattr(subprocess, "run", fake_run)
    before = signal.getsignal(signal.SIGINT)

    tool.run_cmd("true")

    assert callable(seen["handler"])
    assert seen["handler"] is not before     # ... so Ctrl-C spares rungs
    assert signal.getsignal(signal.SIGINT) is before   # and is restored


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


# --------------------------------------------------------------------------- #
# environment directives (+ENV / [__GLOBAL__])
# --------------------------------------------------------------------------- #
class _FakeMenu:
    """Stands in for InlineMenu.Menu so do_menu runs without a tty."""

    seen_env = None

    def __init__(self, prompts, default=None, title="", notice=None):
        _FakeMenu.seen_env = dict(os.environ)

    def prompt(self):
        return "x"


def test_parse_env_block_pairs_skips_blanks_and_comments():
    pairs = Rungs.parse_env_block(
        "A=1\n\n# comment\n; another\nB='two words'\nC=has=equals\n", "s"
    )
    assert pairs == [("A", "1"), ("B", "two words"), ("C", "has=equals")]


def test_extract_env_pops_directive_only(tool):
    options = {"a": "echo hi", "+ENV": "FOO=bar"}
    assert tool.extract_env(options, "m") == [("FOO", "bar")]
    assert "+ENV" not in options and "a" in options


def test_global_section_rejects_non_env_keys(tool, capsys):
    options = {"+ENV": "G=1", "a": "echo hi"}
    assert tool.extract_env(options, Rungs.global_section) == [("G", "1")]
    assert options == {}
    assert "WARNING" in capsys.readouterr().out


def test_do_menu_applies_section_env_then_restores(tool, monkeypatch):
    monkeypatch.setattr("rungs.main.Menu", _FakeMenu)
    monkeypatch.setenv("RV_KEEP", "orig")

    tool.do_menu("m", {"x": "exit",
                       "+ENV": "RV_SCOPE=scoped\nRV_KEEP=changed"})

    assert _FakeMenu.seen_env["RV_SCOPE"] == "scoped"   # visible while running
    assert _FakeMenu.seen_env["RV_KEEP"] == "changed"
    assert "RV_SCOPE" not in os.environ                 # removed on exit
    assert os.environ["RV_KEEP"] == "orig"              # restored


def test_section_env_overrides_global(tool, monkeypatch):
    monkeypatch.setattr("rungs.main.Menu", _FakeMenu)
    Rungs.apply_env(Rungs.parse_env_block("RV_SHARED=global", "g"))
    try:
        tool.do_menu("m", {"x": "exit", "+ENV": "RV_SHARED=section"})
        assert _FakeMenu.seen_env["RV_SHARED"] == "section"
        assert os.environ["RV_SHARED"] == "global"   # global restored after
    finally:
        os.environ.pop("RV_SHARED", None)


def test_global_section_is_hidden_and_applied(home):
    cfg_dir = home / ".config" / "rungs"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "rungs.ini").write_text(
        "[__GLOBAL__]\n"
        "+ENV: RV_GLOBAL=hello\n"
        "      RV_OTHER=2\n"
        "\n"
        "[m]\n"
        "x: exit\n",
        encoding="utf-8",
    )
    try:
        tool = Rungs()
        assert Rungs.global_section not in tool.menus
        assert "m" in tool.menus
        assert os.environ["RV_GLOBAL"] == "hello"
        assert os.environ["RV_OTHER"] == "2"
    finally:
        os.environ.pop("RV_GLOBAL", None)
        os.environ.pop("RV_OTHER", None)


def test_load_menu_file_applies_its_global_env(tool, tmp_path):
    menu_file = tmp_path / "proc.ini"
    menu_file.write_text(
        "[__GLOBAL__]\n+ENV: RV_FILE=1\n\n[adhoc]\nx: exit\n",
        encoding="utf-8",
    )
    try:
        menus = tool.load_menu_file(str(menu_file))
        assert set(menus) == {"adhoc"}
        assert os.environ["RV_FILE"] == "1"
    finally:
        os.environ.pop("RV_FILE", None)


def test_reserved_plus_prefix_is_reported(tool, capsys):
    options = {"+FOO": "bar", "a": "run"}
    assert tool.extract_env(options, "m") == []
    assert "+FOO" not in options and "a" in options
    assert "WARNING" in capsys.readouterr().out


# --------------------------------------------------------------------------- #
# literal vs. auto keys
# --------------------------------------------------------------------------- #
def test_auto_keys_follow_file_order(tool):
    options = {"01": "one", "02": "two", "025": "between", "03": "three"}
    keys, prompts, cmds = tool.build_prompts(options)
    assert keys == ["a", "b", "c", "d"]
    assert [prompts[k] for k in keys] == ["one", "two", "between", "three"]
    assert cmds["c"] == "between"


def test_literal_keys_are_used_verbatim(tool):
    options = {"a": "add", "d": "delete", "x": "exit"}
    keys, prompts, cmds = tool.build_prompts(options)
    assert keys == ["a", "d", "x"]
    assert prompts["a"] == cmds["a"] == "add"


def test_auto_keys_skip_literals_and_x(tool):
    options = {"a": "add", "01": "auto-one", "x": "exit", "02": "auto-two"}
    keys, prompts, cmds = tool.build_prompts(options)
    # 'a' and 'x' are used literally, so the autos take 'b' and 'c'
    assert keys == ["a", "b", "x", "c"]


def test_auto_pool_reserves_x(tool):
    options = {f"{i:02d}": f"cmd-{i}" for i in range(24)}
    keys, prompts, cmds = tool.build_prompts(options)
    assert "x" not in keys
    assert keys == list("abcdefghijklmnopqrstuvwy")


def test_auto_pool_exhaustion_warns(tool, capsys, monkeypatch):
    monkeypatch.setattr(Rungs, "auto_pool", "ab")
    options = {"01": "one", "02": "two", "03": "three"}
    keys, prompts, cmds = tool.build_prompts(options)
    assert keys == ["a", "b"]
    assert "03" not in cmds
    assert "WARNING" in capsys.readouterr().out


def test_build_prompts_ignores_reserved_directives(tool):
    options = {"+ENV": "FOO=bar", "a": "run"}
    keys, prompts, cmds = tool.build_prompts(options)
    assert keys == ["a"]


def test_config_parses_multichar_auto_keys(home):
    cfg_dir = home / ".config" / "rungs"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "rungs.ini").write_text(
        "[m]\n01: one\n02: two\n025: between\nx: exit\n",
        encoding="utf-8",
    )
    tool = Rungs()
    # Keys survive parsing intact -- previously [:1] truncated these to '0'
    # and raised DuplicateOptionError.
    assert list(tool.menus["m"]) == ["01", "02", "025", "x"]
    keys, prompts, cmds = tool.build_prompts(tool.menus["m"])
    assert keys == ["a", "b", "c", "x"]


# --------------------------------------------------------------------------- #
# preamble directives (+PRE)
# --------------------------------------------------------------------------- #
class _QueueMenu:
    """A stand-in for InlineMenu.Menu that returns a scripted key queue."""

    queue = []

    def __init__(self, prompts, default=None, title="", notice=None):
        self.prompts = prompts

    def prompt(self):
        return _QueueMenu.queue.pop(0)


def test_extract_pre_pops_directive_only(tool):
    options = {"a": "echo hi", "+PRE": "fail() { echo fail; }"}
    assert tool.extract_pre(options) == "fail() { echo fail; }"
    assert "+PRE" not in options and "a" in options


def test_extract_pre_blank_is_none(tool):
    assert tool.extract_pre({}) is None
    assert tool.extract_pre({"+PRE": "   \n  "}) is None


def test_pre_is_not_reported_as_stray(tool, capsys):
    options = {"a": "run", "+PRE": "X=1"}
    assert tool.extract_pre(options) == "X=1"
    assert tool.extract_env(options, "m") == []
    assert capsys.readouterr().out == ""


def test_join_preamble_skips_empties():
    assert Rungs.join_preamble(None, "a", "", "b") == "a\nb"
    assert Rungs.join_preamble() == ""


def test_section_preamble_orders_global_inherited_section(tool):
    tool.global_pre = "GLOBAL=1"
    tool.inherited_pre = "INHERITED=1"
    assert (tool.section_preamble("SECTION=1")
            == "GLOBAL=1\nINHERITED=1\nSECTION=1")


def test_child_preamble_omits_global(tool):
    tool.global_pre = "GLOBAL=1"
    tool.inherited_pre = "INHERITED=1"
    assert tool.child_preamble("SECTION=1") == "INHERITED=1\nSECTION=1"


def test_run_cmd_prepends_preamble_but_echoes_command(tool, capsys, monkeypatch):
    seen = {}

    class Completed:
        returncode = 0

    def fake_run(command, **kwargs):
        seen["command"] = command
        return Completed()

    monkeypatch.setattr(subprocess, "run", fake_run)
    tool.run_cmd("echo hi", preamble="PRE=1")

    assert seen["command"] == "PRE=1\necho hi"
    out = capsys.readouterr().out
    assert "==> echo hi" in out
    assert "PRE=1" not in out          # the preamble is not reprinted


def test_do_menu_runs_with_section_preamble(tool, monkeypatch):
    monkeypatch.setattr("rungs.main.Menu", _QueueMenu)
    _QueueMenu.queue = ["a", "x"]
    calls = []
    monkeypatch.setattr(
        tool, "run_cmd",
        lambda cmd, **kw: calls.append((cmd, kw.get("preamble"))) or 0)

    tool.do_menu("m", {"a": "echo hi", "x": "exit", "+PRE": "SECTION=1"})

    assert calls == [("echo hi", "SECTION=1")]


def test_do_menu_exports_preamble_to_submenus_then_restores(tool, monkeypatch):
    monkeypatch.setattr("rungs.main.Menu", _QueueMenu)
    _QueueMenu.queue = ["a", "x"]
    tool.global_pre = "GLOBAL=1"
    seen = {}

    def fake_run(cmd, **kw):
        seen["RUNGS_PRE"] = os.environ.get(Rungs.pre_env_var)
        return 0

    monkeypatch.setattr(tool, "run_cmd", fake_run)
    tool.do_menu("m", {"a": "echo hi", "x": "exit", "+PRE": "SECTION=1"})

    # Sub-menus inherit the section chain, but not the (re-added) global ...
    assert seen["RUNGS_PRE"] == "SECTION=1"
    assert Rungs.pre_env_var not in os.environ    # ... and it is restored


def test_section_preamble_is_not_env_expanded(tool, monkeypatch):
    monkeypatch.setenv("RV_EXPAND", "boom")
    monkeypatch.setattr("rungs.main.Menu", _QueueMenu)
    _QueueMenu.queue = ["a", "x"]
    seen = {}
    monkeypatch.setattr(tool, "run_cmd", lambda cmd, **kw: seen.update(kw) or 0)

    tool.do_menu("m", {"a": "echo hi", "x": "exit", "+PRE": "echo $RV_EXPAND"})

    assert seen["preamble"] == "echo $RV_EXPAND"   # +PRE is never expanded


def test_global_section_accepts_and_applies_pre(home):
    cfg_dir = home / ".config" / "rungs"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "rungs.ini").write_text(
        "[__GLOBAL__]\n"
        "+PRE: GLOBAL_HELPER=1\n"
        "\n"
        "[m]\n"
        "x: exit\n",
        encoding="utf-8",
    )
    tool = Rungs()
    assert tool.global_pre == "GLOBAL_HELPER=1"
    assert Rungs.global_section not in tool.menus


def test_load_menu_file_applies_its_global_pre(tool, tmp_path):
    menu_file = tmp_path / "proc.ini"
    menu_file.write_text(
        "[__GLOBAL__]\n+PRE: FILE_HELPER=1\n\n[adhoc]\nx: exit\n",
        encoding="utf-8",
    )
    menus = tool.load_menu_file(str(menu_file))
    assert set(menus) == {"adhoc"}
    assert tool.global_pre == "FILE_HELPER=1"


def test_inherited_preamble_is_read_from_environment(home, monkeypatch):
    monkeypatch.setenv(Rungs.pre_env_var, "FROM_PARENT=1")
    tool = Rungs()
    assert tool.inherited_pre == "FROM_PARENT=1"
    assert tool.section_preamble(None) == "FROM_PARENT=1"
