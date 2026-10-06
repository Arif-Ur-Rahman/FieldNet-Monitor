from django.db import models


class Sensor(models.Model):
    class Type(models.TextChoices):
        TEMPERATURE = "temperature"
        RAIN = "rain"
        WIND = "wind"

    class Lifecycle(models.TextChoices):
        PENDING = "pending"
        ACTIVE = "active"
        DORMANT = "dormant"
        SAMPLING = "sampling"
        RETIRED = "retired"
        DECOMMISSIONED = "decommissioned"

    UNITS = {Type.TEMPERATURE: "C", Type.RAIN: "mm", Type.WIND: "m/s"}

    sensor_id = models.CharField(max_length=128, primary_key=True)
    type = models.CharField(max_length=16, choices=Type.choices)
    created_at = models.DateTimeField()

    # Current state. Coverage is recomputed whenever its inputs change; the
    # lifecycle fields are the cached result of the sensor engine's replay.
    lifecycle = models.CharField(max_length=16, choices=Lifecycle.choices, default=Lifecycle.PENDING)
    lifecycle_reason = models.TextField(null=True)
    lifecycle_since = models.DateTimeField()
    collection = models.CharField(max_length=24, default="not_checked")
    coverage = models.CharField(max_length=16, default="none")
    quiet_checked_days = models.PositiveIntegerField(default=0)
    sampling_cycles_done = models.PositiveIntegerField(default=0)
    next_evaluation_at = models.DateTimeField(null=True)
    # The next moment the engine's result could change by time alone; tick() reconciles the sensor then.
    reconcile_at = models.DateTimeField(null=True, db_index=True)

    @property
    def unit(self) -> str:
        return self.UNITS[self.type]

    def __str__(self):
        return self.sensor_id


class CoverageAssignment(models.Model):
    """Which gateway covers which sensor, over time. valid_to is null while current."""

    sensor = models.ForeignKey(Sensor, on_delete=models.CASCADE, related_name="assignments")
    gateway = models.ForeignKey("gateways.Gateway", on_delete=models.CASCADE, related_name="assignments")
    valid_from = models.DateTimeField()
    valid_to = models.DateTimeField(null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["sensor", "gateway"],
                condition=models.Q(valid_to__isnull=True),
                name="one_open_assignment_per_pair",
            ),
        ]


class SensorAction(models.Model):
    """Operator actions on a sensor (decommission). Input to the sensor engine's replay."""

    sensor = models.ForeignKey(Sensor, on_delete=models.CASCADE, related_name="actions")
    action = models.CharField(max_length=32)
    reason = models.TextField()
    at = models.DateTimeField()  # server clock
