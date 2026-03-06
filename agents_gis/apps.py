from django.apps import AppConfig


class AgentsGisConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "agents_gis"

    def ready(self):
        from . import tools_spatial  # noqa
        from . import tools_query  # noqa
        from . import tools_nearby  # noqa
        from . import tools_intersects  # noqa
        from . import tools_context  # noqa