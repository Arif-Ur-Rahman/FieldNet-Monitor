"""Failure stories. Each resets the server, plays devices through /gw/v1 and the test clock, and asserts."""

from sim import API, at, expect, reading, say, story


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


class Example:
    """The brief's worked example: S covered only by G, reported once a day at 12:00.

    G also cycles for a second sensor, S2, at 04:00 and 20:00, so it never goes
    12 hours without qualifying evidence (the 12-hour stale rule).
    """

    def __init__(self, api: API):
        self.api = api
        api.clock(at(0))
        self.g = api.gateway("G")
        api.sensor("S")
        api.sensor("S2")
        api.cover("S", ["G"])
        api.cover("S2", ["G"])

    def day(self, n: int, s_outcome: str | None = "no_readings", *, until: int = 24, session: str = "ok") -> None:
        """Play day n's cycles (04:00, 12:00, 20:00) before hour `until`, then move the clock there."""
        for hour in (4, 12, 20):
            if hour >= until:
                break
            self.api.clock(at(n, hour))
            results = [{"sensor_id": "S2", "outcome": "no_readings"}]
            if hour == 12 and s_outcome:
                results.append({"sensor_id": "S", "outcome": s_outcome})
            self.g.cycle(at(n, hour), results, session=session)
        self.api.clock(at(n, until) if until < 24 else at(n + 1))

    def start(self) -> None:
        say("Day 0 12:00: G reports readings for S; the batch is processed at 12:01.")
        self.api.clock(at(0, 4))
        self.g.cycle(at(0, 4), [{"sensor_id": "S2", "outcome": "no_readings"}])
        self.api.clock(at(0, 12))
        self.g.cycle(at(0, 12), [{"sensor_id": "S", "outcome": "readings", "batch_id": "b0"}])
        self.api.clock(at(0, 12, 1))
        self.g.batch("b0", "S", [reading("r0", at(0, 12))])
        self.api.drain()
        self.api.clock(at(0, 20))
        self.g.cycle(at(0, 20), [{"sensor_id": "S2", "outcome": "no_readings"}])
        self.api.clock(at(1))

    def sensor(self) -> dict:
        return self.api.get_sensor("S")


@story("auth-flap-mid-sampling", "credentials fail mid sampling window: the window pauses and ends on day 39")
def auth_flap_mid_sampling(api: API) -> None:
    ex = Example(api)
    ex.start()
    say("Days 1-28: no_readings every day; S goes dormant at day 15 and sampling at day 29.")
    for n in range(1, 30):
        ex.day(n)
    s = ex.sensor()
    expect("S lifecycle", s["lifecycle"], "sampling")
    expect("S window ends (next_evaluation_at)", s["next_evaluation_at"], at(32))

    say("Day 30 12:00: G's cycle comes back auth_failed. Then silence until day 37 12:00.")
    ex.day(30, until=12)
    ex.g.cycle(at(30, 12), [{"sensor_id": "S", "outcome": "no_readings"}], session="auth_failed")
    expect("G status", api.get_gateway("G")["status"], "disconnected")
    api.clock(at(33))
    s = ex.sensor()
    expect("S lifecycle while paused", s["lifecycle"], "sampling")
    expect("S next_evaluation_at while paused", s["next_evaluation_at"], None)
    expect("S collection while paused", s["collection"], "not_checked")

    say("Day 37 12:00: a good cycle; the window resumes with 36 hours left.")
    api.clock(at(37, 12))
    ex.g.cycle(at(37, 12), [{"sensor_id": "S", "outcome": "no_readings"}])
    expect("G status", api.get_gateway("G")["status"], "connected")
    expect("S next_evaluation_at", ex.sensor()["next_evaluation_at"], at(39))
    api.clock(at(37, 20))
    ex.g.cycle(at(37, 20), [{"sensor_id": "S2", "outcome": "no_readings"}])
    ex.day(38)
    s = ex.sensor()
    expect("S lifecycle at day 39", s["lifecycle"], "dormant")
    expect("S dormant since", s["lifecycle_since"], at(39))
    expect("S sampling_cycles_done", s["sampling_cycles_done"], 1)
