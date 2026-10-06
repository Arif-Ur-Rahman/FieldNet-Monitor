from django.apps import AppConfig


class SensorsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "sensors"

    def ready(self):
        from core import tick
        from sensors.engine import reconcile

        tick.register("sensors", reconcile.next_due, order=tick.SENSORS)
