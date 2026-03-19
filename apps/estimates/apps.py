from django.apps import AppConfig


class EstimatesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.estimates'

    def ready(self):
        import apps.estimates.signals
