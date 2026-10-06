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
- **Duplicate readings.** A repeat of an accepted reading with the same content (sensor, `taken_at`, value, unit) is ignored: not counted, not quarantined. Batches are processed in received order, so "the first processed version" is the first received. A batch whose readings are all ignored repeats ends `processed` with `accepted_count` 0.

## Trade-offs and compromises
_TBD_

## Known issues
_TBD_
