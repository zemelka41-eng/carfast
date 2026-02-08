import pytest

from tests.factories import ModelVariantFactory, ProductFactory


@pytest.mark.django_db
@pytest.mark.parametrize("input_formula", ["8×4", "8х4", " 8 x 4 "])
def test_product_wheel_formula_normalization(input_formula):
    model_variant = ModelVariantFactory(wheel_formula="8x4")
    product = ProductFactory(
        model_variant=model_variant,
        series=model_variant.brand,
        wheel_formula=input_formula,
    )
    product.full_clean()
    assert product.wheel_formula == "8x4"
