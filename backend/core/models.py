from django.db import models


class ClockState(models.Model):
    """Singleton row holding the server clock in TEST_MODE (see core.clock)."""

    id = models.PositiveSmallIntegerField(primary_key=True, default=1)
    now = models.DateTimeField()


class TimelineEntry(models.Model):
    """One append-only record of a change on any axis of a gateway, sensor or batch.

    Entries are never edited or deleted (save() refuses updates, delete() refuses).
    seq is per entity and is allocated by core.timeline.append while the caller
    holds a lock on the entity row.
    """

    class Kind(models.TextChoices):
        TRANSITION = "transition"
        CORRECTION = "correction"
        ACTION = "action"
        ACK = "ack"
        FLAG = "flag"
        RULE_CHANGE = "rule_change"

    entity_type = models.CharField(max_length=16)  # gateway | sensor | batch
    entity_id = models.CharField(max_length=128)
    seq = models.PositiveIntegerField()
    kind = models.CharField(max_length=16, choices=Kind.choices)
    axis = models.CharField(max_length=32, null=True)
    from_value = models.CharField(max_length=64, null=True)
    to_value = models.CharField(max_length=64, null=True)
    effective_at = models.DateTimeField()
    recorded_at = models.DateTimeField()
    rule = models.CharField(max_length=64)
    evidence_ids = models.JSONField(default=list)
    detail = models.JSONField(null=True)  # e.g. a correction's recomputed transitions, an action's reason

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["entity_type", "entity_id", "seq"], name="timeline_entity_seq_unique"),
        ]
        indexes = [models.Index(fields=["entity_type", "entity_id", "seq"])]
        ordering = ["entity_type", "entity_id", "seq"]

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise RuntimeError("Timeline entries are append-only")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise RuntimeError("Timeline entries are append-only")


class ConfigVersion(models.Model):
    """Thresholds in force from effective_from onwards. No rows means the defaults apply."""

    effective_from = models.DateTimeField(unique=True)
    recorded_at = models.DateTimeField()
    quiet_days_before_dormant = models.PositiveIntegerField()
    dormant_wait_hours = models.PositiveIntegerField()
    sampling_window_hours = models.PositiveIntegerField()
    sampling_cycles_before_retired = models.PositiveIntegerField()
    stale_after_hours = models.PositiveIntegerField()
    command_timeout_minutes = models.PositiveIntegerField()
    batch_deadline_hours = models.PositiveIntegerField()

    class Meta:
        ordering = ["effective_from"]
