"""Coverage class: what a gateway contributes to the sensors it covers.

Pure functions of status and command state (the brief's "Coverage" table).
"""

AVAILABLE = "available"
STOPPED = "stopped"
RECOVERABLE = "recoverable"
DEAD = "dead"

_NO_PROOF_STOPPED = {"running", "stop_pending", "stop_failed"}
_NO_PROOF_RESUMED = {"stopped", "resume_pending", "resume_failed"}


def gateway_class(status: str, command_state: str) -> str:
    if status == "connected":
        return AVAILABLE if command_state in _NO_PROOF_STOPPED else STOPPED
    if status in ("new", "stale", "disconnected"):
        return RECOVERABLE
    if status in ("suspended", "retired"):
        return DEAD
    # spare: covers no sensors by definition (mark_spare requires that), so it
    # never contributes. Treated as recoverable; see DECISIONS.md.
    return RECOVERABLE


_RANK = {AVAILABLE: 0, STOPPED: 1, RECOVERABLE: 2}


def sensor_coverage(gateway_classes) -> str:
    """Best class among the covering gateways; none if all are dead or there are none."""
    live = [c for c in gateway_classes if c in _RANK]
    return min(live, key=_RANK.__getitem__) if live else "none"
