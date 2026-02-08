# Generated manually: ShacmanHubSEO.force_index for white-list thin hub indexing

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("catalog", "0037_shacmanhubseo_facet_key"),
    ]

    operations = [
        migrations.AddField(
            model_name="shacmanhubseo",
            name="force_index",
            field=models.BooleanField(
                default=False,
                help_text="Если включено и контент достаточный (текст/body ≥1500 символов или FAQ ≥3), хаб с 1 товаром может быть index,follow и в sitemap.",
                verbose_name="Индексировать при малом числе товаров",
            ),
        ),
    ]
