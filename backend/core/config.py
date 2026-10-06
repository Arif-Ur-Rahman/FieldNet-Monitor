"""Thresholds, versioned over time.

Rules ask for the configuration in force at a given moment (the brief: "the
configuration in force at each moment"). With no ConfigVersion rows, the
brief's defaults apply. Changing the config is #23.
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


DEFAULT = Config()


def config_at(moment: datetime) -> Config:
    """The configuration in force at `moment`."""
    version = ConfigVersion.objects.filter(effective_from__lte=moment).order_by("-effective_from").first()
    return Config.from_version(version) if version else DEFAULT


def history() -> list[tuple[datetime | None, Config]]:
    """All versions in order, starting with the defaults (in force from the beginning of time)."""
    return [(None, DEFAULT)] + [(v.effective_from, Config.from_version(v)) for v in ConfigVersion.objects.all()]
