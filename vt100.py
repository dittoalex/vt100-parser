#!/usr/bin/env python

# Requires Python 2.6
from __future__ import print_function

import itertools
import re
import sys
import numpy as np
from optparse import OptionParser


__metaclass__ = type


class Character:
    """A single character along with an associated attribute."""
    def __init__(self, char, attr = None):
        self.char = char
        self.attr = attr
    def __repr__(self):
        return str(self.char)
    def __str__(self):
        return str(self.char)

class InvalidParameterListError (RuntimeError):
    pass

def param_list(s, default, zero_is_default=True, min_length=1):
    """Return the list of integer parameters assuming `s` is a standard
    control sequence parameter list.  Empty elements are set to `default`."""
    def f(token):
        if not token:
            return default
        value = int(token)
        if zero_is_default and value == 0:
            return default
        if value < 0:
            raise ValueError
        return value
    if s is None:
        l = []
    else:
        try:
            l = [f(token) for token in s.split(';')]
        except ValueError:
            raise InvalidParameterListError
    l += [default] * (min_length - len(l))
    return l


def clip(n, start, stop=None):
    """Return n clipped to range(start,stop)."""
    if stop is None:
        stop = start
        start = 0
    if n < start:
        return start
    if n >= stop:
        return stop-1
    return n


def new_sequence_decorator(dictionary):
    def decorator_generator(key):
        assert isinstance(key, str)
        def decorator(f, key=key):
            dictionary[key] = f.__name__
            return f
        return decorator
    return decorator_generator



class Terminal:

    # ---------- Decorators for Defining Sequences ----------

    commands = {}
    escape_sequences = {}
    control_sequences = {}

    command = new_sequence_decorator(commands)
    escape  = new_sequence_decorator(escape_sequences)
    control = new_sequence_decorator(control_sequences)

    # ---------- Constructor ----------

    def __init__(self, height=24, width=80, verbosity=False):
        self.verbosity = verbosity
        self.state = 'ground'
        self.prev_state = None
        self.next_state = None
        self.history = []
        self.width = width
        self.height = height
        self.screen = np.array([[None] * width] * height, dtype=object)
        self.row = 0
        self.col = 0
        self.previous = '\0'
        self.tabstops = [(i%8)==0 for i in range(width)]
        self.attr = None
        self.clear()

    # ---------- Utilities ----------

    @property
    def pos(self):
        """The cursor position as (row, column)."""
        return self.row, self.col

    def clear(self):
        """Reset internal buffers for switching between states."""
        self.collected = ''

    def output(self, c):
        """Print the character at the current position and increment the
        cursor to the next position.  If the current position is past the end
        of the line, starts a new line."""
        if self.col >= self.width:
            self.NEL()
        c = Character(c, self.attr)
        self.screen[self.pos] = c
        self.CUF()

    def scroll(self, n, top = None, bottom = None):
        """Scroll the scrolling region n lines upward (data moves up) between
        rows top (inclusive, default 0) and bottom (exclusive, default
        height).  Any data moved off the top of the screen (if top is 0) is
        saved to the history."""
        # TODO scroll region
        if top is None:
            top = 0
        if bottom is None:
            bottom = self.height
        s = self.screen
        height = bottom-top
        if n > 0:
            # TODO transform history?
            if top == 0:
                self.history.extend( s[:n].copy() )
            if n > height:
                extra = n - self.height
                self.history.extend( [[None]*self.width]*extra )
                n = self.height
            s[top:bottom-n] = s[top+n:bottom]
            s[bottom-n:bottom] = None
        elif n < 0:
            n = -n
            if n > self.height:
                n = self.height
            s[top+n:bottom] = s[top:bottom-n]
            s[top:top+n] = None

    def ignore(self, c):
        """Ignore the character."""
        self.debug(1, 'ignoring character: %s' % repr(c))

    def collect(self, c):
        """Record the character as an intermediate."""
        self.collected += c

    def clear_on_enter(self, old_state):
        """Since most enter_* functions just call self.clear(), this is a
        common function so that you can set enter_foo = clear_on_enter."""
        self.clear()

    def debug(self, level, *args, **kwargs):
        if self.verbosity >= level:
            kwargs.setdefault('file', sys.stderr)
            print(*args, **kwargs)

    # ---------- Parsing ----------

    def parse(self, s):
        """Parse an entire string."""
        for c in s:
            self.parse_single(c)

    def parse_single(self, c):
        """Parse a single character."""
        if isinstance(c, int):
            c = chr(c)
        try:
            f = getattr(self, 'parse_%s' % self.state)
        except AttributeError:
            raise RuntimeError("internal error: unknown state %s" %
                    repr(self.state))
        self.next_state = self.state
        self.previous = c
        f(c)
        self.transition()

    def transition(self):
        if self.next_state != self.state:
            f = getattr(self, 'leave_%s' % self.state, None)
            if f is not None:
                f(self.next_state)
        self.next_state, self.state, self.prev_state = (None,
                self.next_state, self.state)
        if self.state != self.prev_state:
            f = getattr(self, 'enter_%s' % self.state, None)
            if f is not None:
                f(self.prev_state)

    def parse_ground(self, c):
        if ord(c) < 0x20:
            self.execute(c)
        else:
            self.output(c)

    # ---------- Output ----------

    def to_string(self, history=True, screen=True, remove_blank_end=True):
        """Return a string form of the history and the current screen."""
        # TODO use attributes / formatter
        input = []
        if history:
            input.append(self.history)
        if screen:
            input.append(self.screen)
        if not input:
            return
        lines = itertools.chain(*input)
        def f(line):
            s = ''.join(x.char if x is not None else '\0'
                        for x in line)
            return s.rstrip('\0').replace('\0',' ')
        s = '\n'.join(map(f, lines))
        if remove_blank_end:
            s = s.rstrip('\n')
        return s + '\n'

    def print_screen(self):
        print(self.to_string(False, True, False), end='')

    # ---------- Single-character commands (C0) ----------

    def execute(self, c):
        """Execute a C0 command."""
        name = self.commands.get(c, None)
        f = None
        if name is not None:
            f = getattr(self, name, None)
        if f is None:
            f = self.ignore
        f(c)

    @command('\x07')        # ^G
    def BEL(self, c=None):
        """Bell"""
        pass

    @command('\x08')        # ^H
    def BS(self, c=None):
        """Backspace"""
        self.col -= 1  if self.col > 0 else 0

    @command('\x09')        # ^I
    def HT(self, c=None):
        """Horizontal Tab"""
        if self.col >= self.width:
            self.NEL()
        while self.col < self.width-1:
            self.col += 1
            if self.tabstops[self.col]:
                break

    @command('\x0a')        # ^J
    def LF(self, c=None):
        """Line Feed"""
        self.IND()

    @command('\x0b')        # ^K
    def VT(self, c=None):
        """Vertical Tab"""
        self.LF(c)

    @command('\x0c')        # ^L
    def FF(self, c=None):
        """Form Feed"""
        self.LF(c)

    @command('\x0d')        # ^M
    def CR(self, c=None):
        """Carriage Return"""
        self.col = 0

    @command('\x18')        # ^X
    def CAN(self, c=None):
        """Cancel"""
        self.next_state = 'ground'

    @command('\x1a')        # ^Z
    def SUB(self, c=None):
        """Substitute"""
        self.next_state = 'ground'

    @command('\x1b')        # ^[
    def ESC(self, c=None):
        """Escape"""
        self.next_state = 'escape'


    # ---------- Escape Sequences ----------

    enter_escape = clear_on_enter

    def parse_escape(self, c):
        if ord(c) < 0x20:
            self.execute(c)
        elif ord(c) < 0x30:
            self.collect(c)
        elif ord(c) < 0x7f:
            self.next_state = 'ground'
            self.dispatch_escape(c)
        else:
            self.ignore(c)

    def dispatch_escape(self, c):
        command = self.collected + c
        name = self.escape_sequences.get(c, None)
        f = None
        if name is not None:
            f = getattr(self, name, None)
        if f is None:
            f = self.ignore
        f(command)


    @escape('D')
    def IND(self, c=None):
        """Index"""
        if self.row < self.height - 1:
            self.row += 1
        else:
            self.scroll(1)

    @escape('E')
    def NEL(self, c=None):
        """Next Line"""
        self.IND()
        self.col = 0

    @escape('H')
    def HTS(self, c=None):
        """Horizontal Tab Set"""
        self.tabstops[self.col] = True

    @escape('M')
    def RI(self, c=None):
        """Reverse Index (reverse line feed)"""
        if self.row > 0:
            self.row -= 1
        else:
            self.scroll(-1)

    @escape('P')
    def DCS(self, c=None):
        """Device Control String"""
        self.next_state = 'dcs'

    @escape('X')
    def SOS(self, c=None):
        """Start of String"""
        self.next_state = 'sos'

    @escape('[')
    def CSI(self, c=None):
        """Control Sequence Introducer"""
        self.next_state = 'control_sequence'

    @escape('\\')
    def ST(self, c=None):
        """String Terminator"""
        pass

    @escape(']')
    def OSC(self, c=None):
        """Operating System Command"""
        self.next_state = 'osc'

    @escape('^')
    def PM(self, c=None):
        """Privacy Message"""
        self.next_state = 'pm'

    @escape('_')
    def APC(self, c=None):
        """Application Program Command"""
        self.next_state = 'apc'


    # ---------- Control Sequences ----------

    enter_control_sequence = clear_on_enter

    def parse_control_sequence(self, c):
        if ord(c) < 0x20:
            self.execute(c)
        elif ord(c) < 0x40:
            self.collect(c)
        elif ord(c) < 0x7f:
            self.next_state = 'ground'
            self.dispatch_control_sequence(c)
        else:
            self.ignore(c)

    def dispatch_control_sequence(self, c):
        self.collect(c)
        m = re.match('^([\x30-\x3f]*)([\x20-\x2f]*[\x40-\x7f])$',
                     self.collected)
        if not m:
            return self.invalid_control_sequence()
        param, command = m.groups()

        name = self.control_sequences.get(command, None)
        f = None
        if name is not None:
            f = getattr(self, name, None)
        if f is None:
            f = self.ignore_control_sequence
        try:
            f(command, param)
        except InvalidParameterListError:
            self.invalid_control_sequence()

    def invalid_control_sequence(self):
        """Called when the control sequence is invalid."""
        self.debug(0, 'invalid control sequence: %s'
                % (repr(self.collected)))

    def ignore_control_sequence(self, command, param):
        """Called when the control sequence is ignored."""
        self.debug(1, 'ignoring control sequence: %s, %s'
                % (repr(command), repr(param)))


    @control('@')
    def ICH(self, command=None, param=None):
        """Insert (blank) Characters"""
        return NotImplemented

    @control('A')
    def CUU(self, command=None, param=None):
        """Cursor Up"""
        n = param_list(param, 1)[0]
        self.row = clip(self.row-n, self.height)

    @control('B')
    def CUD(self, command=None, param=None):
        """Cursor Down"""
        n = param_list(param, 1)[0]
        self.row = clip(self.row+n, self.height)

    @control('C')
    def CUF(self, command=None, param=None):
        """Cursor Forward"""
        n = param_list(param, 1)[0]
        self.col = clip(self.col+n, self.width)

    @control('D')
    def CUB(self, command=None, param=None):
        """Cursor Backward"""
        n = param_list(param, 1)[0]
        self.col = clip(self.col-n, self.width)

    @control('E')
    def CNL(self, command=None, param=None):
        """Cursor Next Line"""
        self.CUD(command, param)
        self.col = 0

    @control('F')
    def CPL(self, command=None, param=None):
        """Cursor Previous Line"""
        self.CUU(command, param)
        self.col = 0

    @control('G')
    def CHA(self, command=None, param=None):
        """Character Position Absolute"""
        n = param_list(param, 1)[0]
        self.col = clip(n-1, self.width)

    @control('H')
    def CUP(self, command=None, param=None):
        """Cursor Position [row;column]"""
        n,m = param_list(param, 1, min_length=2)[:2]
        self.row = clip(n-1, self.height)
        self.col = clip(m-1, self.width)

    @control('I')
    def CHT(self, command=None, param=None):
        """Cursor Forward Tabulation"""
        n = param_list(param, 1)[0]
        for i in range(n):
            self.HT()

    @control('J')
    def ED(self, command=None, param=None):
        """Erase in Display

        Ps = 0  -> Erase Below (default)
        Ps = 1  -> Erase Above
        Ps = 2  -> Erase All
        Ps = 3  -> Erase Saved Lines (xterm)
        """
        # TODO param =~ ^\?   selective erase
        n = param_list(param, 0)[0]
        if n == 0:
            self.screen[self.row, self.col:] = None
            self.screen[self.row+1:, :] = None
        elif n == 1:
            self.screen[:self.row, :] = None
            self.screen[self.row, :self.col+1] = None
        elif n == 2:
            self.screen[:] = None
        # no plans to implement 3

    @control('K')
    def EL(self, command=None, param=None):
        """Erase in Line

        Ps = 0  -> Erase to Right (default)
        Ps = 1  -> Erase to Left
        Ps = 2  -> Erase All
        """
        # TODO param =~ ^\?   selective erase
        n = param_list(param, 0)[0]
        if n == 0:
            self.screen[self.row, self.col:] = None
        elif n == 1:
            self.screen[self.row, :self.col+1] = None
        elif n == 2:
            self.screen[self.row, :] = None

    @control('L')
    def IL(self, command=None, param=None):
        """Insert Line(s)"""
        # TODO scroll region?
        n = param_list(param, 1)[0]
        self.scroll(n, bottom=self.row)
        self.CUU(param=str(n))

    @control('M')
    def DL(self, command=None, param=None):
        """Delete Line(s)"""
        # TODO scroll region?
        n = param_list(param, 1)[0]
        self.scroll(n, top=self.row)

    @control('P')
    def DCH(self, command=None, param=None):
        """Delete Character(s)"""
        n = param_list(param, 1)[0]
        r = self.row
        c = self.col
        self.screen[r,c:-n] = self.screen[r,c+n:]
        self.screen[r,-n:] = None

    @control('S')
    def SU(self, command=None, param=None):
        """Scroll Up"""
        # TODO scroll region?
        n = param_list(param, 1)[0]
        self.scroll(n)

    @control('T')
    def SD(self, command=None, param=None):
        """Scroll Down / Mouse Tracking"""
        # TODO scroll region?
        # TODO mouse tracking
        n = param_list(param, 1)[0]
        self.scroll(-n)

    @control('X')
    def ECH(self, command=None, param=None):
        """Erase Character"""
        n = param_list(param, 1)[0]
        self.screen[self.row, self.col:self.col+n] = None

    @control('Z')
    def CBT(self, command=None, param=None):
        """Cursor Backward Tabulation"""
        n = param_list(param, 1)[0]
        for i in range(n):
            while self.col > 0:
                self.col -= 1
                if self.tabstops[self.col]:
                    break

    @control('`')
    def HPA(self, command=None, param=None):
        """Character Position Absolute"""
        self.CHA(command, param)

    @control('a')
    def HPR(self, command=None, param=None):
        """Character Position Forward (Horizontal Position Right)"""
        self.CUF(command, param)

    @control('b')
    def REP(self, command=None, param=None):
        """Repeat"""
        n = param_list(param, 1)[0]
        if ord(self.previous) >= 0x20:
            for i in range(n):
                self.output(self.previous)

    @control('d')
    def VPA(self, command=None, param=None):
        """Line Position Absolute"""
        n = param_list(param, 1)[0]
        self.row = clip(n-1, self.height)

    @control('e')
    def VPR(self, command=None, param=None):
        """Line Position Forward"""
        self.CUD(command, param)

    @control('f')
    def HVP(self, command=None, param=None):
        """Horizontal and Vertical Position"""
        self.CUP(command, param)

    @control('g')
    def TBC(self, command=None, param=None):
        """Tab Clear"""
        n = param_list(param, 0)[0]
        if n == 0:
            self.tabstops[self.col] = False
        elif n == 3:
            self.tabstops[:] = [False] * self.width

    @control('h')
    def SM(self, command=None, param=None):
        """Set Mode"""
        return NotImplemented

    @control('j')
    def HPB(self, command=None, param=None):
        """Character Position Backward"""
        self.CUB(command, param)

    @control('k')
    def VPB(self, command=None, param=None):
        """Line Position Backward"""
        self.CUU(command, param)

    @control('l')
    def RM(self, command=None, param=None):
        """Reset Mode"""
        return NotImplemented

    @control('m')
    def SGR(self, command=None, param=None):
        """Set Graphics Attributes"""
        return NotImplemented
        # TODO '>m' xterm

    @control('!p')
    def DECSTR(self, command=None, param=None):
        """Soft Terminal Reset"""
        return NotImplemented

    @control('r')
    def DECSTBM(self, command=None, param=None):
        """Set Scrolling Region"""
        return NotImplemented
        # Note: with param = "? Pm", restore DEC private mode values

    @control('$r')
    def DECCARA(self, command=None, param=None):
        """Change Attributes in Rectangular Area"""
        return NotImplemented

    @control('s')
    def save_cursor(self, command=None, param=None):
        """Save cursor"""
        return NotImplemented
        # Note: with param = "? Pm", set DEC private mode values

    @control('$t')
    def DECRARA(self, command=None, param=None):
        """Reverse Attributes in Rectangular Area"""
        return NotImplemented

    @control('u')
    def restore_cursor(self, command=None, param=None):
        """Restore cursor"""
        return NotImplemented

    # TODO more from ctlseqs.txt



    # ---------- Control Strings ----------

    enter_osc = clear_on_enter
    enter_dsc = clear_on_enter
    enter_sos = clear_on_enter
    enter_apc = clear_on_enter
    enter_pm  = clear_on_enter

    def parse_osc(self, c): self.parse_control_string(c)
    def parse_dsc(self, c): self.parse_control_string(c)
    def parse_sos(self, c): self.parse_control_string(c)
    def parse_pm (self, c): self.parse_control_string(c)
    def parse_apc(self, c): self.parse_control_string(c)

    finish_osc = None
    finish_dsc = None
    finish_sos = None
    finish_apc = None
    finish_pm  = None

    def parse_control_string(self, c):
        # Consume the whole string and pass it to the process function.
        if c in '\x18\x1a':
            # CAN and SUB quit the string
            self.cancel_control_string()
            # should we self.execute(c) ?
        elif c == '\x07' and self.state == 'osc':
            # NOTE: xterm ends OSC with BEL, in addition to ESC \
            self.finish_control_string()
        elif self.collected and self.collected[-1] == '\x1b':
            # NOTE: xterm consumes the character after the ESC always, but
            # only process it if it is '\'.  Not sure about VTxxx.
            self.collected = self.collected[:-1]
            if c == '\x5c':
                self.finish_control_string()
            else:
                self.cancel_control_string()
        else:
            self.collect(c)

    def finish_control_string(self):
        name = 'finish_%s' % self.state
        f = getattr(self, name, None)
        if f is None:
            f = self.ignore_control_string
        f(self.collected)
        self.next_state = 'ground'

    def cancel_control_string(self):
        self.next_state = 'ground'

    def ignore_control_string(self, *args):
        """Called when a control string is ignored."""
        self.debug(1, 'ignoring %s control string: %s' % (self.state,
            repr(args)))




    # ================================================================
    #             Things implemented by xterm but not here.
    # ================================================================

    @command('\x05')       # ^E
    def ENQ(self, c=None):
        """ENQuiry"""
        return NotImplemented

    @command('\x0e')       # ^N
    def SO(self, c=None):
        """Shift Out (LS1)"""
        return NotImplemented

    @command('\x0f')       # ^O
    def SI(self, c=None):
        """Shift In (LS0)"""
        return NotImplemented

    # --------------------

    @escape('7')
    def DECSC(self, c=None):
        """Save Cursor"""
        return NotImplemented

    @escape('8')
    def DECRC(self, c=None):
        """Restore Cursor"""
        return NotImplemented

    @escape('=')
    def DECPAM(self, command=None, param=None):
        """Application Keypad"""
        return NotImplemented

    @escape('>')
    def DECPNM(self, command=None, param=None):
        """Normal Keypad"""
        return NotImplemented

    @escape('N')
    def SS2(self, c=None):
        """Single Shift 2"""
        return NotImplemented

    @escape('O')
    def SS3(self, c=None):
        """Single Shift 3"""
        return NotImplemented

    @escape(' F')
    def S7C1T(self, c=None):
        """7-bit controls"""
        return NotImplemented

    @escape(' G')
    def S8C1T(self, c=None):
        """8-bit controls"""
        return NotImplemented

    @escape(' L')
    def set_ansi_level_1(self, c=None):
        """Set ANSI conformance level 1"""
        return NotImplemented

    @escape(' M')
    def set_ansi_level_2(self, c=None):
        """Set ANSI conformance level 2"""
        return NotImplemented

    @escape(' N')
    def set_ansi_level_3(self, c=None):
        """Set ANSI conformance level 3"""
        return NotImplemented

    # ESC # 3   DEC double-height line, top half (DECDHL)
    # ESC # 4   DEC double-height line, bottom half (DECDHL)
    # ESC # 5   DEC single-width line (DECSWL)
    # ESC # 6   DEC double-width line (DECDWL)
    # ESC # 8   DEC Screen Alignment Test (DECALN)
    # ESC % @   Select default character set, ISO 8859-1 (ISO 2022)
    # ESC % G   Select UTF-8 character set (ISO 2022)
    # ESC ( C   Designate G0 Character Set (ISO 2022)
    # ESC ) C   Designate G1 Character Set (ISO 2022)
    # ESC * C   Designate G2 Character Set (ISO 2022)
    # ESC + C   Designate G3 Character Set (ISO 2022)
    # ESC - C   Designate G1 Character Set (VT300)
    # ESC . C   Designate G2 Character Set (VT300)
    # ESC / C   Designate G3 Character Set (VT300)
    # ESC F     Cursor to lower left corner of screen (if enabled by the
    #           hpLowerleftBugCompat resource).
    # ESC l     Memory Lock (per HP terminals).  Locks memory above the cur-
    #           sor.
    # ESC m     Memory Unlock (per HP terminals)
    # ESC n     Invoke the G2 Character Set as GL (LS2).
    # ESC o     Invoke the G3 Character Set as GL (LS3).
    # ESC |     Invoke the G3 Character Set as GR (LS3R).
    # ESC }     Invoke the G2 Character Set as GR (LS2R).
    # ESC ~     Invoke the G1 Character Set as GR (LS1R).

    # --------------------

    @control('c')
    def DA(self, command=None, param=None):
        """Send Device Attributes"""
        return NotImplemented

    @control('i')
    def MC(self, command=None, param=None):
        """Media Copy"""
        return NotImplemented

    @control('n')
    def DSR(self, command=None, param=None):
        """Device Status Report"""
        return NotImplemented

    # @control('p') with '>': xterm pointer mode

    @control('"p')
    def DECSCL(self, command=None, param=None):
        """Set Conformance Level"""
        return NotImplemented

    @control('"q')
    def DECSCA(self, command=None, param=None):
        """Set Character protection Attribute"""
        return NotImplemented

    @control('t')
    def window_manipulation(self, command=None, param=None):
        """Window manipulation"""
        return NotImplemented

    # ================================================================
    #                  Things not implemented by xterm.
    # ================================================================

    @command('\x00')        # ^@
    def NUL(self, c=None):
        """NULl"""
        return NotImplemented

    @command('\x01')        # ^A
    def SOH(self, c=None):
        """Start Of Heading"""
        return NotImplemented

    @command('\x02')        # ^B
    def STX(self, c=None):
        """Start of TeXt"""
        return NotImplemented

    @command('\x03')        # ^C
    def ETX(self, c=None):
        """End of TeXt"""
        return NotImplemented

    @command('\x04')        # ^D
    def EOT(self, c=None):
        """End Of Transmission"""
        return NotImplemented

    @command('\x06')        # ^F
    def ACK(self, c=None):
        """ACKnowledge"""
        return NotImplemented

    @command('\x10')        # ^P
    def DLE(self, c=None):
        """Data Link Escape"""
        return NotImplemented

    @command('\x11')        # ^Q
    def DC1(self, c=None):
        """Device Control 1"""
        return NotImplemented

    @command('\x12')        # ^R
    def DC2(self, c=None):
        """Device Control 2"""
        return NotImplemented

    @command('\x13')        # ^S
    def DC3(self, c=None):
        """Device Control 3"""
        return NotImplemented

    @command('\x14')        # ^T
    def DC4(self, c=None):
        """Device Control 4"""
        return NotImplemented

    @command('\x15')        # ^U
    def NAK(self, c=None):
        """Negative AcKnowledge"""
        return NotImplemented

    @command('\x16')        # ^V
    def SYN(self, c=None):
        """SYNchronous idle"""
        return NotImplemented

    @command('\x17')        # ^W
    def ETB(self, c=None):
        """End of Transmission Block"""
        return NotImplemented

    @command('\x19')        # ^Y
    def EM(self, c=None):
        """End of Medium"""
        return NotImplemented

    @command('\x1c')        # ^\
    def FS(self, c=None):
        """File Separator (IS4)"""
        return NotImplemented

    @command('\x1d')        # ^]
    def GS(self, c=None):
        """Group Separator (IS3)"""
        return NotImplemented

    @command('\x1e')        # ^^
    def RS(self, c=None):
        """Record Separator (IS2)"""
        return NotImplemented

    @command('\x1f')        # ^_
    def US(self, c=None):
        """Unit Separator (IS1)"""
        return NotImplemented

    # --------------------

    # no @escape('0')
    # no @escape('1')
    # no @escape('2')
    # no @escape('3')
    # no @escape('4')
    # no @escape('5')
    # no @escape('6')
    # no @escape('9')
    # no @escape(':')
    # no @escape(';')
    # no @escape('<')
    # no @escape('?')
    # no @escape('@')
    # no @escape('A')

    @escape('B')
    def BPH(self, command=None, param=None):
        """Break Permitted Here"""
        return NotImplemented

    @escape('C')
    def NBH(self, command=None, param=None):
        """No Break Here"""
        return NotImplemented

    @escape('F')
    def SSA(self, command=None, param=None):
        """Start of Selected Area"""
        return NotImplemented

    @escape('G')
    def ESA(self, command=None, param=None):
        """End of Selected Area"""
        return NotImplemented

    @escape('I')
    def HTJ(self, command=None, param=None):
        """Character Tabulation with Justification"""
        return NotImplemented

    @escape('J')
    def VTS(self, command=None, param=None):
        """Veritical Tab Set"""
        return NotImplemented

    @escape('K')
    def PLD(self, command=None, param=None):
        """Partial Line forward (Down)"""
        return NotImplemented

    @escape('L')
    def PLU(self, command=None, param=None):
        """Partial Line backward (Up)"""
        return NotImplemented

    @escape('Q')
    def PU1(self, command=None, param=None):
        """Private Use 1"""
        return NotImplemented

    @escape('R')
    def PU2(self, command=None, param=None):
        """Private Use 2"""
        return NotImplemented

    @escape('S')
    def STS(self, command=None, param=None):
        """Set Transmit State"""
        return NotImplemented

    @escape('T')
    def CCH(self, command=None, param=None):
        """Cancel CHaracter"""
        return NotImplemented

    @escape('U')
    def MW(self, command=None, param=None):
        """Message Waiting"""
        return NotImplemented

    @escape('V')
    def SPA(self, c=None):
        """Start of guarded (Protected) Area"""
        return NotImplemented

    @escape('W')
    def EPA(self, c=None):
        """End of guarded (Protected) Area"""
        return NotImplemented

    # no @escape('Y')

    @escape('Z')
    def SCI(self, c=None):
        """Single Character Introducer"""
        return NotImplemented

    @escape('a')
    def INT(self, command=None, param=None):
        """INTerrupt"""
        return NotImplemented

    @escape('b')
    def EMI(self, command=None, param=None):
        """Enable Manual Input"""
        return NotImplemented

    @escape('c')
    def RIS(self, command=None, param=None):
        """Reset to Initial State"""
        return NotImplemented
        # TODO

    @escape('d')
    def CMD(self, command=None, param=None):
        """Coding Method Delimiter"""
        return NotImplemented

    # --------------------

    @control('N')
    def EF(self, command=None, param=None):
        """Erase in Field"""
        return NotImplemented

    @control('O')
    def EA(self, command=None, param=None):
        """Erase in Area"""
        return NotImplemented

    @control('Q')
    def SSE(self, command=None, param=None):
        return NotImplemented
        pass

    @control('R')
    def CPR(self, command=None, param=None):
        """Active Position Report"""
        return NotImplemented

    @control('U')
    def NP(self, command=None, param=None):
        """Next Page"""
        return NotImplemented

    @control('V')
    def PP(self, command=None, param=None):
        """Previous Page"""
        return NotImplemented

    @control('W')
    def CTC(self, command=None, param=None):
        """Cursor Tabulation Control"""
        return NotImplemented

    @control('Y')
    def CVT(self, command=None, param=None):
        """Cursor Line Tabulation"""
        return NotImplemented

    @control('[')
    def SRS(self, command=None, param=None):
        """Start Reversed String"""
        return NotImplemented

    @control('\\')
    def PTX(self, command=None, param=None):
        """Parallel Texts"""
        return NotImplemented

    @control(']')
    def SDS(self, command=None, param=None):
        """Start Directed String"""
        return NotImplemented

    @control('^')
    def SIMD(self, command=None, param=None):
        """Select Implicit Movement Direction"""
        return NotImplemented

    # no @control('_')

    @control('o')
    def DAQ(self, command=None, param=None):
        """Define Area Qualification"""
        return NotImplemented




if __name__ == "__main__":
    usage = "%prog (filename|-)"
    parser = OptionParser(usage=usage)
    parser.add_option('-q', '--quiet', action='count', default=0,
            help='Decrease debugging verbosity.')
    parser.add_option('-v', '--verbose', action='count', default=0,
            help='Increase debugging verbosity.')
    parser.add_option('--non-script', action='store_true', default=False,
            help='Do not ignore "Script (started|done) on <date>" lines')
    options, args = parser.parse_args()
    options.verbose -= options.quiet
    del options.quiet
    if len(args) != 1:
        parser.error('missing required filename argument')
    filename, = args
    if filename == '-':
        f = sys.stdin
    else:
        f = open(filename, 'rb')
    t = Terminal(verbosity=options.verbose)
    script_re = re.compile(r'^Script (started|done) on \w+ \d+ \w+ \d{4} '
            r'\d\d:\d\d:\d\d \w+ \w+$')
    for line in f:
        if not options.non_script and script_re.match(line):
            continue
        t.parse(line)
    print(t.to_string(), end='')
    if filename != '-':
        f.close()
