import pytest
from django.core.exceptions import ValidationError

from catalog.models import Category, ModelVariant, Product, Series

pytestmark = pytest.mark.django_db


def test_product_slug_auto_generates_full_components():
    series, _ = Series.objects.get_or_create(name="SHACMAN", slug="shacman")
    category, _ = Category.objects.get_or_create(name="Самосвалы", slug="samosval")
    model_variant = ModelVariant.objects.create(
        brand=series,
        line="L3000",
        wheel_formula="6x4",
        name="L3000 6x4",
        slug="l3000-6x4-test-1",
    )
    product = Product.objects.create(
        sku="SKU-1",
        slug="",
        series=series,
        category=category,
        model_variant=model_variant,
        model_name_ru="Test",
        model_name_en="Test",
        model_code="SX31888K401C",
        wheel_formula="6x4",
        published=True,
        is_active=True,
    )
    assert product.slug == "shacman-samosval-l3000-6x4-sx31888k401c"


def test_product_slug_auto_generates_without_wheel_formula():
    series, _ = Series.objects.get_or_create(name="SHACMAN", slug="shacman")
    category, _ = Category.objects.get_or_create(name="Тягачи", slug="tyagach")
    model_variant = ModelVariant.objects.create(
        brand=series,
        line="X6000",
        wheel_formula="",
        name="X6000",
        slug="x6000-test-1",
    )
    product = Product.objects.create(
        sku="SKU-2",
        slug="",
        series=series,
        category=category,
        model_variant=model_variant,
        model_name_ru="Test 2",
        model_name_en="Test 2",
        model_code="SX1234",
        wheel_formula="",
        published=True,
        is_active=True,
    )
    assert product.slug == "shacman-tyagach-x6000-sx1234"


def test_product_slug_preserves_manual_value():
    series, _ = Series.objects.get_or_create(name="SHACMAN", slug="shacman")
    category, _ = Category.objects.get_or_create(name="Самосвалы", slug="samosval")
    product = Product.objects.create(
        sku="SKU-3",
        slug="custom-slug-1",
        series=series,
        category=category,
        model_name_ru="Manual",
        model_name_en="Manual",
        model_code="SX999",
        published=True,
        is_active=True,
    )
    product.save()
    assert product.slug == "custom-slug-1"


def test_product_slug_uses_category_name_mapping_when_slug_missing():
    series, _ = Series.objects.get_or_create(name="SHACMAN", slug="shacman")
    category = Category.objects.filter(name="Самосвалы", slug="").first()
    if not category:
        category = Category.objects.create(name="Самосвалы", slug="")
    model_variant = ModelVariant.objects.create(
        brand=series,
        line="L3000",
        wheel_formula="6x4",
        name="L3000 6x4",
        slug="l3000-6x4-test-2",
    )
    product = Product.objects.create(
        sku="SKU-4",
        slug="",
        series=series,
        category=category,
        model_variant=model_variant,
        model_name_ru="Test 4",
        model_name_en="Test 4",
        model_code="SX1",
        wheel_formula="6x4",
        published=True,
        is_active=True,
    )
    assert product.slug == "shacman-samosval-l3000-6x4-sx1"


def test_product_slug_requires_type():
    series, _ = Series.objects.get_or_create(name="SHACMAN", slug="shacman")
    product = Product(
        sku="SKU-5",
        slug="",
        series=series,
        category=None,
        model_name_ru="No type",
        model_name_en="No type",
        model_code="SX5",
        published=True,
        is_active=True,
    )
    with pytest.raises(ValidationError):
        product.save()


def test_product_slug_collision_adds_suffix():
    series, _ = Series.objects.get_or_create(name="SHACMAN", slug="shacman")
    category, _ = Category.objects.get_or_create(name="Самосвалы", slug="samosval")
    model_variant = ModelVariant.objects.create(
        brand=series,
        line="L3000",
        wheel_formula="6x4",
        name="L3000 6x4 collision",
        slug="l3000-6x4-collision",
    )
    first = Product.objects.create(
        sku="SKU-6",
        slug="",
        series=series,
        category=category,
        model_variant=model_variant,
        model_name_ru="Collision 1",
        model_name_en="Collision 1",
        model_code="SX777",
        wheel_formula="6x4",
        published=True,
        is_active=True,
    )
    second = Product.objects.create(
        sku="SKU-7",
        slug="",
        series=series,
        category=category,
        model_variant=model_variant,
        model_name_ru="Collision 2",
        model_name_en="Collision 2",
        model_code="SX777",
        wheel_formula="6x4",
        published=True,
        is_active=True,
    )
    assert first.slug == "shacman-samosval-l3000-6x4-sx777"
    assert second.slug == "shacman-samosval-l3000-6x4-sx777-2"


def test_product_slug_truncates_model_code_when_too_long():
    series, _ = Series.objects.get_or_create(name="SHACMAN", slug="shacman")
    category, _ = Category.objects.get_or_create(name="Самосвалы", slug="samosval")
    model_variant = ModelVariant.objects.create(
        brand=series,
        line="L3000",
        wheel_formula="6x4",
        name="L3000 6x4 long code",
        slug="l3000-6x4-long-code",
    )
    long_code = "S" * 90
    product = Product.objects.create(
        sku="SKU-8",
        slug="",
        series=series,
        category=category,
        model_variant=model_variant,
        model_name_ru="Long code",
        model_name_en="Long code",
        model_code=long_code,
        wheel_formula="6x4",
        published=True,
        is_active=True,
    )
    assert len(product.slug) <= 80
    assert product.slug.startswith("shacman-samosval-l3000-")
    assert product.slug.endswith("s" * 56)


def test_product_slug_drops_wheel_when_needed():
    series, _ = Series.objects.get_or_create(name="SHACMAN", slug="shacman")
    category, _ = Category.objects.get_or_create(name="Самосвалы", slug="samosval")
    model_variant = ModelVariant.objects.create(
        brand=series,
        line="L3000",
        wheel_formula="6x4",
        name="L3000 6x4 drop wheel",
        slug="l3000-6x4-drop-wheel",
    )
    code = "S" * 55
    product = Product.objects.create(
        sku="SKU-9",
        slug="",
        series=series,
        category=category,
        model_variant=model_variant,
        model_name_ru="Drop wheel",
        model_name_en="Drop wheel",
        model_code=code,
        wheel_formula="6x4",
        published=True,
        is_active=True,
    )
    assert "6x4" not in product.slug
    assert product.slug == "shacman-samosval-l3000-" + ("s" * 55)


def test_product_manual_slug_case_insensitive_unique():
    series, _ = Series.objects.get_or_create(name="SHACMAN", slug="shacman")
    category, _ = Category.objects.get_or_create(name="Самосвалы", slug="samosval")
    Product.objects.create(
        sku="SKU-10",
        slug="Test-Slug",
        series=series,
        category=category,
        model_name_ru="Manual 1",
        model_name_en="Manual 1",
        model_code="SX10",
        published=True,
        is_active=True,
    )
    second = Product(
        sku="SKU-11",
        slug="test-slug",
        series=series,
        category=category,
        model_name_ru="Manual 2",
        model_name_en="Manual 2",
        model_code="SX11",
        published=True,
        is_active=True,
    )
    with pytest.raises(ValidationError):
        second.save()
