from django.apps import AppConfig


class GamesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "games"

    def ready(self):
        """Import signals when the app is ready."""
        from django.db.models.signals import post_migrate

        import games.signals

        # Sender is this AppConfig instance, which only exists by now, so the
        # receiver is connected here rather than with @receiver
        post_migrate.connect(
            games.signals.rederive_open_ended,
            sender=self,
            dispatch_uid="games.rederive_open_ended",
        )
