import json

from django.core.management.base import BaseCommand, CommandError

from carfst_site.health import run_health_checks


class Command(BaseCommand):
    help = "Run application health checks."

    def add_arguments(self, parser):
        parser.add_argument(
            "--json",
            action="store_true",
            help="Output the full health report as JSON for automation.",
        )

    def handle(self, *args, **options):
        as_json = options["json"]
        report = run_health_checks()
        status = report["status"]

        if as_json:
            self.stdout.write(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            for name, check in report.get("checks", {}).items():
                detail = check.get("detail")
                label = f"{name}: {check.get('status', 'unknown')}"
                if detail:
                    label = f"{label} - {detail}"
                if check.get("status") == "error":
                    self.stderr.write(self.style.ERROR(label))
                elif check.get("status") == "warning":
                    self.stdout.write(self.style.WARNING(label))
                elif check.get("status") == "skipped":
                    self.stdout.write(self.style.NOTICE(label) if hasattr(self.style, "NOTICE") else label)

        if status != "ok":
            for message in report.get("errors", []):
                self.stderr.write(self.style.ERROR(message))
            raise CommandError(f"Health checks {status}.")

        if not as_json:
            for message in report.get("warnings", []):
                self.stdout.write(self.style.WARNING(message))
            self.stdout.write(self.style.SUCCESS("Health checks passed."))
