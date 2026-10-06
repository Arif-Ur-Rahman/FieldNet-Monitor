"""Situation counts for the console dashboard: every value of every axis, zeros included."""

from collections import Counter

from django.db.models import Count

from batches.models import Batch
from gateways.coverage import AVAILABLE, DEAD, RECOVERABLE, STOPPED, gateway_class
from gateways.models import Gateway
from sensors.engine.collection import PRECEDENCE
from sensors.models import Sensor

SENSOR_COVERAGE = [AVAILABLE, STOPPED, RECOVERABLE, "none"]
COLLECTION = PRECEDENCE + ["not_checked", "collection_stopped"]
RETIRED_REASONS = ["no_readings", "no_live_coverage"]


def tally(queryset, *fields) -> list[tuple]:
    """(value of each field..., count) rows."""
    return [(*(row[f] for f in fields), row["n"]) for row in queryset.values(*fields).annotate(n=Count("pk"))]


def zeros(values) -> dict:
    return {v: 0 for v in values}


def counts() -> dict:
    status, command, classes = zeros(Gateway.Status.values), zeros(Gateway.CommandState.values), Counter()
    classes.update(zeros([AVAILABLE, STOPPED, RECOVERABLE, DEAD]))
    gateways_total = 0
    for s, c, n in tally(Gateway.objects, "status", "command_state"):
        status[s] += n
        command[c] += n
        classes[gateway_class(s, c)] += n
        gateways_total += n

    lifecycle, coverage, collection = zeros(Sensor.Lifecycle.values), zeros(SENSOR_COVERAGE), zeros(COLLECTION)
    retired = zeros(RETIRED_REASONS)
    sensors_total = 0
    for life, reason, cov, col, n in tally(Sensor.objects, "lifecycle", "lifecycle_reason", "coverage", "collection"):
        lifecycle[life] += n
        coverage[cov] += n
        collection[col] += n
        if life == Sensor.Lifecycle.RETIRED and reason in retired:
            retired[reason] += n
        sensors_total += n

    processing = zeros(Batch.Processing.values)
    for p, n in tally(Batch.objects, "processing"):
        processing[p] += n

    return {
        "gateways": {
            "total": gateways_total,
            "status": status,
            "command_state": command,
            "coverage_class": dict(classes),
            "flags": {"collecting_after_stop": Gateway.objects.filter(collecting_after_stop=True).count()},
        },
        "sensors": {
            "total": sensors_total,
            "lifecycle": lifecycle,
            "retired_reason": retired,
            "coverage": coverage,
            "collection": collection,
        },
        "batches": {"total": sum(processing.values()), "processing": processing},
    }
