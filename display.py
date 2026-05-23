"""Render train departures on the 16x2 I2C character LCD.

Top row lists the next two departures across all routes, each tagged with its
line, e.g. ``N 3m  W 5m`` (or ``N 3m  N 9m`` if the same line is up twice).

Bottom row is an animated scene that reads left-to-right:

    cat man woman ..dots.. train

A cat and two people (a man and a woman) idle at the far left -- the people bob
gently out of sync, the cat blinks. A train pulls in from the right as its
arrival nears (closer the sooner it comes), its cars filling the whole length
from its front out to the right edge, so more of it shows the closer it gets.
The track ahead of it is a row of low dots (ascii ".") and a pulse rides it
toward the people (right to left) by lifting one dot a pixel. When a due train
drops out of the feed it has left, so it rapidly pulls back out to the right
(Ditmars is a terminus). With no service the group dozes with cycling ``z``'s.

When ``render`` is given an active alert, a ``!`` blinks in the top-right corner
of the times row and the alert text occasionally scrolls across the whole bar.

Custom CGRAM glyphs (all 8 slots): two man frames, two woman frames, two cat
frames (open/blink), the subway car (repeated for the train), and the lifted
wave dot. The caller
advances an incrementing ``frame`` counter; each ``render`` overwrites both rows
in full (no clear) so animation is flicker-free and stale characters never
linger.
"""

from RPLCD.i2c import CharLCD

from mta import ROUTES

# 5x8 CGRAM glyphs (one int per row, low 5 bits = pixel columns left->right).
# Man and woman idle frames: frame B is frame A nudged down a pixel, so they bob
# (hop) in place. The man has trousered legs; the woman a flared skirt.
MAN_A = [0b01110, 0b01110, 0b00100, 0b01110, 0b00100, 0b00100, 0b01010, 0b00000]
MAN_B = [0b00000, 0b01110, 0b01110, 0b00100, 0b01110, 0b00100, 0b00100, 0b01010]
WOMAN_A = [0b01110, 0b01110, 0b00100, 0b01110, 0b00100, 0b01110, 0b11111, 0b00000]
WOMAN_B = [0b00000, 0b01110, 0b01110, 0b00100, 0b01110, 0b00100, 0b01110, 0b11111]
# Cat face: open-eyed (A) and mid-blink (B, eye row filled in).
CAT_A = [0b10001, 0b11011, 0b11111, 0b10101, 0b11111, 0b11111, 0b01110, 0b00000]
CAT_B = [0b10001, 0b11011, 0b11111, 0b11111, 0b11111, 0b11111, 0b01110, 0b00000]
# Subway car (boxy, two windows, wheels), repeated to draw the whole train.
CAR = [0b00000, 0b00000, 0b11111, 0b10101, 0b11111, 0b11111, 0b01010, 0b00000]
# Wave pulse: a 2x2 dot riding high above the bottom-row "." track dots, so the
# crest is clearly visible as it travels (one pixel of lift was imperceptible).
WAVE = [0b00000, 0b00000, 0b00000, 0b01100, 0b01100, 0b00000, 0b00000, 0b00000]

MAN_CHARS = ("\x00", "\x01")
WOMAN_CHARS = ("\x02", "\x03")
CAT_A_CHAR = "\x04"
CAT_B_CHAR = "\x05"
CAR_CHAR = "\x06"
WAVE_CHAR = "\x07"

# A train this many minutes out (or more) sits at the far right; sooner trains
# pull left toward the waiting people.
MAX_MIN = 12

# Frames the wave pulse lingers on each track cell before advancing (higher is
# slower).
WAVE_STEP = 3

# Frames each idle pose holds (the bob), how often the cat blinks, and how many
# frames a blink stays shut.
IDLE_STEP = 5
BLINK_EVERY = 35
BLINK_LEN = 3

# When a train at or under this many minutes drops out of the feed it has left;
# play a quick departure as it pulls back out (Ditmars is a terminus).
DEPART_TRIGGER = 1
# Columns the departing train jumps per frame (higher is faster/snappier).
DEPART_STEP = 2

# Alert "!" blink rate (frames per on/off). The scroll hops SCROLL_CHARS columns
# every SCROLL_FRAMES frames (2 chars per 0.4s at 5 fps), with SCROLL_GAP columns
# of normal top bar between passes (~12s).
BANG_BLINK = 3
SCROLL_FRAMES = 2
SCROLL_CHARS = 2
SCROLL_GAP = 60


class TrainDisplay:
    def __init__(self, address=0x27, port=1, cols=16, rows=2):
        self.cols = cols
        self.rows = rows
        self.lcd = CharLCD(
            i2c_expander="PCF8574",
            address=address,
            port=port,
            cols=cols,
            rows=rows,
        )
        for slot, bitmap in enumerate(
            (MAN_A, MAN_B, WOMAN_A, WOMAN_B, CAT_A, CAT_B, CAR, WAVE)
        ):
            self.lcd.create_char(slot, bitmap)
        self.lcd.clear()

        # Fixed group at the left: cat, man, woman.
        self.cat_col = 0
        self.man_col = 1
        self.woman_col = 2
        # Track and train: the locomotive parks here when due and slides right
        # as the wait grows.
        self.track_start = self.woman_col + 1
        self.train_near = self.track_start
        self.train_far = cols - 1

        # Departure animation state.
        self._prev_soonest = None
        self._depart_col = None

    def _fit(self, text):
        return text[: self.cols].ljust(self.cols)

    def _next_trains(self, departures, count=2):
        """Return up to `count` (minutes, route) pairs soonest-first."""
        upcoming = []
        for route in ROUTES:
            for m in departures.for_route(route):
                upcoming.append((m, route))
        upcoming.sort()
        return upcoming[:count]

    def _top_line(self, upcoming):
        if not upcoming:
            return "No trains"
        return "  ".join(f"{route} {m}m" for m, route in upcoming)

    def _compose_top(self, times, frame, alert_active, alert_text):
        """Times line, plus a blinking '!' when alerted and an occasional scroll
        of the alert text across the whole bar."""
        if alert_active and alert_text:
            padded = " " * self.cols + alert_text + " " * self.cols
            windows = len(padded) - self.cols + 1
            pos = (frame // SCROLL_FRAMES * SCROLL_CHARS) % (windows + SCROLL_GAP)
            if pos < windows:
                return padded[pos : pos + self.cols]
        if alert_active:
            line = list(self._fit(times))
            line[-1] = "!" if (frame // BANG_BLINK) % 2 == 0 else " "
            return "".join(line)
        return times

    def _draw_group(self, cells, frame):
        """Cat (blinking) and two people (bobbing out of sync) at the left."""
        bob = (frame // IDLE_STEP) % 2
        cells[self.cat_col] = CAT_B_CHAR if frame % BLINK_EVERY < BLINK_LEN else CAT_A_CHAR
        cells[self.man_col] = MAN_CHARS[bob]
        cells[self.woman_col] = WOMAN_CHARS[1 - bob]

    def _scene_line(self, upcoming, frame):
        cells = [" "] * self.cols
        self._draw_group(cells, frame)

        if not upcoming:
            return self._sleep_tail(cells, frame)

        # Train pulls in from the right as arrival nears.
        mins = upcoming[0][0]
        capped = min(mins, MAX_MIN)
        reach = self.train_far - self.train_near
        train_col = self.train_near + round((capped / MAX_MIN) * reach)
        train_col = max(self.train_near, min(self.train_far, train_col))

        # Dotted track between the people and the train.
        for c in range(self.track_start, train_col):
            cells[c] = "."

        # A pulse rides the track toward the people (right -> left), lifting a
        # dot a pixel as it passes.
        span = train_col - self.track_start
        if span > 0:
            offset = (frame // WAVE_STEP) % span
            cells[train_col - 1 - offset] = WAVE_CHAR

        # The train fills the whole length from its front out to the right edge.
        for c in range(train_col, self.cols):
            cells[c] = CAR_CHAR
        return "".join(cells)

    def _depart_scene(self, train_col, frame):
        cells = [" "] * self.cols
        self._draw_group(cells, frame)
        for c in range(self.track_start, self.cols):
            cells[c] = "."
        for c in range(max(train_col, self.track_start), self.cols):
            cells[c] = CAR_CHAR
        return "".join(cells)

    def _sleep_tail(self, cells, frame):
        zzz = ["z..", "zz.", "zzz"][(frame // WAVE_STEP) % 3]
        for i, ch in enumerate(zzz):
            col = self.track_start + 1 + i
            if col < self.cols:
                cells[col] = ch
        return "".join(cells)

    def render(self, departures, frame, alert_active=False, alert_text=""):
        """Draw the scene for a Departures snapshot at the given frame."""
        upcoming = self._next_trains(departures)
        top = self._compose_top(
            self._top_line(upcoming), frame, alert_active, alert_text
        )
        mins = upcoming[0][0] if upcoming else None

        # A near train that drops out of the feed has departed: play it leaving.
        if (
            self._depart_col is None
            and self._prev_soonest is not None
            and self._prev_soonest <= DEPART_TRIGGER
            and (mins is None or mins > self._prev_soonest)
        ):
            self._depart_col = self.train_near

        if self._depart_col is not None:
            bottom = self._depart_scene(self._depart_col, frame)
            self._depart_col += DEPART_STEP
            if self._depart_col >= self.cols:
                self._depart_col = None
                self._prev_soonest = mins
        else:
            bottom = self._scene_line(upcoming, frame)
            self._prev_soonest = mins

        self._write_lines([top, bottom], clear=False)

    def show_message(self, *lines):
        """Render arbitrary text lines (e.g. for startup or error states)."""
        self._write_lines(list(lines))

    def _write_lines(self, lines, clear=True):
        if clear:
            self.lcd.clear()
        for i in range(self.rows):
            text = lines[i] if i < len(lines) else ""
            self.lcd.cursor_pos = (i, 0)
            self.lcd.write_string(self._fit(text))

    def close(self):
        self.lcd.clear()
        self.lcd.close(clear=True)
