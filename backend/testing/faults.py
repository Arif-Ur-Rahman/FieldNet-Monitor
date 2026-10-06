"""Injected processing failures, set through POST /test/faults to exercise retries."""

from django.conf import settings
from django.db.models import F

from testing.models import FaultInjection


def set_processing_failures(n: int) -> None:
    FaultInjection.objects.update_or_create(pk=1, defaults={"processing_failures": n})


def take_processing_failure() -> bool:
    """True if this processing attempt must fail. Consumes one injected failure.

    Batch processing calls this once per attempt. Always False outside TEST_MODE.
    """
    if not settings.TEST_MODE:
        return False
    return (
        FaultInjection.objects.filter(pk=1, processing_failures__gt=0).update(
            processing_failures=F("processing_failures") - 1
        )
        == 1
    )
