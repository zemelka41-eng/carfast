import re

from django.core.management.base import BaseCommand

from blog.models import BlogPost, BlogPostImage


ANCHORS = {
    "lizing-kredit-ili-pokupka-za-svoi-2026": {
        2: "Что сравнивать в первую очередь",
        3: "Лизинг vs кредит vs покупка за свои",
        4: "Сценарии 2026",
        5: "Как сравнить варианты правильно: чек-лист",
        6: "Типовые ошибки",
    },
    "servis-ili-sam-sebe-master-kakie-raboty-po-kitayskim-gruzovikam-luchshe-ne-delat-bez-kvalifikatsii": {
        2: "Работы в сервис",
        3: "1) Тормозная система",
        4: "2) Рулевое управление",
        5: "3) Ступицы/подшипники/колеса",
        6: "4) Топливная система дизеля",
    },
    "utechka-vozduha-i-padaet-davlenie-diagnostika-pnevmosistemy": {
        2: "Визуальный осмотр",
        3: "Соединения, шланги, фитинги",
        4: "Осушитель и регулятор давления",
        5: "Тормозные камеры",
        6: "Таблица: симптом",
    },
}

FILE_PATTERNS = {
    "lizing-kredit-ili-pokupka-za-svoi-2026": r"lizing-kredit_(\d+)_",
    "servis-ili-sam-sebe-master-kakie-raboty-po-kitayskim-gruzovikam-luchshe-ne-delat-bez-kvalifikatsii": r"sam-sebe-master_(\d+)_",
    "utechka-vozduha-i-padaet-davlenie-diagnostika-pnevmosistemy": r"utechka-vozduha_(\d+)_",
}


class Command(BaseCommand):
    help = "Backfill @after anchors into BlogPostImage captions."

    def add_arguments(self, parser):
        parser.add_argument(
            "--slugs",
            nargs="*",
            help="Optional list of blog slugs to process.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print changes without saving.",
        )

    def handle(self, *args, **options):
        slugs = options.get("slugs") or list(ANCHORS.keys())
        dry_run = options.get("dry_run")
        updated = 0
        skipped = 0

        for slug in slugs:
            if slug not in ANCHORS:
                self.stdout.write(f"Skipped (unknown slug): {slug}")
                continue

            mapping = ANCHORS[slug]
            post = BlogPost.objects.filter(slug=slug).first()
            if not post:
                self.stdout.write(f"Post not found: {slug}")
                continue

            images = list(post.images.order_by("sort_order", "id"))
            if not images:
                self.stdout.write(f"No images for: {slug}")
                continue

            pattern = FILE_PATTERNS.get(slug)
            for img in images:
                caption = (img.caption or "").strip()
                if "@after:" in caption:
                    skipped += 1
                    continue

                file_name = (img.image.name or "").split("/")[-1]
                match = re.search(pattern, file_name, flags=re.IGNORECASE) if pattern else None
                if not match:
                    skipped += 1
                    continue
                index = int(match.group(1))
                anchor = mapping.get(index)
                if not anchor:
                    skipped += 1
                    continue

                new_caption = f"@after: {anchor}"
                if caption:
                    new_caption = f"{new_caption} | {caption}"

                if dry_run:
                    self.stdout.write(f"[DRY RUN] {slug}: {file_name} -> {new_caption}")
                    updated += 1
                    continue

                img.caption = new_caption
                img.save(update_fields=["caption"])
                updated += 1

            self.stdout.write(f"Anchors processed: {slug}")

        self.stdout.write(f"Updated: {updated}, skipped: {skipped}")
