import re

import pytest
from django.urls import reverse

from carfst_site.build_id import get_build_id


@pytest.mark.django_db
def test_build_id_header_present_and_consistent(client):
    urls = [
        reverse("catalog:home"),
        reverse("catalog:parts"),
        reverse("catalog:service"),
        reverse("catalog:used"),
        reverse("blog:blog_list"),
    ]
    headers = []
    for url in urls:
        response = client.get(url)
        assert response.status_code == 200
        assert "X-Build-ID" in response.headers
        headers.append(response.headers["X-Build-ID"])
    assert len(set(headers)) == 1
    assert headers[0] == get_build_id()


@pytest.mark.django_db
def test_build_id_footer_consistent(client):
    urls = [
        reverse("catalog:home"),
        reverse("catalog:service"),
        reverse("blog:blog_list"),
    ]
    build_values = []
    for url in urls:
        response = client.get(url)
        assert response.status_code == 200
        content = response.content.decode("utf-8")
        match = re.search(r"build:\s*([\w.-]+)", content)
        assert match
        build_values.append(match.group(1))
    assert len(set(build_values)) == 1
    assert build_values[0] == get_build_id()
