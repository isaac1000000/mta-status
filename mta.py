"""Fetch upcoming N/W train times at Astoria-Ditmars Blvd from the MTA feed.

Astoria-Ditmars Blvd (GTFS stop "R01") is the northern terminus of the
Astoria line. Trains arrive northbound ("R01N") and depart southbound
("R01S") toward Manhattan and Brooklyn. The southbound departures are what a
rider boarding here cares about, so that is the default direction.

The N realtime feed (NYCTFeed("N")) carries the whole N/Q/R/W line, so a single
fetch covers both the N and the W.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone

from nyct_gtfs import NYCTFeed

STOP_ID = "R01"
STATION_NAME = "Astoria-Ditmars Blvd"
ROUTES = ("N", "W")

# Southbound = departing Ditmars toward Manhattan/Brooklyn (the boarding
# direction at a terminus). Northbound = trains terminating at Ditmars.
SOUTHBOUND = "S"
NORTHBOUND = "N"


@dataclass
class Departures:
    """Upcoming train times at the station, in whole minutes from now."""

    direction: str
    updated_at: datetime
    minutes: dict = field(default_factory=dict)  # route -> sorted [int minutes]

    def for_route(self, route):
        return self.minutes.get(route, [])


def fetch_departures(direction=SOUTHBOUND, routes=ROUTES, limit=3):
    """Return a Departures snapshot for the given routes and direction.

    `direction` is "S" (toward Manhattan, the default) or "N" (into Ditmars).
    `minutes` maps each route to up to `limit` whole-minute waits, ascending.
    Trains already due or past are dropped. A route with no service maps to [].
    """
    feed = NYCTFeed("N")
    target_stop = STOP_ID + direction
    now = datetime.now()

    minutes = {route: [] for route in routes}
    for train in feed.trips:
        if train.route_id not in minutes:
            continue
        for stop in train.stop_time_updates:
            if stop.stop_id != target_stop:
                continue
            when = stop.departure or stop.arrival
            if when is None:
                continue
            wait = (when - now).total_seconds() / 60.0
            if wait < 0:
                continue
            minutes[train.route_id].append(int(round(wait)))

    for route in minutes:
        minutes[route] = sorted(minutes[route])[:limit]

    updated = feed.last_generated or datetime.now(timezone.utc)
    return Departures(direction=direction, updated_at=updated, minutes=minutes)


if __name__ == "__main__":
    deps = fetch_departures()
    print(f"{STATION_NAME} (southbound), updated {deps.updated_at:%H:%M:%S}")
    for route in ROUTES:
        mins = deps.for_route(route)
        label = ", ".join(f"{m} min" for m in mins) if mins else "no service"
        print(f"  {route}: {label}")
