import hashlib
import secrets

from django.db import models


class Gateway(models.Model):
    class Status(models.TextChoices):
        NEW = "new"
        SPARE = "spare"
        CONNECTED = "connected"
        STALE = "stale"
        DISCONNECTED = "disconnected"
        SUSPENDED = "suspended"
        RETIRED = "retired"

    class CommandState(models.TextChoices):
        RUNNING = "running"
        STOP_PENDING = "stop_pending"
        STOPPED = "stopped"
        STOP_FAILED = "stop_failed"
        RESUME_PENDING = "resume_pending"
        RESUME_FAILED = "resume_failed"

    gateway_id = models.CharField(max_length=128, primary_key=True)
    name = models.CharField(max_length=200)
    # Only a hash of the bearer token is stored; the token itself is returned once at registration.
    token_hash = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField()

    status = models.CharField(max_length=16, choices=Status.choices, default=Status.NEW)
    status_since = models.DateTimeField()
    suspended_reason = models.TextField(null=True)
    command_state = models.CharField(max_length=16, choices=CommandState.choices, default=CommandState.RUNNING)
    command_state_since = models.DateTimeField()

    last_heartbeat_at = models.DateTimeField(null=True)  # received time of the latest heartbeat
    last_qualifying_at = models.DateTimeField(null=True)  # event time of the newest qualifying evidence
    disconnected_since = models.DateTimeField(null=True)  # event time of the first auth failure of this disconnection
    last_auth_failure_at = models.DateTimeField(null=True)  # event time of the newest auth failure
    collecting_after_stop = models.BooleanField(default=False)

    @staticmethod
    def new_token() -> tuple[str, str]:
        token = secrets.token_urlsafe(32)
        return token, Gateway.hash_token(token)

    @staticmethod
    def hash_token(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    @property
    def coverage_class(self) -> str:
        from gateways.coverage import gateway_class

        return gateway_class(self.status, self.command_state)

    @property
    def flags(self) -> list[str]:
        return ["collecting_after_stop"] if self.collecting_after_stop else []

    def __str__(self):
        return self.gateway_id


class Session(models.TextChoices):
    OK = "ok"
    AUTH_FAILED = "auth_failed"


class Heartbeat(models.Model):
    """Evidence that the gateway is running (never that it is collecting)."""

    gateway = models.ForeignKey(Gateway, on_delete=models.CASCADE, related_name="heartbeats")
    sent_at = models.DateTimeField()  # event time
    session = models.CharField(max_length=16, choices=Session.choices)
    received_at = models.DateTimeField()

    class Meta:
        constraints = [
            # A retried heartbeat is the same heartbeat.
            models.UniqueConstraint(fields=["gateway", "sent_at", "session"], name="heartbeat_unique"),
        ]


class Cycle(models.Model):
    """One check of a gateway's sensors. Idempotent on (gateway, cycle_id)."""

    gateway = models.ForeignKey(Gateway, on_delete=models.CASCADE, related_name="cycles")
    cycle_id = models.CharField(max_length=128)
    started_at = models.DateTimeField()
    finished_at = models.DateTimeField()  # event time
    session = models.CharField(max_length=16, choices=Session.choices)
    received_at = models.DateTimeField()
    body_hash = models.CharField(max_length=64)  # canonical JSON hash, to tell a repeat from a conflict
    ignored = models.JSONField(default=list)  # sensor ids in the body this gateway did not cover

    class Meta:
        constraints = [models.UniqueConstraint(fields=["gateway", "cycle_id"], name="cycle_unique_per_gateway")]


class CycleResult(models.Model):
    """One sensor's outcome in a cycle, as recorded (auth_failed -> could_not_read, timeout -> timed_out)."""

    class Outcome(models.TextChoices):
        READINGS = "readings"
        NO_READINGS = "no_readings"
        COULD_NOT_READ = "could_not_read"
        TIMED_OUT = "timed_out"

    cycle = models.ForeignKey(Cycle, on_delete=models.CASCADE, related_name="results")
    sensor = models.ForeignKey("sensors.Sensor", on_delete=models.CASCADE, related_name="cycle_results")
    gateway = models.ForeignKey(Gateway, on_delete=models.CASCADE, related_name="cycle_results")
    finished_at = models.DateTimeField()  # copied from the cycle for per-sensor queries
    outcome = models.CharField(max_length=16, choices=Outcome.choices)
    reported_outcome = models.CharField(max_length=16)  # what the device sent
    batch_id = models.CharField(max_length=128, null=True)  # set only when the recorded outcome is readings

    class Meta:
        constraints = [models.UniqueConstraint(fields=["cycle", "sensor"], name="one_result_per_sensor_per_cycle")]
        indexes = [models.Index(fields=["sensor", "finished_at"]), models.Index(fields=["batch_id"])]
