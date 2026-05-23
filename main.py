"""Astoria-Ditmars Blvd N/W train tracker.

Polls the MTA realtime feed and shows the next southbound (Manhattan-bound)
N and W departures on the 16x2 I2C LCD as a little animated scene. The feed is
refreshed every REFRESH_SECONDS and service alerts every ALERT_SECONDS, but the
display is redrawn every ANIM_SECONDS so the scene animates between fetches.
Runs until interrupted.
"""

import time

from mta import STATION_NAME, fetch_alerts, fetch_departures
from display import TrainDisplay

REFRESH_SECONDS = 30
ALERT_SECONDS = 120
ANIM_SECONDS = 0.2


def main():
    display = TrainDisplay()
    display.show_message("Astoria-Ditmars", "loading...")

    departures = None
    service_alerts = []
    last_fetch = 0.0
    last_alert = 0.0
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

            if last_alert == 0.0 or now - last_alert >= ALERT_SECONDS:
                try:
                    service_alerts = fetch_alerts()
                except Exception as exc:
                    print(f"alert error: {exc}")  # non-fatal: keep last alerts
                last_alert = now

            # Combine the per-line delay flag with any service-alert headlines.
            parts = []
            if departures.delayed_routes:
                parts.append("/".join(departures.delayed_routes) + " delays")
            parts += service_alerts
            alert_text = "   -   ".join(parts)

            display.render(
                departures, frame, alert_active=bool(parts), alert_text=alert_text
            )
            frame += 1
            time.sleep(ANIM_SECONDS)
    except KeyboardInterrupt:
        pass
    finally:
        display.close()


if __name__ == "__main__":
    main()
