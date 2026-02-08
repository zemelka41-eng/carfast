from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("catalog", "0004_alter_category_options_alter_series_options_and_more"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="product",
            options={
                "ordering": ["-created_at", "-id"],
                "verbose_name": "Единица Техники",
                "verbose_name_plural": "Техника",
            },
        ),
        migrations.AlterModelOptions(
            name="productimage",
            options={
                "ordering": ["order", "id"],
                "verbose_name": "Изображение товара",
                "verbose_name_plural": "Изображения товаров",
            },
        ),
        migrations.AddIndex(
            model_name="product",
            index=models.Index(
                fields=["availability"], name="product_availability_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="product",
            index=models.Index(
                fields=["published", "-created_at"],
                name="product_published_created_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="product",
            index=models.Index(
                fields=["category", "published"],
                name="product_category_published_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="product",
            index=models.Index(
                fields=["series", "published"],
                name="product_series_published_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="productimage",
            index=models.Index(
                fields=["product", "order"], name="productimage_order_idx"
            ),
        ),
        migrations.AddConstraint(
            model_name="productimage",
            constraint=models.UniqueConstraint(
                fields=["product", "order"], name="product_image_order_unique"
            ),
        ),
    ]
