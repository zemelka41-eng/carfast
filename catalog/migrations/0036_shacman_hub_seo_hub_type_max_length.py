# Generated manually for hub_type max_length (fields.E009: choices longer than 32)

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("catalog", "0035_shacman_hub_seo_combo_types"),
    ]

    operations = [
        migrations.AlterField(
            model_name="shacmanhubseo",
            name="hub_type",
            field=models.CharField(
                choices=[
                    ("main", "Главный хаб /shacman/"),
                    ("in_stock", "В наличии /shacman/in-stock/"),
                    ("category", "Категория /shacman/<category>/"),
                    ("category_in_stock", "Категория в наличии /shacman/<category>/in-stock/"),
                    ("formula", "Формула /shacman/formula/<formula>/"),
                    ("formula_in_stock", "Формула в наличии /shacman/formula/<formula>/in-stock/"),
                    ("engine", "Двигатель /shacman/engine/<engine>/"),
                    ("engine_in_stock", "Двигатель в наличии /shacman/engine/<engine>/in-stock/"),
                    ("line", "Линейка /shacman/line/<line>/"),
                    ("line_in_stock", "Линейка в наличии /shacman/line/<line>/in-stock/"),
                    ("category_line", "Категория + линейка /shacman/category/<cat>/line/<line>/"),
                    ("category_line_in_stock", "Категория + линейка в наличии"),
                    ("line_formula", "Линейка + формула /shacman/line/<line>/formula/<formula>/"),
                    ("line_formula_in_stock", "Линейка + формула в наличии"),
                    ("category_formula_explicit", "Категория + формула /shacman/category/<cat>/formula/<formula>/"),
                    ("category_formula_explicit_in_stock", "Категория + формула в наличии"),
                ],
                max_length=50,
                verbose_name="Тип хаба",
            ),
        ),
    ]
