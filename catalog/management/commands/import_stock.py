from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from catalog.services.import_stock import import_stock


class Command(BaseCommand):
    help = "Импорт остатков/предложений из XLSX (города/цены/кол-ва)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--file",
            required=True,
            help="Путь к XLSX файлу (например: Наличие ООО КАРФАСТ 08.12.2025.xlsx)",
        )
        parser.add_argument(
            "--sheet",
            default=None,
            help='Название листа (если не указано — активный). Например: "Table 1"',
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Показать отчёт без записи в БД",
        )
        parser.add_argument(
            "--deactivate-missing",
            type=int,
            choices=[0, 1],
            default=0,
            help="Если 1 — деактивировать предложения из этого файла, которых нет в новом импорте",
        )

    def handle(self, *args, **options):
        file_path = Path(options["file"])
        if not file_path.exists():
            raise CommandError(f"Файл не найден: {file_path}")

        report = import_stock(
            file=file_path,
            file_name=file_path.name,
            sheet=options.get("sheet"),
            dry_run=bool(options.get("dry_run")),
            deactivate_missing=bool(options.get("deactivate_missing")),
        )

        prefix = "DRY-RUN" if options.get("dry_run") else "APPLIED"
        self.stdout.write(self.style.SUCCESS(f"[{prefix}] {report.file_name} / {report.sheet_name}"))
        self.stdout.write(
            f"Rows: parsed={report.parsed_rows}, skipped={report.skipped_rows}, errors={len(report.errors or [])}"
        )
        self.stdout.write(
            "Created: "
            f"series={report.created_series}, categories={report.created_categories}, cities={report.created_cities}, "
            f"products={report.created_products}, offers={report.created_offers}"
        )
        self.stdout.write(
            "Updated: "
            f"products={report.updated_products}, offers={report.updated_offers}"
        )
        if report.deactivated_offers:
            self.stdout.write(self.style.WARNING(f"Deactivated offers: {report.deactivated_offers}"))

        if report.errors:
            self.stdout.write(self.style.WARNING("Errors:"))
            for err in report.errors[:50]:
                self.stdout.write(f"- row {err.get('row')}: {err.get('message')}")
            if len(report.errors) > 50:
                self.stdout.write(f"... and {len(report.errors) - 50} more")
