# rungs — interactive menus for fuzzy Linux procedures

[![PyPI version](https://img.shields.io/pypi/v/rungs.svg)](https://pypi.org/project/rungs/)
[![Python versions](https://img.shields.io/pypi/pyversions/rungs.svg)](https://pypi.org/project/rungs/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://github.com/joedefen/rungs/blob/main/LICENSE)
[![PyPI downloads](https://img.shields.io/pypi/dm/rungs.svg)](https://pypi.org/project/rungs/)

`rungs` turns a plain `.ini` file into a friendly, keyboard-driven menu for
running shell commands — one **rung** at a time up the ladder of a procedure.

It is built for *fuzzy* procedures on Linux, where the exact steps depend on
what you encounter along the way:

* **skip** steps whose vague preconditions are already met, and
* **repeat** steps that failed — because retrying them makes sense.

Instead of scrolling back through your shell history (or keeping a notes file
of cryptic one-liners), you get a menu where you highlight the next step, hit
<kbd>Enter</kbd>, and watch it run. Which step you run next is your call.

Typical configs are **system updates** and **Docker housekeeping** — the chores
with "too many commands to remember".

![eos-update-menu](https://github.com/joedefen/rungs/blob/main/images/eos-update-menu.png?raw=true)

---

## Why `rungs`?

| | |
|---|---|
| **Fuzzy, not fixed** | A procedure is a *menu*, not a script. You decide what runs next based on what you observe. |
| **Tiny & self-contained** | Pure Python standard library — no dependencies. One `.ini` file holds every menu. |
| **Nothing to remember** | Commands live in a readable config; the menu shows descriptions for the messy ones. |
| **Recoverable** | Every valid config is auto-backed-up to `rungs.ini.bak`, so a bad edit is easy to undo. |
| **Composable** | Menus can launch other menus, so you can build multi-level procedures. |

## Requirements

* Python **3.11+**
* A POSIX-ish terminal (Linux); reads single keypresses via `termios`

## Installation

`rungs` is a console app, so [`pipx`](https://pipx.pypa.io/) is the recommended
way to install it in an isolated environment:

```sh
python3 -m pip install --user pipx        # if pipx isn't installed
python3 -m pipx ensurepath                # if needed (restart your terminal)
pipx upgrade rungs || pipx install rungs  # install / upgrade
```

Prefer a plain `pip` install? That works too:

```sh
python3 -m pip install --user --upgrade rungs
```

## Quick start

```sh
rungs                 # show a menu of all your menus, then pick one
rungs eos-update      # run a specific menu directly
rungs --edit          # edit your configuration file
rungs --dry-run       # show the commands without running them
```

Once a menu is up:

* type the **key** shown before the `:` (or move with <kbd>↑</kbd>/<kbd>↓</kbd>),
* press <kbd>Enter</kbd> to run the highlighted command,
* after it finishes, the **next** entry is pre-selected — just press
  <kbd>Enter</kbd> to continue, or pick any other entry to skip/repeat.

> **Note:** if a menu does not fit your terminal, resize the terminal until it
> does — `rungs` re-flows automatically.

## Configuration: `~/.config/rungs/rungs.ini`

The first time you run `rungs` it creates a config for you. A menu is just an
`.ini` section; each entry is `key: command`.

```ini
[eos-update]
a: my-snaps                                 # replace snaps of root, home, etc.
b: sudo reflector -l20 -cus,ca --sort rate --save /etc/pacman.d/mirrorlist
c: eos-rankmirrors                          # update EndeavourOS mirrors
d: eos-update --yay                         # EndeavourOS update script
e: sudo paccache -rk1; sudo paccache -ruk0  # cleanup cache
f: sudo pacman -Rns $(pacman -Qdtq)         # cleanup orphans
g: flatpak update
h: flatpak uninstall --unused; flatpak repair
i: sudo journalctl --vacuum-time=2weeks
j: sudo reboot now
x: exit
```

Notes:

* This config mirrors the menu you see, so the menu *is* the documentation.
* For long commands, put a **description on the first line** and the command on
  the **indented lines** that follow — the menu shows the description and bash
  receives the rest, literally:

  ```ini
  b: prompt-b          # shown in the menu
     command-b         # sent to bash literally
  ```

* Keys must be a **single character** and **unique** within a menu. If you use a
  longer key, only its first character is used.
* `exit` (or `quit`) closes the menu.

## Command line

```
usage: rungs [-h] [-e] [-n] [menus ...]

positional arguments:
  menus          zero or more menu name specifiers

options:
  -h, --help     show this help message and exit
  -e, --edit     edit config (i.e., runs edit-rungs-config)
  -n, --dry-run  show commands w/o running them
```

Menu names can be matched:

* **exactly** (`eos-update`, and any "special" name),
* **case-insensitively exactly** (if unique and ordinary), e.g. `EOS-UPDATE`,
* or by a **case-insensitive substring at a word boundary** (if unique and
  ordinary) — for menus `['edit-rungs-config', 'example', 'eos-update']`:
  * `edit`, `ex`, `EOS-` and `EOS-UPDATE` all resolve,
  * but `date` and `e` do **not**.

### Ordinary vs. special menus

A menu name beginning with a word character (`[_A-Za-z0-9]`) is **ordinary** and
can be fuzzy-matched. A name beginning with anything else is **special**: it is
hidden from the "all menus" list and only runs when you give its exact name.
Suggested conventions:

* `>name` — a sub-menu that shouldn't be called on its own,
* `!name` — a deprecated menu you're not ready to delete yet.

## The edit menu & recovering a broken config

`rungs --edit` opens the `edit-rungs-config` menu, whose default action launches
`${EDITOR:-vi}`. **Do not remove that menu** — it powers `--edit` *and* recovery.

If your `.ini` ever becomes corrupt, `rungs` prints the error and drops you into
`edit-rungs-config`. After every successful read, your config is copied to
`~/.config/rungs/rungs.ini.bak`; restore it manually if you make a terrible edit.

## Examples

The [`samples/`](samples/) directory contains ready-to-adapt menus, including a
two-level Fedora update + release-upgrade procedure. These are **not** tested
against the latest distro releases — review them before running.

## Recipes

* **System update:** mirrors → package manager update → flatpak → cache/orphan
  cleanup → reboot.
* **Docker housekeeping:** `docker system df` → prune images/containers/volumes →
  `docker system prune` → review leftover networks.
* **Onboarding a machine:** snapshots → config sync → dotfiles → reboot.

## Development

```sh
git clone https://github.com/joedefen/rungs.git
cd rungs
python3 -m venv .venv && . .venv/bin/activate
python3 -m pip install -e .

# run from source, no install needed:
./runner --help
# ...which is equivalent to:
PYTHONPATH=src python3 src/rungs/main.py --help
```

Releases are built and published with [flit](https://flit.pypa.io/):

```sh
python3 -m pip install --user flit
# bump version in pyproject.toml
flit build              # sdist + wheel in dist/
flit publish            # upload to PyPI (prompts for your token)
```

## License

MIT — see [LICENSE](LICENSE).

**Mnemonic:** step through the **rungs** of your laddered procedure.
