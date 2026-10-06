"""Query parameters shared by the console list endpoints."""

from core.errors import Unprocessable


def choices_filter(request, name: str, allowed) -> list[str] | None:
    """`?name=a,b`: the values asked for, or None when the parameter is absent. Unknown values are 422."""
    raw = request.query_params.get(name)
    if raw is None or raw.strip() == "":
        return None
    values = [v.strip() for v in raw.split(",") if v.strip()]
    unknown = [v for v in values if v not in allowed]
    if unknown:
        raise Unprocessable("invalid_filter", f"{name}: unknown value {unknown[0]!r}; one of {', '.join(allowed)}.")
    return values
