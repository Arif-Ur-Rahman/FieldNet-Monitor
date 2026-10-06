# FieldNet Monitor

Server, state engine and operator console for an unreliable sensor network.

| Path | What |
|---|---|
| `backend/` | Django + DRF API, state engine, background worker |
| `frontend/` | Next.js + TypeScript operator console |
| `simulator/` | CLI that plays failure stories through the API |

## Run

```bash
make up        # docker compose up: db, api (:8000), worker, web (:3000)
make test      # backend test suite in Docker
make sim       # simulator stories against the running stack
```

### Without Docker (local Postgres 16 + Python 3.12)

```bash
cd backend && python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt -r requirements-dev.txt
createdb fieldnet && .venv/bin/python manage.py migrate
make test-local
```

API docs: http://localhost:8000/api/docs/

## Simulator

`simulator/sim.py` plays gateway failure stories through the fixed API and the test clock. Each story ends in assertions; the exit code is 0 if every story passed, 1 if one failed, 2 if the server can't run them.

```bash
make sim                      # every story, against the stack from `make up`
make sim STORY=ignored-stop   # one story
make sim-local                # against a local server on :8000 (TEST_MODE=1)
python simulator/sim.py --list
```

| Story | What happens |
|---|---|
| `ghost-heartbeat` | A gateway keeps heartbeating but stops collecting: it goes stale 12h after its last qualifying evidence, and its sensor shows `not_checked`. |
| `auth-flap-mid-sampling` | Credentials fail at day 30 12:00 during a sampling window and recover at day 37 12:00: the window pauses with 36h left and ends on day 39. |
| `late-batch-correction` | A reading taken on day 9 arrives on day 20, after the sensor went dormant: one correction from dormant to active. |
| `ignored-stop` | A stop goes unacknowledged (`stop_failed`), a late ack arrives, and readings taken while stopped raise `collecting_after_stop`. |

**Every story starts with `/test/reset`, which empties every table.** Run it only against a server whose data you don't need. The server must run with `TEST_MODE=1` (the compose default). The stories also run in the test suite, against Django's live test server (`tests/test_simulator.py`).
