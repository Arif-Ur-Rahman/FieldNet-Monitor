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

## Trade-offs and compromises
_TBD_

## Known issues
_TBD_
