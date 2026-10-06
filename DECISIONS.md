# Decisions

> Two pages max. Filled in as each branch lands; finalised in `docs/handin` (#21).

## State and time model
_TBD_

## Where each rule lives
_TBD_

## Retries, late data and corrections
_TBD_

## Interpretations
_Every ambiguity in the brief gets one line here: what the brief says, what we chose, why._

- **Test clock before it is set.** In TEST_MODE, until the first `POST /test/clock`, `now()` falls back to wall time without storing it; the first set accepts any value. Setting the same time again is allowed (not "backwards").
- **Timeline `detail`.** Entries carry the fixed fields plus one extra, `detail` (null unless needed): a correction's recomputed transitions, an action's reason. Extra keys don't break the fixed shape.
- **Error codes.** Bodies that fail validation are `invalid_body`, malformed JSON `invalid_json` (both 422); specific conflicts keep the brief's names (`cycle_conflict`, `batch_conflict`), others get descriptive snake_case codes.
- **Timeline response.** `GET …/timeline` returns a bare JSON array of entries, oldest first (the brief wraps only `/gw/v1/commands` in an object).
- **`spare` coverage class.** Not in the brief's table. A spare gateway covers no sensors (that is `mark_spare`'s precondition), so its class never affects a sensor; we report `recoverable`.
- **Coverage on a decommissioned sensor.** "Any later action returns 409" is read as the sensor actions endpoint. Coverage can still be edited; it never changes a decommissioned lifecycle.
- **Gateway tokens.** Only a SHA-256 hash is stored; the token is shown once, at registration.
- **`cycle_id` scope.** Unique per gateway (the brief calls only `batch_id` globally unique). "Identical body" means the same canonical JSON (sorted keys).
- **Future device timestamps on heartbeats and cycles.** A `sent_at`, `started_at` or `finished_at` more than 5 minutes after the received time makes the whole request 422 `timestamp_in_future` (readings, by contrast, are quarantined one by one).
- **Cycle body checks.** `finished_at` before `started_at`, or the same sensor twice in `results`, is 422. `"batch_id": null` counts as absent.
- **Ignored results.** A result is ignored when the gateway has no current assignment for that sensor at the received time, including unknown sensor ids. Ignored results are not stored.
- **Heartbeat retries.** The same `(sent_at, session)` from the same gateway is one heartbeat; `last_heartbeat_at` only moves forward.
- **Work due at the same instant.** `tick()` runs the earliest due item first; ties run in source order: batches and retries, then gateway timers, then sensor timers. Each item runs in its own transaction with its due time as `effective_at`; `recorded_at` is the server clock.
- **Test endpoint responses.** `/test/clock` and `/test/drain` return 200 `{"now"}`; `/test/reset` and `/test/faults` return 204. `/test/reset` empties every project table, the clock included, so the next `/test/clock` accepts any time.
- **`/test/faults`.** `processing_failures` replaces any count left over; each failure is one processing attempt, consumed in order whatever the batch.
- **Batch body checks.** The PUT is 422 only for a malformed body (`sensor_id` not a string, `readings` not a list). Problems inside a reading are quarantined during processing with a reason: `missing_field`, `invalid_reading_id`, `invalid_value` (not a JSON number; booleans and numeric strings included), `wrong_unit`, `invalid_taken_at`, `timestamp_in_future`, `conflicting_duplicate`.
- **Unknown sensor in a batch.** The batch-processing rule wins over the general "unknown id → 404": the batch is accepted (202) and then quarantined with every reading listed as `unknown_sensor`.
- **Empty batch.** `readings: []` is accepted and then quarantined as `empty_batch`: it carries no reading to accept.
- **Batch for an uncovered sensor.** Accepted and processed: "readings are facts", whatever the coverage. Unlike cycle results, it is not ignored.
- **Processed time.** A batch is processed at its attempt's due time (its received time, or a retry time), so a clock jump never stamps it with the jump time.
- **When gateway transitions take effect.** Evidence-driven transitions are effective at the evidence's event time (a cycle's `finished_at`, a heartbeat's `sent_at`, a batch's latest accepted `taken_at`); the stale timer at `last_qualifying_at + 12h`; operator actions at the server clock. No transition is effective before the current `status_since`, so a gateway's timeline stays in order. Coverage changes caused by any of them use the server clock.
- **Late evidence for a stale gateway.** Evidence older than 12 hours doesn't reconnect it ("updates nothing"), but still moves `last_qualifying_at` forward if it is newer, per the late-data rule.
- **Old auth failures.** An auth failure whose event time is not after `last_qualifying_at` doesn't disconnect, matching how unsuspend compares the two. It still updates the latest auth failure.
- **Qualifying cycles.** Only recorded results count: a cycle whose `readings`/`no_readings` results are all for sensors the gateway doesn't cover (ignored) does not qualify.
- **First evidence that is already old.** It connects a new gateway at its event time; if that is more than 12 hours ago the gateway goes stale at once, effective at `last_qualifying_at + 12h`.
- **Spare and suspended gateways.** Automatic rules never change them; timestamps keep updating. Unsuspending a gateway that never had qualifying evidence gives `new`, also if it was spare before.
- **Unsuspend into disconnected.** `disconnected_since` becomes the event time of the first auth failure after `last_qualifying_at`.
- **Repeated gateway actions.** 409 for suspend while suspended (`already_suspended`), unsuspend while not suspended (`not_suspended`), mark_spare outside `new` (`illegal_transition`) or while covering sensors (`gateway_covers_sensors`), and any action on a retired gateway (`gateway_retired`). A reason is optional except for suspend.
- **Stop while `stop_failed`, resume while `resume_failed`.** Neither is in the table or the 409 list. Both are allowed: they issue a fresh command that supersedes the failed one, which is how an operator retries. Resume while `resume_pending` is 409, mirroring stop while `stop_pending`.
- **Commands on suspended gateways.** Allowed: command state is its own axis. On a retired gateway every action, stop and resume included, is 409.
- **When command transitions take effect.** Issuing at the server clock; an ack at its `acked_at`, never before `command_state_since` (so a late ack after a timeout is effective no earlier than the failure); a timeout at `issued_at + 10 min`. Acks repeat safely: the first `acked_at` wins and a repeat changes nothing.
- **Stop periods.** Every acked stop opens one, superseded or not: the gateway did stop. It is closed by the ack of the first resume issued after that stop. A period includes both its ends.
- **`collecting_after_stop`.** Each accepted reading inside any stop period writes a `flag` entry, effective at its `taken_at`. Only a reading in the current, open period raises the flag; one in a past period is recorded only. A stop acked late also checks readings already accepted. The flag clears when a resume ack closes the open period.
- **A batch arriving after its 24h deadline.** At the deadline the readings outcome resolves as `could_not_read`; a later arrival doesn't reopen that. Its accepted readings still make reading days, so the replay corrects the sensor from their `taken_at`.
- **A readings outcome resolved as processed.** It doesn't make its cycle's day a reading day by itself: only an accepted reading taken that day does. A day decided late (its batch resolved after midnight) counts from that resolution time.
- **Stale threshold.** The stale timer uses the threshold in force at `last_qualifying_at` (thresholds can't change yet; #23).
- **Duplicate readings.** A repeat of an accepted reading with the same content (sensor, `taken_at`, value, unit) is ignored: not counted, not quarantined. Batches are processed in received order, so "the first processed version" is the first received. A batch whose readings are all ignored repeats ends `processed` with `accepted_count` 0.
- **Coverage history for the engine.** The sensor's coverage history is read from its recorded coverage transitions, timed by the server clock as the brief requires for coverage changes, rather than rebuilt from gateway transitions (which use event times). A gateway's class history, used for quiet days, comes from its status and command state transitions.
- **Collection while a batch is pending.** A `readings` outcome whose batch hasn't resolved yet shows as `readings` (the gateway reported readings and the batch still has time); it turns `could_not_read` if the batch is missing at its deadline or ends quarantined. Two outcomes from one gateway at the same instant are decided by precedence. "Within the last 24 hours" excludes exactly 24 hours ago, so the value changes at the moment `tick` re-evaluates it.
- **The lifecycle is a replay.** The sensor's lifecycle is recomputed from creation to now by a pure function over its evidence, coverage history, operator actions and the configuration in force; the stored fields are a cache. Days are evaluated at 00:00 after them, but only once every earlier day is decided, so an unresolved day holds back all later counting.
- **Readings under coverage `none`.** They don't wake the sensor: the coverage table keeps `pending` and retires everything else while coverage is `none`.
- **Coverage loss on `retired (no_readings)`.** It is "any other state", so the reason becomes `no_live_coverage` (and regaining coverage then makes it `pending`).
- **Which thresholds apply.** A dormant wait or sampling window uses the configuration in force when it starts; the quiet-day threshold and the cycle limit use the one in force when they are evaluated.
- **`quiet_checked_days` outside active.** It keeps its value while dormant or sampling and resets on a reading or on entering `pending`. A reading resets it at the reading's time.
- **A window waiting on a batch.** A sampling window whose `[start, end)` holds a `readings` outcome with an unresolved batch is evaluated only once that batch resolves; the transition is still effective at the window end.

## Trade-offs and compromises
_TBD_

## Known issues
_TBD_
