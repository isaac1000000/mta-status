"""Astoria-Ditmars Blvd transit tracker.

Cycles through three views with a GPIO button: the southbound N/W subway, the
Q100 toward Queens Plaza, and the Q69 toward Queens Plaza. Each view shows the
next arrivals as a little animated scene on the 16x2 I2C LCD. Subway + alert
feeds refresh every REFRESH_SECONDS / ALERT_SECONDS; the active view's bus feed
refreshes every REFRESH_SECONDS; the display redraws every ANIM_SECONDS so the
scene animates between fetches. The button is optional -- without it (or without
the GPIO library) the tracker just stays in Subway view.
"""

import os
import threading
import time

from config import load_env

load_env()

import mta
from mta import STATION_NAME, fetch_alerts, fetch_departures
from bus import fetch_bus
from display import TrainDisplay

REFRESH_SECONDS = 30
ALERT_SECONDS = 120
ANIM_SECONDS = 0.2
ALERT_MAX_CHARS = 45  # truncate each alert headline so scrolls stay short


def truncate(text, limit=ALERT_MAX_CHARS):
    return text if len(text) <= limit else text[: limit - 3].rstrip() + "..."

MODES = [
    {"key": "subway", "kind": "train", "empty": "No trains"},
    {"key": "q100", "kind": "bus", "line": "Q100",
     "stop": os.environ.get("Q100_STOP", ""), "empty": "No Q100"},
    {"key": "q69", "kind": "bus", "line": "Q69",
     "stop": os.environ.get("Q69_STOP", ""), "empty": "No Q69"},
]


def setup_button(state, lock, count):
    """Wire the GPIO mode button if configured/available; else return None."""
    pin = os.environ.get("BUTTON_GPIO", "")
    if not pin:
        print("BUTTON_GPIO not set; staying in Subway view")
        return None
    try:
        from gpiozero import Button
    except Exception as exc:  # library not installed yet
        print(f"gpiozero unavailable ({exc}); mode button disabled")
        return None

    def advance():
        with lock:
            state["idx"] = (state["idx"] + 1) % count

    button = Button(int(pin), pull_up=True, bounce_time=0.3)
    button.when_pressed = advance
    return button


def fetch_arrivals(mode):
    """Return (upcoming, delayed_routes, alerts). delayed_routes is () for buses;
    alerts is [] for the subway (its alerts are fetched separately)."""
    if mode["kind"] == "train":
        dep = fetch_departures()
        return mta.upcoming(dep), dep.delayed_routes, []
    snap = fetch_bus(mode["line"], mode["stop"])
    return [(m, snap.line) for m in snap.minutes][:2], (), snap.alerts


def main():
    display = TrainDisplay()
    display.show_message("Astoria-Ditmars", "loading...")

    state = {"idx": 0}
    lock = threading.Lock()
    button = setup_button(state, lock, len(MODES))  # noqa: F841 (keep ref alive)

    cache = {m["key"]: {"up": [], "fetched": 0.0, "alerts": []} for m in MODES}
    delayed_routes = ()
    service_alerts = []
    last_alert = 0.0
    frame = 0

    try:
        while True:
            now = time.monotonic()
            with lock:
                mode = MODES[state["idx"]]
            slot = cache[mode["key"]]

            if not slot["fetched"] or now - slot["fetched"] >= REFRESH_SECONDS:
                try:
                    slot["up"], delays, slot["alerts"] = fetch_arrivals(mode)
                    if mode["kind"] == "train":
                        delayed_routes = delays
                except Exception as exc:
                    print(f"{mode['key']} fetch error: {exc}")  # keep stale data
                slot["fetched"] = now

            if mode["kind"] == "train":
                # Subway alerts = per-line delays + the service-alerts feed.
                if last_alert == 0.0 or now - last_alert >= ALERT_SECONDS:
                    try:
                        service_alerts = fetch_alerts()
                    except Exception as exc:
                        print(f"alert error: {exc}")
                    last_alert = now
                parts = []
                if delayed_routes:
                    parts.append("/".join(delayed_routes) + " delays")
                parts += service_alerts
            else:
                # Bus alerts ride along in the SIRI response.
                parts = slot["alerts"]
            alert_active = bool(parts)
            alert_text = "   -   ".join(truncate(p) for p in parts)

            display.render(
                slot["up"],
                frame,
                mode=mode["key"],
                empty_text=mode["empty"],
                alert_active=alert_active,
                alert_text=alert_text,
            )
            frame += 1
            time.sleep(ANIM_SECONDS)
    except KeyboardInterrupt:
        pass
    finally:
        display.close()


if __name__ == "__main__":
    main()
