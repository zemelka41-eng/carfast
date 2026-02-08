from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("catalog", "0020_product_wheelbase_mm"),
    ]

    operations = [
        migrations.AlterField(
            model_name="product",
            name="slug",
            field=models.SlugField(max_length=80, unique=True, verbose_name="URL"),
        ),
    ]
