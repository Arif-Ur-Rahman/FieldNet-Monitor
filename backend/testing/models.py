from django.db import models


class FaultInjection(models.Model):
    """Singleton row: how many upcoming batch processing attempts must fail (POST /test/faults)."""

    id = models.PositiveSmallIntegerField(primary_key=True, default=1)
    processing_failures = models.PositiveIntegerField(default=0)
