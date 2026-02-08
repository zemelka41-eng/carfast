import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from catalog.models import Category, Product, ProductImage, Series

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def base_series(series_factory):
    return series_factory(name="Series", slug="series")


@pytest.fixture
def base_category(category_factory):
    return category_factory(name="Category", slug="category")


def _create_product(series: Series, category: Category, sku: str, slug: str) -> Product:
    return Product.objects.create(
        sku=sku,
        slug=slug,
        series=series,
        category=category,
        model_name_ru="Модель",
        model_name_en="Model",
    )


def test_series_slug_case_insensitive_unique():
    Series.objects.create(name="Other", slug="unique")
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Series.objects.create(name="Other-2", slug="UNIQUE")


def test_category_slug_case_insensitive_unique():
    Category.objects.create(name="Other", slug="distinct")
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Category.objects.create(name="Other-2", slug="DISTINCT")


def test_product_slug_case_insensitive_unique(base_series, base_category):
    _create_product(base_series, base_category, "SKU-1", "prod-1")
    with pytest.raises(ValidationError):
        _create_product(base_series, base_category, "SKU-2", "PROD-1")


def test_product_sku_case_insensitive_unique(base_series, base_category):
    _create_product(base_series, base_category, "SKU-3", "prod-3")
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            _create_product(base_series, base_category, "sku-3", "prod-4")


def test_product_image_order_unique_per_product(base_series, base_category):
    product = _create_product(base_series, base_category, "SKU-10", "prod-10")
    ProductImage.objects.create(product=product, image="products/a.jpg", order=0)
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            ProductImage.objects.create(
                product=product,
                image="products/b.jpg",
                order=0,
            )
