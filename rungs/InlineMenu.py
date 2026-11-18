#!/usr/bin/env python3
""" A simple menu tool w/o the full curses ado.

    The menu is drawn *inline*: it never takes over the alternate screen, so a
    run reads as one continuous terminal history -- the menu frames, the
    ``==>`` command echoes and the command output all share the same
    scrollback.

    The viewport is deliberately bounded.  :meth:`Menu.plan_view` fits the menu
    to the terminal's height; rows that do not fit are represented by a single
    "fold" row (``<<<<<< a..e`` at the top, ``>>>>>> a..e`` at the bottom).
    A fold is never selectable: the cursor simply re-plans the view as it
    approaches one, so more choice is shown near the cursor and both menu
    extremes stay on screen.
"""
# pylint: disable=invalid-name,broad-except,too-many-instance-attributes
# pylint: disable=too-few-public-methods

import shutil
import signal
import sys
import termios
import tty

####################################################################################

class Term:
    """ Escape sequences; e.g., see:
     - https://en.wikipedia.org/wiki/ANSI_escape_code
     - https://gist.github.com/fnky/458719343aabd01cfb17a3a4f7296797#file-ansi-md
    """
    esc = '\x1B'
    # pylint: disable=missing-function-docstring,multiple-statements
    @staticmethod
    def erase_line(): return f'{Term.esc}[2K'
    @staticmethod
    def bold(): return f'{Term.esc}[1m'
    @staticmethod
    def reverse_video(): return f'{Term.esc}[7m'
    @staticmethod
    def normal_video(): return f'{Term.esc}[m'
    @staticmethod
    def pos_up(cnt): return f'{Term.esc}[{cnt}F' if cnt > 0 else ''
    @staticmethod
    def pos_down(cnt): return f'{Term.esc}[{cnt}E' if cnt > 0 else ''
    @staticmethod
    def col(pos): return f'{Term.esc}[{pos}G'
    @staticmethod
    def clear_screen(): return f'{Term.esc}[H{Term.esc}[2J{Term.esc}[3J'

####################################################################################

class Menu:
    """ A simple menu system """

    save_attrs = None
    MIN_ROWS = 6
    # chrome rows: the title line and the bottom notice line.
    CHROME_ROWS = 2

    class InputTimeout(Exception):
        """ Raised for obvious reasons. """

    @staticmethod
    def _fileno():
        """ stdin's file descriptor, resolved lazily so that merely importing
            this module does not require a real (tty) stdin. """
        return sys.stdin.fileno()

    @staticmethod
    def _prompt_mode(enable=False):
        """ Used to start / complete prompting the user so that we can read
            one character at a time, etc.
        """
        if enable:
            if not Menu.save_attrs:
                Menu.save_attrs = termios.tcgetattr(Menu._fileno())
                tty.setcbreak(Menu._fileno())
        else:
            if Menu.save_attrs:
                termios.tcsetattr(Menu._fileno(), termios.TCSADRAIN,
                                  Menu.save_attrs)
                Menu.save_attrs = None

    def __init__(self, prompts, default=None, title='', notice=None):
        self.prompts = prompts
        self.keys = list(prompts.keys())
        self.lines = [f'{key}: {prompt}' for key, prompt in prompts.items()]
        self.index_of = {key: idx for idx, key in enumerate(self.keys)}
        # ``len(prompts)`` is the "no selection yet" sentinel,
        # matching the historical behavior (Enter before an arrow/key is rejected).
        self.selected = len(prompts)
        self.title = title
        self._interrupt_armed = False
        self.cols, self.rows = shutil.get_terminal_size()
        self.default_bottom = 'Use Up/Down/key to highlight and Enter to select'
        self.prev_bottom = notice if notice else self.default_bottom
        self.view = []
        # Number of screen rows occupied by the last draw, title and notice included.
        # The cursor is left on the *last* of those rows,
        # so an in-place redraw can always return to the title with pos_up().
        self._drawn = 0
        if default in prompts:
            self.selected = self.index_of[default]
        self._draw(first=True)

    # ##########################################################################
    # View planning

    @staticmethod
    def plan_view(total, selected, height):
        """ Plan the rows to display for a ``height``-line viewport.

            Each row is either ``('item', logical_index)`` or
            ``('fold', side, first_hidden, last_hidden)`` where *side* is
            ``'top'`` or ``'bot'``.  A fold stands in for a contiguous run of
            hidden items and is never selectable.

            The window keeps *selected* visible and slides so that the cursor
            stays away from a fold where the height allows -- i.e. moving
            toward a collapse reveals more items on that side while the
            opposite fold grows.  ``selected`` may be ``None`` (or any
            out-of-range value) for "no highlight".
        """
        if total <= 0 or height <= 0:
            return []
        if total <= height:
            return [('item', i) for i in range(total)]

        anchor = selected if isinstance(selected, int) and 0 <= selected < total else 0

        if height == 1:
            # Degenerate: only the cursor item fits; hidden rows cannot be shown at all.
            # MIN_ROWS keeps this out of the normal path.
            return [('item', anchor)]
        if height == 2:
            # One item plus one fold.  Prefer the side with more hidden rows.
            if anchor == 0:
                return [('item', 0), ('fold', 'bot', 1, total - 1)]
            if anchor == total - 1:
                return [('fold', 'top', 0, total - 2), ('item', anchor)]
            if anchor <= total - 1 - anchor:
                return [('item', anchor),
                        ('fold', 'bot', anchor + 1, total - 1)]
            return [('fold', 'top', 0, anchor - 1), ('item', anchor)]

        # A full-height window with no folds, clamped to the list.
        lo = min(max(anchor - height // 2, 0), total - height)
        if lo == 0:
            hi = height - 1                 # one row for the bottom fold
        elif lo == total - height:
            lo = total - (height - 1)       # one row for the top fold
            hi = total
        else:
            span = height - 2               # two rows for the two folds
            lo = min(max(anchor - span // 2, 1), total - span - 1)
            hi = lo + span

        rows = []
        if lo > 0:
            rows.append(('fold', 'top', 0, lo - 1))
        rows.extend(('item', i) for i in range(lo, hi))
        if hi < total:
            rows.append(('fold', 'bot', hi, total - 1))
        return rows

    # ########################################################################## Drawing

    def _title_line(self):
        """ The bold title line (always the first row of the block). """
        line = (f'     {Term.bold()}<<<< {self.title} >>>>'
                f'{Term.normal_video()}')
        return line[:max(0, self.cols)]

    def _bottom_str(self):
        """ The notice line (always the last row of the block). """
        return f':::: {self.prev_bottom} ::::'[:max(0, self.cols)]

    def _fold_line(self, row):
        """ Render a fold row, e.g. ``  <<<<<< a..e``. """
        _, side, first, last = row
        if first == last:
            span = str(self.keys[first])
        else:
            span = f'{self.keys[first]}..{self.keys[last]}'
        indent = '  '
        room = max(1, self.cols - len(indent) - len(span) - 1)
        arrows = min(7, room)
        sym = '<' if side == 'top' else '>'
        text = f'{indent}{sym * arrows} {span}'
        return Term.bold() + text[:max(0, self.cols)] + Term.normal_video()

    def _item_line(self, idx):
        """ Render a selectable item row, reverse-video when highlighted. """
        text = self.lines[idx][:max(0, self.cols - 2)]
        if self.selected == idx:
            return ('> ' + Term.reverse_video() + text
                    + Term.normal_video())
        return f'  {text}'

    def _row_line(self, row):
        """ Render either kind of view row. """
        if row[0] == 'item':
            return self._item_line(row[1])
        return self._fold_line(row)

    def _draw(self, clear=False, first=False):
        """ Draw (or redraw in place) the bounded menu block.

            ``clear`` wipes the screen and starts at the top (used for the
            first draw and after a resize).  Otherwise the cursor -- which the
            previous draw left on the notice line -- walks back to the title
            and the block is repainted without touching the scrollback above.
        """
        self.cols, self.rows = shutil.get_terminal_size()

        if clear:
            prefix = Term.clear_screen()
        elif first or self._drawn == 0:
            # Separate the menu from whatever was printed before it; this
            # scrolls the preceding output up exactly like any other output.
            prefix = '\n\n'
        else:
            prefix = Term.pos_up(self._drawn - 1)

        if self.rows < self.MIN_ROWS:
            self.view = []
            msg = (f'resize: need >= {self.MIN_ROWS} rows '
                   f'(have {self.rows})')[:max(0, self.cols)]
            print(prefix + Term.erase_line() + Term.reverse_video()
                  + msg + Term.normal_video(), end='', flush=True)
            self._drawn = 1
            return

        total = len(self.lines)
        selected = self.selected if 0 <= self.selected < total else None
        self.view = self.plan_view(total, selected,
                                   max(1, self.rows - self.CHROME_ROWS))

        out = [prefix, Term.erase_line(), self._title_line(), '\n']
        for row in self.view:
            out += [Term.erase_line(), self._row_line(row), '\n']
        out += [Term.erase_line(), self._bottom_str()]
        self._drawn = len(self.view) + self.CHROME_ROWS
        print(''.join(out), end='', flush=True)

    def _refresh(self, clear=True):
        """ Redraw the menu, optionally wiping the screen first. """
        self._draw(clear=clear)

    def _move(self, cnt):
        """ Move the cursor by *cnt* rows (negative up, positive down).

            Fold rows are not menu entries, so the logical index moves
            directly between items; the view is re-planned afterwards so the
            cursor is always on a real item and never on a collapse.
        """
        total = len(self.lines)
        if total == 0 or cnt == 0:
            return
        if self.selected >= total:
            # No selection yet: any movement selects the last entry,
            # exactly as the historical clamped arithmetic did.
            idx = total - 1
        else:
            idx = min(max(self.selected + cnt, 0), total - 1)
        if idx != self.selected:
            self.selected = idx
            self._draw()

    def _select(self, idx):
        """ Jump to a logical index (a pressed mnemonic key). """
        if idx != self.selected:
            self.selected = idx
            self._draw()

    def _get_char(self):
        """ Get one char from stdin, polling so terminal resizes redraw. """
        def init_timeout_handling():
            # `SIGWINCH` is sent on terminal resizes
            def handle_timeout(*ignore):
                raise Menu.InputTimeout
            signal.signal(signal.SIGALRM, handle_timeout)
            signal.setitimer(signal.ITIMER_REAL, 0.25, 0.25)

        def reset_timeout_handling() -> None:
            signal.setitimer(signal.ITIMER_REAL, 0, 0)
            signal.signal(signal.SIGALRM, signal.SIG_IGN)

        rv = None
        while True:
            try:
                init_timeout_handling()
                rv = sys.stdin.read(1)
            except Menu.InputTimeout:
                rv = None
            finally:
                # Always disarm the alarm -- even when a Ctrl-C
                # (KeyboardInterrupt) unwinds us out of the blocking read.
                reset_timeout_handling()

            cols, rows = shutil.get_terminal_size()
            if self.cols != cols or self.rows != rows:
                self.cols, self.rows = cols, rows
                self._refresh()
            if rv is not None:
                return rv

    def _bottom_line(self, string=None):
        """ Redraw the notice line in place (the cursor sits on it).

            ``erase_line`` clears the line but leaves the cursor in its
            current column, so home first -- otherwise each new message would
            be written further to the right of the previous one.
        """
        self.prev_bottom = string if string else self.prev_bottom
        if self._drawn == 0:
            return
        print(Term.col(1) + Term.erase_line() + self._bottom_str(),
              end='', flush=True)

    def _finish(self, string=''):
        """ Complete the menu selection by erasing the block, printing a
            PICK annotation and leaving the cursor below it.
        """
        total = len(self.lines)
        picked = self.lines[self.selected] if 0 <= self.selected < total else ''
        if self._drawn > 0:
            print(Term.pos_up(self._drawn - 1), end='')
            for _ in range(self._drawn - 1):
                print(Term.erase_line() + '\n', end='')
            print(Term.erase_line(), end='')
        print(Term.col(1) + Term.reverse_video() + 'PICK' + Term.normal_video()
              + ': ' + picked[:max(0, self.cols - 6)] + '\n',
              end='', flush=True)
        self._drawn = 0

    def _restore_default_bottom(self):
        """ After the user does something right, clear the error message. """
        if self.prev_bottom != self.default_bottom:
            self._bottom_line(self.default_bottom)

    def prompt(self):
        """ The external entry point which prompts the user
        to select and choose a menu entry.

        Ctrl-C is deliberately swallowed here -- if
        it were allowed to raise all the way out,
        rungs would die mid-draw and leave the terminal display in a mess.
        So the first Ctrl-C merely shows a hint and a *second* Ctrl-C
        with no other key pressed in between is the escape hatch.
        This works for every menu, whether or not it defines an ``x: exit`` entry.

        Returns ``None`` when the user abandons the menu this way.
        """
        while True:
            try:
                self._prompt_mode(enable=True)
                ans = ''
                while True:
                    key = self._get_char()
                    ans += key
                    # A real keystroke means the user is not simply mashing Ctrl-C,
                    # so a pending "second Ctrl-C quits" no longer applies.
                    self._interrupt_armed = False
                    if key.isalnum() or key in ('\r', '\n', ' '):
                        break
                if self.rows < self.MIN_ROWS:
                    # Waiting for a resize: only Ctrl-C (handled below) acts.
                    continue
                if ans == '\033[A':          # Up arrow
                    self._restore_default_bottom()
                    self._move(-1)
                elif ans == '\033[B':        # Down arrow
                    self._restore_default_bottom()
                    self._move(1)
                elif ans in ('\r', '\n', ' '):
                    if self.selected < len(self.lines):
                        self._restore_default_bottom()
                        picked = self.keys[self.selected]
                        self._prompt_mode(enable=False)
                        self._finish()
                        return picked
                    self._bottom_line('invalid(no selection); pick again')
                elif ans in self.index_of:
                    self._restore_default_bottom()
                    # A mnemonic key works even for a row hidden
                    # inside a fold: the view re-plans around it.
                    self._select(self.index_of[ans])
                else:
                    self._bottom_line(f'invalid({repr(ans)}); pick again')
            except KeyboardInterrupt:
                if self._interrupt_armed:
                    # Second consecutive Ctrl-C: the user really wants out.
                    print(flush=True)
                    return None
                self._interrupt_armed = True
                self._bottom_line('Ctrl-C again to exit')
            finally:
                self._prompt_mode(enable=False)
