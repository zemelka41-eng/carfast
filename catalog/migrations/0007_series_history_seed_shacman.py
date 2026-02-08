from django.db import migrations, models


SHACMAN_HISTORY = (
    "SHACMAN — бренд грузовой техники и решений для коммерческой эксплуатации. "
    "В линейке встречаются шасси, самосвалы, тягачи и другие типы техники — "
    "в зависимости от задач и требуемой комплектации.\n\n"
    "Техника бренда применяется в строительстве, логистике, на производственных площадках и в карьерах, "
    "когда важны надёжность, ремонтопригодность и прогнозируемые сроки обслуживания.\n\n"
    "CARFAST сопровождает поставку техники SHACMAN: помогает подобрать конфигурацию под условия работы, "
    "подготовить документы и организовать сервисную поддержку."
)


def seed_shacman(apps, schema_editor):
    Series = apps.get_model("catalog", "Series")

    series = Series.objects.filter(slug__iexact="shacman").first()
    if series is None:
        Series.objects.create(slug="shacman", name="SHACMAN", history=SHACMAN_HISTORY)
        return

    update_fields = []

    if (series.slug or "").lower() == "shacman" and series.slug != "shacman":
        series.slug = "shacman"
        update_fields.append("slug")

    if series.name != "SHACMAN":
        series.name = "SHACMAN"
        update_fields.append("name")

    if not (getattr(series, "history", "") or "").strip():
        series.history = SHACMAN_HISTORY
        update_fields.append("history")

    if update_fields:
        series.save(update_fields=update_fields)


class Migration(migrations.Migration):
    dependencies = [
        ("catalog", "0006_case_insensitive_constraints"),
    ]

    operations = [
        migrations.AddField(
            model_name="series",
            name="history",
            field=models.TextField(blank=True, default="", verbose_name="История бренда"),
        ),
        migrations.RunPython(seed_shacman, migrations.RunPython.noop),
    ]
