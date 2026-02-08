import logging

from django.apps import AppConfig
from django.conf import settings

logger = logging.getLogger(__name__)


class CatalogConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "catalog"
    verbose_name = "Каталог Техники"

    def ready(self):
        # Import signal handlers to register them.
        from . import signals  # noqa: F401
        
        # Log email configuration at startup (in DEBUG mode or always for warnings)
        self._log_email_config()

    def _log_email_config(self):
        """Log email configuration status at startup (safe, no passwords)."""
        email_host = getattr(settings, "EMAIL_HOST", "")
        email_port = getattr(settings, "EMAIL_PORT", 25)
        email_user = getattr(settings, "EMAIL_HOST_USER", "")
        default_from = getattr(settings, "DEFAULT_FROM_EMAIL", "")
        lead_emails = getattr(settings, "LEAD_NOTIFY_EMAILS", []) or []
        
        # Check if email is configured
        email_configured = bool(
            email_host and email_host != "localhost" and email_user
        )
        
        if email_configured:
            logger.info(
                "Email configured: SMTP %s:%s, from=%s",
                email_host,
                email_port,
                default_from,
            )
            if lead_emails:
                # Log recipients safely (show first 3, then count)
                if len(lead_emails) <= 3:
                    logger.info(
                        "Lead notification emails configured: %s",
                        ", ".join(lead_emails),
                    )
                else:
                    logger.info(
                        "Lead notification emails configured: %s, ... (%d total)",
                        ", ".join(lead_emails[:3]),
                        len(lead_emails),
                    )
            else:
                logger.warning(
                    "LEAD_NOTIFY_EMAILS is empty. Lead notifications will only go to SiteSettings.email if configured."
                )
        else:
            logger.warning(
                "Email not configured (EMAIL_HOST=%s, EMAIL_HOST_USER=%s). "
                "Lead notifications will be disabled. Set EMAIL_HOST, EMAIL_HOST_USER, EMAIL_HOST_PASSWORD to enable.",
                email_host or "not set",
                email_user or "not set",
            )

