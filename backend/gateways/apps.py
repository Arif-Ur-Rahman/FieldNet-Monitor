from django.apps import AppConfig


class GatewaysConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "gateways"

    def ready(self):
        from core import tick
        from gateways import commands, state

        tick.register("gateways", state.next_stale_due, order=tick.GATEWAYS)
        tick.register("commands", commands.next_timeout_due, order=tick.GATEWAYS)
