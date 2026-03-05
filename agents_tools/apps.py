from django.apps import AppConfig


class AgentsToolsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = 'agents_tools'

    def ready(self):
        # Importa tools para que se registren en REGISTRY
        from . import tools_utils  # noqa