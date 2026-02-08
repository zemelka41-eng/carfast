import logging

from django.apps import apps
from django.db.models.signals import post_migrate
from django.dispatch import receiver

logger = logging.getLogger(__name__)


@receiver(post_migrate)
def ensure_default_site_settings(sender, app_config, using, **kwargs):
    """
    Guarantee a singleton SiteSettings row with pk=1 after migrations.
    """
    if app_config.name != "catalog":
        return

    SiteSettings = apps.get_model("catalog", "SiteSettings")
    try:
        obj, created = SiteSettings.objects.using(using).get_or_create(pk=1)
        if created:
            logger.info("Created default SiteSettings with pk=1 for database '%s'", using)
    except Exception as e:  # noqa: BLE001
        # Log but don't fail migrations if schema mismatch (e.g., table doesn't exist yet)
        logger.warning(
            "Failed to ensure default SiteSettings for database '%s': %s. "
            "This is normal if migrations are still running.",
            using,
            e
        )
