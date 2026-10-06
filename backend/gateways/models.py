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
