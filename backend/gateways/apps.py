from django.apps import AppConfig


class GatewaysConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "gateways"

    def ready(self):
        from core import tick
        from gateways import state

        tick.register("gateways", state.next_stale_due, order=tick.GATEWAYS)
