# Decisions

## State and time model

Each entity keeps its current state on its row: a gateway's `status` and `command_state` (its `coverage_class` is derived from both), a sensor's `lifecycle` and reason, `coverage` and `collection`, a batch's `processing`. Every change of any axis appends a `TimelineEntry` (per-entity `seq`, `effective_at`, `recorded_at`); entries are never edited.

**Gateways** move forward through a state machine driven by evidence and timers. They are never recomputed backwards.

**Sensors** are a replay. Their lifecycle is a pure function, recomputed from creation to now over their evidence, coverage history, decommission and the configuration in force at each moment. The stored fields are a cache. After every relevant event, `reconcile` compares the replay with the recorded history and appends only what changed.

**Time** is read only through `core.clock.now()`, which is the test clock in TEST_MODE (a test enforces this). There are three clocks: the device's event time, the server's received time, and a batch's processed time (its attempt's due time). A transition is effective at the evidence's event time, a timer's due time, or the server clock for operator actions, coverage and configuration changes. It is recorded at the server clock.

**Background work** is a database-polled loop rather than Celery or RQ: nothing to install, and every due item is a row with a due time. Engine modules register *sources* in `core.tick`: batches and retries, the stale timer, command timeouts, and each sensor's `reconcile_at`. `tick(now)` runs the earliest due item, in its own transaction, effective at its own due time, until nothing is due. Ties go batches, then gateways, then sensors. `manage.py run_worker` calls it every 2 seconds. In TEST_MODE only `/test/clock` and `/test/drain` call it, so a clock jump applies every transition at its own time.

## Where each rule lives

| Rules | Code |
|---|---|
| Clock, timeline, threshold versions, due work | `core/clock.py`, `core/timeline.py`, `core/config.py`, `core/tick.py` |
| Heartbeat and cycle ingest, request order | `gateways/ingest.py` |
| Gateway transitions, stale timer, coverage recompute | `gateways/state.py`, `gateways/coverage.py` |
| Operator actions | `gateways/actions.py` |
| Stop and resume, acks, timeouts, stop periods, `collecting_after_stop` | `gateways/commands.py` |
| Batch receipt, validation, quarantine, retries, duplicates | `batches/services.py`, `batches/processing.py` |
| Sensor days, available time, latest collection, lifecycle | `sensors/engine/days.py`, `availability.py`, `collection.py`, `replay.py` |
| Loading evidence; recording transitions and corrections | `sensors/engine/evidence.py`, `reconcile.py` |
| Threshold changes (`rule_change`) | `core/rule_changes.py` |
| Console API, dashboard, OpenAPI | `gateways/views.py`, `sensors/views.py`, `core/dashboard.py`, `core/openapi.py` |

Every rule of the brief is mapped to its tests in [docs/conformance.md](docs/conformance.md).

## Retries, late data and corrections

**Repeats.** Each gateway request is one transaction under a lock on the gateway row. Unique keys back each idempotency rule: cycle per gateway, batch id, reading id, and heartbeat `(sent_at, session)`. An identical repeat returns 200 and changes nothing; the same id with another body is 409; the first ack wins. Concurrent duplicates are tested from threads.

**Batches.** A `PUT` only stores the batch (202 at once); `tick` processes it. Each attempt runs in a savepoint and its outcome is applied only on success, so a retry never double-counts. Attempt k waits 2^(k-1) minutes, and the fifth failure quarantines the batch as `processing_failed`. Workers don't claim with `SKIP LOCKED`. Instead each due item re-checks under its row lock that it is still due, so two workers do it once.

**Late data.** A gateway's `last_qualifying_at` only moves forward, and its status is never recomputed. A sensor is replayed on every evidence event. If the replay extends the recorded history, the new steps are appended. If a past step differs, one `correction` entry is appended: effective where the histories diverge, holding the previous and corrected states, the recomputed transitions and the evidence id. Earlier entries stay, and `lifecycle_since` comes from the replay. A reading id is global: the first processed version wins, a same-content repeat is ignored, and different content is quarantined.

## Interpretations

The ones that change observable behaviour most. All 49, with reasons, are in [docs/interpretations.md](docs/interpretations.md).

- **Transition times.** Evidence-driven transitions take effect at the evidence's event time, never before the current `status_since`, so timelines stay ordered.
- **Batches.** An unknown sensor or an empty `readings` list is accepted (202) and then quarantined (`unknown_sensor`, `empty_batch`), not rejected with 404 or 422. Per-reading problems are quarantined with a reason; only a malformed body is 422.
- **Future timestamps.** A heartbeat, cycle or ack more than 5 minutes ahead is 422 `timestamp_in_future`.
- **Ignored results.** Only results for sensors the gateway currently covers are recorded, and only those can qualify it.
- **Old auth failures.** An auth failure not after `last_qualifying_at` doesn't disconnect, matching how unsuspend compares the two.
- **Retrying commands.** Stop while `stop_failed` and resume while `resume_failed` issue a fresh command (neither is in the brief's table nor its 409 list). Resume while `resume_pending` is 409.
- **Stop periods.** Every acked stop opens one; the ack of the next resume closes it. Only a reading in the open period raises `collecting_after_stop`; one in a past period is recorded only.
- **Readings under coverage `none`** don't wake a sensor.
- **Coverage history** is the sensor's recorded coverage transitions (server clock), not one rebuilt from gateway event times.
- **Collection.** A `readings` outcome whose batch is still pending shows as `readings`. "Within 24 hours" includes exactly 24 hours, so a gateway reporting every 24 hours never flaps.
- **Thresholds** change through `GET`/`PUT /api/v1/config` (the brief names no endpoint). Waits and windows keep the length they started with, the stale timer uses the value in force when it falls due, and nothing past is corrected.
- **The worked example vs the stale rule.** Reporting once a day would make G stale every night under the 12-hour rule. We apply the rule as written; our end-to-end run keeps G connected with keep-alive cycles for a second sensor.

## Trade-offs and compromises

- **503 and `Retry-After`** are not implemented: the server never sheds load. The brief allows this compromise.
- **Replay cost.** Each event replays the sensor's whole history. That is simple and always consistent, but linear in evidence. A long-lived system would checkpoint the replay. A threshold change replays every sensor synchronously.
- **One worker loop**, polling every 2 seconds. It is safe with two workers, but there's no queue and no backpressure.
- **Console.** Pages poll every 5 seconds with a small hook (no SWR) and use inline forms rather than dialogs, in a light theme. Filters cover gateway status and sensor lifecycle only; there's no sorting or pagination, and the timeline is a plain list. There are no UI tests: the console is typechecked, linted, built, and checked by hand against simulator data.

## Change request

No change request had arrived when this was written; issue #17 is reserved for it.

## Known issues

None known.
