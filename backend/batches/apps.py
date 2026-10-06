from django.apps import AppConfig


class BatchesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "batches"

    def ready(self):
        from batches import processing
        from core import tick

        tick.register("batches", processing.next_due, order=tick.BATCHES)
