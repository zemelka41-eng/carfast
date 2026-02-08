import json
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import pytest
from django.core.cache import caches
from django.core.management import call_command
from django.core.management.base import CommandError

from carfst_site import health

pytestmark = pytest.mark.django_db


def test_health_view_ok_when_paths_present(client, tmp_path, settings):
    static_root = tmp_path / "staticfiles"
    media_root = tmp_path / "media"
    static_root.mkdir()
    media_root.mkdir()
    (static_root / "placeholder.txt").write_text("ok", encoding="utf-8")

    settings.STATIC_ROOT = static_root
    settings.MEDIA_ROOT = media_root

    response = client.get("/health/")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["errors"] == []
    assert data["warnings"] == []
    assert data["checks"]["static_root"]["status"] == "ok"
    assert data["checks"]["media_root"]["status"] == "ok"
    assert data["checks"]["cache"]["status"] == "ok"
    assert "meta" in data


def test_health_view_degraded_when_static_missing(client, tmp_path, settings):
    """Warnings-only (degraded) should return 200, not 503, to avoid breaking smoke checks."""
    static_root = tmp_path / "staticfiles"
    media_root = tmp_path / "media"
    media_root.mkdir()

    settings.STATIC_ROOT = static_root
    settings.MEDIA_ROOT = media_root

    response = client.get("/health/")

    assert response.status_code == 200, "Degraded (warnings-only) should return 200, not 503"
    data = response.json()
    assert data["status"] == "degraded"
    assert not data["errors"]
    assert data["warnings"]
    assert data["checks"]["static_root"]["status"] == "warning"
    assert "static" in data["checks"]["static_root"]["detail"]


def test_health_view_strict_mode_degraded_returns_503(client, tmp_path, settings):
    """Strict mode (?strict=1) should return 503 for degraded status."""
    static_root = tmp_path / "staticfiles"
    media_root = tmp_path / "media"
    media_root.mkdir()

    settings.STATIC_ROOT = static_root
    settings.MEDIA_ROOT = media_root

    response = client.get("/health/?strict=1")

    assert response.status_code == 503, "Strict mode should return 503 for degraded"
    data = response.json()
    assert data["status"] == "degraded"


def test_health_view_errors_return_503(client, monkeypatch):
    """Real errors should always return 503."""
    monkeypatch.setattr(health, "_check_database", lambda: "Database connection failed")
    
    response = client.get("/health/")
    
    assert response.status_code == 503, "Errors should return 503"
    data = response.json()
    assert data["status"] == "error"
    assert data["errors"]


def test_database_failure_skips_followup_checks(monkeypatch):
    monkeypatch.setattr(health, "_check_database", lambda: "db down")
    report = health.run_health_checks()

    assert report["status"] == "error"
    assert report["checks"]["database"]["status"] == "error"
    assert report["checks"]["migrations"]["status"] == "skipped"
    assert report["checks"]["slug_duplicates"]["status"] == "skipped"
    assert report["checks"]["orphaned_media"]["status"] == "skipped"


def test_health_orphaned_media_skipped_by_default(client, tmp_path, settings):
    """Without deep=1 or HEALTH_ORPHANED_MEDIA=1, orphaned_media is skipped and scan is not run."""
    static_root = tmp_path / "staticfiles"
    media_root = tmp_path / "media"
    static_root.mkdir()
    media_root.mkdir()
    (static_root / "placeholder.txt").write_text("ok", encoding="utf-8")
    settings.STATIC_ROOT = static_root
    settings.MEDIA_ROOT = media_root

    scan_called = []

    def track_scan():
        scan_called.append(1)
        return {"missing_files": [], "unreferenced_files": []}

    from carfst_site import health as health_mod
    with patch.object(health_mod, "_check_orphaned_media", side_effect=track_scan):
        response = client.get("/health/")

    assert response.status_code == 200
    data = response.json()
    o = data["checks"]["orphaned_media"]
    assert o["status"] == "skipped"
    assert "detail" in o
    assert "reason" in o["detail"]
    assert "disabled by default" in o["detail"]["reason"]
    assert len(scan_called) == 0


def test_health_orphaned_media_default_contract(client, tmp_path, settings):
    """GET /health/ without deep: orphaned_media.status==skipped, detail and detail.reason present (regression)."""
    static_root = tmp_path / "staticfiles"
    media_root = tmp_path / "media"
    static_root.mkdir()
    media_root.mkdir()
    (static_root / "placeholder.txt").write_text("ok", encoding="utf-8")
    settings.STATIC_ROOT = static_root
    settings.MEDIA_ROOT = media_root

    response = client.get("/health/")
    assert response.status_code == 200
    assert "application/json" in response.get("Content-Type", "")
    data = response.json()
    o = data["checks"]["orphaned_media"]
    assert o["status"] == "skipped", f"expected status=skipped, got {o.get('status')}"
    assert "detail" in o, "orphaned_media must have detail"
    assert "reason" in o["detail"], "detail must have reason"
    assert len((o["detail"]["reason"] or "").strip()) > 0, "detail.reason must not be empty"


def test_health_orphaned_media_deep_contract(client, tmp_path, settings):
    """GET /health/?deep=1: orphaned_media.detail has cached, cache_age_seconds, missing_files, unreferenced_files (regression)."""
    static_root = tmp_path / "staticfiles"
    media_root = tmp_path / "media"
    static_root.mkdir()
    media_root.mkdir()
    (static_root / "placeholder.txt").write_text("ok", encoding="utf-8")
    settings.STATIC_ROOT = static_root
    settings.MEDIA_ROOT = media_root

    response = client.get("/health/?deep=1")
    assert response.status_code in (200, 503)
    assert "application/json" in response.get("Content-Type", "")
    data = response.json()
    o = data["checks"]["orphaned_media"]
    assert "detail" in o, "orphaned_media must have detail"
    det = o["detail"]
    for key in ("cached", "cache_age_seconds", "missing_files", "unreferenced_files"):
        assert key in det, f"detail must contain {key}"
    assert isinstance(det.get("missing_files"), list), "missing_files must be a list"
    assert isinstance(det.get("unreferenced_files"), list), "unreferenced_files must be a list"


def test_health_orphaned_media_deep_runs_and_caches(client, tmp_path, settings):
    """With ?deep=1 first request runs scan, second request within TTL returns cache (cached=true)."""
    static_root = tmp_path / "staticfiles"
    media_root = tmp_path / "media"
    static_root.mkdir()
    media_root.mkdir()
    (static_root / "placeholder.txt").write_text("ok", encoding="utf-8")
    settings.STATIC_ROOT = static_root
    settings.MEDIA_ROOT = media_root
    settings.HEALTH_ORPHANED_MEDIA_TTL_SECONDS = 600

    from carfst_site import health as health_mod
    health_mod._orphaned_media_cache_fallback.clear()
    try:
        caches["default"].delete(health_mod.ORPHANED_MEDIA_CACHE_KEY)
    except Exception:
        pass

    scan_called = []
    fixed_result = {"missing_files": ["/a"], "unreferenced_files": ["/b"]}

    def mock_scan():
        scan_called.append(1)
        return dict(fixed_result)

    with patch.object(health_mod, "_check_orphaned_media", side_effect=mock_scan):
        r1 = client.get("/health/?deep=1")
        r2 = client.get("/health/?deep=1")

    assert r1.status_code == 200
    assert r2.status_code == 200
    d1 = r1.json()["checks"]["orphaned_media"]
    d2 = r2.json()["checks"]["orphaned_media"]
    assert d1["status"] == "warning"
    assert d1["detail"]["cached"] is False
    assert d1["detail"]["cache_age_seconds"] == 0
    assert d1["detail"]["missing_files"] == ["/a"]
    assert d1["detail"]["unreferenced_files"] == ["/b"]
    assert d2["detail"]["cached"] is True
    assert d2["detail"]["cache_age_seconds"] >= 0
    assert d2["detail"]["missing_files"] == ["/a"]
    assert d2["detail"]["unreferenced_files"] == ["/b"]
    assert "cached" in d1["detail"] and "cache_age_seconds" in d1["detail"]
    assert len(scan_called) == 1


def test_health_orphaned_media_exception_has_detail(client, tmp_path, settings):
    """When scan raises, orphaned_media still has detail with error and cached=False (no KeyError)."""
    static_root = tmp_path / "staticfiles"
    media_root = tmp_path / "media"
    static_root.mkdir()
    media_root.mkdir()
    (static_root / "placeholder.txt").write_text("ok", encoding="utf-8")
    settings.STATIC_ROOT = static_root
    settings.MEDIA_ROOT = media_root

    from carfst_site import health as health_mod
    health_mod._orphaned_media_cache_fallback.clear()
    try:
        caches["default"].delete(health_mod.ORPHANED_MEDIA_CACHE_KEY)
    except Exception:
        pass

    def failing_scan():
        raise RuntimeError("scan failed")

    with patch.object(health_mod, "_check_orphaned_media", side_effect=failing_scan):
        response = client.get("/health/?deep=1")

    assert response.status_code == 503
    data = response.json()
    o = data["checks"]["orphaned_media"]
    assert o["status"] == "error"
    assert "detail" in o
    det = o["detail"]
    assert "error" in det
    assert "scan failed" in det["error"]
    assert det.get("cached") is False
    assert "cache_age_seconds" in det
    assert det.get("missing_files") == []
    assert det.get("unreferenced_files") == []


def test_health_orphaned_media_cache_expires(client, tmp_path, settings):
    """After TTL expires, deep request runs scan again."""
    static_root = tmp_path / "staticfiles"
    media_root = tmp_path / "media"
    static_root.mkdir()
    media_root.mkdir()
    (static_root / "placeholder.txt").write_text("ok", encoding="utf-8")
    settings.STATIC_ROOT = static_root
    settings.MEDIA_ROOT = media_root
    settings.HEALTH_ORPHANED_MEDIA_TTL_SECONDS = 1

    from carfst_site import health as health_mod
    health_mod._orphaned_media_cache_fallback.clear()
    try:
        caches["default"].delete(health_mod.ORPHANED_MEDIA_CACHE_KEY)
    except Exception:
        pass

    scan_called = []

    def mock_scan():
        scan_called.append(1)
        return {"missing_files": [], "unreferenced_files": []}

    with patch.object(health_mod, "_check_orphaned_media", side_effect=mock_scan):
        with patch("carfst_site.health.time") as mtime:
            # Request 1: set stored_at=1000. Request 2: get expiry 1000, cache_age 1000. Request 3: get 1002 (expired), set 1002, cache_age 1002.
            mtime.time.side_effect = [1000.0, 1000.0, 1000.0, 1002.0, 1002.0, 1002.0]
            client.get("/health/?deep=1")
            client.get("/health/?deep=1")
            client.get("/health/?deep=1")

    assert len(scan_called) == 2


def test_health_command_outputs_json(tmp_path, settings):
    out = StringIO()
    err = StringIO()
    static_root = tmp_path / "staticfiles"
    media_root = tmp_path / "media"
    static_root.mkdir()
    media_root.mkdir()
    (static_root / "placeholder.txt").write_text("ok", encoding="utf-8")

    settings.STATIC_ROOT = static_root
    settings.MEDIA_ROOT = media_root

    call_command("healthcheck", "--json", stdout=out, stderr=err)

    payload = json.loads(out.getvalue())
    assert payload["status"] == "ok"
    assert err.getvalue() == ""


def test_health_command_raises_on_degraded(tmp_path, settings):
    out = StringIO()
    err = StringIO()
    static_root = tmp_path / "staticfiles"
    media_root = tmp_path / "media"
    media_root.mkdir()

    settings.STATIC_ROOT = static_root
    settings.MEDIA_ROOT = media_root

    with pytest.raises(CommandError) as excinfo:
        call_command("healthcheck", stdout=out, stderr=err)

    assert "degraded" in str(excinfo.value)
    assert "static_root" in out.getvalue()
