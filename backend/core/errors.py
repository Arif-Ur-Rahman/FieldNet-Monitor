"""One error shape for the whole API: {"error": "<code>", "detail": "<text>"}.

Invalid bodies are 422, conflicts and illegal actions 409, unknown ids 404,
unknown gateway tokens 401, retired gateways 403.
"""

import logging

from django.http import Http404, JsonResponse
from rest_framework import exceptions, status
from rest_framework.response import Response

log = logging.getLogger(__name__)


class APIError(exceptions.APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_code = "error"

    def __init__(self, code: str | None = None, detail: str = ""):
        self.code = code or self.default_code
        super().__init__(detail=detail or self.code, code=self.code)


class Unprocessable(APIError):
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    default_code = "invalid_body"


class Conflict(APIError):
    status_code = status.HTTP_409_CONFLICT
    default_code = "conflict"


class NotFound(APIError):
    status_code = status.HTTP_404_NOT_FOUND
    default_code = "not_found"


class Unauthorized(APIError):
    status_code = status.HTTP_401_UNAUTHORIZED
    default_code = "unauthorized"


class Forbidden(APIError):
    status_code = status.HTTP_403_FORBIDDEN
    default_code = "forbidden"


def _flatten(detail, prefix: str = "") -> list[str]:
    """Turn DRF's nested error dicts/lists into 'field: message' strings."""
    if isinstance(detail, dict):
        out = []
        for key, value in detail.items():
            name = key if key != "non_field_errors" else ""
            out += _flatten(value, f"{prefix}.{name}" if prefix and name else (name or prefix))
        return out
    if isinstance(detail, list):
        out = []
        for i, value in enumerate(detail):
            sub = f"{prefix}[{i}]" if isinstance(value, dict | list) else prefix
            out += _flatten(value, sub)
        return out
    return [f"{prefix}: {detail}" if prefix else str(detail)]


def body(code: str, detail: str) -> dict:
    return {"error": code, "detail": detail}


# DRF exception -> (status, code) for the cases the brief pins down.
_MAPPED = {
    exceptions.ValidationError: (422, "invalid_body"),
    exceptions.ParseError: (422, "invalid_json"),
    exceptions.NotAuthenticated: (401, "unauthorized"),
    exceptions.AuthenticationFailed: (401, "unauthorized"),
    exceptions.PermissionDenied: (403, "forbidden"),
    exceptions.NotFound: (404, "not_found"),
    exceptions.MethodNotAllowed: (405, "method_not_allowed"),
    exceptions.UnsupportedMediaType: (422, "unsupported_media_type"),
}


def exception_handler(exc, context):
    if isinstance(exc, Http404):
        return Response(body("not_found", str(exc) or "Not found."), status=404)
    if isinstance(exc, APIError):
        return Response(body(exc.code, str(exc.detail)), status=exc.status_code)
    for cls, (code_status, code) in _MAPPED.items():
        if isinstance(exc, cls):
            return Response(body(code, "; ".join(_flatten(exc.detail))), status=code_status)
    if isinstance(exc, exceptions.APIException):
        return Response(body(exc.default_code, "; ".join(_flatten(exc.detail))), status=exc.status_code)
    log.exception("Unhandled API error", exc_info=exc)
    return Response(body("internal_error", "Unexpected server error."), status=500)


def handler404(request, exception=None):
    return JsonResponse(body("not_found", f"No route for {request.path}."), status=404)


def handler500(request):
    return JsonResponse(body("internal_error", "Unexpected server error."), status=500)
