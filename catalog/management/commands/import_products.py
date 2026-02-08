from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from catalog import importers


class Command(BaseCommand):
    help = "Импорт товаров из Excel с созданием серий, категорий и изображений."

    def add_arguments(self, parser):
        parser.add_argument("file_path", help="Путь к Excel-файлу (xlsx)")
        parser.add_argument(
            "media_dir",
            nargs="?",
            default=None,
            help="Каталог с изображениями (относительно MEDIA_ROOT или абсолютный путь)",
        )

    def handle(self, *args, **options):
        file_path = Path(options["file_path"])
        media_dir = options.get("media_dir")

        if not file_path.exists():
            raise CommandError(f"Файл {file_path} не найден")

        created, updated, errors = importers.run_import(file_path, media_dir)

        self.stdout.write(self.style.SUCCESS(f"Created: {created}"))
        self.stdout.write(self.style.SUCCESS(f"Updated: {updated}"))
        if errors:
            self.stdout.write(self.style.WARNING(f"Errors: {errors}"))
        else:
            self.stdout.write("Errors: 0")

