"""
JSON-LD schema builders for carfst.ru (Organization, LocalBusiness, WebSite).
Used only on clean URLs (no GET params) — schema_allowed is enforced in templates.
"""
from django.conf import settings


def build_local_business_schema(
    request,
    site_settings=None,
    company_addresses=None,
    contact_phone_display="",
    contact_email_display="",
    contact_whatsapp_href="",
    contact_telegram_href="",
    contact_max_href="",
    logo_url="",
    image_url="",
    opening_hours=None,
):
    """
    Build LocalBusiness (AutoDealer) JSON-LD dict.
    Subtype: AutomotiveBusiness / AutoDealer for car/truck dealer.
    """
    canonical_host = getattr(settings, "CANONICAL_HOST", "carfst.ru")
    base_url = f"https://{canonical_host}"
    same_as = []
    for href in (contact_whatsapp_href, contact_telegram_href, contact_max_href):
        if href and (href or "").strip():
            same_as.append((href or "").strip())
    address_list = []
    if company_addresses:
        for addr in company_addresses:
            if isinstance(addr, dict) and addr.get("full_address"):
                address_list.append({
                    "@type": "PostalAddress",
                    "addressCountry": "RU",
                    "streetAddress": addr["full_address"],
                })
            elif isinstance(addr, str) and addr.strip():
                address_list.append({
                    "@type": "PostalAddress",
                    "addressCountry": "RU",
                    "streetAddress": addr.strip(),
                })
    schema = {
        "@context": "https://schema.org",
        "@type": ["LocalBusiness", "AutomotiveBusiness", "AutoDealer"],
        "@id": f"{base_url}/#localbusiness",
        "name": "CARFAST",
        "url": f"{base_url}/",
    }
    if logo_url:
        schema["logo"] = logo_url
    if image_url:
        schema["image"] = image_url
    if contact_phone_display and (contact_phone_display or "").strip():
        schema["telephone"] = (contact_phone_display or "").strip()
    if contact_email_display and (contact_email_display or "").strip():
        schema["email"] = (contact_email_display or "").strip()
    if address_list:
        schema["address"] = address_list
    if same_as:
        schema["sameAs"] = same_as
    if opening_hours and isinstance(opening_hours, (list, tuple)):
        schema["openingHoursSpecification"] = opening_hours
    elif opening_hours and isinstance(opening_hours, str) and opening_hours.strip():
        schema["openingHours"] = opening_hours.strip()
    return schema
