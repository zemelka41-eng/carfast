# Generated manually

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('catalog', '0024_add_series_category_seo'),
    ]

    operations = [
        migrations.AddField(
            model_name='sitesettings',
            name='in_stock_seo_description',
            field=models.TextField(blank=True, verbose_name='SEO описание: В наличии'),
        ),
        migrations.AddField(
            model_name='sitesettings',
            name='in_stock_seo_faq',
            field=models.TextField(blank=True, help_text='Формат: Вопрос|Ответ построчно', verbose_name='SEO FAQ: В наличии'),
        ),
    ]
