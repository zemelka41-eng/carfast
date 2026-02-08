"""
Safe helper for accessing SiteSettings without crashing on database schema mismatches.
"""
import logging

from django.db import OperationalError, ProgrammingError

logger = logging.getLogger(__name__)


def get_site_settings_safe():
    """
    Safely retrieve SiteSettings instance.
    
    Returns SiteSettings instance if available, None if database schema mismatch
    or other database errors occur. Logs warnings for database errors.
    
    Returns:
        SiteSettings instance or None
    """
    try:
        from ..models import SiteSettings
        return SiteSettings.get_solo()
    except (OperationalError, ProgrammingError) as e:
        logger.warning(
            "SiteSettings unavailable (DB schema mismatch?): %s. "
            "Site will continue to work, but contact blocks may be hidden.",
            e
        )
        return None
    except Exception as e:  # noqa: BLE001
        # Catch any other unexpected errors (e.g., table doesn't exist)
        logger.warning(
            "SiteSettings unavailable (unexpected error): %s. "
            "Site will continue to work, but contact blocks may be hidden.",
            e,
            exc_info=True
        )
        return None

