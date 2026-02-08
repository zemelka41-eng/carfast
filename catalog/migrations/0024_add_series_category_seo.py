from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("catalog", "0023_add_series_category_seo_fields"),
    ]

    operations = [
        migrations.CreateModel(
            name="SeriesCategorySEO",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "seo_description",
                    models.TextField(
                        blank=True,
                        help_text="Короткое описание для витрины series+category. Если пусто — блок не показывается.",
                        verbose_name="SEO описание",
                    ),
                ),
                (
                    "seo_faq",
                    models.TextField(
                        blank=True,
                        help_text='Формат: один вопрос/ответ на строку, разделитель «|».',
                        verbose_name="SEO FAQ",
                    ),
                ),
                (
                    "category",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="series_category_seo",
                        to="catalog.category",
                        verbose_name="Категория",
                    ),
                ),
                (
                    "series",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="series_category_seo",
                        to="catalog.series",
                        verbose_name="Бренд",
                    ),
                ),
            ],
            options={
                "verbose_name": "SEO контент (series+category)",
                "verbose_name_plural": "SEO контент (series+category)",
                "ordering": ["series__name", "category__name"],
            },
        ),
        migrations.AddConstraint(
            model_name="seriescategoryseo",
            constraint=models.UniqueConstraint(
                fields=("series", "category"),
                name="series_category_seo_unique",
            ),
        ),
    ]
