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

## Trade-offs and compromises
_TBD_

## Known issues
_TBD_
