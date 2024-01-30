#!/usr/bin/env python3
"""
"rungs" is a tool to step thru fuzz scripts.
- its config file is at "~/.config/rungs/rungs.yaml
- the last syntactically correct  "~/.config/rungs/rungs.yaml"
"""
# pylint: disable=import-outside-toplevel,invalid-name
# pylint: disable=too-many-branches,broad-exception-caught

import os
import traceback
import re
import shutil
import shlex
from configparser import ConfigParser
try:
    from InlineMenu import Menu
except Exception:
    from rungs.InlineMenu import Menu

class Rungs:
    """ Fuzzy script tool workhorse class. """
    edit_menu = 'edit-rungs-config'
    def __init__(self):
        self.rung_cmd = os.path.abspath(__file__)
        self.opts = None
        self.prompts = None
        self.config_abstract = "~/.config/rungs/rungs.ini"
        self.config_dir = os.path.expanduser("~/.config/rungs")
        self.config_file = self.config_dir + '/rungs.ini'
        self.config_backup = self.config_file + '.bak'
        self.config = None
        self.menus = {}
        self.corrupt_config = False
        self.get_config()

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
        self.config.optionxform = str # makes keys case sensitive
                      
        self.read_file()
        for section, options in self.config.items():
            if section != 'DEFAULT':
                self.menus[section] = options
                
    def read_file(self):
        """ Read the config file ... if not working, try the backup file"""
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


    def dump(self):
        """ Dump the menus found."""
        for section, values in self.menus.items():
            print(f'\nMENU: {section} ...')
            for option, value in values.items():
                print(f'{option}: {value}')

    @staticmethod
    def ordinary(name): # not special
        """ Return true if the name starts with a word character"""
        return bool(re.match(r'\w', name))


    def run_cmd(self, cmd, precmd=None, dry_run=None):
        """Run a command and optional prior command;
           - opts.args.dry_run can be overridden
         """
        dry_run = self.opts.dry_run if dry_run is None else dry_run
        echo = 'echo -e WOULD RUN:' if dry_run else 'set -x; '
        # os.system('clear')
        if dry_run:
            cmd = shlex.quote(cmd)
            precmd = shlex.quote(precmd) if precmd else None
        if precmd:
            # print(f'1 ---- {echo} {precmd!r}')
            os.system(f'{echo} {precmd}')
            # print(f'2 ---- {echo} {cmd!r}')
            os.system(f'{echo} {cmd}')
        else:
            # print(f'3 ---- {echo} {cmd!r}')
            os.system(f'{echo} {cmd}')

    def build_prompts(self, options):
        """ From the "options" in the sections options, create
            the prompts per what InlineMenu requires. """
        keys = []
        prompts = {}
        cmds = {}
        for key, value in options.items():
            keys.append(key)
            lines = value.splitlines()
            prompts[key] = lines.pop(0)
            if not lines:
                cmds[key] = prompts[key]
            else:
                cmds[key] = '\n'.join(lines)

        return keys, prompts, cmds

    def make_section_menu(self):
        """ In the case there are no specified menus, make a menu of them all """
        keys = 'abcdefghijklmnopqrstuvwyz0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ'
        options = {}
        for section in self.menus:
            if self.ordinary(section):
                key, keys = keys[:1], keys[1:]
                if key:
                    options[key] = f"rungs '{section}'"

        options['x'] = 'exit'
        return options

    def do_menu(self, menu_name, options=None):
        """ TBD """
        options = options if options else self.menus.get(menu_name)
        keys, prompts, cmds = self.build_prompts(options)

        todo = keys[0]
        while True:
            menu = Menu(prompts, todo, title=menu_name)
            choice = menu.prompt()
            cmd = cmds[choice]
            if cmd in ('exit', 'quit'):
                return
            if cmd.startswith('rungs '):
                opts=' -n' if self.opts.dry_run else ''
                cmd = f'python3 "{self.rung_cmd}"{opts} {cmd[5:]}'
                self.run_cmd(cmd, dry_run=False)
            else:
                self.run_cmd(cmd)

            idx = keys.index(choice)
            todo = keys[min(idx+1, len(keys)-1)]

    def find_menu(self, wanted):
        """ Find the menu given the name spec several different ways. """
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

            ##### Look for exact match
        founds = []
        found = wanted if wanted in self.menus else None
            ##### look for case independent match
        if not found:
            for name in self.menus:
                if self.ordinary(name) and wanted.lower() == name.lower():
                    founds.append(name)
            ##### look for case independent partial match
        if not found and not founds:
            for name in self.menus:
                if self.ordinary(name) and within_on_boundary(
                                wanted.lower(), name.lower()):
                    founds.append(name)
        if not found and founds:
            found = founds[0] if len(founds) == 1 else found

        if not found and len(founds) > 1:
            print(f'ERROR: multiple {wanted!r} in {list(founds)}')
        elif not found and len(founds) < 1:
            print(f'ERROR: no {wanted!r} in {list(self.menus)}')
        return found

    def main(self):
        """TDB"""
        import argparse
        parser = argparse.ArgumentParser()
        parser.add_argument('-e', '--edit', action="store_true",
                help='edit config (i.e., runs edit-rungs-config)')
        parser.add_argument('-n', '--dry-run', action="store_true",
                help='show commands w/o running them')
        parser.add_argument('menus', nargs='*',
                help='zero or more arguments')
        self.opts = parser.parse_args()
        if self.opts.edit or self.corrupt_config:
            self.opts.menus = [self.edit_menu]
        if self.corrupt_config:
            print(f'NOTE: substituting {self.edit_menu!r} ...')
        # os.system('reset')
        # self.dump()
        if self.opts.menus:
            for menu_name in self.opts.menus:
                found = self.find_menu(menu_name)
                if found:
                    # os.system('reset')
                    self.do_menu(found)
        else:
            self.opts.menus = ['ALL-MENUS']
            self.do_menu ('ALL-MENUS', self.make_section_menu())

def run():
    """Wrap main in try/except."""
    try:
        Rungs().main()
    except KeyboardInterrupt:
        pass
    except Exception as exce:
        print("exception:", str(exce))
        print(traceback.format_exc())

if __name__ == '__main__':
    run()
