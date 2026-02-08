# Generated manually for CatalogLandingSEO model

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("catalog", "0033_static_page_seo"),
    ]

    operations = [
        migrations.CreateModel(
            name="CatalogLandingSEO",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "landing_key",
                    models.CharField(
                        choices=[("catalog_in_stock", "/catalog/in-stock/")],
                        help_text="Уникальный ключ страницы: catalog_in_stock.",
                        max_length=50,
                        unique=True,
                        verbose_name="Ключ посадочной страницы",
                    ),
                ),
                (
                    "meta_title",
                    models.CharField(
                        blank=True,
                        default="",
                        help_text="Если заполнен — переопределяет title страницы.",
                        max_length=255,
                        verbose_name="Meta Title (переопределение)",
                    ),
                ),
                (
                    "meta_description",
                    models.CharField(
                        blank=True,
                        default="",
                        help_text="Если заполнен — переопределяет meta description страницы.",
                        max_length=500,
                        verbose_name="Meta Description (переопределение)",
                    ),
                ),
                (
                    "seo_intro_html",
                    models.TextField(
                        blank=True,
                        default="",
                        help_text="Короткий блок над листингом. HTML допускается.",
                        verbose_name="SEO-интро (над карточками)",
                    ),
                ),
                (
                    "seo_body_html",
                    models.TextField(
                        blank=True,
                        default="",
                        help_text="Развёрнутый блок под листингом. HTML допускается.",
                        verbose_name="SEO-блок под карточками",
                    ),
                ),
                (
                    "faq_items",
                    models.TextField(
                        blank=True,
                        default="",
                        help_text=(
                            "Один вопрос-ответ на строку, разделитель «|». "
                            "Пример: Какие сроки поставки?|Сроки зависят от наличия. "
                            "Рекомендуется 5–10 вопросов для FAQPage schema."
                        ),
                        verbose_name="FAQ (вопрос | ответ на строку)",
                    ),
                ),
            ],
            options={
                "verbose_name": "SEO каталожной посадочной",
                "verbose_name_plural": "SEO каталожных посадочных",
                "ordering": ["landing_key"],
            },
        ),
    ]
