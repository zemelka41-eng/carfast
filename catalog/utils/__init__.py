import logging
import urllib.parse

import requests
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string

logger = logging.getLogger(__name__)


def send_email(subject, template, context, recipients):
    """
    Send email notification. If email is not configured, logs warning instead of failing.
    
    Returns True if email was sent successfully, False otherwise.
    """
    if not recipients:
        logger.warning("No recipients provided for email: %s", subject)
        return False
    
    # Check if email is configured
    email_host = getattr(settings, "EMAIL_HOST", "")
    email_user = getattr(settings, "EMAIL_HOST_USER", "")
    email_configured = bool(email_host and email_host != "localhost" and email_user)
    
    if not email_configured:
        logger.warning(
            "Email disabled: EMAIL_HOST=%s, EMAIL_HOST_USER=%s. "
            "Set EMAIL_HOST, EMAIL_HOST_USER, EMAIL_HOST_PASSWORD to enable. "
            "Site will continue to work, but lead notifications will not be sent.",
            email_host or "not set",
            email_user or "not set",
        )
        return False
    
    try:
        html_content = render_to_string(template, context)
        msg = EmailMultiAlternatives(
            subject=subject,
            body=html_content,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=recipients,
        )
        msg.attach_alternative(html_content, "text/html")
        sent_count = msg.send(fail_silently=False)
        if sent_count:
            logger.info("Email sent successfully: '%s' to %s", subject, recipients)
            return True
        else:
            logger.warning("Email send returned 0: '%s' to %s", subject, recipients)
            return False
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to send email '%s' to %s: %s", subject, recipients, exc, exc_info=True)
        return False


def send_telegram_message(text):
    token = getattr(settings, "TELEGRAM_BOT_TOKEN", None)
    chat_id = getattr(settings, "TELEGRAM_CHAT_ID", None)
    if not token or not chat_id:
        from .site_settings import get_site_settings_safe

        s = get_site_settings_safe()
        if s:
            token = token or s.telegram_bot_token
            chat_id = chat_id or s.telegram_chat_id
    if not token or not chat_id:
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        requests.post(url, data={"chat_id": chat_id, "text": text}, timeout=5)
    except requests.RequestException as exc:
        logger.warning("Failed to send telegram message: %s", exc)


def generate_whatsapp_link(number, message):
    if not number:
        return ""
    encoded = urllib.parse.quote_plus(message or "")
    return f"https://wa.me/{number}?text={encoded}"
