from django.db import migrations


REPLACEMENTS = {
    "CARFAST — официальный представитель SHACMAN": "CARFAST — официальный дилер SHACMAN",
    "Официальный представитель SHACMAN": "Официальный дилер SHACMAN",
    "SHACMAN — официальный представитель": "SHACMAN — официальный дилер",
}


def update_series_texts(apps, schema_editor):
    Series = apps.get_model("catalog", "Series")

    for series in Series.objects.all().iterator():
        changed_fields = []

        history = getattr(series, "history", "") or ""
        new_history = history
        for old, new in REPLACEMENTS.items():
            new_history = new_history.replace(old, new)
        if new_history != history:
            series.history = new_history
            changed_fields.append("history")

        # Optional: handle legacy fields if used as fallbacks for brand pages.
        desc_ru = getattr(series, "description_ru", "") or ""
        new_desc_ru = desc_ru
        for old, new in REPLACEMENTS.items():
            new_desc_ru = new_desc_ru.replace(old, new)
        if new_desc_ru != desc_ru:
            series.description_ru = new_desc_ru
            changed_fields.append("description_ru")

        desc_en = getattr(series, "description_en", "") or ""
        new_desc_en = desc_en
        for old, new in REPLACEMENTS.items():
            new_desc_en = new_desc_en.replace(old, new)
        if new_desc_en != desc_en:
            series.description_en = new_desc_en
            changed_fields.append("description_en")

        if changed_fields:
            series.save(update_fields=changed_fields)


class Migration(migrations.Migration):
    dependencies = [
        ("catalog", "0009_product_config_product_is_active_product_model_code_and_more"),
    ]

    operations = [
        migrations.RunPython(update_series_texts, migrations.RunPython.noop),
    ]
