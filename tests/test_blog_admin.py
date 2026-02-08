import re

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from blog.models import BlogPost


pytestmark = pytest.mark.django_db


def test_blogpost_change_form_renders_inline_management_form(client):
    User = get_user_model()
    admin = User.objects.create_user(
        username="admin",
        email="admin@example.com",
        password="password123",
        is_staff=True,
        is_superuser=True,
    )
    post = BlogPost.objects.create(
        title="Пост с галереей",
        slug="post-with-gallery",
        excerpt="Описание",
        content_html="<p>Контент</p>",
        is_published=True,
        published_at=timezone.now(),
    )

    client.force_login(admin)
    url = reverse("admin:blog_blogpost_change", args=[post.id])
    response = client.get(url)
    content = response.content.decode("utf-8")

    assert response.status_code == 200
    assert "Изображения статьи" in content
    assert "TOTAL_FORMS" in content
    assert "INITIAL_FORMS" in content
