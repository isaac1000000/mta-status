"""Render train departures on the 16x2 I2C character LCD.

Top row lists the next two departures across all routes, each tagged with its
line, e.g. ``N 3m  W 5m`` (or ``N 3m  N 9m`` if the same line is up twice).

Bottom row is an animated scene that reads left-to-right:

    cat man woman ..dots.. train

A cat and two people (a man and a woman) idle at the far left -- the people bob
gently out of sync, the cat blinks. A train pulls in from the right as its
arrival nears (closer the sooner it comes). The subway fills the whole length
from its front out to the right edge; the bus is a two-cell vehicle. The ground
around the vehicle is drawn with underscores (track / road). When a due train
drops out of the feed it has left, so it rapidly pulls back out to the right
(Ditmars is a terminus). With no service the group dozes with cycling ``z``'s.

When ``render`` is given an active alert, a ``!`` blinks in the top-right corner
of the times row and the alert text occasionally scrolls across the whole bar.

Custom CGRAM glyphs: two man frames, two woman frames, two cat frames
(open/blink), and the subway car -- with the bus's two halves swapped into the
CAT_B / CAR slots while a bus view is active. The caller
advances an incrementing ``frame`` counter; each ``render`` overwrites both rows
in full (no clear) so animation is flicker-free and stale characters never
linger.
"""

from RPLCD.i2c import CharLCD

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
# Bus: a two-cell vehicle with rounded front/back roof corners (so it reads as a
# bus, not a train). Loaded into the CAR/CAT_B slots only while in a bus view.
BUS_LEFT = [0b00000, 0b00000, 0b01111, 0b10001, 0b11111, 0b11111, 0b01010, 0b00000]
BUS_RIGHT = [0b00000, 0b00000, 0b11110, 0b10001, 0b11111, 0b11111, 0b01010, 0b00000]

MAN_CHARS = ("\x00", "\x01")
WOMAN_CHARS = ("\x02", "\x03")
CAT_A_CHAR = "\x04"
CAT_B_CHAR = "\x05"
CAR_CHAR = "\x06"
# Bus glyphs reuse the CAT_B / CAR slots (swapped in on a mode change), since
# all 8 CGRAM slots are otherwise spoken for.
BUS_RIGHT_CHAR = "\x05"
BUS_LEFT_CHAR = "\x06"

# A train this many minutes out (or more) sits at the far right; sooner trains
# pull left toward the waiting people.
MAX_MIN = 12

# Ground the vehicle rides on, drawn around it (underscore = track and road).
GROUND_CHAR = "_"

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
# of normal top bar between passes (~30s).
BANG_BLINK = 3
SCROLL_FRAMES = 2
SCROLL_CHARS = 2
SCROLL_GAP = 150


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
            (MAN_A, MAN_B, WOMAN_A, WOMAN_B, CAT_A, CAT_B, CAR)
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

        # Animation state. `_mode` lets render() reset on a mode switch so the
        # incoming view doesn't trigger a false departure. `_is_bus` tracks which
        # glyphs are currently loaded in the shared CAT_B / CAR slots.
        self._mode = None
        self._is_bus = False
        self._prev_soonest = None
        self._depart_col = None

    def _fit(self, text):
        return text[: self.cols].ljust(self.cols)

    def _top_line(self, upcoming, empty_text):
        if not upcoming:
            return empty_text
        # One label (e.g. both buses, or both N): "Q100 2m 29m". Mixed lines
        # (e.g. N and W): "N 3m  W 5m".
        if len({label for _, label in upcoming}) == 1:
            label = upcoming[0][1]
            return f"{label} " + " ".join(f"{m}m" for m, _ in upcoming)
        return "  ".join(f"{label} {m}m" for m, label in upcoming)

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
        # The cat only blinks in subway view; in a bus view its blink slot holds
        # a bus glyph, so it stays open-eyed.
        blink = not self._is_bus and frame % BLINK_EVERY < BLINK_LEN
        cells[self.cat_col] = CAT_B_CHAR if blink else CAT_A_CHAR
        cells[self.man_col] = MAN_CHARS[bob]
        cells[self.woman_col] = WOMAN_CHARS[1 - bob]

    def _scene_line(self, upcoming, frame):
        cells = [" "] * self.cols
        self._draw_group(cells, frame)

        if not upcoming:
            return self._sleep_tail(cells, frame)

        # Vehicle pulls in from the right as arrival nears. A bus is two cells,
        # so its front must stop one column short of the edge.
        mins = upcoming[0][0]
        capped = min(mins, MAX_MIN)
        far = (self.cols - 2) if self._is_bus else self.train_far
        front = self.train_near + round((capped / MAX_MIN) * (far - self.train_near))
        front = max(self.train_near, min(far, front))

        # Ground around the vehicle (underscores), on both sides of it.
        for c in range(self.track_start, self.cols):
            cells[c] = GROUND_CHAR

        self._draw_vehicle(cells, front)
        return "".join(cells)

    def _draw_vehicle(self, cells, front):
        """Bus: two cells at `front`. Train: cars from `front` to the edge."""
        if self._is_bus:
            cells[front] = BUS_LEFT_CHAR
            if front + 1 < self.cols:
                cells[front + 1] = BUS_RIGHT_CHAR
        else:
            for c in range(front, self.cols):
                cells[c] = CAR_CHAR

    def _depart_scene(self, front, frame):
        cells = [" "] * self.cols
        self._draw_group(cells, frame)
        for c in range(self.track_start, self.cols):
            cells[c] = GROUND_CHAR
        self._draw_vehicle(cells, max(front, self.track_start))
        return "".join(cells)

    def _sleep_tail(self, cells, frame):
        zzz = ["z..", "zz.", "zzz"][(frame // IDLE_STEP) % 3]
        for i, ch in enumerate(zzz):
            col = self.track_start + 1 + i
            if col < self.cols:
                cells[col] = ch
        return "".join(cells)

    def render(
        self,
        upcoming,
        frame,
        mode="subway",
        empty_text="No trains",
        alert_active=False,
        alert_text="",
    ):
        """Draw the scene for an arrivals list (sorted (minutes, label) pairs).

        `mode` identifies the current view; switching it resets the departure
        animation so the new view doesn't read as a train pulling away.
        """
        if mode != self._mode:
            self._mode = mode
            self._prev_soonest = None
            self._depart_col = None
            is_bus = mode != "subway"
            if is_bus != self._is_bus:
                self._is_bus = is_bus
                # Swap the shared slots between (cat-blink, train car) and the
                # two bus halves.
                self.lcd.create_char(5, BUS_RIGHT if is_bus else CAT_B)
                self.lcd.create_char(6, BUS_LEFT if is_bus else CAR)

        top = self._compose_top(
            self._top_line(upcoming, empty_text), frame, alert_active, alert_text
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
