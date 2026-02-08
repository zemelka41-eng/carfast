import pytest
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from catalog.models import Category, Product, ProductImage, Series

pytestmark = pytest.mark.django_db


def test_product_slug_and_url(product):
    assert product.get_absolute_url() == reverse(
        "catalog:product_detail", kwargs={"slug": product.slug}
    )


def test_product_clean_rejects_invalid_availability(series, category):
    product = Product(
        sku="SKU-2",
        slug="sku-2",
        series=series,
        category=category,
        model_name_ru="Модель",
        model_name_en="Model",
        availability="UNKNOWN",
    )
    with pytest.raises(ValidationError):
        product.full_clean()


def test_product_normalizes_options_and_tags(series, category):
    product = Product(
        sku="SKU-3",
        slug="sku-3",
        series=series,
        category=category,
        model_name_ru="Модель",
        model_name_en="Model",
        options=None,
        tags=None,
    )
    product.full_clean()
    assert product.options == {}
    assert product.tags == []


def test_product_image_clean_requires_unique_order(product):
    ProductImage.objects.create(
        product=product, image=SimpleUploadedFile("a.jpg", b"file"), order=0
    )

    duplicate = ProductImage(
        product=product,
        image=SimpleUploadedFile("b.jpg", b"file2"),
        order=0,
    )
    with pytest.raises(ValidationError):
        duplicate.full_clean()


def test_series_and_category_clean_validate_slug():
    series = Series(name="Bad Series", slug="bad slug")
    with pytest.raises(ValidationError):
        series.full_clean()

    Category.objects.create(name="Duplicate", slug="dup")
    category = Category(name="Duplicate 2", slug="DUP")
    with pytest.raises(ValidationError):
        category.full_clean()
