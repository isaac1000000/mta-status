"""Fetch upcoming N/W train times (and alerts) at Astoria-Ditmars Blvd.

Astoria-Ditmars Blvd (GTFS stop "R01") is the northern terminus of the
Astoria line. Trains arrive northbound ("R01N") and depart southbound
("R01S") toward Manhattan and Brooklyn. The southbound departures are what a
rider boarding here cares about, so that is the default direction.

The N realtime feed (NYCTFeed("N")) carries the whole N/Q/R/W line, so a single
fetch covers both the N and the W. That feed also carries *delay* alerts per
train. Broader service alerts (planned work, suspensions, reroutes) live in a
separate Subway Service Alerts feed, fetched as JSON by `fetch_alerts`.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone

import requests
from nyct_gtfs import NYCTFeed

STOP_ID = "R01"
STATION_NAME = "Astoria-Ditmars Blvd"
ROUTES = ("N", "W")

# Southbound = departing Ditmars toward Manhattan/Brooklyn (the boarding
# direction at a terminus). Northbound = trains terminating at Ditmars.
SOUTHBOUND = "S"
NORTHBOUND = "N"

# MTA Subway Service Alerts, GTFS-realtime served as JSON (no API key needed).
ALERTS_URL = (
    "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/camsys%2Fsubway-alerts.json"
)


@dataclass
class Departures:
    """Upcoming train times at the station, in whole minutes from now."""

    direction: str
    updated_at: datetime
    minutes: dict = field(default_factory=dict)  # route -> sorted [int minutes]
    delayed_routes: tuple = ()  # routes (in ROUTES order) with a delay alert

    def for_route(self, route):
        return self.minutes.get(route, [])

    @property
    def delayed(self):
        return bool(self.delayed_routes)


def fetch_departures(direction=SOUTHBOUND, routes=ROUTES, limit=3):
    """Return a Departures snapshot for the given routes and direction.

    `direction` is "S" (toward Manhattan, the default) or "N" (into Ditmars).
    `minutes` maps each route to up to `limit` whole-minute waits, ascending.
    Trains already due or past are dropped. A route with no service maps to [].
    `delayed` is True if any train serving our stop has a delay alert.
    """
    feed = NYCTFeed("N")
    target_stop = STOP_ID + direction
    now = datetime.now()

    minutes = {route: [] for route in routes}
    delayed = set()
    for train in feed.trips:
        if train.route_id not in minutes:
            continue
        serves = False
        for stop in train.stop_time_updates:
            if stop.stop_id != target_stop:
                continue
            serves = True
            when = stop.departure or stop.arrival
            if when is None:
                continue
            wait = (when - now).total_seconds() / 60.0
            if wait < 0:
                continue
            minutes[train.route_id].append(int(round(wait)))
        if serves and train.has_delay_alert:
            delayed.add(train.route_id)

    for route in minutes:
        minutes[route] = sorted(minutes[route])[:limit]

    updated = feed.last_generated or datetime.now(timezone.utc)
    delayed_routes = tuple(r for r in routes if r in delayed)
    return Departures(
        direction=direction,
        updated_at=updated,
        minutes=minutes,
        delayed_routes=delayed_routes,
    )


def fetch_alerts(routes=ROUTES, stop_prefix=STOP_ID, limit=3, timeout=20):
    """Return up to `limit` currently-active service-alert headlines that affect
    our routes or station, newest-feed-order first, whitespace collapsed.

    Pulls the separate Subway Service Alerts JSON feed and keeps alerts whose
    informed entities name one of `routes` or a stop under `stop_prefix`, and
    whose active period (if any) includes now.
    """
    resp = requests.get(ALERTS_URL, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()

    now = datetime.now(timezone.utc).timestamp()
    routeset = set(routes)
    headlines = []
    for entity in data.get("entity", []):
        alert = entity.get("alert")
        if not alert:
            continue

        informed = alert.get("informed_entity", [])
        relevant = any(
            ie.get("route_id") in routeset
            or str(ie.get("stop_id", "")).startswith(stop_prefix)
            for ie in informed
        )
        if not relevant:
            continue

        periods = alert.get("active_period")
        if periods and not _any_active(periods, now):
            continue

        text = " ".join(_english(alert.get("header_text", {})).split())
        if not text:
            continue
        named = {ie.get("route_id") for ie in informed}
        label = "/".join(r for r in routes if r in named)
        headline = f"{label}: {text}" if label else text
        if headline not in headlines:
            headlines.append(headline)
        if len(headlines) >= limit:
            break

    return headlines


def _any_active(periods, now):
    for p in periods:
        try:
            start = int(p.get("start", 0) or 0)
            end = p.get("end")
            end = int(end) if end not in (None, "") else None
        except (TypeError, ValueError):
            return True  # unparseable period -> assume active
        if start <= now and (end is None or now <= end):
            return True
    return False


def _english(translated):
    translations = translated.get("translation", []) if translated else []
    for t in translations:
        if str(t.get("language", "en")).lower().startswith("en"):
            return t.get("text", "")
    return translations[0].get("text", "") if translations else ""


if __name__ == "__main__":
    deps = fetch_departures()
    flag = f" [{'/'.join(deps.delayed_routes)} DELAYS]" if deps.delayed_routes else ""
    print(f"{STATION_NAME} (southbound), updated {deps.updated_at:%H:%M:%S}{flag}")
    for route in ROUTES:
        mins = deps.for_route(route)
        label = ", ".join(f"{m} min" for m in mins) if mins else "no service"
        print(f"  {route}: {label}")
    print("alerts:")
    for headline in fetch_alerts():
        print(f"  ! {headline}")
