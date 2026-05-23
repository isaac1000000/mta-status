"""Astoria-Ditmars Blvd N/W train tracker.

Polls the MTA realtime feed and shows the next southbound (Manhattan-bound)
N and W departures on the 16x2 I2C LCD as a little animated scene. The feed is
refreshed every REFRESH_SECONDS, but the display is redrawn every ANIM_SECONDS
so the scene animates between fetches. Runs until interrupted.
"""

import time

from mta import STATION_NAME, fetch_departures
from display import TrainDisplay

REFRESH_SECONDS = 30
ANIM_SECONDS = 0.2


def main():
    display = TrainDisplay()
    display.show_message("Astoria-Ditmars", "loading...")

    departures = None
    last_fetch = 0.0
    frame = 0

    try:
        while True:
            now = time.monotonic()
            if departures is None or now - last_fetch >= REFRESH_SECONDS:
                try:
                    departures = fetch_departures()
                    last_fetch = now
                except Exception as exc:
                    print(f"feed error: {exc}")
                    display.show_message(STATION_NAME[:16], "feed error")
                    departures = None
                    time.sleep(REFRESH_SECONDS)
                    continue

            display.render(departures, frame)
            frame += 1
            time.sleep(ANIM_SECONDS)
    except KeyboardInterrupt:
        pass
    finally:
        display.close()


if __name__ == "__main__":
    main()
