# Conformance: the brief, rule by rule

Every rule in the brief, in the brief's order, with the tests that cover it. Test ids are relative to `backend/tests/` (`file::Class::test`). Rules the brief lets us skip are listed at the end with where the compromise is documented. `tests/test_conformance.py::test_cited_tests_exist` keeps this table honest.

## Situations

| Rule | Tests |
|---|---|
| Axis values are the exact strings the API returns | `test_conformance.py::TestExactStrings::test_gateway_status`, `::test_gateway_command_state`, `::test_coverage`, `::test_sensor_lifecycle`, `::test_sensor_collection`, `::test_batch_processing` |
| Lifecycle reason: `no_readings`/`no_live_coverage` when retired, the operator's text when decommissioned, else null | `test_engine_replay.py::TestWorkedExample::test_second_window_retires_it`, `test_sensor_engine.py::TestCoverage::test_losing_all_coverage_retires_it_at_once`, `test_sensor_engine.py::TestDecommission::test_still_terminal_through_the_engine` |
| Every change of any axis appends a timeline entry | `test_timelines.py::test_gateway_timeline`, `test_timelines.py::test_sensor_timeline`, `test_timelines.py::test_batch_timeline` |
| Entries are never edited or deleted | `test_core.py::TestTimeline::test_entries_are_append_only` |

## Time and evidence

| Rule | Tests |
|---|---|
| A device timestamp more than 5 minutes after its received time is invalid | `test_ingest.py::TestHeartbeat::test_more_than_5_minutes_ahead_is_422`, `test_ingest.py::TestCycle::test_finished_more_than_5_minutes_ahead_is_422`, `test_batches.py::TestProcessing::test_some_invalid_readings_make_it_partially_processed`, `test_commands.py::TestAcks::test_acked_at_more_than_5_minutes_ahead_is_422` |
| `last_heartbeat_at` is the received time of the latest heartbeat | `test_ingest.py::TestHeartbeat::test_records_and_sets_last_heartbeat_at_to_received_time`, `test_ingest.py::TestHeartbeat::test_late_heartbeat_does_not_move_last_heartbeat_at_back` |
| `last_qualifying_at`, the 12-hour stale rule, `disconnected_since` and recovery use event time | `test_gateway_states.py::TestNewToConnected::test_qualifying_cycle_connects_at_its_finished_at`, `test_gateway_states.py::TestConnectedToStale::test_twelve_hours_after_last_qualifying_at`, `test_gateway_states.py::TestToDisconnected::test_auth_failed_cycle_disconnects_at_its_finished_at`, `test_gateway_states.py::TestDisconnectedToConnected::test_qualifying_evidence_after_disconnected_since_reconnects` |
| Sensor days, quiet counts, wake-ups and sampling checks use event time | `test_engine_days.py::TestRules::test_reading_day`, `test_engine_replay.py::TestReadingsWake::test_dormant`, `test_worked_example.py::TestWorkedExample::test_the_full_run` |
| Operator actions, coverage changes, configuration changes and command timeouts use the server clock | `test_gateway_states.py::TestUnsuspend::test_connected_when_last_qualifying_is_within_12_hours`, `test_gateway_states.py::TestNewToConnected::test_coverage_of_covered_sensors_follows`, `test_config_changes.py::TestEndpoint::test_change_takes_effect_now_and_keeps_the_rest`, `test_commands.py::TestStopPendingToStopFailed::test_no_ack_within_10_minutes` |
| Each timeline entry carries `effective_at` and `recorded_at` (server clock) | `test_core.py::TestTimeline::test_recorded_at_comes_from_the_clock`, `test_tick.py::TestClockEndpoint::test_jump_applies_each_item_at_its_own_due_time` |
| Qualifying: an `ok` cycle with a `readings` or `no_readings` outcome, at `finished_at` | `test_gateway_states.py::TestNewToConnected::test_qualifying_cycle_connects_at_its_finished_at`, `test_gateway_states.py::TestNewToConnected::test_readings_outcome_qualifies_too`, `test_gateway_states.py::TestNewToConnected::test_cycle_without_readings_or_no_readings_does_not_qualify` |
| Qualifying: a batch ending processed or partially processed with an accepted reading, at its latest accepted `taken_at` | `test_gateway_states.py::TestNewToConnected::test_processed_batch_qualifies_at_its_latest_accepted_taken_at`, `test_conformance.py::TestQualifyingEvidence::test_a_partially_processed_batch_qualifies` |
| Heartbeats, batches still received or retrying, and `auth_failed` cycles never qualify | `test_gateway_states.py::TestNewToConnected::test_heartbeats_never_qualify`, `test_conformance.py::TestQualifyingEvidence::test_a_batch_still_retrying_never_qualifies`, `test_gateway_states.py::TestNewToConnected::test_quarantined_batch_does_not_qualify`, `test_gateway_states.py::TestToDisconnected::test_auth_failed_cycle_disconnects_at_its_finished_at` |
| Days are UTC dates, complete at 00:00 the next day; only complete days count | `test_engine_days.py::TestClassifyDays::test_only_complete_days`, `test_engine_days.py::TestClassifyDays::test_a_day_is_complete_at_midnight` |
| Reading day: an accepted reading that day, from any gateway | `test_engine_days.py::TestRules::test_reading_day`, `test_engine_days.py::TestRules::test_reading_from_another_day_does_not_count` |
| Unresolved: a `readings` outcome whose batch hasn't resolved (processed, partially processed, quarantined, or 24h after `finished_at` without arriving) | `test_engine_days.py::TestBatchResolution::test_unarrived_batch_is_unresolved_until_the_deadline`, `test_engine_days.py::TestBatchResolution::test_processed_batch_resolves_at_its_processed_time`, `test_engine_days.py::TestBatchResolution::test_received_but_still_processing_is_unresolved_with_no_known_end` |
| A quarantined or missing batch turns the outcome into `could_not_read` | `test_engine_days.py::TestBatchResolution::test_missing_batch_becomes_could_not_read_at_the_deadline`, `test_engine_days.py::TestBatchResolution::test_quarantined_batch_is_could_not_read`, `test_engine_collection.py::TestBatches::test_quarantined_batch_is_could_not_read` |
| Quiet day: a `no_readings` outcome from a gateway whose class was available then | `test_engine_days.py::TestRules::test_quiet_day`, `test_engine_days.py::TestRules::test_quiet_needs_an_available_gateway_at_finished_at`, `test_engine_days.py::TestRules::test_one_available_gateway_is_enough` |
| Unchecked: everything else, including `could_not_read`, `timed_out` and silence | `test_engine_days.py::TestRules::test_could_not_read_and_timed_out_are_unchecked`, `test_engine_days.py::TestRules::test_silence_is_unchecked` |
| First match wins | `test_engine_days.py::TestFirstMatchWins::test_reading_beats_unresolved`, `test_engine_days.py::TestFirstMatchWins::test_unresolved_beats_quiet`, `test_engine_days.py::TestFirstMatchWins::test_quiet_beats_unchecked` |
| An evaluation that depends on an unresolved day waits until it resolves | `test_engine_replay.py::TestVariationUnresolvedDay::test_day_14_blocks_while_unresolved`, `test_engine_replay.py::TestSamplingWindows::test_window_waits_for_an_unresolved_readings_outcome_inside_it` |
| Waits and windows run in available time and pause when coverage isn't available | `test_engine_availability.py::TestAvailableTime::test_add_available_skips_unavailable_time`, `test_engine_replay.py::TestCoverage::test_dormant_wait_pauses_while_not_available` |
| `next_evaluation_at` is when the wait or window ends if coverage stays available; null while paused | `test_engine_availability.py::TestAvailableTime::test_next_evaluation_at_is_null_while_paused`, `test_worked_example.py::TestDisconnectionMidWindow::test_window_pauses_with_36_hours_left_and_ends_on_day_39` |
| Latest collection: each available gateway's most recent outcome within 24h, by precedence | `test_engine_collection.py::TestLatestPerGateway::test_only_the_most_recent_outcome_of_a_gateway_counts`, `test_engine_collection.py::TestLatestPerGateway::test_older_than_24_hours_does_not_count`, `test_engine_collection.py::TestLatestPerGateway::test_only_available_gateways_count`, `test_engine_collection.py::TestPrecedenceAcrossGateways::test_best_outcome_wins` |
| No qualifying outcome: `collection_stopped` if coverage is stopped, else `not_checked` | `test_engine_collection.py::TestCoverage::test_stopped_coverage_is_collection_stopped`, `test_engine_collection.py::TestCoverage::test_available_with_nothing_qualifying_is_not_checked`, `test_engine_collection.py::TestCoverage::test_other_coverage_is_not_checked` |
| A reading from a batch no cycle mentions counts as a `readings` outcome at its `taken_at` | `test_engine_collection.py::TestUnmentionedReadings::test_count_as_a_readings_outcome_from_their_gateway`, `test_engine_collection.py::TestUnmentionedReadings::test_timed_at_taken_at` |

## Coverage

| Rule | Tests |
|---|---|
| Gateway coverage class from status and command state (every cell) | `test_conformance.py::TestGatewayCoverageClassTable::test_cell` |
| Sensor coverage: the best class among covering gateways; none if all are dead or none assigned | `test_registry.py::TestCoverage::test_best_class_wins`, `test_registry.py::TestCoverage::test_replacing_with_empty_set_gives_none`, `test_sensor_engine.py::TestCoverage::test_suspending_the_only_gateway_retires_it_at_once` |
| Coverage `stopped`: collection `collection_stopped`, lifecycle unchanged, readings still wake it, timers paused | `test_commands.py::TestStopPendingToStopped::test_ack_stops_it_at_acked_at`, `test_engine_replay.py::TestCoverage::test_readings_wake_under_stopped_or_recoverable_coverage` |
| Coverage `recoverable`: `not_checked`, lifecycle unchanged, readings still wake it, timers paused | `test_worked_example.py::TestDisconnectionMidWindow::test_window_pauses_with_36_hours_left_and_ends_on_day_39`, `test_engine_replay.py::TestCoverage::test_readings_wake_under_stopped_or_recoverable_coverage` |
| Coverage `none`: `pending` and `decommissioned` stay; anything else is `retired (no_live_coverage)` at once | `test_engine_replay.py::TestCoverage::test_loss_retires_with_no_live_coverage_at_once`, `test_engine_replay.py::TestCoverage::test_pending_stays_pending`, `test_sensor_engine.py::TestCoverage::test_losing_all_coverage_retires_it_at_once` |
| Recompute coverage when a gateway's status or command state, or a sensor's assignment, changes | `test_gateway_states.py::TestNewToConnected::test_coverage_of_covered_sensors_follows`, `test_commands.py::TestResumePendingToRunning::test_ack_resumes`, `test_registry.py::TestCoverage::test_assigning_a_new_gateway_gives_recoverable` |
| A `retired (no_live_coverage)` sensor becomes `pending` as soon as coverage isn't none (reassignment, a gateway leaving suspended); counters reset | `test_sensor_engine.py::TestCoverage::test_regaining_coverage_makes_it_pending`, `test_conformance.py::test_a_covering_gateway_leaving_suspended_makes_a_retired_sensor_pending`, `test_worked_example.py::TestCoverage::test_loss_retires_and_reassignment_makes_it_pending` |
| Request order: gateway, then coverage, then sensors (a stale gateway's first good cycle counts as a check) | `test_conformance.py::TestRequestOrder::test_a_stale_gateways_first_good_cycle_counts_as_a_check` |

## Gateway transitions

| From → to | Tests |
|---|---|
| new → connected on qualifying evidence | `test_gateway_states.py::TestNewToConnected::test_qualifying_cycle_connects_at_its_finished_at` |
| new → spare by `mark_spare`, only when covering no sensors (else 409) | `test_gateway_states.py::TestNewToSpare::test_mark_spare_when_it_covers_no_sensors`, `test_gateway_states.py::TestNewToSpare::test_409_while_it_covers_sensors` |
| spare → new when a sensor is assigned | `test_gateway_states.py::TestSpareToNew::test_assigning_a_sensor_makes_it_new`, `test_registry.py::TestCoverage::test_spare_gateway_becomes_new_when_assigned` |
| connected → stale 12h after `last_qualifying_at` | `test_gateway_states.py::TestConnectedToStale::test_twelve_hours_after_last_qualifying_at`, `test_gateway_states.py::TestConnectedToStale::test_heartbeats_do_not_keep_it_connected` |
| stale → connected on evidence from the last 12h; older late evidence updates nothing | `test_gateway_states.py::TestStaleToConnected::test_evidence_from_the_last_12_hours_reconnects`, `test_gateway_states.py::TestStaleToConnected::test_older_late_evidence_changes_no_status` |
| new, connected, stale → disconnected on `auth_failed`; later failures keep the first time | `test_gateway_states.py::TestToDisconnected::test_auth_failed_heartbeat_disconnects`, `test_gateway_states.py::TestToDisconnected::test_auth_failed_cycle_disconnects_at_its_finished_at`, `test_gateway_states.py::TestToDisconnected::test_later_failures_keep_the_first_time` |
| disconnected → connected on evidence after `disconnected_since`; not an ok heartbeat, not an old batch re-sent | `test_gateway_states.py::TestDisconnectedToConnected::test_qualifying_evidence_after_disconnected_since_reconnects`, `test_gateway_states.py::TestDisconnectedToConnected::test_ok_heartbeat_is_not_enough`, `test_gateway_states.py::TestDisconnectedToConnected::test_old_batch_resent_after_the_failure_is_not_enough` |
| any but retired → suspended with a reason; automatic rules stop, timestamps keep updating | `test_gateway_states.py::TestSuspend::test_suspend_from_any_status_but_retired`, `test_gateway_states.py::TestSuspend::test_reason_is_required`, `test_gateway_states.py::TestSuspend::test_automatic_rules_do_not_change_it_but_timestamps_keep_updating` |
| suspended → derived status on unsuspend (disconnected, connected, stale, new) | `test_gateway_states.py::TestUnsuspend::test_disconnected_when_the_latest_auth_failure_is_newer`, `test_gateway_states.py::TestUnsuspend::test_connected_when_last_qualifying_is_within_12_hours`, `test_gateway_states.py::TestUnsuspend::test_stale_when_last_qualifying_is_older`, `test_gateway_states.py::TestUnsuspend::test_new_when_there_was_never_qualifying_evidence` |
| any → retired, terminal; later gateway requests get 403 and change nothing | `test_gateway_states.py::TestRetire::test_retire_from_any_status`, `test_gateway_states.py::TestRetire::test_terminal`, `test_gateway_states.py::TestRetire::test_later_gateway_requests_are_403_and_change_nothing` |
| A new gateway with no evidence stays new | `test_gateway_states.py::TestNewToConnected::test_a_new_gateway_without_evidence_stays_new` |

## Stop and resume

| Rule | Tests |
|---|---|
| Commands are ordered per gateway; the latest is the desired state | `test_commands.py::TestToResumePending::test_operator_resume_supersedes_the_stop`, `test_commands.py::TestResumeToStopPending::test_operator_stop_supersedes_the_resume` |
| `GET /gw/v1/commands` returns only the latest command, while unacknowledged | `test_commands.py::TestRunningToStopPending::test_operator_stop`, `test_commands.py::TestStopPendingToStopped::test_ack_stops_it_at_acked_at`, `test_commands.py::TestStopPendingToStopFailed::test_failed_command_is_still_served_until_acknowledged` |
| An ack of a superseded command is accepted (204) and recorded, but changes nothing | `test_commands.py::TestAcks::test_ack_of_a_superseded_command_is_recorded_only` |
| running → stop_pending (operator stop) | `test_commands.py::TestRunningToStopPending::test_operator_stop` |
| stop_pending → stopped (ack) | `test_commands.py::TestStopPendingToStopped::test_ack_stops_it_at_acked_at` |
| stop_pending → stop_failed (no ack within 10 minutes, server clock) | `test_commands.py::TestStopPendingToStopFailed::test_no_ack_within_10_minutes` |
| stop_failed → stopped (late ack of the latest stop) | `test_commands.py::TestStopFailedToStopped::test_late_ack_of_the_latest_stop` |
| stop_pending, stopped, stop_failed → resume_pending (operator resume) | `test_commands.py::TestToResumePending::test_operator_resume_supersedes_the_stop` |
| resume_pending → running (ack) | `test_commands.py::TestResumePendingToRunning::test_ack_resumes` |
| resume_pending → resume_failed (no ack within 10 minutes) | `test_commands.py::TestResumePendingToResumeFailed::test_no_ack_within_10_minutes` |
| resume_failed → running (late ack) | `test_commands.py::TestResumeFailedToRunning::test_late_ack_of_the_latest_resume` |
| resume_pending, resume_failed → stop_pending (operator stop) | `test_commands.py::TestResumeToStopPending::test_operator_stop_supersedes_the_resume` |
| Stop while stop_pending or stopped, and resume while running, are 409 | `test_commands.py::TestIllegal::test_stop_while_stop_pending_or_stopped_is_409`, `test_commands.py::TestIllegal::test_resume_while_running_is_409` |
| A reading taken inside a stop period is kept and counted, raises `collecting_after_stop` and adds an entry | `test_commands.py::TestCollectingAfterStop::test_reading_inside_the_stop_period_raises_the_flag` |
| The flag shows while the current stop period has such readings and clears on a resume ack | `test_commands.py::TestCollectingAfterStop::test_resume_ack_clears_it`, `test_commands.py::TestCollectingAfterStop::test_resume_issued_but_not_acked_keeps_the_period_open` |
| Readings before the stop's ack or after the resume's ack never raise it | `test_commands.py::TestCollectingAfterStop::test_reading_before_the_stop_ack_does_not`, `test_commands.py::TestCollectingAfterStop::test_reading_after_the_resume_ack_does_not_raise_it` |

## Sensor transitions

| From → to | Tests |
|---|---|
| pending → active at the first reading's `taken_at` | `test_engine_replay.py::TestWorkedExample::test_day_0_reading_makes_it_active`, `test_sensor_engine.py::TestForwardProgress::test_first_reading_makes_it_active` |
| active → dormant when the 14th quiet day since the last reading day completes; reading days reset, unchecked days don't count | `test_engine_replay.py::TestWorkedExample::test_quiet_days_count_as_each_day_completes`, `test_engine_replay.py::TestWorkedExample::test_dormant_when_day_14_completes`, `test_engine_replay.py::TestReadingsWake::test_reading_day_resets_the_quiet_count`, `test_engine_replay.py::TestVariationUnresolvedDay::test_unchecked_once_resolved_at_day_15_noon` |
| dormant → sampling after 14 days of available time | `test_engine_replay.py::TestWorkedExample::test_sampling_after_14_days_of_available_time` |
| sampling → active on a reading inside the window | `test_engine_replay.py::TestReadingsWake::test_sampling` |
| sampling → dormant at window end with a `no_readings` check and no reading (cycles + 1) | `test_engine_replay.py::TestWorkedExample::test_window_ends_with_checks_and_no_reading` |
| sampling → retired (no_readings) on the 2nd such window | `test_engine_replay.py::TestWorkedExample::test_second_window_retires_it` |
| sampling → sampling (new window) when the window saw no check; not a cycle | `test_engine_replay.py::TestSamplingWindows::test_window_without_checks_starts_a_new_window_and_is_not_a_cycle` |
| dormant, retired (no_readings) → active on a reading | `test_engine_replay.py::TestReadingsWake::test_dormant`, `test_engine_replay.py::TestReadingsWake::test_retired_no_readings` |
| any but decommissioned → decommissioned with a reason; terminal, later actions 409 | `test_registry.py::TestDecommission::test_decommission_is_terminal`, `test_engine_replay.py::TestDecommission::test_terminal`, `test_sensor_engine.py::TestDecommission::test_still_terminal_through_the_engine` |
| Counter resets: quiet days on reading days and entering pending; cycles on entering active or pending | `test_engine_replay.py::TestReadingsWake::test_reading_day_resets_the_quiet_count`, `test_engine_replay.py::TestReadingsWake::test_sampling`, `test_engine_replay.py::TestCoverage::test_regaining_coverage_makes_it_pending_with_counters_reset` |
| Same instant: decommission, loss of coverage, readings, then timers | `test_engine_replay.py::TestDecommission::test_wins_over_a_reading_at_the_same_instant`, `test_conformance.py::test_loss_of_coverage_comes_before_a_reading_at_the_same_instant`, `test_tick.py::test_lower_order_runs_first_on_ties_whatever_the_registration_order` |
| Thresholds are configuration (with the brief's defaults) | `test_core.py::TestConfig::test_defaults_without_versions`, `test_engine_replay.py::TestConfiguration::test_thresholds_come_from_the_config`, `test_config_changes.py::TestOnlyLaterBehaviourMoves::test_shortening_the_quiet_threshold_mid_run` |

## Late data and corrections

| Rule | Tests |
|---|---|
| The lifecycle is a deterministic function of evidence, coverage history, operator actions and configuration | `test_engine_replay.py::TestWorkedExample::test_one_replay_at_the_end_equals_stepping_through` |
| Recomputed history matches → nothing recorded | `test_sensor_engine.py::TestLateReadingCorrection::test_the_same_late_reading_again_records_nothing_more` |
| It differs → one correction entry (previous, corrected, recomputed transitions, evidence id); earlier entries stay | `test_sensor_engine.py::TestLateReadingCorrection::test_correction_from_dormant_to_active`, `test_worked_example.py::TestLateReading::test_correction_from_dormant_to_active_and_the_day_15_entry_stays` |
| After a correction, `lifecycle_since` is the latest recomputed transition's `effective_at` | `test_sensor_engine.py::TestLateReadingCorrection::test_correction_from_dormant_to_active` |
| A late reading moves every later timer; the sensor may still be dormant or sampling | `test_engine_replay.py::TestVariationLateReading::test_it_moves_every_later_timer` |
| Reading ids are global: first processed wins; same content ignored; different content `conflicting_duplicate` | `test_batches.py::TestDuplicates::test_the_first_processed_version_wins`, `test_batches.py::TestDuplicates::test_same_reading_again_is_ignored`, `test_batches.py::TestDuplicates::test_same_id_different_content_is_conflicting_duplicate` |
| Gateway status is not recomputed backwards; late evidence moves `last_qualifying_at` only forward | `test_gateway_states.py::TestStaleToConnected::test_late_evidence_older_than_last_qualifying_at_changes_nothing`, `test_gateway_states.py::TestStaleToConnected::test_older_late_evidence_changes_no_status` |

## Worked example

| Rule | Tests |
|---|---|
| Day 0 to day 49 | `test_worked_example.py::TestWorkedExample::test_the_full_run`, `test_engine_replay.py::TestWorkedExample::test_second_window_retires_it` |
| Disconnection mid-window (ends day 39, `not_checked` while paused) | `test_worked_example.py::TestDisconnectionMidWindow::test_window_pauses_with_36_hours_left_and_ends_on_day_39` |
| A late reading (correction dormant → active, day-15 entry stays) | `test_worked_example.py::TestLateReading::test_correction_from_dormant_to_active_and_the_day_15_entry_stays` |
| An unresolved day (dormant on day 16) | `test_worked_example.py::TestUnresolvedDay::test_dormant_only_after_another_quiet_day_completes` |

## The fixed API

| Rule | Tests |
|---|---|
| JSON bodies, ISO 8601 UTC times | `test_core.py::TestTimeutil::test_iso_uses_z`, `test_core.py::TestTimeline::test_serialized_shape` |
| Errors are `{"error", "detail"}`; invalid bodies 422, conflicts 409, unknown ids 404 | `test_core.py::TestErrors::test_validation_error_is_422_with_flat_detail`, `test_core.py::TestErrors::test_custom_codes`, `test_core.py::TestErrors::test_unknown_route_is_json_404`, `test_registry.py::TestGatewayRegistration::test_unknown_gateway_is_404` |
| Gateway API: unknown token 401, retired gateway 403 | `test_registry.py::TestGatewayAuth::test_unknown_or_missing_token_is_401`, `test_registry.py::TestGatewayAuth::test_retired_gateway_is_403`, `test_ingest.py::TestAuth::test_retired_gateway_is_403_and_changes_nothing` |
| `POST /gw/v1/heartbeat` → 204 | `test_ingest.py::TestHeartbeat::test_records_and_sets_last_heartbeat_at_to_received_time` |
| `POST /gw/v1/cycles` → 202 `{ignored}`; identical repeat 200; same id other body 409 `cycle_conflict` | `test_ingest.py::TestCycle::test_records_results_and_lists_ignored`, `test_ingest.py::TestCycle::test_identical_repeat_is_200_and_changes_nothing`, `test_ingest.py::TestCycle::test_same_id_different_body_is_409` |
| `batch_id` required for `readings`, absent otherwise; `auth_failed` records `could_not_read`; `timeout` shows as `timed_out` | `test_ingest.py::TestCycle::test_invalid_results_are_422`, `test_ingest.py::TestCycle::test_auth_failed_records_every_outcome_as_could_not_read`, `test_ingest.py::TestCycle::test_records_results_and_lists_ignored` |
| `PUT /gw/v1/batches/{id}` → 202 (processed in the background); identical 200; other body or gateway 409 `batch_conflict`; any order relative to its cycle | `test_batches.py::TestPut::test_stores_the_batch_as_received_without_processing_it`, `test_batches.py::TestPut::test_identical_repeat_is_200_and_changes_nothing`, `test_batches.py::TestPut::test_same_id_different_body_is_409`, `test_batches.py::TestPut::test_same_id_from_another_gateway_is_409`, `test_batches.py::TestMatchingCycles::test_batch_first_then_cycle` |
| `GET /gw/v1/commands` → `{"commands": [...]}` | `test_commands.py::TestRunningToStopPending::test_operator_stop` |
| `POST /gw/v1/commands/{id}/ack` → 204, idempotent; 404 if not this gateway's | `test_commands.py::TestAcks::test_repeat_is_204_and_changes_nothing`, `test_commands.py::TestAcks::test_another_gateways_command_is_404` |
| Every write is safe to repeat | `test_idempotency.py::TestReplays::test_heartbeat`, `test_idempotency.py::TestReplays::test_cycle`, `test_idempotency.py::TestReplays::test_batch_before_and_after_processing`, `test_idempotency.py::TestReplays::test_ack`, `test_idempotency.py::TestConcurrentDuplicates::test_cycles` |
| Invalid readings (missing field, non-numeric value, wrong unit, `taken_at` ahead) quarantined with a reason; units C / mm / m/s | `test_batches.py::TestProcessing::test_some_invalid_readings_make_it_partially_processed`, `test_batches.py::TestProcessing::test_units_follow_the_sensor_type` |
| Some invalid → partially_processed; all invalid or unknown sensor → quarantined | `test_batches.py::TestProcessing::test_some_invalid_readings_make_it_partially_processed`, `test_batches.py::TestProcessing::test_every_reading_invalid_quarantines_the_batch`, `test_batches.py::TestProcessing::test_unknown_sensor_quarantines_the_batch` |
| Processing failure → retrying, attempt k waits 2^(k-1) min; 5th failure → quarantined `processing_failed`; no double counting | `test_batches.py::TestRetries::test_failed_attempts_retry_with_backoff_then_succeed`, `test_batches.py::TestRetries::test_fifth_failure_quarantines_with_processing_failed`, `test_batches.py::TestRetries::test_a_crash_mid_attempt_leaves_nothing_behind` |
| `POST /api/v1/gateways` → 201 `{token}`; duplicate 409 | `test_registry.py::TestGatewayRegistration::test_register_returns_token_and_initial_state`, `test_registry.py::TestGatewayRegistration::test_duplicate_id_is_409` |
| `POST /api/v1/sensors` registers pending with no coverage | `test_registry.py::TestSensorRegistration::test_register_pending_with_no_coverage` |
| `PUT /api/v1/sensors/{id}/coverage` replaces the set; a retired gateway is 409 | `test_registry.py::TestCoverage::test_best_class_wins`, `test_registry.py::TestCoverage::test_retired_gateway_is_409` |
| `POST /api/v1/gateways/{id}/actions` returns the new gateway state | `test_gateway_states.py::TestActionsEndpoint::test_returns_the_gateway_state_shape` |
| `POST /api/v1/sensors/{id}/actions` decommission, reason required | `test_registry.py::TestDecommission::test_invalid_body_is_422`, `test_registry.py::TestDecommission::test_decommission_is_terminal` |
| `GET` gateway, sensor, timeline and batch shapes | `test_registry.py::TestGatewayRegistration::test_register_returns_token_and_initial_state`, `test_registry.py::TestSensorRegistration::test_register_pending_with_no_coverage`, `test_core.py::TestTimeline::test_serialized_shape`, `test_batches.py::TestProcessing::test_valid_readings_are_accepted` |
| Test endpoints exist only with `TEST_MODE=1`; background work runs only inside `/test/clock` and `/test/drain` | `test_tick.py::test_routes_are_404_outside_test_mode`, `test_tick.py::TestWorker::test_idles_in_test_mode`, `test_batches.py::TestProcessing::test_nothing_is_processed_until_the_clock_moves_or_drains` |
| `/test/reset` empties every table | `test_tick.py::TestResetEndpoint::test_empties_every_table_including_the_clock` |
| `/test/clock` moves forward only (409 backwards), runs everything due, each effective at its own due time | `test_tick.py::TestClockEndpoint::test_backwards_is_409_and_runs_nothing`, `test_tick.py::TestClockEndpoint::test_jump_applies_each_item_at_its_own_due_time`, `test_batches.py::TestRetries::test_a_clock_jump_runs_every_due_retry` |
| `/test/drain` does the same without moving the clock | `test_tick.py::TestDrainEndpoint::test_runs_due_work_without_moving_the_clock` |
| `/test/faults` makes the next n processing attempts fail | `test_tick.py::TestFaults::test_endpoint_sets_how_many_attempts_fail`, `test_batches.py::TestRetries::test_failed_attempts_retry_with_backoff_then_succeed` |
| Time is read only through the clock | `test_conformance.py::test_time_is_read_only_through_the_clock` |

## What we build

| Requirement | Where |
|---|---|
| Automated tests for the transition rules, timers, coverage and a late-data correction | this table; `make test` |
| Fleet page, sensors page, situation counts | `frontend/src/app` (checked by hand; see DECISIONS.md) |
| A console API documented in OpenAPI | `test_console_api.py::TestOpenAPI::test_schema_validates_without_warnings`, `test_console_api.py::TestOpenAPI::test_every_route_is_documented` |
| A simulator with three failure stories, each ending in an assertion | `test_simulator.py::test_story_passes`, `test_simulator.py::test_the_script_itself_finds_the_stories` |

## Allowed compromises (documented, not tested)

503 with `Retry-After`; console filters beyond status and lifecycle, sorting and pagination; UI tests; a polished timeline view. See DECISIONS.md, Trade-offs and compromises.
