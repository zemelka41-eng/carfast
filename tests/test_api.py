import pytest
from django.urls import reverse
from rest_framework import status

from catalog.models import Lead

pytestmark = pytest.mark.django_db


def test_create_lead(api_client, product):
    url = reverse("api-leads")
    payload = {
        "product": product.pk,
        "name": "Test",
        "phone": "+100",
        "email": "a@b.com",
        "message": "Hi",
    }
    response = api_client.post(url, payload, format="json")
    assert response.status_code == status.HTTP_201_CREATED
    assert Lead.objects.filter(name="Test", product=product).exists()
