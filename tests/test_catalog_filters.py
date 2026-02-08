import pytest

from catalog.filters import ProductFilter
from catalog.models import Product

pytestmark = pytest.mark.django_db

def test_product_filter_by_category(product_factory, category_factory):
    cat_a = category_factory(name="Cat A", slug="cat-a")
    cat_b = category_factory(name="Cat B", slug="cat-b")

    p1 = product_factory(category=cat_a)
    p2 = product_factory(category=cat_b)

    product_filter = ProductFilter({"category": cat_a.slug}, queryset=Product.objects.public())
    products = list(product_filter.qs)

    assert p1 in products
    assert p2 not in products
    assert all(p.category_id == cat_a.id for p in products)


def test_product_filter_by_model(product_factory, model_variant_factory, series_factory):
    brand = series_factory(name="BRAND", slug="brand")
    mv_a = model_variant_factory(brand=brand, line="XTESTA", wheel_formula="4x2")
    mv_b = model_variant_factory(brand=brand, line="XTESTB", wheel_formula="6x4")

    p1 = product_factory(series=brand, model_variant=mv_a)
    p2 = product_factory(series=brand, model_variant=mv_b)

    product_filter = ProductFilter({"model": mv_a.slug}, queryset=Product.objects.public())
    products = list(product_filter.qs)

    assert p1 in products
    assert p2 not in products
    assert all(getattr(p.model_variant, "slug", None) == mv_a.slug for p in products)


def test_product_filter_category_and_model_and_logic(
    product_factory, category_factory, model_variant_factory, series_factory
):
    brand = series_factory(name="BRAND", slug="brand2")
    cat_a = category_factory(name="Cat A", slug="cat-a2")
    cat_b = category_factory(name="Cat B", slug="cat-b2")
    mv_a = model_variant_factory(brand=brand, line="XTESTC", wheel_formula="6x4")
    mv_b = model_variant_factory(brand=brand, line="XTESTD", wheel_formula="8x4")

    p_match = product_factory(series=brand, category=cat_a, model_variant=mv_a)
    product_factory(series=brand, category=cat_a, model_variant=mv_b)
    product_factory(series=brand, category=cat_b, model_variant=mv_a)

    product_filter = ProductFilter(
        {"category": cat_a.slug, "model": mv_a.slug}, queryset=Product.objects.public()
    )
    products = list(product_filter.qs)

    assert products == [p_match]


def test_product_filter_unknown_slugs_return_empty_results(product_factory):
    product_factory()

    product_filter = ProductFilter(
        {"category": "unknown-category"}, queryset=Product.objects.public()
    )
    assert list(product_filter.qs) == []

    product_filter = ProductFilter(
        {"model": "unknown-model"}, queryset=Product.objects.public()
    )
    assert list(product_filter.qs) == []
