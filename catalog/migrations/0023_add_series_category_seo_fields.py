from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("catalog", "0022_alter_category_slug"),
    ]

    operations = [
        migrations.AddField(
            model_name="series",
            name="seo_description",
            field=models.TextField(
                blank=True,
                help_text="Короткое описание для витрины бренда. Если пусто — блок не показывается.",
                verbose_name="SEO описание (витрина бренда)",
            ),
        ),
        migrations.AddField(
            model_name="series",
            name="seo_faq",
            field=models.TextField(
                blank=True,
                help_text="Формат: один вопрос/ответ на строку, разделитель «|».",
                verbose_name="SEO FAQ (витрина бренда)",
            ),
        ),
        migrations.AddField(
            model_name="category",
            name="seo_description",
            field=models.TextField(
                blank=True,
                help_text="Короткое описание для витрины категории. Если пусто — блок не показывается.",
                verbose_name="SEO описание (витрина категории)",
            ),
        ),
        migrations.AddField(
            model_name="category",
            name="seo_faq",
            field=models.TextField(
                blank=True,
                help_text="Формат: один вопрос/ответ на строку, разделитель «|».",
                verbose_name="SEO FAQ (витрина категории)",
            ),
        ),
    ]
