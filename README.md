# rungs — interactive menus for fuzzy Linux procedures

[![PyPI version](https://img.shields.io/pypi/v/rungs.svg)](https://pypi.org/project/rungs/)
[![Python versions](https://img.shields.io/pypi/pyversions/rungs.svg)](https://pypi.org/project/rungs/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://github.com/joedefen/rungs/blob/main/LICENSE)
[![PyPI downloads](https://img.shields.io/pypi/dm/rungs.svg)](https://pypi.org/project/rungs/)
[![CI](https://github.com/joedefen/rungs/actions/workflows/ci.yml/badge.svg)](https://github.com/joedefen/rungs/actions/workflows/ci.yml)

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
with "too many commands to remember". `rungs` also makes a great **executable
runbook** — see [Executable runbooks (stepped specs)](#executable-runbooks-stepped-specs).

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

## Executable runbooks (stepped specs)

`rungs` shines when a procedure is too fuzzy for a script but too important to
leave in a wiki page: a "kick the tires" check of a freshly installed package, a
host-specific teardown, or a manual integration test. Call it
**the layer between `make test` and a wiki page.**

Unit tests prove your logic against mocks; they never see the real host. A
**stepped spec** proves the product actually *wired itself into the box* —
`$PATH`, the pipx launcher, the systemd unit, `/dev/zram0`, `sudo`. A missing
`/usr/local/bin/...` (reported as *command not found*), a `--unsetup` that
deletes itself, or a stray `/tmp` file are invisible to mocks; a stepped spec
catches them by looking at the machine.

Why `rungs` is a good vehicle for it:

* **Human-in-the-loop is the feature.** Unloading swap, removing a service, and
  reaching for `sudo` are exactly where automation is unsafe. Just pick another
  entry to **skip** a step, or run it again to **repeat** one — the right model
  for a fuzzy procedure.
* **Noisy evidence, plus a machine verdict.** You read the `EXPECT:` lines while
  CI greps the *same* run for a marker. One artifact serves both the human and
  the machine — *a runbook you can also run in CI*.
* **Zero deployment.** An ad-hoc `.ini` file, `+ENV` for shared tokens, and
  auto-keys mean the spec lives **versioned in your repo**, not in
  `~/.config`.

Each check prints its raw evidence, states what to `EXPECT:`, then a one-line
verdict pulled from `$OK_MSG` / `$FAIL_MSG`:

```ini
[__GLOBAL__]
+ENV: OK_MSG=✓✓✓✓✓✓✓✓✓✓ OK
      FAIL_MSG=✘✘✘✘✘✘✘✘✘✘ FAIL

[smoke]
01: :: *Install the working tree          # state-changing; '*' butts the text
   pipx install --force .
02: ::  - CHK: launcher is on PATH. EXPECT: a resolved path
   echo '$ command -v mytool'
   command -v mytool
   command -v mytool >/dev/null 2>&1 \
     && { echo; echo "$OK_MSG"; } \
     || { echo; echo "$FAIL_MSG"; exit 1; }
x: exit
```

Run it (needs a TTY, and a human for the risky steps):

```sh
rungs samples/IntegrationSpec.ini
```

Capture the run and let CI read the verdict:

```sh
rungs samples/IntegrationSpec.ini | tee run.log
grep -q '✓✓✓' run.log && echo PASS || echo FAIL
```

The TTY-and-human requirement is a *feature*: it is exactly the layer
automation should **not** cover. Use it *alongside* your mocked unit tests, not
as a replacement for them. See
[`samples/IntegrationSpec.ini`](samples/IntegrationSpec.ini) for a runnable
example that "kicks the tires" of a `rungs` install.

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
rungs my-procedure    # run an .ini file directly (any filename)
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

### Ctrl-C behaves politely

<kbd>Ctrl</kbd>+<kbd>C</kbd> will not knock `rungs` over and wreck the display:

* **At the menu**, it is ignored — a message reminds you to use the **exit key**
  (`x`) to leave on purpose.
* **While a command runs**, it interrupts *that command only*; `rungs` returns to
  the menu with the step pre-selected so you can read the result (a command
  stopped by Ctrl-C is reported as status `130`) and retry or pick another step.

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

* Keys must be **unique** within a menu. A **one-character** key is used
  literally, so make it a mnemonic when you can (`a: add`, `d: delete`).
* A **longer** key is a placeholder that only needs to be unique in the file;
  `rungs` assigns it the next free display character (`a`, `b`, `c`, ...) in
  file order, reserving `x` for exit. This lets you insert a step without
  re-lettering its neighbours:

  ```ini
  [maint]
  a: add                          # literal mnemonic
  00: git fetch --all             # auto key -> b
  037: prune merged branches      # auto key -> c
  x: exit
  ```

* `exit` (or `quit`) closes the menu.

### Environment variables (`+ENV`)

A section can set environment variables that **every** command in that section
sees, using a `+ENV` entry whose value is one `NAME=VALUE` per line:

```ini
[docker-maint]
+ENV: DOCKER_HOST=tcp://127.0.0.1:2375
      REGISTRY=registry.local
a: docker system df
x: exit
```

Notes:

* The block applies to the **whole section** and is removed when you leave it —
  your shell is unaffected, and sub-menus launched from the section inherit it.
* Values are de-quoted and `$VAR` references are expanded when the section
  starts, so `PATH=$PATH:/opt/bin` works.
* The directive's key is literally `+ENV` — a reserved, `+`-prefixed name that
  is never a menu entry. **Only one `+ENV` block per section** is allowed — list
  every variable on its own indented line; two `+ENV` entries make the file
  invalid.
* Removing variables is not supported.
* Write `+ENV` first in the section by convention; it reads more clearly,
  although its position does not change what it does.

To share variables across **all** sections, use the reserved, hidden
`[__GLOBAL__]` section, which accepts only `+ENV` and `+PRE`:

```ini
[__GLOBAL__]
+ENV: REGISTRY=registry.local
      PKG=dnf
```

`[__GLOBAL__]` never appears in the menu list, is applied once at start-up, and
is inherited by every section and sub-menu. A section's own `+ENV` overrides a
global of the same name while that section runs, and the global is restored
afterwards.

### Shared preambles (`+PRE`)

A section can prepend a chunk of shell text to **every** command it runs, using
a `+PRE` entry. This is a *preamble*, not an exported shell function: each
command runs in a fresh `/bin/sh`, so define whatever you need — variables,
helper functions — as plain shell text, and it is re-stated before each command:

```ini
[test-suite]
+PRE: fail=0
      OK_MSG='all good'
      report() { echo "$1: $OK_MSG"; }
      verdict() { if [ "$fail" -eq 0 ]; then echo PASS; else echo FAIL; fi; }
a: run-tests && report tests
   verdict
x: exit
```

Notes:

* The block applies to the **whole section** and is inherited by sub-menus
  launched from it. A section's own `+PRE` comes *after* any global / inherited
  preamble, so it can redefine a helper it inherited.
* `+PRE` is **not** de-quoted or `$VAR`-expanded (unlike `+ENV`): the text is
  handed to the shell verbatim. That is what lets a helper's `$fail` stay a
  reference until the command actually runs — the reason a distinct directive is
  needed rather than stuffing the snippet into `+ENV`.
* The preamble is echoed **once** at the top of the section (`==> [preamble]`);
  each step then echoes only its own command, so the shared snippet is not
  reprinted before every run.
* **Only one `+PRE` block per section** is allowed — like `+ENV`, list every
  line indented beneath the directive.

`+PRE` may also live in `[__GLOBAL__]`, so helpers used by *every* menu are
defined in one place:

```ini
[__GLOBAL__]
+PRE: log() { printf '%s\n' "$*" >&2; }
+ENV: REGISTRY=registry.local
```

## Command line

```
usage: rungs [-h] [-e] [-n] [menus ...]

positional arguments:
  menus          zero or more menu names or .ini file paths

options:
  -h, --help     show this help message and exit
  -e, --edit     edit config (i.e., runs edit-rungs-config)
  -n, --dry-run  show commands w/o running them
  --version      show program's version number and exit
```

Menu names can be matched:

* **exactly** (`eos-update`, and any "special" name),
* **case-insensitively exactly** (if unique and ordinary), e.g. `EOS-UPDATE`,
* or by a **case-insensitive substring at a word boundary** (if unique and
  ordinary) — for menus `['edit-rungs-config', 'example', 'eos-update']`:
  * `edit`, `ex`, `EOS-` and `EOS-UPDATE` all resolve,
  * but `date` and `e` do **not**.

### Running an ad-hoc file

Each positional argument is resolved in order:

1. if it contains **no `/`**, it is tried as a **menu name** first (as above);
2. otherwise — the name wasn't found, or it contains a `/` — it is treated as a
   path to an **`.ini` file**. The *filename* may be anything (`my-procedure`,
   `notes.txt`, ...); only the *contents* must be `.ini` format;
3. if it is neither a known menu nor a readable menu file, `rungs` treats it as
   **misuse** and exits with a usage error.

```sh
rungs samples/DockerMaintenance.ini   # a file (name ends in .ini)
rungs my-procedure                    # a file by any other name
rungs ./notes                         # a path containing a slash
```

An ad-hoc file behaves like a slice of your config: a single ordinary menu
runs directly, several are offered as a list, and a `>sub` menu defined in the
file is still reachable via `rungs '>sub'` (the file is handed to the child
process automatically).

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

The [`samples/`](samples/) directory has ready-to-adapt menus:

* [`UbuntuUpdateUpgrade.ini`](samples/UbuntuUpdateUpgrade.ini) — `apt`/`snap`/`flatpak`
  update plus a two-level LTS release upgrade.
* [`FedoraUpdateUpgrade.ini`](samples/FedoraUpdateUpgrade.ini) — `dnf` update plus a
  two-level Fedora release upgrade.
* [`DockerMaintenance.ini`](samples/DockerMaintenance.ini) — reclaim Docker disk space
  (images, containers, volumes, build cache).
* [`IntegrationSpec.ini`](samples/IntegrationSpec.ini) — a **stepped spec**: a
  read-only "kick the tires" runbook with `EXPECT:` lines and ✓/✘ verdicts.

These are **not** tested against the latest distro releases — review them before running.

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
python3 -m pip install -e '.[test]'

# run the test suite
python3 -m pytest

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
