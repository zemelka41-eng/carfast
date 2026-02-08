from django.db import migrations, models
from django.db.models.functions import Lower


class Migration(migrations.Migration):
    dependencies = [
        ("catalog", "0005_product_indexes_image_constraints"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="series",
            constraint=models.UniqueConstraint(
                Lower("slug"),
                name="series_slug_ci_unique",
            ),
        ),
        migrations.AddConstraint(
            model_name="category",
            constraint=models.UniqueConstraint(
                Lower("slug"),
                name="category_slug_ci_unique",
            ),
        ),
        migrations.AddConstraint(
            model_name="product",
            constraint=models.UniqueConstraint(
                Lower("slug"),
                name="product_slug_ci_unique",
            ),
        ),
        migrations.AddConstraint(
            model_name="product",
            constraint=models.UniqueConstraint(
                Lower("sku"),
                name="product_sku_ci_unique",
            ),
        ),
    ]
