"""Background worker loop: runs tick(clock.now()) every few seconds.

In TEST_MODE it idles, because background work must only run inside
/test/clock and /test/drain.
"""

import logging
import time

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import close_old_connections

from core import clock
from core.tick import tick

log = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Run background processing (batches, retries, timers) in a loop."

    def add_arguments(self, parser):
        parser.add_argument("--interval", type=float, default=2.0)
        parser.add_argument("--once", action="store_true", help="Run a single pass and exit.")

    def handle(self, *args, interval, once, **options):
        if settings.TEST_MODE:
            self.stdout.write("TEST_MODE=1: background work only runs inside /test/clock and /test/drain; idling.")
            while not once:
                time.sleep(interval)
            return
        while True:
            self.run_pass()
            if once:
                return
            time.sleep(interval)

    def run_pass(self):
        # A long-lived process must drop connections the database has closed.
        close_old_connections()
        try:
            ran = tick(clock.now())
        except Exception:
            # One failing item must not kill the worker; it is retried on the next pass.
            log.exception("Worker pass failed")
            return
        if ran:
            log.info("Worker pass ran %d due items", ran)
