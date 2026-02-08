from django.db import migrations


SHACMAN_HISTORY = """
SHACMAN — марка тяжёлой грузовой техники, созданная для коммерческой эксплуатации: там, где важны выносливость, ремонтопригодность и стабильная работа в нагрузке. Техника проектируется под реальные условия — строительные площадки, логистику, промышленность и работы вне идеального асфальта.

Линейка SHACMAN сформировалась вокруг прикладных задач бизнеса: перевозка сыпучих материалов, магистральные маршруты, работа с прицепами и полуприцепами, эксплуатация в регионах с разными климатическими условиями. Поэтому в модельном ряду встречаются шасси, тягачи, самосвалы и другие конфигурации — под конкретный сценарий, а не “универсально для всего”.

Почему SHACMAN выбирают для работы:
• Надёжность в нагрузке и понятная сервисная логика.
• Практичная комплектация под задачу: осевая формула, надстройки, опции кабины, подготовка к условиям эксплуатации.
• Ремонтопригодность и фокус на быстром возврате техники в работу.
• Экономика владения: подбор конфигурации под маршрут и груз снижает лишние расходы.

CARFAST — официальный дилер SHACMAN. Мы сопровождаем поставку “под ключ”: помогаем подобрать конфигурацию, подготовить документы, согласовать условия поставки и организовать сервисную поддержку. Если техника нужна в лизинг — подберём программу и поможем с пакетом документов.

Оставьте заявку — уточним задачу и подготовим коммерческое предложение с оптимальной конфигурацией и условиями поставки.
""".strip()


SITRAK_HISTORY = """
SITRAK — бренд коммерческой грузовой техники, ориентированный на магистральные перевозки и интенсивную эксплуатацию. Решения подбираются под условия работы и требования к комплектации, где важны ресурс, стабильность и предсказуемое обслуживание.

CARFAST поможет подобрать конфигурацию SITRAK под задачу, подготовит коммерческое предложение и предложит оптимальные условия поставки.
""".strip()


DAYUN_HISTORY = """
DAYUN — бренд коммерческой техники для практичных задач бизнеса, где важны удобство эксплуатации и ремонтопригодность. Конфигурации позволяют подобрать решение под тип работ и условия эксплуатации.

CARFAST подберёт технику DAYUN под вашу задачу и подготовит КП. Оставьте заявку — уточним требования и предложим подходящую комплектацию.
""".strip()


OLD_SHACMAN_HISTORY = (
    "SHACMAN — бренд грузовой техники и решений для коммерческой эксплуатации. "
    "В линейке встречаются шасси, самосвалы, тягачи и другие типы техники — "
    "в зависимости от задач и требуемой комплектации.\n\n"
    "Техника бренда применяется в строительстве, логистике, на производственных площадках и в карьерах, "
    "когда важны надёжность, ремонтопригодность и прогнозируемые сроки обслуживания.\n\n"
    "CARFAST сопровождает поставку техники SHACMAN: помогает подобрать конфигурацию под условия работы, "
    "подготовить документы и организовать сервисную поддержку."
)


def seed_brands(apps, schema_editor):
    Series = apps.get_model("catalog", "Series")

    def upsert_series(slug: str, name: str, history: str, *, update_seed_history=False):
        series = Series.objects.filter(slug__iexact=slug).first()
        if series is None:
            Series.objects.create(slug=slug, name=name, history=history)
            return

        update_fields = []

        if (series.slug or "").lower() == slug and series.slug != slug:
            series.slug = slug
            update_fields.append("slug")

        if series.name != name:
            series.name = name
            update_fields.append("name")

        current_history = (getattr(series, "history", "") or "").strip()
        if not current_history:
            series.history = history
            update_fields.append("history")
        elif update_seed_history and current_history == OLD_SHACMAN_HISTORY.strip():
            series.history = history
            update_fields.append("history")

        if update_fields:
            series.save(update_fields=update_fields)

    upsert_series("shacman", "SHACMAN", SHACMAN_HISTORY, update_seed_history=True)
    upsert_series("sitrak", "SITRAK", SITRAK_HISTORY)
    upsert_series("dayun", "DAYUN", DAYUN_HISTORY)


class Migration(migrations.Migration):
    dependencies = [
        ("catalog", "0007_series_history_seed_shacman"),
    ]

    operations = [
        migrations.RunPython(seed_brands, migrations.RunPython.noop),
    ]

