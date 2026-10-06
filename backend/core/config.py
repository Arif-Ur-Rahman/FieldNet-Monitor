"""Thresholds, versioned over time.

Rules ask for the configuration in force at a given moment (the brief: "the
configuration in force at each moment"). With no ConfigVersion rows, the
brief's defaults apply. PUT /api/v1/config adds a version (core.rule_changes).
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

from core.models import ConfigVersion


@dataclass(frozen=True)
class Config:
    quiet_days_before_dormant: int = 14
    dormant_wait: timedelta = timedelta(days=14)
    sampling_window: timedelta = timedelta(hours=72)
    sampling_cycles_before_retired: int = 2
    stale_after: timedelta = timedelta(hours=12)
    command_timeout: timedelta = timedelta(minutes=10)
    batch_deadline: timedelta = timedelta(hours=24)

    @classmethod
    def from_version(cls, v: ConfigVersion) -> "Config":
        return cls(
            quiet_days_before_dormant=v.quiet_days_before_dormant,
            dormant_wait=timedelta(hours=v.dormant_wait_hours),
            sampling_window=timedelta(hours=v.sampling_window_hours),
            sampling_cycles_before_retired=v.sampling_cycles_before_retired,
            stale_after=timedelta(hours=v.stale_after_hours),
            command_timeout=timedelta(minutes=v.command_timeout_minutes),
            batch_deadline=timedelta(hours=v.batch_deadline_hours),
        )

    def fields(self) -> dict[str, int]:
        """As the API and ConfigVersion spell them: whole hours, minutes or counts."""
        return {
            "quiet_days_before_dormant": self.quiet_days_before_dormant,
            "dormant_wait_hours": _hours(self.dormant_wait),
            "sampling_window_hours": _hours(self.sampling_window),
            "sampling_cycles_before_retired": self.sampling_cycles_before_retired,
            "stale_after_hours": _hours(self.stale_after),
            "command_timeout_minutes": int(self.command_timeout.total_seconds() // 60),
            "batch_deadline_hours": _hours(self.batch_deadline),
        }


def _hours(d: timedelta) -> int:
    return int(d.total_seconds() // 3600)


DEFAULT = Config()
FIELDS = list(DEFAULT.fields())


def config_at(moment: datetime) -> Config:
    """The configuration in force at `moment`."""
    version = ConfigVersion.objects.filter(effective_from__lte=moment).order_by("-effective_from").first()
    return Config.from_version(version) if version else DEFAULT


def history() -> list[tuple[datetime | None, Config]]:
    """All versions in order, starting with the defaults (in force from the beginning of time)."""
    return [(None, DEFAULT)] + [(v.effective_from, Config.from_version(v)) for v in ConfigVersion.objects.all()]


def deadline(start: datetime, threshold: str) -> datetime:
    """The first moment t >= start at which t - start reaches the `threshold` in force at t.

    So a threshold shortened or lengthened mid-wait applies from the change on: e.g. a
    gateway goes stale once the time since its last qualifying evidence reaches the stale
    threshold in force at that moment.
    """
    versions = history()
    for i, (effective_from, cfg) in enumerate(versions):
        until = versions[i + 1][0] if i + 1 < len(versions) else None
        if until is not None and until <= start:
            continue
        candidate = start + getattr(cfg, threshold)
        if effective_from is not None:
            candidate = max(candidate, effective_from)
        if until is None or candidate < until:
            return candidate
    raise AssertionError("the last version is open-ended")
