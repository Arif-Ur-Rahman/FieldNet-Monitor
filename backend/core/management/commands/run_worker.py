"""Background worker loop. Runs the engine's tick() every few seconds.

The tick itself arrives in feat/test-endpoints-tick (#9); until then this only
proves the worker container starts.
"""

import time

from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Run background processing (batches, retries, timers) in a loop."

    def add_arguments(self, parser):
        parser.add_argument("--interval", type=float, default=2.0)

    def handle(self, *args, interval, **options):
        if settings.TEST_MODE:
            self.stdout.write("TEST_MODE=1: background work only runs inside /test/clock and /test/drain; idling.")
        while True:
            time.sleep(interval)
