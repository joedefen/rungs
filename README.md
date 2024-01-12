# rung -- A Tool for Fuzzy Procedures
`rung` is a tool help navigate "fuzzy" procedures on Linux where you might want to:
* skip certain steps if certain vague criteria are met
* repeat certain steps if they failed and trying again makes sense

You very simply specify your procedures a single `.ini` file.

##  A Practical Example -- Manually Updating EndeavourOS

![eos-update-menu](https://github.com/joedefen/rung/blob/main/images/eos-update-menu.png?raw=true)

Notes:
* Except for the first personal command, all commands are standard
* All commands are run literally by `bash` except:
  * `exit` which means exit the menu.
  * `rung {menu-name}` runs rung recursively using `python3`
* To run a command:
  * highlight the command by typing the character before the ':' or move the cursor by using the up and down arrow keys.
  * then press enter.
* After the command runs, the following command is highlighted.
* Repeat and skip commands by manipulating the cursor.
* **If the menu does not fit in your terminal, the resize until it fits.**

## Config: `~/.config/rung/rung.ini`
Edit `~/.config/rung/rung.ini` to configure your menu. The "eos-update-menu" was configured by adding this section:
```
[eos-update]
a: my-snaps               # replace snaps of root, home, etc 
b: reflector-simple       # update Arch mirrors
c: eos-rankmirrors        # update EndeavourOS mirrors
d: eos-update --yay       # EndeavourOS update script
e: sudo paccache -rk1; sudo paccache -ruk0 # cleanup cache
f: sudo pacman -Rns $(pacman -Qdtq)        # cleanup orphans
g: flatpak update
h: flatpak uninstall --unused; flatpak repair
i: sudo journalctl --vacuum-time=2weeks
j: sudo reboot now
x: exit
```
So, the config looks nearly the same as the menu, but if you specify a multiline value, then:
* the first line is shown, and
* the subsequent lines are given to bash literally.

In this manner, for very complicated commands, you can provide a summary description of what is to be run.

# `rung` Command Line
```
usage: rung [-h] [-e] [-n] [menus ...]

positional arguments:
  menus          zero or more arguments

options:
  -h, --help     show this help message and exit
  -e, --edit     edit config (i.e., runs edit-rung-config)
  -n, --dry-run  do NOT do anything
```
Thus, you can:
* run `rung -e` to edit the configuration file.
* run `rung` with no arguments to given a menu of all the defined menus.
* provide the name specifiers of the menus to run them; each name spec can match:
  * exactly,
  * case independent exactly (if unique),
  * or case independent substring match but only at word boundaries (if unique); e.g., for the menus, `['edit-rung-config', 'example', 'eos-update']`:
    * these name specs would find a menu:  'edit', 'ex', 'EOS-', 'EOS-UPDATE'
    * these name specs would NOT: 'date', 'e'.


