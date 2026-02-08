import copy
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from django.conf import settings
from django.core.cache import caches
from django.db import DEFAULT_DB_ALIAS, DatabaseError, connections
from django.db.migrations.executor import MigrationExecutor
from django.db.models import Count
from django.db.models.functions import Lower
from django.http import HttpRequest, JsonResponse
from django.utils.timezone import now
from django.views.decorators.cache import never_cache

from catalog.models import Category, Product, ProductImage, Series

logger = logging.getLogger(__name__)

# In-process fallback when Django cache is unavailable (key -> (payload, stored_at))
_orphaned_media_cache_fallback: Dict[str, Tuple[Dict[str, Any], float]] = {}
ORPHANED_MEDIA_CACHE_KEY = "health_orphaned_media"


def _check_database() -> str | None:
    try:
        connection = connections[DEFAULT_DB_ALIAS]
        connection.ensure_connection()
    except DatabaseError as exc:  # pragma: no cover - defensive
        return str(exc)
    return None


def _check_unapplied_migrations() -> List[str]:
    connection = connections[DEFAULT_DB_ALIAS]
    executor = MigrationExecutor(connection)
    plan = executor.migration_plan(executor.loader.graph.leaf_nodes())
    return [f"{migration.app_label}.{migration.name}" for migration, _ in plan]


def _check_static_root() -> str | None:
    static_root = Path(settings.STATIC_ROOT)
    if not static_root.exists():
        return "STATIC_ROOT is missing; run collectstatic."
    if not static_root.is_dir():
        return "STATIC_ROOT is not a directory."
    if not any(static_root.glob("*")):
        return "STATIC_ROOT is empty; run collectstatic."
    if not os.access(static_root, os.R_OK):
        return "STATIC_ROOT is not readable."
    return None


def _check_media_root() -> str | None:
    media_root = Path(settings.MEDIA_ROOT)
    if not media_root.exists():
        return "MEDIA_ROOT is missing."
    if not media_root.is_dir():
        return "MEDIA_ROOT is not a directory."
    if not os.access(media_root, os.W_OK):
        return "MEDIA_ROOT is not writable."
    return None


def _check_slug_duplicates() -> Dict[str, List[str]]:
    duplicates: Dict[str, List[str]] = {}
    for model, field in (
        (Series, "slug"),
        (Category, "slug"),
        (Product, "slug"),
    ):
        rows = (
            model.objects.values(lower=Lower(field))
            .annotate(count=Count("id"))
            .filter(count__gt=1)
        )
        if rows:
            duplicates[model._meta.label_lower] = [row["lower"] for row in rows if row["lower"]]
    return duplicates


def _check_orphaned_media() -> Dict[str, List[str]]:
    return ProductImage.find_orphaned_media()


def _get_orphaned_media_cached(ttl_seconds: int) -> Optional[Tuple[Dict[str, Any], float]]:
    """Return (payload, stored_at) or None. Uses Django cache with in-process fallback."""
    try:
        cache = caches["default"]
        payload = cache.get(ORPHANED_MEDIA_CACHE_KEY)
        if payload is None:
            return None
        stored_at = payload.get("_stored_at")
        if stored_at is None:
            return None
        if time.time() - stored_at > ttl_seconds:
            return None
        result = {k: v for k, v in payload.items() if k != "_stored_at"}
        return (result, stored_at)
    except Exception:
        entry = _orphaned_media_cache_fallback.get(ORPHANED_MEDIA_CACHE_KEY)
        if entry is None:
            return None
        result, stored_at = entry
        if time.time() - stored_at > ttl_seconds:
            _orphaned_media_cache_fallback.pop(ORPHANED_MEDIA_CACHE_KEY, None)
            return None
        return (result, stored_at)


def _set_orphaned_media_cached(payload: Dict[str, Any], ttl_seconds: int) -> None:
    """Store payload with current timestamp. Uses Django cache with in-process fallback."""
    stored_at = time.time()
    to_store = {**payload, "_stored_at": stored_at}
    try:
        cache = caches["default"]
        cache.set(ORPHANED_MEDIA_CACHE_KEY, to_store, timeout=ttl_seconds)
    except Exception:
        pass
    _orphaned_media_cache_fallback[ORPHANED_MEDIA_CACHE_KEY] = (
        {k: v for k, v in payload.items()},
        stored_at,
    )


def _check_cache() -> str | None:
    try:
        cache = caches["default"]
        probe_key = "healthcheck_ping"
        cache.set(probe_key, "pong", timeout=5)
        if cache.get(probe_key) != "pong":
            return "Cache read/write validation failed."
    except Exception as exc:  # pragma: no cover - defensive
        return str(exc)
    return None


def _check_log_dir() -> str | None:
    log_dir = Path(settings.LOG_DIR)
    if not log_dir.exists():
        return "LOG_DIR is missing."
    if not log_dir.is_dir():
        return "LOG_DIR is not a directory."
    if not os.access(log_dir, os.W_OK):
        return "LOG_DIR is not writable."
    return None


def _build_check(status: str, detail: Any | None = None) -> Dict[str, Any]:
    data: Dict[str, Any] = {"status": status}
    if detail not in (None, "", [], {}):
        data["detail"] = detail
    return data


def run_health_checks(request: Optional[HttpRequest] = None) -> Dict[str, Any]:
    errors: List[str] = []
    warnings: List[str] = []
    checks: Dict[str, Any] = {}
    db_available = True

    deep = bool(
        (request and request.GET.get("deep", "").strip() == "1")
        or os.environ.get("HEALTH_ORPHANED_MEDIA") == "1"
    )

    db_error = _check_database()
    checks["database"] = _build_check("ok" if not db_error else "error", db_error)
    if db_error:
        errors.append(f"Database unavailable: {db_error}")
        db_available = False

    if db_available:
        try:
            unapplied = _check_unapplied_migrations()
        except Exception as exc:  # pragma: no cover - defensive
            unapplied = str(exc)
            logger.exception("Failed to inspect migrations")

        if isinstance(unapplied, str):
            checks["migrations"] = _build_check("error", unapplied)
            errors.append(f"Migrations check failed: {unapplied}")
        else:
            checks["migrations"] = _build_check("ok" if not unapplied else "error", unapplied or None)
            if unapplied:
                errors.append(f"Unapplied migrations: {', '.join(unapplied)}")
    else:
        checks["migrations"] = _build_check("skipped", "Database unavailable")

    cache_issue = _check_cache()
    checks["cache"] = _build_check("ok" if not cache_issue else "error", cache_issue)
    if cache_issue:
        errors.append(f"Cache unavailable: {cache_issue}")

    media_issue = _check_media_root()
    if media_issue:
        warnings.append(media_issue)
    checks["media_root"] = _build_check("ok" if not media_issue else "warning", media_issue)

    static_issue = _check_static_root()
    if static_issue:
        warnings.append(static_issue)
    checks["static_root"] = _build_check("ok" if not static_issue else "warning", static_issue)

    if db_available:
        try:
            slug_dupes = _check_slug_duplicates()
        except Exception as exc:  # pragma: no cover - defensive
            slug_dupes = str(exc)
            logger.exception("Failed to inspect slug duplicates")

        if isinstance(slug_dupes, str):
            checks["slug_duplicates"] = _build_check("error", slug_dupes)
            errors.append(f"Slug duplicate check failed: {slug_dupes}")
        else:
            if slug_dupes:
                warnings.append(f"Duplicate slugs: {slug_dupes}")
            checks["slug_duplicates"] = _build_check("ok" if not slug_dupes else "warning", slug_dupes or None)
    else:
        checks["slug_duplicates"] = _build_check("skipped", "Database unavailable")

    log_dir_issue = _check_log_dir()
    checks["log_dir"] = _build_check("ok" if not log_dir_issue else "warning", log_dir_issue)
    if log_dir_issue:
        warnings.append(log_dir_issue)

    if db_available:
        if not deep:
            checks["orphaned_media"] = {
                "status": "skipped",
                "detail": {"reason": "disabled by default (set HEALTH_ORPHANED_MEDIA=1 or use ?deep=1)"},
            }
        else:
            ttl_seconds = int(getattr(settings, "HEALTH_ORPHANED_MEDIA_TTL_SECONDS", 600))
            cached = _get_orphaned_media_cached(ttl_seconds)
            if cached is not None:
                orphaned, stored_at = cached
                cache_age = int(time.time() - stored_at)
                detail = {
                    "missing_files": orphaned.get("missing_files", []),
                    "unreferenced_files": orphaned.get("unreferenced_files", []),
                    "cached": True,
                    "cache_age_seconds": cache_age,
                }
                if orphaned.get("missing_files") or orphaned.get("unreferenced_files"):
                    warnings.append("Orphaned media detected.")
                    checks["orphaned_media"] = {"status": "warning", "detail": detail}
                else:
                    checks["orphaned_media"] = {"status": "ok", "detail": detail}
            else:
                try:
                    orphaned = _check_orphaned_media()
                except Exception as exc:  # pragma: no cover - defensive
                    orphaned = {"error": str(exc)}
                    logger.exception("Failed to inspect orphaned media")

                if orphaned.get("error"):
                    detail = {
                        "error": orphaned["error"],
                        "missing_files": [],
                        "unreferenced_files": [],
                        "cached": False,
                        "cache_age_seconds": 0,
                    }
                    checks["orphaned_media"] = {"status": "error", "detail": detail}
                    errors.append(f"Orphaned media check failed: {orphaned['error']}")
                else:
                    _set_orphaned_media_cached(orphaned, ttl_seconds)
                    detail = {
                        "missing_files": orphaned.get("missing_files", []),
                        "unreferenced_files": orphaned.get("unreferenced_files", []),
                        "cached": False,
                        "cache_age_seconds": 0,
                    }
                    if orphaned.get("missing_files") or orphaned.get("unreferenced_files"):
                        warnings.append("Orphaned media detected.")
                        checks["orphaned_media"] = {"status": "warning", "detail": detail}
                    else:
                        checks["orphaned_media"] = {"status": "ok", "detail": detail}
    else:
        checks["orphaned_media"] = {
            "status": "skipped",
            "detail": {"reason": "Database unavailable"},
        }

    status = "ok"
    if errors:
        status = "error"
    elif warnings:
        status = "degraded"

    report: Dict[str, Any] = {
        "status": status,
        "errors": errors,
        "warnings": warnings,
        "checks": checks,
        "meta": {
            "service": getattr(settings, "SITE_DOMAIN", ""),
            "django_version": getattr(settings, "DJANGO_VERSION_STR", ""),
            "debug": settings.DEBUG,
            "timestamp": now().isoformat(),
        },
    }
    # Log summary only for orphaned_media to avoid flooding logs with full file lists
    log_report = report
    orphan_detail = (checks.get("orphaned_media") or {}).get("detail")
    if isinstance(orphan_detail, dict) and (
        orphan_detail.get("missing_files") or orphan_detail.get("unreferenced_files")
    ):
        log_report = copy.deepcopy(report)
        missing = orphan_detail.get("missing_files") or []
        unreferenced = orphan_detail.get("unreferenced_files") or []
        sample = 5
        summary = {
            "missing_count": len(missing),
            "unreferenced_count": len(unreferenced),
            "missing_sample": missing[:sample],
            "unreferenced_sample": unreferenced[:sample],
        }
        if "cached" in orphan_detail:
            summary["cached"] = orphan_detail["cached"]
        if "cache_age_seconds" in orphan_detail:
            summary["cache_age_seconds"] = orphan_detail["cache_age_seconds"]
        log_report["checks"]["orphaned_media"]["detail"] = summary

    if status == "ok":
        logger.debug("Health check report: %s", report)
    elif status == "degraded":
        logger.info("Health degraded (warnings only): %s", log_report)
    else:
        logger.error("Health errors detected: %s", log_report)
    return report


@never_cache
def health_view(request: HttpRequest) -> JsonResponse:
    report = run_health_checks(request=request)
    strict_mode = request.GET.get("strict", "").lower() in ("1", "true", "yes")
    
    # Return 200 if no errors (warnings-only degraded is acceptable for smoke checks)
    # Return 503 only if there are actual errors, or if strict mode requires perfect status
    if report["status"] == "error" or (strict_mode and report["status"] != "ok"):
        status_code = 503
    else:
        status_code = 200
    
    return JsonResponse(report, status=status_code)
