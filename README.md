# rungs -- A Tool for Fuzzy Procedures
`rungs` is a tool help navigate "fuzzy" procedures on Linux where you might want to:
* skip certain steps if certain vague criteria are met
* repeat certain steps if they failed and trying again makes sense

You very simply specify your procedures within a single `.ini` file.

> **Quick Start**: from the CLI
> * **If `python3 -V` shows v3.11 or later, install using `pipx`**:
>   * `python3 -m pip install --user pipx # if pipx not installed`
>   * `python3 -m pipx ensurepath # if needed (restart terminal)`
>   * `pipx upgrade rungs || pipx install rungs # to install/upgrade`
> * **Else for python3.10 and lesser versions, install using `pip`**:
>   * `python3 -m pip install --user --upgrade rungs`
> * **To run**:
>   * `rungs # to run and show all menus`
>   * `rungs {menu-name} # run the specified menu`
>   * `rungs --edit # edit your menus`

**Mnemonic**: step through the **rungs** of your laddered procedure ;-)

##  A Practical Example -- Manually Updating EndeavourOS
Here is an example menu for manually update an EndeavourOS:

![eos-update-menu](https://github.com/joedefen/rungs/blob/main/images/eos-update-menu.png?raw=true)

Notes:
* Except for the first personal command, all commands are standard on EndeavourOS.
* All commands are run literally by `bash` except:
  * `exit` which means exit the menu.
  * `rungs {menu-name}` runs rungs recursively using `python3`
* To run a command:
  * highlight the command by typing the character before the ':' or move the cursor with the up/down arrow keys.
  * then press ENTER.
* After the command runs, the next command is highlighted and runs with just ENTER if desired.
* To, repeat and skip commands, just select another command rather than the next.
* **IMPORTANT: If the menu does not fit within your terminal, then resize until it does fit.**

## Config: `~/.config/rungs/rungs.ini`
Edit `~/.config/rungs/rungs.ini` to configure your menu. The "eos-update-menu" was configured by adding this section:
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

## `rungs` Command Line
```
usage: rungs [-h] [-e] [-n] [menus ...]

positional arguments:
  menus          zero or more arguments

options:
  -h, --help     show this help message and exit
  -e, --edit     edit config (i.e., runs edit-rungs-config)
  -n, --dry-run  show commands w/o running them
```
Thus, you can:
* run `rungs --edit` to edit the configuration file.
* run `rungs` with no arguments to given a menu of all the "ordinary" menus.
* provide the name specifiers of the menus to run them; each name spec can match:
  * exactly,
  * case independent exactly (if unique and ordinary),
  * or case independent substring match but only at word boundaries (if unique and ordinary); e.g., for the menus, `['edit-rungs-config', 'example', 'eos-update']`:
    * these name specs would find a menu:  'edit', 'ex', 'EOS-', 'EOS-UPDATE'
    * these name specs would NOT: 'date', 'e'.
    
**"Special" (vs "Ordinary")** menu names begin with character other than [_A-Za-z0-9], and are excluded from being run unless given the whole, exact, memory sensitive name. A suggested naming convention for menus:
* beginning `>` for a sub-menu that should not be called independently
* beginning `!` for a deprecated menu (but not ready to remove it)
    
## The Edit Menu and Handling Corrupt .ini Files
On first startup, the .ini file contains a menu for editing that you may customize:
```
[edit-rungs-config]
a: ${EDITOR=-vi} ~/.config/rungs/rungs.ini
x: exit

[example]
a: command-a
b: prompt-b
   command-b
x: exit
```
For example, you might change the default from `vi` to `geany` if installed and desired. Also, note:
* You may remove the `example` which shows a multilined value which must be indented lines after the first.
* Do **NOT** remove the `edit-rungs-config` menu; it is needed for `--edit` option AND recovery.
* The `edit-rungs-config` shows how to pass variables to your commands.
* In case of a corrupt `.ini`, you will see the error and the `edit-rungs-config` menu.
* Each time the `.ini` file is read and valid, `~/.config/rungs/rungs.ini.bak` is written; in the case you just made a terrible change, recover using the `.ini.bak` file manually (w/o running `rungs -e`).

## Practical Examples
The `examples` subdirectory includes more practical examples, including
* A two-level menu for Fedora updates and release upgrades.

These menus many not be current and are not tested; use only after reviewing for correctness and completeness.


