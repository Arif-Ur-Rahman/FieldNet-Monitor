"""Gateway simulator: plays failure stories through the fixed API and the test clock.

    python sim.py [STORY|all]     run one story, or every story (default)
    python sim.py --list          list the stories

Each story resets the server (/test/reset), sets its own clock, drives the
gateway API like a device would, and ends in assertions. Exit code 0 if every
story passed, 1 if one failed, 2 if the server can't run stories.

The server must run with TEST_MODE=1. /test/reset empties every table: never
point this at data you want to keep. API_URL picks the server (default
http://localhost:8000). Standard library only, so it runs in the API image.
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta

EPOCH = datetime(2026, 1, 1, tzinfo=UTC)  # day 0, 00:00 UTC


def at(day: float, hour: int = 0, minute: int = 0) -> str:
    """Day n of a story, as an ISO 8601 UTC string."""
    t = EPOCH + timedelta(days=day, hours=hour, minutes=minute)
    return t.isoformat().replace("+00:00", "Z")


class StoryFailed(Exception):
    pass


class ServerUnavailable(Exception):
    pass


def expect(what: str, actual, expected) -> None:
    if actual != expected:
        raise StoryFailed(f"{what}: expected {expected!r}, got {actual!r}")
    say(f"  ✓ {what} = {actual!r}")


def say(text: str) -> None:
    print(text, flush=True)


class API:
    def __init__(self, base_url: str):
        self.base = base_url.rstrip("/")

    def call(self, method: str, path: str, body=None, *, token: str | None = None, expect_status=None):
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(self.base + path, data=data, method=method)
        request.add_header("Content-Type", "application/json")
        if token:
            request.add_header("Authorization", f"Bearer {token}")
        try:
            with urllib.request.urlopen(request, timeout=30) as resp:
                status, raw = resp.status, resp.read()
        except urllib.error.HTTPError as err:
            status, raw = err.code, err.read()
        except urllib.error.URLError as err:
            raise ServerUnavailable(f"cannot reach {self.base}: {err.reason}") from None
        payload = json.loads(raw) if raw else None
        if expect_status is not None and status != expect_status:
            raise StoryFailed(f"{method} {path}: expected HTTP {expect_status}, got {status} {payload}")
        return status, payload

    # Test endpoints

    def reset(self) -> None:
        status, _ = self.call("POST", "/test/reset")
        if status == 404:
            raise ServerUnavailable("the server is not in TEST_MODE (/test/reset is 404); start it with TEST_MODE=1")
        if status != 204:
            raise StoryFailed(f"/test/reset: HTTP {status}")

    def clock(self, now: str) -> None:
        self.call("POST", "/test/clock", {"now": now}, expect_status=200)

    def drain(self) -> None:
        self.call("POST", "/test/drain", expect_status=200)

    # Operator API

    def gateway(self, gateway_id: str) -> "Gateway":
        body = {"gateway_id": gateway_id, "name": gateway_id}
        _, body = self.call("POST", "/api/v1/gateways", body, expect_status=201)
        return Gateway(self, gateway_id, body["token"])

    def sensor(self, sensor_id: str, sensor_type: str = "temperature") -> None:
        self.call("POST", "/api/v1/sensors", {"sensor_id": sensor_id, "type": sensor_type}, expect_status=201)

    def cover(self, sensor_id: str, gateway_ids: list[str]) -> None:
        self.call("PUT", f"/api/v1/sensors/{sensor_id}/coverage", {"gateway_ids": gateway_ids}, expect_status=200)

    def action(self, gateway_id: str, action: str, reason: str | None = None) -> dict:
        body = {"action": action} | ({"reason": reason} if reason else {})
        return self.call("POST", f"/api/v1/gateways/{gateway_id}/actions", body, expect_status=200)[1]

    def get_gateway(self, gateway_id: str) -> dict:
        return self.call("GET", f"/api/v1/gateways/{gateway_id}", expect_status=200)[1]

    def get_sensor(self, sensor_id: str) -> dict:
        return self.call("GET", f"/api/v1/sensors/{sensor_id}", expect_status=200)[1]

    def timeline(self, entity: str, entity_id: str) -> list[dict]:
        return self.call("GET", f"/api/v1/{entity}/{entity_id}/timeline", expect_status=200)[1]


class Gateway:
    """A simulated device: calls /gw/v1 with its bearer token."""

    def __init__(self, api: API, gateway_id: str, token: str):
        self.api, self.id, self.token, self.n = api, gateway_id, token, 0

    def heartbeat(self, sent_at: str, session: str = "ok") -> None:
        body = {"sent_at": sent_at, "session": session}
        self.api.call("POST", "/gw/v1/heartbeat", body, token=self.token, expect_status=204)

    def cycle(self, finished_at: str, results: list[dict], session: str = "ok") -> dict:
        self.n += 1
        body = {
            "cycle_id": f"{self.id}-c{self.n}",
            "started_at": finished_at,
            "finished_at": finished_at,
            "session": session,
            "results": results,
        }
        return self.api.call("POST", "/gw/v1/cycles", body, token=self.token, expect_status=202)[1]

    def batch(self, batch_id: str, sensor_id: str, readings: list[dict]) -> None:
        body = {"sensor_id": sensor_id, "readings": readings}
        self.api.call("PUT", f"/gw/v1/batches/{batch_id}", body, token=self.token, expect_status=202)

    def commands(self) -> list[dict]:
        return self.api.call("GET", "/gw/v1/commands", token=self.token, expect_status=200)[1]["commands"]

    def ack(self, command_id: str, acked_at: str) -> None:
        body = {"acked_at": acked_at}
        self.api.call("POST", f"/gw/v1/commands/{command_id}/ack", body, token=self.token, expect_status=204)


def reading(reading_id: str, taken_at: str, value: float = 21.0, unit: str = "C") -> dict:
    return {"reading_id": reading_id, "taken_at": taken_at, "value": value, "unit": unit}


STORIES: dict[str, tuple] = {}


def story(name: str, description: str):
    """Register a story: a function taking an API client."""

    def register(fn):
        STORIES[name] = (fn, description)
        return fn

    return register


def run(api: API, name: str) -> bool:
    fn, description = STORIES[name]
    say(f"\n▶ {name}: {description}")
    api.reset()
    try:
        fn(api)
    except StoryFailed as err:
        say(f"✘ {name} FAILED: {err}")
        return False
    say(f"✔ {name} passed")
    return True


def main(argv=None) -> int:
    import stories  # noqa: F401  registers the stories

    parser = argparse.ArgumentParser(description="Play gateway failure stories against FieldNet.")
    parser.add_argument("story", nargs="?", default="all", help="a story name, or 'all'")
    parser.add_argument("--list", action="store_true", help="list the stories and exit")
    args = parser.parse_args(argv)

    if args.list:
        for name, (_, description) in STORIES.items():
            say(f"{name:28} {description}")
        return 0
    if not STORIES:
        say("No stories registered.")
        return 2
    names = list(STORIES) if args.story == "all" else [args.story]
    unknown = [n for n in names if n not in STORIES]
    if unknown:
        say(f"Unknown story {unknown[0]!r}. Stories: {', '.join(STORIES)}")
        return 2

    api = API(os.environ.get("API_URL", "http://localhost:8000"))
    try:
        results = {name: run(api, name) for name in names}
    except ServerUnavailable as err:
        say(f"✘ {err}")
        return 2
    failed = [n for n, ok in results.items() if not ok]
    summary = f"\n{len(results) - len(failed)}/{len(results)} stories passed"
    say(summary + (f"; failed: {', '.join(failed)}" if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    # Run as a script, this module is __main__; let `import sim` in stories.py find this
    # same module, or the stories would register into a second copy the CLI never sees.
    sys.modules.setdefault("sim", sys.modules[__name__])
    sys.exit(main())
