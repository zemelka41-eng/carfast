import logging

import requests
from django.conf import settings
from django.core.mail import send_mail

logger = logging.getLogger(__name__)


def _get_recipients() -> list[str]:
    recipients = list(getattr(settings, "LEADS_NOTIFY_EMAIL_TO", []) or [])
    if not recipients:
        recipients = list(getattr(settings, "LEAD_NOTIFY_EMAILS", []) or [])
    return [email for email in recipients if email]


def _email_configured() -> bool:
    email_host = getattr(settings, "EMAIL_HOST", "")
    email_user = getattr(settings, "EMAIL_HOST_USER", "")
    return bool(email_host and email_host != "localhost" and email_user)


def _format_message(lead_data: dict, source: str) -> str:
    lines = [
        "CARFAST: новая заявка",
        f"Источник: {source or 'не указан'}",
        f"Страница: {lead_data.get('page', '') or 'не указана'}",
        f"URL страницы: {lead_data.get('page_url', '') or 'не указан'}",
        "",
        f"Имя: {lead_data.get('name', '') or 'не указано'}",
        f"Телефон: {lead_data.get('phone', '') or 'не указан'}",
        f"Email: {lead_data.get('email', '') or 'не указан'}",
        f"Город: {lead_data.get('city', '') or 'не указан'}",
        f"Сообщение: {lead_data.get('message', '') or 'не указано'}",
        "",
        f"User-Agent: {lead_data.get('user_agent', '') or 'не указан'}",
        f"IP: {lead_data.get('ip', '') or 'не указан'}",
    ]

    referrer = lead_data.get("referrer")
    if referrer:
        lines.append(f"Referrer: {referrer}")

    utm_fields = [
        ("utm_source", "UTM source"),
        ("utm_medium", "UTM medium"),
        ("utm_campaign", "UTM campaign"),
        ("utm_term", "UTM term"),
        ("utm_content", "UTM content"),
    ]
    for key, label in utm_fields:
        value = lead_data.get(key)
        if value:
            lines.append(f"{label}: {value}")

    return "\n".join(lines)


def send_lead_notification(lead_data: dict, source: str) -> None:
    """
    Best-effort notification for leads/contacts.
    """
    if not getattr(settings, "LEADS_NOTIFY_ENABLE", True):
        logger.info("Lead notifications disabled by LEADS_NOTIFY_ENABLE")
        return

    subject = "CARFAST: новая заявка"
    message = _format_message(lead_data, source)

    recipients = _get_recipients()
    if recipients and _email_configured():
        try:
            send_mail(
                subject=subject,
                message=message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=recipients,
                fail_silently=False,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to send lead email notification: %s", exc, exc_info=True)
    else:
        logger.warning("Email notifications disabled or recipients not set")

    token = getattr(settings, "TELEGRAM_BOT_TOKEN", "")
    chat_id = getattr(settings, "TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        logger.info("Telegram notifications skipped: missing TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID")
        return

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    timeout = getattr(settings, "LEADS_NOTIFY_TIMEOUT", 3)
    try:
        response = requests.post(
            url,
            data={"chat_id": chat_id, "text": message},
            timeout=timeout,
        )
        if response.status_code >= 400:
            logger.warning(
                "Telegram notification failed: status=%s body=%s",
                response.status_code,
                getattr(response, "text", "") or "",
            )
    except requests.RequestException as exc:
        logger.warning("Failed to send telegram notification: %s", exc, exc_info=True)
