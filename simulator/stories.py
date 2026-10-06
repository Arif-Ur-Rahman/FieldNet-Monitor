"""Failure stories. Each resets the server, plays devices through /gw/v1 and the test clock, and asserts."""

from sim import API, at, expect, say, story


@story("ghost-heartbeat", "a gateway keeps heartbeating but stops collecting: stale, and not_checked")
def ghost_heartbeat(api: API) -> None:
    api.clock(at(0, 8))
    g = api.gateway("G1")
    api.sensor("S1")
    api.cover("S1", ["G1"])

    say("Day 0 08:00: one good cycle connects G1.")
    g.cycle(at(0, 8), [{"sensor_id": "S1", "outcome": "no_readings"}])
    expect("G1 status", api.get_gateway("G1")["status"], "connected")
    expect("S1 collection", api.get_sensor("S1")["collection"], "no_readings")

    say("Then only heartbeats, every hour, for two days.")
    for hour in range(9, 9 + 48):
        api.clock(at(0, hour))
        g.heartbeat(at(0, hour))

    gw = api.get_gateway("G1")
    expect("G1 status", gw["status"], "stale")
    expect("G1 stale since (last qualifying + 12h)", gw["status_since"], at(0, 20))
    expect("G1 last_heartbeat_at keeps moving", gw["last_heartbeat_at"], at(0, 56))
    expect("G1 last_qualifying_at", gw["last_qualifying_at"], at(0, 8))
    s1 = api.get_sensor("S1")
    expect("S1 coverage", s1["coverage"], "recoverable")
    expect("S1 collection", s1["collection"], "not_checked")
