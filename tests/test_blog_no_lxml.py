"""
Tests that blog app imports and works without lxml (stdlib fallback).
"""
import sys
import types

import pytest


def test_blog_views_import_without_lxml(monkeypatch):
    """Blog views must import when lxml is missing; HAS_LXML becomes False."""
    fake_lxml = types.ModuleType("lxml")
    # __getattr__ is called when attribute is not found; raise to simulate missing lxml
    def _getattr(name):
        raise ImportError("No module named 'lxml'")
    fake_lxml.__getattr__ = _getattr

    # Force reimport of blog.views so it runs top-level try/except again
    monkeypatch.delitem(sys.modules, "blog.views", raising=False)
    if "blog" in sys.modules:
        monkeypatch.delattr(sys.modules["blog"], "views", raising=False)
    monkeypatch.setitem(sys.modules, "lxml", fake_lxml)

    from blog import views

    assert views.HAS_LXML is False
    assert hasattr(views, "inject_images_into_html")


def test_inject_images_stdlib_inserts_after_heading(monkeypatch):
    """Stdlib fallback inserts figure after matching h2/h3 (no lxml)."""
    from blog import views

    monkeypatch.setattr(views, "HAS_LXML", False)
    html = "<p>Intro</p><h2>Foo bar</h2><p>After</p>"
    # Mock image: caption with @after: anchor | caption
    class MockImage:
        id = 1
        image = type("Img", (), {"url": "/media/test.jpg"})()
        alt = "alt"
        post = type("Post", (), {"title": "Post"})()

    img = MockImage()
    img.caption = "@after: Foo bar | My caption"
    images = [img]

    out, used = views.inject_images_into_html(html, images)

    assert used == [1]
    assert "<figure class=\"blog-inline-image\"" in out
    assert "src=\"/media/test.jpg\"" in out or 'src="/media/test.jpg"' in out
    assert "<figcaption>My caption</figcaption>" in out
    assert "<h2>Foo bar</h2>" in out
    # Figure should appear after the heading
    assert out.index("<figure") > out.index("</h2>")


def test_inject_images_stdlib_no_match_returns_unchanged(monkeypatch):
    """When no heading matches anchor, HTML is unchanged and used_ids empty."""
    from blog import views

    monkeypatch.setattr(views, "HAS_LXML", False)
    html = "<h2>Other</h2>"
    class MockImage:
        id = 1
        image = type("Img", (), {"url": "/x.jpg"})()
        alt = ""
        post = type("Post", (), {"title": "T"})()

    img = MockImage()
    img.caption = "@after: No match | Cap"
    out, used = views.inject_images_into_html(html, [img])

    assert used == []
    assert out == html
