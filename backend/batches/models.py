from django.db import models


class Batch(models.Model):
    """One uploaded batch of readings. batch_id is globally unique (gateways generate UUIDs).

    The PUT only stores the body; tick() processes it at next_attempt_at, retrying
    on failure. sensor_id is kept as sent, because an unknown sensor quarantines
    the batch instead of rejecting the request.
    """

    class Processing(models.TextChoices):
        RECEIVED = "received"
        PROCESSED = "processed"
        PARTIALLY_PROCESSED = "partially_processed"
        RETRYING = "retrying"
        QUARANTINED = "quarantined"

    PENDING = (Processing.RECEIVED, Processing.RETRYING)

    batch_id = models.CharField(max_length=128, primary_key=True)
    gateway = models.ForeignKey("gateways.Gateway", on_delete=models.CASCADE, related_name="batches")
    sensor_id = models.CharField(max_length=128)
    readings = models.JSONField()  # the readings exactly as sent
    body_hash = models.CharField(max_length=64)  # canonical JSON hash, to tell a repeat from a conflict
    received_at = models.DateTimeField()

    processing = models.CharField(max_length=24, choices=Processing.choices, default=Processing.RECEIVED)
    reason = models.CharField(max_length=32, null=True)  # set when the whole batch is quarantined
    attempts = models.PositiveSmallIntegerField(default=0)
    next_attempt_at = models.DateTimeField(null=True)  # null once resolved
    resolved_at = models.DateTimeField(null=True)  # processed time once it ends processed, partially or quarantined
    accepted_count = models.PositiveIntegerField(default=0)
    latest_accepted_taken_at = models.DateTimeField(null=True)  # when a processed batch qualifies its gateway

    class Meta:
        indexes = [models.Index(fields=["processing", "next_attempt_at"])]

    @property
    def resolved(self) -> bool:
        return self.processing not in self.PENDING

    def __str__(self):
        return self.batch_id


class Reading(models.Model):
    """An accepted reading. reading_id is globally unique: the first processed version wins."""

    reading_id = models.CharField(max_length=128, primary_key=True)
    batch = models.ForeignKey(Batch, on_delete=models.CASCADE, related_name="accepted")
    sensor = models.ForeignKey("sensors.Sensor", on_delete=models.CASCADE, related_name="readings")
    gateway = models.ForeignKey("gateways.Gateway", on_delete=models.CASCADE, related_name="readings")
    taken_at = models.DateTimeField()  # event time
    value = models.FloatField()
    unit = models.CharField(max_length=8)
    content_hash = models.CharField(max_length=64)  # to tell a duplicate from a conflicting one

    class Meta:
        indexes = [models.Index(fields=["sensor", "taken_at"])]


class QuarantinedReading(models.Model):
    """A reading that was not accepted, with why. reading_id is null when the reading had none."""

    batch = models.ForeignKey(Batch, on_delete=models.CASCADE, related_name="quarantined")
    position = models.PositiveIntegerField()  # index in the batch's readings, to keep the order stable
    reading_id = models.CharField(max_length=128, null=True)
    reason = models.CharField(max_length=32)

    class Meta:
        ordering = ["batch", "position"]
