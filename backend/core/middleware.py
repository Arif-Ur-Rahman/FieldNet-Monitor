"""Send the server clock with every API response.

The console measures durations ("Disconnected · 2h") against the server's
clock, which in TEST_MODE is whatever /test/clock set, not the browser's.
"""

from core import clock
from core.timeutil import iso

HEADER = "X-Server-Now"


def server_now(get_response):
    def middleware(request):
        response = get_response(request)
        # Data endpoints only: the schema and docs pages don't need it (and mustn't need the database).
        if request.path.startswith(("/api/v1/", "/gw/", "/test/")):
            response[HEADER] = iso(clock.now())
        return response

    return middleware
