"""Render train departures on the 16x2 I2C character LCD.

One route per row, e.g.:

    N 3m 9m 16m
    W --

Each row is padded/truncated to the display width so stale characters from a
previous frame never linger.
"""

from RPLCD.i2c import CharLCD

from mta import ROUTES


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
        self.lcd.clear()

    def _fit(self, text):
        return text[: self.cols].ljust(self.cols)

    def _row_for_route(self, route, mins):
        if mins:
            times = " ".join(f"{m}m" for m in mins)
            return f"{route} {times}"
        return f"{route} --"

    def show(self, departures):
        """Render a Departures snapshot, one route per row."""
        lines = [self._row_for_route(route, departures.for_route(route)) for route in ROUTES]
        self._write_lines(lines)

    def show_message(self, *lines):
        """Render arbitrary text lines (e.g. for startup or error states)."""
        self._write_lines(list(lines))

    def _write_lines(self, lines):
        self.lcd.clear()
        for i in range(self.rows):
            text = lines[i] if i < len(lines) else ""
            self.lcd.cursor_pos = (i, 0)
            self.lcd.write_string(self._fit(text))

    def close(self):
        self.lcd.clear()
        self.lcd.close(clear=True)
