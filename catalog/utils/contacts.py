import re


_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def digits(s: object) -> str:
    """Return only digits from input."""
    if s is None:
        return ""
    return "".join(ch for ch in str(s) if ch.isdigit())


def normalize_ru_phone_to_e164(raw: object) -> str | None:
    """Normalize RU phone to E.164: +7XXXXXXXXXX.

    Accepts inputs like "+7 (961) 269-41-69", "89612694169", "79612694169".

    Rules:
    - 8XXXXXXXXXX -> 7XXXXXXXXXX
    - 10 digits -> 7 + 10 digits
    - result must be 11 digits and start with 7
    """

    d = digits(raw)
    if not d:
        return None

    if len(d) == 11 and d.startswith("8"):
        d = "7" + d[1:]
    elif len(d) == 10:
        d = "7" + d

    if len(d) != 11 or not d.startswith("7"):
        return None

    return "+" + d


def format_ru_phone_display(e164: object) -> str:
    """Format E.164 RU phone as: +7 (XXX) XXX-XX-XX."""

    d = digits(e164)
    if len(d) != 11 or not d.startswith("7"):
        return ""

    code = d[1:4]
    p1 = d[4:7]
    p2 = d[7:9]
    p3 = d[9:11]
    return f"+7 ({code}) {p1}-{p2}-{p3}"


def build_contact_links(
    phone_raw: object,
    whatsapp_raw: object,
    telegram_raw: object,
    email_raw: object,
    defaults: dict,
) -> dict:
    """Build normalized contact links with safe defaults."""

    defaults = defaults or {}

    def _pick(primary: object, fallback_key: str) -> object:
        value = (str(primary).strip() if primary is not None else "")
        if value:
            return value
        return defaults.get(fallback_key, "")

    phone_source = _pick(phone_raw, "phone")
    whatsapp_source = _pick(whatsapp_raw, "whatsapp")
    telegram_source = _pick(telegram_raw, "telegram_phone")
    email_source = _pick(email_raw, "email")

    phone_e164 = normalize_ru_phone_to_e164(phone_source) or normalize_ru_phone_to_e164(
        defaults.get("phone", "")
    )
    phone_display = format_ru_phone_display(phone_e164)
    phone_href = f"tel:{phone_e164}" if phone_e164 else ""

    whatsapp_e164 = (
        normalize_ru_phone_to_e164(whatsapp_source)
        or normalize_ru_phone_to_e164(defaults.get("whatsapp", ""))
        or phone_e164
    )
    whatsapp_digits11 = digits(whatsapp_e164)
    whatsapp_href = f"https://wa.me/{whatsapp_digits11}" if whatsapp_digits11 else ""

    telegram_e164 = (
        normalize_ru_phone_to_e164(telegram_source)
        or normalize_ru_phone_to_e164(defaults.get("telegram_phone", ""))
        or phone_e164
    )
    telegram_digits11 = digits(telegram_e164)
    telegram_href = (
        f"tg://resolve?phone={telegram_digits11}" if telegram_digits11 else ""
    )

    def _normalize_email(raw: object) -> str:
        s = (str(raw).strip() if raw is not None else "")
        if not s:
            return ""
        # Drop obvious placeholder/template artifacts (seen in prod)
        # Check for markdown header artifacts (3+ hash symbols), template comments, and placeholders
        if "###" in s or "{#" in s or "Inline SVG placeholder" in s:
            return ""
        if not _EMAIL_RE.match(s):
            return ""
        return s

    email_display = _normalize_email(email_source) or _normalize_email(defaults.get("email", ""))
    email_href = f"mailto:{email_display}" if email_display else ""

    return {
        "phone_display": phone_display,
        "phone_href": phone_href,
        "whatsapp_href": whatsapp_href,
        "telegram_href": telegram_href,
        "email_display": email_display,
        "email_href": email_href,
    }
