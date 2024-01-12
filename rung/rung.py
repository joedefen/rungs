#!/usr/bin/env python3
"""
"rung" is a tool to step thru fuzz scripts.
- its config file is at "~/.config/rung/rung.yaml
- the last syntactically correct  "~/.config/rung/rung.yaml"
"""
# pylint: disable=import-outside-toplevel,invalid-name
# pylint: disable=too-many-branches,broad-exception-caught

import os
import traceback
import re
from configparser import ConfigParser
try:
    from InlineMenu import Menu
except:
    from rung.InlineMenu import Menu

class Rung:
    """ Fuzzy script tool workhorse class. """
    def __init__(self):
        self.rung_cmd = os.path.abspath(__file__)
        self.opts = None
        self.prompts = None
        self.config_dir = os.path.expanduser("~/.config/rung")
        self.config_file = self.config_dir + '/rung.ini'
        self.config = None
        self.menus = {}
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
                f.write('[edit-rung-config]\n')
                f.write('a: ${EDITOR=-vi} ' + f'"{self.config_file}"\n')
                f.write('x: exit\n\n')
                f.write('[example]\n')
                f.write('a: command-a\n')
                f.write('b: prompt-b\n')
                f.write('   command-b\n')
                f.write('x: exit\n')
        self.config = ConfigParser()
        self.config.read(filenames=[self.config_file], encoding='utf-8')
        for section, options in self.config.items():
            if section != 'DEFAULT':
                self.menus[section] = options

    def dump(self):
        """ Dump the menus found."""
        for section, values in self.menus.items():
            print(f'\nMENU: {section} ...')
            for option, value in values.items():
                print(f'{option}: {value}')


    def run_cmd(self, cmd, precmd=None):
        """Run a command and option prior command
           - clear the screen first
           - if dry run, clear the screen first
         """
        echo = 'echo WOULD +' if self.opts.dry_run else 'set -x; '
        os.system('clear')
        if self.opts.dry_run:
            cmd = f'{cmd!r}'
            precmd = f'{precmd!r}' if precmd else None
        if precmd:
            print(f'1 ---- {echo} {precmd!r}')
            os.system(f'{echo} {precmd}')
            print(f'2 ---- {echo} {cmd!r}')
            os.system(f'{echo} {cmd}')
        else:
            print(f'3 ---- {echo} {cmd!r}')
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
        keys = 'abcdefghijklmnopqrstuvwyz0123456780ABCDEFGHIJKLMNOPQRSTUVWXYZ'
        options = {}
        for section in self.menus:
            key, keys = keys[:1], keys[1:]
            if key:
                options[key] = f'rung {section}'

        options['x'] = 'exit'
        return options

    def do_menu(self, menu_name, options):
        """ TBD """
        keys, prompts, cmds = self.build_prompts(options)

        todo = keys[0]
        while True:
            menu = Menu(prompts, todo, title=menu_name)
            choice = menu.prompt()
            cmd = cmds[choice]
            if cmd in ('exit', 'quit'):
                return
            if cmd.startswith('rung '):
                cmd = f'python3 "{self.rung_cmd}" {cmd[5:]}'
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
        founds, found = [], self.menus.get(wanted, None)
            ##### look for case independent match
        if not found:
            for name in self.menus:
                if wanted.lower() == name.lower():
                    founds.append(name)
            ##### look for case independent partial match
        if not found and not founds:
            for name in self.menus:
                if within_on_boundary(wanted.lower(), name.lower()):
                    founds.append(name)
        if not found and founds:
            found = founds[0] if len(founds) == 1 else found
        return found, self.menus.get(found) if found else None

    def main(self):
        """TDB"""
        import argparse
        parser = argparse.ArgumentParser()
        parser.add_argument('-e', '--edit', action="store_true",
                help='edit config (i.e., runs edit-rung-config)')
        parser.add_argument('-n', '--dry-run', action="store_true",
                help='do NOT do anything')
        parser.add_argument('menus', nargs='*',
                help='zero or more arguments')
        self.opts = parser.parse_args()
        if self.opts.edit:
            self.opts.menus = ['edit-rung-config'] + self.opts.menus
        os.system('reset')
        # self.dump()
        if self.opts.menus:
            for menu_name in self.opts.menus:
                found, options = self.find_menu(menu_name)
                if found:
                    self.do_menu(found, options)
                else:
                    print(f'ERROR: no {menu_name!r} in {list(self.menus)}')
        else:
            self.opts.menus = ['ALL-MENUS']
            self.do_menu ('ALL-MENUS', self.make_section_menu())

def run():
    """Wrap main in try/except."""
    try:
        Rung().main()
    except KeyboardInterrupt:
        pass
    except Exception as exce:
        print("exception:", str(exce))
        print(traceback.format_exc())

if __name__ == '__main__':
    run()
