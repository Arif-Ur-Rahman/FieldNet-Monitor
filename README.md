# FieldNet Monitor

Server, state engine and operator console for a sensor network whose devices are unreliable. Every gateway's and sensor's situation is computed from the evidence the devices send, moved between situations by the brief's rules, and exposed through an API and a console.

| Path | What |
|---|---|
| `backend/` | Django + DRF + PostgreSQL: the fixed API, the gateway state machine, the sensor engine, the background worker |
| `frontend/` | Next.js + TypeScript operator console |
| `simulator/` | CLI that plays gateway failure stories through the API and the test clock |
| `docs/` | [conformance.md](docs/conformance.md) (every brief rule → its tests), [interpretations.md](docs/interpretations.md) (every ambiguity and what we chose) |

[DECISIONS.md](DECISIONS.md) explains the design; [AI.md](AI.md) how AI tools were used.

## Run

```bash
make up      # docker compose up: Postgres, API (:8000), worker, console (:3000)
make test    # the backend test suite, in Docker
make sim     # the simulator stories, against the stack from `make up`
```

- Console: http://localhost:3000
- API docs (OpenAPI): http://localhost:8000/api/docs/
- Postgres is published on :5433 for inspection.

The stack runs with `TEST_MODE=1` by default, so the test endpoints (`/test/*`) are on and background work runs only when `/test/clock` or `/test/drain` is called. For a real run, `TEST_MODE=0 make up`: the worker then processes due work every 2 seconds on the wall clock. `.env.example` lists the override.

## Tests

`make test` (Docker) or `make test-local` (below) runs the whole suite. It includes:
- every row of the brief's transition tables;
- the worked example and its three variations, end to end through the API;
- idempotency and concurrency (identical requests from threads, two workers on one batch);
- the simulator stories, against Django's live test server;
- a check that the OpenAPI schema validates.

[docs/conformance.md](docs/conformance.md) maps each rule to its tests, and a test checks every test it cites exists.

## Simulator

`simulator/sim.py` plays failure stories through the fixed API and the test clock. Each ends in assertions; the exit code is 0 if every story passed, 1 if one failed, 2 if the server can't run them.

```bash
make sim                      # every story
make sim STORY=ignored-stop   # one story
python simulator/sim.py --list
```

| Story | What happens |
|---|---|
| `ghost-heartbeat` | A gateway keeps heartbeating but stops collecting: it goes stale 12h after its last qualifying evidence, and its sensor shows `not_checked`. |
| `auth-flap-mid-sampling` | Credentials fail at day 30 12:00 during a sampling window and recover at day 37 12:00: the window pauses with 36h left and ends on day 39. |
| `late-batch-correction` | A reading taken on day 9 arrives on day 20, after the sensor went dormant: one correction from dormant to active. |
| `ignored-stop` | A stop goes unacknowledged (`stop_failed`), a late ack arrives, and readings taken while stopped raise `collecting_after_stop`. |

**Every story starts with `/test/reset`, which empties every table.** Run it only against a server whose data you don't need, with `TEST_MODE=1`.

## Console

- **Dashboard**: situation counts for every gateway, sensor and batch axis.
- **Fleet**: each gateway's status and how long it has held it, last heartbeat next to last qualifying evidence, command state, coverage class and flags. Operator actions (suspend, unsuspend, mark spare, stop, resume, retire) take a reason inline.
- **Sensors**: lifecycle, reason, collection, coverage, counters and next evaluation as separate columns. Decommission takes a required reason.
- Click any gateway or sensor id for its **timeline**; corrections show their recomputed history.

Durations follow the server clock (the `X-Server-Now` response header), so in TEST_MODE they follow the test clock. Healthy, zero, unknown, paused and not-checked each look different, and every page has a legend.

## Without Docker

Postgres 16, Python 3.12 and Node 22:

```bash
cd backend && python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt -r requirements-dev.txt
createdb fieldnet && TEST_MODE=1 .venv/bin/python manage.py migrate
TEST_MODE=1 .venv/bin/gunicorn fieldnet.wsgi -b :8000      # the API
TEST_MODE=0 .venv/bin/python manage.py run_worker           # the worker (needed with TEST_MODE=0 only)
cd ../frontend && npm ci && API_URL=http://localhost:8000 npm run dev   # the console on :3000
```

| Command | What |
|---|---|
| `make test-local` | The test suite against local Postgres |
| `make sim-local` | The simulator against the API on :8000 (wipes its database: see above) |
| `make lint` / `make fmt` | Ruff on the backend and the simulator |
| `make lint-web` | Typecheck and lint the console |
