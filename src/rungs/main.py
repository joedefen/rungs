#!/usr/bin/env python3
"""
rungs -- step through fuzzy, laddered Linux procedures.

`rungs` reads "menus" from ``~/.config/rungs/rungs.ini`` and lets you
select (and repeat or skip) shell commands interactively.  It is aimed at
multi-step maintenance chores (system updates, Docker housekeeping, ...)
where the exact set of steps depends on what you observe along the way.
"""

import argparse
import contextlib
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import traceback
from configparser import ConfigParser, Error as ConfigError

try:  # installed / run as a package (``python -m rungs.main``)
    from .InlineMenu import Menu
except ImportError:  # run as a plain script (``python3 src/rungs/main.py``)
    from InlineMenu import Menu

try:  # single source of truth lives in rungs/__init__.py
    from . import __version__
except ImportError:  # plain-script mode: fall back to the installed package
    try:
        from rungs import __version__
    except ImportError:
        __version__ = 'unknown'


@contextlib.contextmanager
def _sigint_targets_child():
    """ Aim Ctrl-C at the running command instead of at rungs.

        A terminal Ctrl-C (SIGINT) is delivered to *every* process in the
        foreground process group, including rungs -- so, unguarded, it tears
        down both the command and this program and leaves the screen
        half-drawn.  We install a do-nothing SIGINT handler for the duration
        of the command so rungs survives the interrupt.

        The command still stops: a Python signal *handler* is not carried
        across ``exec`` (the kernel resets it to the default), so the child
        shell/command receives SIGINT normally.  Note that ``SIG_IGN`` would
        *not* do -- an ignored disposition *is* inherited past ``exec``,
        which would make the command ignore Ctrl-C too.
    """
    previous = signal.getsignal(signal.SIGINT)
    signal.signal(signal.SIGINT, lambda _signum, _frame: None)
    try:
        yield
    finally:
        signal.signal(
            signal.SIGINT,
            previous if previous is not None else signal.SIG_DFL)


class Rungs:
    """Fuzzy script tool workhorse class."""

    edit_menu = 'edit-rungs-config'
    env_key = '+ENV'               # the +ENV directive key, kept verbatim
    pre_key = '+PRE'               # the +PRE preamble directive key
    env_prefix = '+'               # reserved prefix: directives, not entries
    # Env var used to hand an enclosing menu's preamble to a sub-menu process.
    pre_env_var = 'RUNGS_PRE'
    # Section (shared by every menu) that may carry +ENV and/or +PRE.
    global_section = '__GLOBAL__'
    # Display keys handed to entries whose own key is longer than one char
    # (an "auto" key).  'x' is omitted because it is the exit convention.
    auto_pool = 'abcdefghijklmnopqrstuvwyz0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ'

    def __init__(self):
        self.opts = None
        self.prompts = None
        self.config_abstract = "~/.config/rungs/rungs.ini"
        self.config_dir = os.path.expanduser("~/.config/rungs")
        self.config_file = self.config_dir + '/rungs.ini'
        self.config_backup = self.config_file + '.bak'
        self.config = None
        self.menus = {}
        self.file_menus = {}
        self.global_env = []
        self.global_pre = ''          # [__GLOBAL__] preamble (a +PRE block)
        self.inherited_pre = os.environ.get(Rungs.pre_env_var) or ''
        self.menu_file = None
        self.corrupt_config = False
        self.get_config()
        self.get_inherited_file()

    def get_config(self):
        """ Read in the .ini file
            - If none, create it.
            - Create a dict of Menus by menu name (a.k.a. section name)
        """
        if not os.path.isdir(self.config_dir):
            os.makedirs(self.config_dir, 0o755, True)
        if not os.path.isfile(self.config_file):
            with open(self.config_file, "w", encoding="utf-8") as f:
                f.write(f'[{self.edit_menu}]\n')
                f.write('a: ${EDITOR=-vi} ' + f'{self.config_abstract}\n')
                f.write('x: exit\n\n')
                f.write('[example]\n')
                f.write('a: command-a\n')
                f.write('b: prompt-b\n')
                f.write('   command-b\n')
                f.write('x: exit\n')
        self.config = ConfigParser(interpolation=None)
        # Keep keys verbatim (case sensitive): a multi-character key is an
        # "auto" key and must survive parsing intact (see build_prompts).
        self.config.optionxform = lambda x: str(x)

        self.read_file()
        for section, options in self.config.items():
            if section == 'DEFAULT':
                continue
            if section == self.global_section:
                global_options = dict(options)
                self.global_pre = Rungs.join_preamble(
                    self.global_pre, self.extract_pre(global_options))
                self.global_env = self.extract_env(global_options, section)
                continue
            self.menus[section] = dict(options)
        self.apply_env(self.global_env)

    def read_file(self):
        """ Read the config file ... if not working, try the backup file """
        try:
            self.config.read(filenames=[self.config_file], encoding='utf-8')

        except Exception as exc:
            print(f'ERROR: Cannot read {self.config_file!r}:', str(exc))
            print(f'   ... Trying backup file: {self.config_backup!r} ...')
            self.config.read(filenames=[self.config_backup], encoding='utf-8')
            self.corrupt_config = True
            return

        # after every successful read of the original, copy it to the backup as
        # last known good copy
        shutil.copy(self.config_file, self.config_backup)

    def get_inherited_file(self):
        """ Re-load an ad-hoc menu file inherited from a parent process.

            When one of an ad-hoc file's menus launches a sub-menu, the child
            ``rungs`` process is told (via ``RUNGS_FILE``) which file to read,
            so sub-menus defined there remain resolvable.
        """
        inherited = os.environ.get('RUNGS_FILE')
        if inherited and os.path.isfile(inherited):
            self.load_menu_file(inherited)

    def load_menu_file(self, path):
        """ Read an ad-hoc menu file (any name; contents must be .ini format).

            The parsed menus are merged into ``self.menus`` (so that sub-menus
            defined in the file are resolvable by name) and remembered in
            ``self.file_menus`` / ``self.menu_file``.  Returns the file's own
            menus, or ``None`` if the file cannot be read / has no menus.
        """
        config = ConfigParser(interpolation=None)
        config.optionxform = lambda x: str(x)  # keep keys verbatim/case sensitive
        try:
            with open(path, encoding='utf-8') as handle:
                config.read_file(handle, source=path)
        except (OSError, ConfigError) as exc:
            print(f'ERROR: cannot read menu file {path!r}: {exc}')
            return None

        file_menus = {}
        global_env = []
        for section, options in config.items():
            if section == 'DEFAULT':
                continue
            options = dict(options)
            if section == self.global_section:
                self.global_pre = Rungs.join_preamble(
                    self.global_pre, self.extract_pre(options))
                global_env = self.extract_env(options, section)
                continue
            file_menus[section] = options
        if not file_menus:
            print(f'ERROR: no menus found in menu file {path!r}')
            return None

        self.menu_file = os.path.abspath(path)
        self.file_menus = file_menus
        self.menus.update(file_menus)  # let sub-menus resolve by name
        self.apply_env(global_env)     # a file's own [__GLOBAL__] applies too
        return file_menus

    def dump(self):
        """ Dump the menus found. """
        for section, values in self.menus.items():
            print(f'\nMENU: {section} ...')
            for option, value in values.items():
                print(f'{option}: {value}')

    @staticmethod
    def ordinary(name):  # not special
        """ Return true if the name starts with a word character"""
        return bool(re.match(r'\w', name))

    @staticmethod
    def parse_env_block(text, section):
        """ Parse a ``+ENV`` value into ``(name, value)`` pairs.

            The value holds one ``NAME=VALUE`` assignment per line; blank
            lines and ``#``/``;`` comments are ignored and one layer of
            matching surrounding quotes is stripped.  Malformed lines are
            reported and skipped.
        """
        pairs = []
        for raw in text.splitlines():
            line = raw.strip()
            if not line or line[0] in ('#', ';'):
                continue
            name, sep, value = line.partition('=')
            name = name.strip()
            if not sep or not name:
                print(f'WARNING: ignoring malformed {Rungs.env_key} '
                      f'entry in {section!r}: {raw.strip()!r}')
                continue
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in '\'"':
                value = value[1:-1]
            pairs.append((name, value))
        return pairs

    def extract_env(self, options, section):
        """ Remove and parse the ``+ENV`` block from a mutable options mapping.

            Returns the section's ``(name, value)`` assignments.  Keys with the
            reserved ``+`` prefix are directives, never menu entries; a stray
            one is reported and dropped.  In the global section every option
            must be ``+ENV``.
        """
        block = options.pop(Rungs.env_key, None)
        for stray in [key for key in options
                      if key.startswith(Rungs.env_prefix)]:
            print(f'WARNING: ignoring reserved directive {stray!r} '
                  f'in {section!r}')
            options.pop(stray, None)
        if section == Rungs.global_section:
            for stray in list(options):
                print(f'WARNING: {section} permits only {Rungs.env_key}; '
                      f'ignoring {stray!r}')
                options.pop(stray, None)
        if block is None:
            return []
        return Rungs.parse_env_block(block, section)

    @staticmethod
    def extract_pre(options):
        """ Remove and return the ``+PRE`` preamble from a mutable options map.

            The preamble is raw shell text that gets prepended to *every*
            command in a section.  Unlike ``+ENV`` it is deliberately *not*
            variable-expanded -- which is exactly why a distinct directive is
            needed: :meth:`apply_env` runs ``expandvars``, so a snippet that
            refers to ``$fail`` / ``$OK_MSG`` would be gutted before it ran.

            Returns the text, or ``None`` when there is no non-blank ``+PRE``.
        """
        block = options.pop(Rungs.pre_key, None)
        return block if block and block.strip() else None

    @staticmethod
    def join_preamble(*parts):
        """ Join the non-empty preamble snippets ``parts`` with newlines. """
        return '\n'.join(part for part in parts if part)

    @staticmethod
    def apply_env(pairs):
        """ Set each ``(name, value)`` in ``os.environ`` (in order), expanding
            ``$VAR`` references -- ``subprocess`` never expands env values for
            us.  Returns the previous values so the caller can restore them.
        """
        saved = []
        for name, value in pairs:
            saved.append((name, os.environ.get(name)))
            os.environ[name] = os.path.expandvars(value)
        return saved

    @staticmethod
    def restore_env(saved):
        """ Undo a matching :meth:`apply_env`, restoring the prior values. """
        for name, old in reversed(saved):
            if old is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = old

    def section_preamble(self, section_pre):
        """ The full ``+PRE`` text to prepend to this section's commands.

            Order matters: the global preamble comes first (a base), then any
            preamble inherited from an enclosing menu (via ``RUNGS_PRE``), and
            finally the section's own ``+PRE`` -- so a section may redefine a
            helper it inherited.
        """
        return Rungs.join_preamble(self.global_pre, self.inherited_pre,
                                   section_pre)

    def child_preamble(self, section_pre):
        """ The preamble exported to sub-menus (``RUNGS_PRE``).

            The global preamble is intentionally *left out*: every ``rungs``
            process adds its own global, so including it here would stack a
            fresh copy at each nesting level.  What we pass down is only the
            "outer sections" chain, which a child cannot otherwise rebuild.
        """
        return Rungs.join_preamble(self.inherited_pre, section_pre)

    def push_preamble(self, preamble):
        """ Export ``preamble`` (if any) so sub-menus inherit it.

            Returns the previous ``RUNGS_PRE`` value for :meth:`pop_preamble`.
        """
        saved = os.environ.get(Rungs.pre_env_var)
        if preamble:
            os.environ[Rungs.pre_env_var] = preamble
        else:
            os.environ.pop(Rungs.pre_env_var, None)
        return saved

    @staticmethod
    def pop_preamble(saved):
        """ Undo a matching :meth:`push_preamble`. """
        if saved is None:
            os.environ.pop(Rungs.pre_env_var, None)
        else:
            os.environ[Rungs.pre_env_var] = saved

    @staticmethod
    def shell_status(returncode):
        """ Present a subprocess return code the way a shell would: a
            command killed by signal *N* becomes ``128 + N`` (so a Ctrl-C
            interruption reads as 130 rather than -2).
        """
        return 128 - returncode if returncode < 0 else returncode

    def run_cmd(self, cmd, precmd=None, dry_run=None, preamble=None):
        """ Run `cmd`, optionally preceded by `preamble` and `precmd`.

            ``preamble`` is the shared shell text prepended to every command
            in a section (the ``+PRE`` directive).  It is executed ahead of
            the command but deliberately kept out of the ``==>`` echo -- else
            the same snippet would be reprinted before every single step.

            Returns the exit status of the last command run -- always 0 in
            dry-run mode -- so callers can surface a failing step instead of
            silently swallowing it (as ``os.system`` did).  A Ctrl-C while
            the command runs interrupts *only* that command (see
            :func:`_sigint_targets_child`); rungs itself keeps going and
            reports the command's status.
        """
        dry_run = self.opts.dry_run if dry_run is None else dry_run
        script = Rungs.join_preamble(preamble, precmd, cmd)
        echo = Rungs.join_preamble(precmd, cmd)
        if dry_run:
            print(f'WOULD RUN: {echo}', flush=True)
            return 0
        print(f'==> {echo}', flush=True)
        with _sigint_targets_child():
            proc = subprocess.run(script, shell=True, check=False)
        return Rungs.shell_status(proc.returncode)

    def relaunch(self, menu_spec):
        """ Launch a sub-menu in a fresh `rungs` process.

            Running in a child process keeps each menu's state (and its
            terminal handling) independent, and lets a menu "call" another
            menu from within a command.  The child uses the current
            interpreter, with this package's parent directory added to
            ``PYTHONPATH`` so it also works from an uninstalled source
            checkout (e.g. via ``./runner``) -- and, unlike an ``os.chdir``
            approach, it leaves our own working directory untouched.
        """
        pkg_parent = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        env = os.environ.copy()
        env['PYTHONPATH'] = os.pathsep.join(
            [pkg_parent] + ([env['PYTHONPATH']] if env.get('PYTHONPATH') else []))
        if self.menu_file:  # keep ad-hoc file sub-menus reachable in the child
            env['RUNGS_FILE'] = self.menu_file

        argv = [sys.executable, '-m', 'rungs.main']
        if self.opts.dry_run:
            argv.append('-n')
        try:
            argv += shlex.split(menu_spec)
        except ValueError:
            argv.append(menu_spec)
        with _sigint_targets_child():
            proc = subprocess.run(argv, env=env, check=False)
        return Rungs.shell_status(proc.returncode)

    def build_prompts(self, options):
        """ Build the prompts InlineMenu needs from a section's options.

            A one-character key is a *literal* display key -- make it a
            mnemonic when you can (``a`` for *add*, ``d`` for *delete*).  A
            longer key is an *auto* key: it only has to be unique in the .ini
            file, and rungs hands the entry the next free display character
            from :data:`auto_pool` (which reserves ``x`` for exit) in file
            order.  Either way the file order sets the menu order, so you can
            insert an entry without re-lettering its neighbours.
        """
        keys = []
        prompts = {}
        cmds = {}
        taken = {key for key in options
                 if len(key) == 1 and not key.startswith(Rungs.env_prefix)}
        pool = iter(Rungs.auto_pool)
        for key, value in options.items():
            if key.startswith(Rungs.env_prefix):
                continue  # reserved directive, not a menu entry
            if len(key) == 1:
                display = key
            else:
                display = next((char for char in pool if char not in taken),
                               None)
                if display is None:
                    print(f'WARNING: no free display key for {key!r}; '
                          f'skipping it')
                    continue
                taken.add(display)
            keys.append(display)
            lines = value.splitlines() if value else ['']
            prompts[display] = lines.pop(0)
            if not lines:
                cmds[display] = prompts[display]
            else:
                cmds[display] = '\n'.join(lines)

        return keys, prompts, cmds

    def make_section_menu(self, menus=None):
        """ In the case there are no specified menus, make a menu of them all """
        menus = self.menus if menus is None else menus
        keys = Rungs.auto_pool
        options = {}
        for section in menus:
            if self.ordinary(section):
                key, keys = keys[:1], keys[1:]
                if key:
                    options[key] = f"rungs '{section}'"

        options['x'] = 'exit'
        return options

    def do_menu(self, menu_name, options=None):
        """ Show a menu and run the picked command until the user exits.

            A section's ``+ENV`` / ``+PRE`` blocks are applied for the whole
            section and removed again on the way out (even on error or
            interrupt).  The preamble is echoed once, up front; the individual
            commands then echo on their own (see :meth:`run_cmd`).
        """
        if options is None:
            options = self.menus.get(menu_name)
        options = dict(options) if options else {}
        # +PRE must be popped before extract_env, which reports any leftover
        # reserved directive as a stray.
        section_pre = self.extract_pre(options)
        env_pairs = self.extract_env(options, menu_name)
        keys, prompts, cmds = self.build_prompts(options)
        if not keys:
            return

        preamble = self.section_preamble(section_pre)
        if preamble:
            print(f'==> [preamble]\n{preamble}', flush=True)
        saved = self.apply_env(env_pairs)
        saved_pre = self.push_preamble(self.child_preamble(section_pre))
        try:
            todo = keys[0]
            notice = None
            while True:
                menu = Menu(prompts, todo, title=menu_name, notice=notice)
                choice = menu.prompt()
                cmd = cmds[choice]
                if cmd in ('exit', 'quit'):
                    return
                if cmd.startswith('rungs '):
                    status = self.relaunch(cmd[len('rungs '):])
                else:
                    status = self.run_cmd(cmd, preamble=preamble)

                notice = (f'{choice!r} exited with status {status}'
                          if status else None)

                idx = keys.index(choice)
                todo = keys[min(idx + 1, len(keys) - 1)]
        finally:
            self.pop_preamble(saved_pre)
            self.restore_env(saved)

    def find_menu(self, wanted, quiet=False):
        """ Find the menu given the name spec several different ways.

            When ``quiet`` is true, the "no match"/"multiple" diagnostics are
            suppressed (used while probing a spec that may name a file).
        """
        def within_on_boundary(menu_name, name):
            index = 0
            while index < len(name):
                mat = re.search(r'\b[a-z]\w*\b', name[index:])
                if mat:
                    remainder = name[index + mat.start():]
                    if remainder.startswith(menu_name):
                        return True
                    index += mat.end()
                    continue
                break
            return False

        # Look for exact match
        founds = []
        found = wanted if wanted in self.menus else None
        # look for case independent match
        if not found:
            for name in self.menus:
                if self.ordinary(name) and wanted.lower() == name.lower():
                    founds.append(name)
        # look for case independent partial match
        if not found and not founds:
            for name in self.menus:
                if self.ordinary(name) and within_on_boundary(
                        wanted.lower(), name.lower()):
                    founds.append(name)
        if not found and founds:
            found = founds[0] if len(founds) == 1 else found

        if not found and not quiet:
            if len(founds) > 1:
                print(f'ERROR: multiple {wanted!r} in {list(founds)}')
            elif len(founds) < 1:
                print(f'ERROR: no {wanted!r} in {list(self.menus)}')
        return found

    def run_spec(self, spec):
        """ Run one positional argument.

            A value without a ``/`` is first tried as a menu name (the usual
            fuzzy matching); if that fails -- or the value contains a ``/`` --
            it is treated as the path of an ad-hoc ``.ini`` menu file.  Returns
            ``False`` when it is neither a known menu nor a readable menu file
            (i.e., misuse).
        """
        if '/' not in spec:
            found = self.find_menu(spec, quiet=True)
            if found:
                self.do_menu(found)
                return True

        if os.path.isfile(spec):
            return self.run_menu_file(spec)

        return False

    def run_menu_file(self, path):
        """ Load an ad-hoc menu file and run the appropriate menu(s).

            A single ordinary menu runs directly; several ordinary menus are
            offered as a list (special ``>name`` menus stay hidden, as in the
            config).  A file with only special menus runs its first one.
        """
        file_menus = self.load_menu_file(path)
        if not file_menus:
            return False

        ordinary = [name for name in file_menus if self.ordinary(name)]
        if len(ordinary) == 1:
            self.do_menu(ordinary[0])
        elif ordinary:
            self.do_menu(os.path.basename(path),
                         self.make_section_menu(file_menus))
        else:
            self.do_menu(next(iter(file_menus)))
        return True

    def main(self):
        """ Parse arguments and dispatch to the requested menu(s). """
        parser = argparse.ArgumentParser(
            prog='rungs',
            description='Menu for fuzzy Linux procedures.')
        parser.add_argument('-e', '--edit', action="store_true",
                            help='edit config (i.e., runs edit-rungs-config)')
        parser.add_argument('-n', '--dry-run', action="store_true",
                            help='show commands w/o running them')
        parser.add_argument('--version', action='version',
                            version=f'%(prog)s {__version__}')
        parser.add_argument('menus', nargs='*',
                            help='zero or more menu names or .ini file paths')
        self.opts = parser.parse_args()
        if self.opts.edit or self.corrupt_config:
            self.opts.menus = [self.edit_menu]
        if self.corrupt_config:
            print(f'NOTE: substituting {self.edit_menu!r} ...')
        if self.opts.menus:
            for spec in self.opts.menus:
                if not self.run_spec(spec):
                    parser.error(
                        f'{spec!r} is neither a known menu nor an .ini file')
        else:
            self.opts.menus = ['ALL-MENUS']
            self.do_menu('ALL-MENUS', self.make_section_menu())


def run():
    """Console-script entry point; wrap main in try/except."""
    try:
        Rungs().main()
    except KeyboardInterrupt:
        pass
    except Exception as exce:  # pylint: disable=broad-exception-caught
        print("exception:", str(exce))
        print(traceback.format_exc())


if __name__ == '__main__':
    run()
