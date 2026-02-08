import pytest

from catalog.importers import run_import
from catalog.models import Product

pytestmark = pytest.mark.django_db


def test_import_creates_product_from_sample(sample_workbook_path):
    created, updated, errors = run_import(sample_workbook_path)

    assert (created, updated, errors) == (1, 0, 0)
    product = Product.objects.get(sku="SKU-FIXTURE")
    assert product.slug == "fixture-product"
