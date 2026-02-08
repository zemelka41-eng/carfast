"""
Management command to test lead email notifications.

Usage:
    python manage.py test_lead_email
    python manage.py test_lead_email --recipient test@example.com
"""

from django.conf import settings
from django.core.management.base import BaseCommand
from django.urls import reverse

from catalog.models import Lead, Product
from catalog.utils import send_email
from catalog.utils.site_settings import get_site_settings_safe


class Command(BaseCommand):
    help = "Test lead email notification system"

    def add_arguments(self, parser):
        parser.add_argument(
            "--recipient",
            type=str,
            help="Override recipient email (default: use LEAD_NOTIFY_EMAILS or SiteSettings.email)",
        )

    def handle(self, *args, **options):
        self.stdout.write("Testing lead email notification system...\n")

        # Check email configuration
        email_host = getattr(settings, "EMAIL_HOST", "")
        email_user = getattr(settings, "EMAIL_HOST_USER", "")
        email_configured = bool(email_host and email_host != "localhost" and email_user)

        if not email_configured:
            self.stdout.write(
                self.style.WARNING(
                    "⚠ Email not configured:\n"
                    f"  EMAIL_HOST={email_host or 'not set'}\n"
                    f"  EMAIL_HOST_USER={email_user or 'not set'}\n"
                    "  Set EMAIL_HOST, EMAIL_HOST_USER, EMAIL_HOST_PASSWORD to enable email.\n"
                )
            )
            return

        # Determine recipients
        recipient_override = options.get("recipient")
        if recipient_override:
            recipients = [recipient_override]
            self.stdout.write(f"Using override recipient: {recipient_override}\n")
        else:
            recipients = list(getattr(settings, "LEAD_NOTIFY_EMAILS", []) or [])
            settings_obj = get_site_settings_safe()
            if settings_obj and settings_obj.email and settings_obj.email not in recipients:
                recipients.append(settings_obj.email)

            if not recipients:
                self.stdout.write(
                    self.style.ERROR(
                        "❌ No recipients configured:\n"
                        "  - LEAD_NOTIFY_EMAILS is empty\n"
                        "  - SiteSettings.email is not set\n"
                        "  Use --recipient test@example.com to test with a specific email.\n"
                    )
                )
                return

            self.stdout.write(f"Recipients: {len(recipients)} email(s)\n")

        # Create a test lead (or use existing)
        test_product = Product.objects.first()
        test_lead, created = Lead.objects.get_or_create(
            name="Тестовая заявка",
            phone="+7 (999) 123-45-67",
            defaults={
                "email": "test@example.com",
                "message": "Это тестовое сообщение для проверки системы уведомлений.",
                "product": test_product,
                "source": "test_command",
            },
        )

        if created:
            self.stdout.write(f"Created test lead: {test_lead.id}\n")
        else:
            self.stdout.write(f"Using existing test lead: {test_lead.id}\n")

        # Build admin URL (if possible)
        try:
            from django.contrib.sites.models import Site
            from django.urls import reverse

            current_site = Site.objects.get_current()
            admin_url = f"https://{current_site.domain}/admin/catalog/lead/{test_lead.id}/change/"
        except Exception:  # noqa: BLE001
            admin_url = None

        # Prepare context
        context = {
            "lead": test_lead,
            "request": None,  # No request object in management command
        }

        # Send test email
        subject = f"[TEST] Новая заявка от {test_lead.name}"
        self.stdout.write(f"Sending test email...\n")
        self.stdout.write(f"  Subject: {subject}\n")
        self.stdout.write(f"  Recipients: {', '.join(recipients)}\n")

        result = send_email(subject, "emails/lead_notification.html", context, recipients)
        if result:
            self.stdout.write(
                self.style.SUCCESS(
                    "\n✅ Email sent successfully!\n"
                    "Check your inbox (and spam folder) for the test message.\n"
                )
            )
            if admin_url:
                self.stdout.write(f"Test lead in admin: {admin_url}\n")
        else:
            self.stdout.write(
                self.style.ERROR(
                    "\n❌ Failed to send email. Check logs for details.\n"
                )
            )

        # Cleanup (optional)
        if created:
            cleanup = input("\nDelete test lead? (y/N): ").strip().lower()
            if cleanup == "y":
                test_lead.delete()
                self.stdout.write("Test lead deleted.\n")

