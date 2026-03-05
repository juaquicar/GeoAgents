from django.apps import AppConfig


class AgentsGisConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "agents_gis"

    def ready(self):
        from . import tools_spatial  # noqa