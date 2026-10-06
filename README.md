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
