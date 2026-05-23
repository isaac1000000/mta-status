"""Astoria-Ditmars Blvd N/W train tracker.

Polls the MTA realtime feed and shows the next southbound (Manhattan-bound)
N and W departures on the 16x2 I2C LCD. Runs until interrupted.
"""

import time

from mta import STATION_NAME, fetch_departures
from display import TrainDisplay

REFRESH_SECONDS = 30


def main():
    display = TrainDisplay()
    display.show_message("Astoria-Ditmars", "loading...")

    try:
        while True:
            try:
                departures = fetch_departures()
                display.show(departures)
            except Exception as exc:
                print(f"feed error: {exc}")
                display.show_message(STATION_NAME[:16], "feed error")
            time.sleep(REFRESH_SECONDS)
    except KeyboardInterrupt:
        pass
    finally:
        display.close()


if __name__ == "__main__":
    main()
