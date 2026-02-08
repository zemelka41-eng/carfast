import logging

import pytest
import requests
from django.core import mail
from django.test import override_settings


pytestmark = pytest.mark.django_db


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    EMAIL_HOST="smtp.example.com",
    EMAIL_HOST_USER="user",
    EMAIL_HOST_PASSWORD="pass",
    DEFAULT_FROM_EMAIL="no-reply@carfst.ru",
    LEADS_NOTIFY_EMAIL_TO=["info@carfst.ru"],
    TELEGRAM_BOT_TOKEN="test",
    TELEGRAM_CHAT_ID="123",
    LEADS_NOTIFY_ENABLE=True,
    LEADS_NOTIFY_TIMEOUT=3,
)
@pytest.mark.parametrize(
    "path,data",
    [
        (
            "/lead/",
            {
                "name": "Тест",
                "phone": "+7 (999) 000-00-00",
                "email": "test@example.com",
                "message": "Нужна консультация",
            },
        ),
        (
            "/contacts/",
            {
                "name": "Тест",
                "phone": "+7 (999) 000-00-00",
                "city": "Владивосток",
                "message": "Напишите мне",
                "consent": "on",
            },
        ),
    ],
)
def test_lead_notifications_sent(client, monkeypatch, path, data):
    calls = []

    def fake_post(url, data=None, timeout=None):
        calls.append({"url": url, "data": data, "timeout": timeout})

        class Response:
            status_code = 200
            text = "ok"

        return Response()

    monkeypatch.setattr("catalog.notifications.requests.post", fake_post)

    response = client.post(path, data)
    assert response.status_code == 302
    assert len(mail.outbox) == 1
    assert mail.outbox[0].subject == "CARFAST: новая заявка"
    assert calls
    assert calls[0]["timeout"] == 3
    assert "sendMessage" in calls[0]["url"]
    assert calls[0]["data"]["chat_id"] == "123"
    assert "CARFAST: новая заявка" in calls[0]["data"]["text"]


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    EMAIL_HOST="",
    EMAIL_HOST_USER="",
    EMAIL_HOST_PASSWORD="",
    DEFAULT_FROM_EMAIL="no-reply@carfst.ru",
    LEADS_NOTIFY_EMAIL_TO=["info@carfst.ru"],
    LEADS_NOTIFY_ENABLE=True,
    TELEGRAM_BOT_TOKEN="",
    TELEGRAM_CHAT_ID="",
)
def test_notifications_missing_config_logs_info(client, caplog, monkeypatch):
    def fail_post(*args, **kwargs):
        raise AssertionError("Telegram should not be called without credentials")

    monkeypatch.setattr("catalog.notifications.requests.post", fail_post)

    data = {
        "name": "Тест",
        "phone": "+7 (999) 000-00-00",
        "city": "Владивосток",
        "message": "Напишите мне",
        "consent": "on",
    }

    with caplog.at_level(logging.INFO, logger="catalog.notifications"):
        response = client.post("/contacts/", data, HTTP_X_FORWARDED_FOR="10.0.0.2")

    assert response.status_code == 302
    assert len(mail.outbox) == 0
    messages = [record.getMessage() for record in caplog.records]
    assert any("Email notifications disabled" in msg for msg in messages)
    assert any("Telegram notifications skipped" in msg for msg in messages)


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    EMAIL_HOST="smtp.example.com",
    EMAIL_HOST_USER="user",
    EMAIL_HOST_PASSWORD="pass",
    DEFAULT_FROM_EMAIL="no-reply@carfst.ru",
    LEADS_NOTIFY_EMAIL_TO=["info@carfst.ru"],
    LEADS_NOTIFY_ENABLE=True,
    TELEGRAM_BOT_TOKEN="test",
    TELEGRAM_CHAT_ID="123",
)
def test_telegram_error_does_not_break_form(client, caplog, monkeypatch):
    def fail_post(*args, **kwargs):
        raise requests.RequestException("boom")

    monkeypatch.setattr("catalog.notifications.requests.post", fail_post)

    data = {
        "name": "Тест",
        "phone": "+7 (999) 000-00-00",
        "email": "test@example.com",
        "message": "Нужна консультация",
    }

    with caplog.at_level(logging.WARNING, logger="catalog.notifications"):
        response = client.post("/lead/", data, HTTP_X_FORWARDED_FOR="10.0.0.3")

    assert response.status_code == 302
    messages = [record.getMessage() for record in caplog.records]
    assert any("Failed to send telegram notification" in msg for msg in messages)
