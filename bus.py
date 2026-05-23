"""Fetch upcoming Q69 / Q100 bus arrivals from MTA Bus Time (SIRI), and look up
the direction-specific stop codes you need for the .env file.

MTA Bus Time is a separate system from the subway feeds and needs an API key
(MTA_BUS_API_KEY in .env). Stops are identified by a SIRI MonitoringRef -- the
short stop code printed on the bus-stop pole. If you don't know it, run:

    venv/bin/python bus.py find Q69 Ditmars

which lists every Q69 stop whose name matches "Ditmars", with its code and the
direction (destination) it serves, so you can pick the right one.
"""

import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone

import requests

from config import load_env

load_env()

API_KEY = os.environ.get("MTA_BUS_API_KEY", "")
SIRI_URL = "https://bustime.mta.info/api/siri/stop-monitoring.json"
STOPS_URL = "https://bustime.mta.info/api/where/stops-for-route/{route}.json"
OPERATOR = "MTABC"  # Q69 and Q100 are run by MTA Bus Company, not NYCT


def _route_ref(line):
    """'Q69' -> 'MTABC_Q69' (the LineRef / route id Bus Time expects)."""
    return f"{OPERATOR}_{line.upper()}"


@dataclass
class BusArrivals:
    """Upcoming arrivals for one line at one stop, in whole minutes from now."""

    line: str
    stop_name: str
    updated_at: datetime
    minutes: list = field(default_factory=list)
    alerts: list = field(default_factory=list)  # active situation headlines


def fetch_bus(line, stop_ref, limit=3, timeout=15):
    """Return a BusArrivals snapshot for `line` at stop code `stop_ref`."""
    if not API_KEY:
        raise RuntimeError("MTA_BUS_API_KEY not set (see .env)")

    # Stop refs live in the MTA namespace even for MTABC lines, so we send the
    # bare stop code and no OperatorRef (passing MTABC here breaks the lookup).
    params = {
        "key": API_KEY,
        "version": 2,
        "MonitoringRef": stop_ref,
        "LineRef": _route_ref(line),
    }
    resp = requests.get(SIRI_URL, params=params, timeout=timeout)
    resp.raise_for_status()

    service = resp.json().get("Siri", {}).get("ServiceDelivery", {})
    deliveries = service.get("StopMonitoringDelivery", [])
    visits = deliveries[0].get("MonitoredStopVisit", []) if deliveries else []

    now = datetime.now(timezone.utc)
    stop_name = ""
    minutes = []
    for visit in visits:
        call = visit.get("MonitoredVehicleJourney", {}).get("MonitoredCall", {})
        if not stop_name:
            name = call.get("StopPointName") or ""
            stop_name = name[0] if isinstance(name, list) and name else name or ""
        when_str = call.get("ExpectedArrivalTime") or call.get("ExpectedDepartureTime")
        if not when_str:
            continue
        wait = (datetime.fromisoformat(when_str) - now).total_seconds() / 60.0
        if wait < 0:
            continue
        minutes.append(int(round(wait)))

    minutes.sort()
    return BusArrivals(
        line=line.upper(),
        stop_name=stop_name,
        updated_at=now,
        minutes=minutes[:limit],
        alerts=_bus_alerts(service, now),
    )


def _bus_alerts(service, now, limit=2):
    """Active situation headlines from a SIRI ServiceDelivery, deduped."""
    headlines = []
    for sx in service.get("SituationExchangeDelivery", []) or []:
        for pt in sx.get("Situations", {}).get("PtSituationElement", []) or []:
            window = pt.get("PublicationWindow")
            if window and not _window_active(window, now):
                continue
            summary = pt.get("Summary")
            if isinstance(summary, list):
                summary = summary[0] if summary else ""
            if isinstance(summary, dict):
                summary = summary.get("text", "")
            text = " ".join((summary or "").split())
            if text and text not in headlines:
                headlines.append(text)
            if len(headlines) >= limit:
                return headlines
    return headlines


def _window_active(window, now):
    def parse(value):
        if isinstance(value, list):
            value = value[0] if value else None
        try:
            return datetime.fromisoformat(value) if value else None
        except (TypeError, ValueError):
            return None

    start, end = parse(window.get("StartTime")), parse(window.get("EndTime"))
    # MTA uses an epoch sentinel (1969-12-31) for "no end time".
    if end and end.year < 2000:
        end = None
    if start and now < start:
        return False
    if end and now > end:
        return False
    return True


def find_stops(line, query="", timeout=15):
    """Return [(code, name, destination)] for stops on `line` matching `query`."""
    if not API_KEY:
        raise RuntimeError("MTA_BUS_API_KEY not set (see .env)")

    url = STOPS_URL.format(route=_route_ref(line))
    resp = requests.get(
        url, params={"key": API_KEY, "version": 2, "includePolylines": "false"}, timeout=timeout
    )
    resp.raise_for_status()
    data = resp.json().get("data", {})

    stops = {s["id"]: s for s in data.get("references", {}).get("stops", [])}
    destination = {}
    for grouping in data.get("entry", {}).get("stopGroupings", []):
        for group in grouping.get("stopGroups", []):
            names = group.get("name", {}).get("names", [])
            dest = names[0] if names else group.get("id", "")
            for stop_id in group.get("stopIds", []):
                destination[stop_id] = dest

    query = query.lower()
    results = []
    for stop_id, stop in stops.items():
        name = stop.get("name", "")
        if query and query not in name.lower():
            continue
        results.append((stop.get("code") or stop_id, name, destination.get(stop_id, "")))
    return sorted(results)


if __name__ == "__main__":
    args = sys.argv[1:]
    if len(args) >= 2 and args[0] == "find":
        line, query = args[1], args[2] if len(args) > 2 else ""
        for code, name, dest in find_stops(line, query):
            print(f"  {code:>8}  {name}  ->  {dest}")
    elif len(args) >= 3 and args[0] == "arrivals":
        snap = fetch_bus(args[1], args[2])
        label = ", ".join(f"{m} min" for m in snap.minutes) if snap.minutes else "no buses"
        print(f"{snap.line} @ {snap.stop_name or args[2]}: {label}")
        for headline in snap.alerts:
            print(f"  ! {headline}")
    else:
        print("usage: bus.py find <LINE> [search]  |  bus.py arrivals <LINE> <STOPCODE>")
