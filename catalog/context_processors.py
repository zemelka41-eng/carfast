import json
from urllib.parse import quote

from django.conf import settings

from .models import Category, Series
from .schema import build_local_business_schema
from .utils.contacts import build_contact_links
from .utils.site_settings import get_site_settings_safe


DEFAULT_CONTACTS = {
    "phone": "+7 (961) 269-41-69",
    "whatsapp": "+7 (961) 269-41-69",
    "telegram_phone": "+7 (961) 269-41-69",
    "email": "info@carfst.ru",
}

# Fallback значения для адресов и реквизитов (используются только при рендере, если поля пустые)
DEFAULT_OFFICE_ADDRESS_1 = "Новорязанское ш., 6, Котельники, Московская обл., 140054"
DEFAULT_OFFICE_ADDRESS_2 = "410005, Саратовская область, г. Саратов, ул. Б.Садовая, дом 239, БЦ «Навигатор», офис 501"
DEFAULT_INN = "2536339021"
DEFAULT_OGRN = "1232500012348"
DEFAULT_LEGAL_ADDRESS = "690091, Приморский край, г. Владивосток, ул. Суханова, д. 4 Б, помещ 1"


def site_settings(request):
    settings_obj = get_site_settings_safe()
    request.site_settings = settings_obj
    nav_series_list = Series.objects.public().only("name", "slug", "logo", "logo_alt_ru")
    nav_category_list = Category.objects.all().only("name", "slug", "cover_image", "cover_alt_ru")

    phone = getattr(settings_obj, "phone", "") if settings_obj else ""
    whatsapp = getattr(settings_obj, "whatsapp_number", "") if settings_obj else ""
    telegram = getattr(settings_obj, "telegram_chat_id", "") if settings_obj else ""
    email = getattr(settings_obj, "email", "") if settings_obj else ""

    contact = build_contact_links(
        phone_raw=phone,
        whatsapp_raw=whatsapp,
        telegram_raw=telegram,
        email_raw=email,
        defaults=DEFAULT_CONTACTS,
    )
    contact_max_href = (getattr(settings, "CONTACT_MAX_URL", "") or "").strip()
    
    # Auto-generate canonical URL using canonical host
    # Views can override this by passing 'canonical' in their context
    # Policy: canonical always without querystring (clean URL)
    # Exceptions (self-canonical with ?page=N) are handled in views where needed (e.g., catalog_in_stock)
    canonical_host = getattr(settings, "CANONICAL_HOST", "carfst.ru")
    canonical = f"https://{canonical_host}{request.path}"
    
    # Check for GET parameters
    query_string = request.META.get("QUERY_STRING", "")
    has_get_params = bool(query_string)
    
    # Schema allowed only on completely clean URLs (no GET params at all)
    schema_allowed = not has_get_params
    # 404 view sets request.schema_disabled = True and schema_disabled=True in context to disable all JSON-LD
    schema_disabled = getattr(request, "schema_disabled", False)
    
    # Подготовка адресов компании
    office_address_1 = getattr(settings_obj, "office_address_1", "") if settings_obj else ""
    office_address_2 = getattr(settings_obj, "office_address_2", "") if settings_obj else ""
    
    company_addresses = []
    if office_address_1 or DEFAULT_OFFICE_ADDRESS_1:
        addr1 = office_address_1 or DEFAULT_OFFICE_ADDRESS_1
        company_addresses.append({
            "title": "Офис (МО)",
            "label": "Офис (МО)",
            "full_address": addr1,
            "yandex_maps_url": f"https://yandex.ru/maps/?text={quote(addr1)}",
            "google_maps_url": f"https://www.google.com/maps/search/?api=1&query={quote(addr1)}",
        })
    if office_address_2 or DEFAULT_OFFICE_ADDRESS_2:
        addr2 = office_address_2 or DEFAULT_OFFICE_ADDRESS_2
        company_addresses.append({
            "title": "Главный офис дилера (Саратов)",
            "label": "Главный офис дилера (Саратов)",
            "full_address": addr2,
            "yandex_maps_url": f"https://yandex.ru/maps/?text={quote(addr2)}",
            "google_maps_url": f"https://www.google.com/maps/search/?api=1&query={quote(addr2)}",
        })
    
    # Подготовка реквизитов компании
    inn = getattr(settings_obj, "inn", "") if settings_obj else ""
    ogrn = getattr(settings_obj, "ogrn", "") if settings_obj else ""
    legal_address = getattr(settings_obj, "legal_address", "") if settings_obj else ""
    
    company_requisites = {
        "inn": inn or DEFAULT_INN,
        "ogrn": ogrn or DEFAULT_OGRN,
        "legal_address": legal_address or DEFAULT_LEGAL_ADDRESS,
    }
    
    # LocalBusiness JSON-LD (only built; template outputs only when schema_allowed)
    local_business_schema = build_local_business_schema(
        request,
        site_settings=settings_obj,
        company_addresses=company_addresses,
        contact_phone_display=contact.get("phone_display", ""),
        contact_email_display=contact.get("email_display", ""),
        contact_whatsapp_href=contact.get("whatsapp_href", ""),
        contact_telegram_href=contact.get("telegram_href", ""),
        contact_max_href=contact_max_href,
    )
    local_business_schema_json = json.dumps(local_business_schema, ensure_ascii=False)
    
    # SearchAction only if real search page exists (e.g. /search/ noindex)
    search_action_target = getattr(settings, "SEARCH_ACTION_TARGET", None)
    
    return {
        "site_settings": settings_obj,
        "nav_series_list": nav_series_list,
        "nav_category_list": nav_category_list,
        "contact_phone_display": contact.get("phone_display", ""),
        "contact_phone_href": contact.get("phone_href", ""),
        "contact_whatsapp_href": contact.get("whatsapp_href", ""),
        "contact_telegram_href": contact.get("telegram_href", ""),
        "contact_max_href": contact_max_href,
        "contact_email_display": contact.get("email_display", ""),
        "contact_email_href": contact.get("email_href", ""),
        "canonical": canonical,
        "schema_allowed": schema_allowed,  # Flag to control page_schema_payload rendering
        "schema_disabled": schema_disabled,  # 404 sets True to disable all JSON-LD
        "company_addresses": company_addresses,
        "company_requisites": company_requisites,
        "local_business_schema_json": local_business_schema_json,
        "search_action_target": search_action_target,
    }

