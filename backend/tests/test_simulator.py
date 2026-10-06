"""Run every simulator story against Django's live test server, so `make test` checks them too.

Locally the simulator is at <repo>/simulator; in Docker, `make test` mounts it at /simulator.
Both are two levels above this file's directory.
"""

import io
import sys
from contextlib import redirect_stdout
from pathlib import Path

import pytest

SIMULATOR = Path(__file__).resolve().parents[2] / "simulator"
if not SIMULATOR.is_dir():
    pytest.skip(f"simulator not found at {SIMULATOR}", allow_module_level=True)
sys.path.insert(0, str(SIMULATOR))

import sim  # noqa: E402
import stories  # noqa: E402, F401  registers the stories


@pytest.mark.parametrize("name", list(sim.STORIES))
def test_story_passes(name, live_server, settings):
    settings.TEST_MODE = True
    out = io.StringIO()
    with redirect_stdout(out):
        passed = sim.run(sim.API(live_server.url), name)
    assert passed, out.getvalue()


def test_cli_reports_a_server_without_test_mode(live_server, settings, monkeypatch):
    settings.TEST_MODE = False
    monkeypatch.setenv("API_URL", live_server.url)
    with redirect_stdout(io.StringIO()) as out:
        code = sim.main(["all"])
    assert code == 2
    assert "not in TEST_MODE" in out.getvalue()


def test_cli_rejects_an_unknown_story():
    with redirect_stdout(io.StringIO()):
        assert sim.main(["no-such-story"]) == 2
