from __future__ import annotations

from datetime import timedelta

from django import template
from django.urls import reverse
from django.utils import timezone

from catalog.models import Lead, Offer, Product

register = template.Library()


def _safe_reverse(name: str) -> str | None:
    try:
        return reverse(name)
    except Exception:  # noqa: BLE001
        return None


@register.inclusion_tag("admin/carfast_dashboard.html", takes_context=True)
def carfast_admin_dashboard(context):
    request = context.get("request")
    user = getattr(request, "user", None)

    def has_perm(codename: str) -> bool:
        return bool(user and user.has_perm(codename))

    now = timezone.now()
    since = now - timedelta(days=7)

    can_view_leads = has_perm("catalog.view_lead")
    can_view_products = has_perm("catalog.view_product")
    can_view_offers = has_perm("catalog.view_offer")

    leads_new_7d = Lead.objects.filter(created_at__gte=since).count() if can_view_leads else None
    leads_in_progress = Lead.objects.filter(processed=False).count() if can_view_leads else None

    products_total = Product.objects.count() if can_view_products else None
    offers_total = Offer.objects.count() if can_view_offers else None

    quick_links: list[dict[str, object]] = []

    add_product_url = _safe_reverse("admin:catalog_product_add")
    if add_product_url and has_perm("catalog.add_product"):
        quick_links.append({"label": "Добавить технику", "url": add_product_url, "primary": True})

    import_stock_url = _safe_reverse("admin:import_stock")
    if import_stock_url and user and user.is_staff:
        quick_links.append({"label": "Импорт остатков", "url": import_stock_url, "primary": False})

    leads_url = _safe_reverse("admin:catalog_lead_changelist")
    if leads_url and can_view_leads:
        quick_links.append({"label": "Заявки", "url": leads_url, "primary": False})

    products_url = _safe_reverse("admin:catalog_product_changelist")
    if products_url and can_view_products:
        quick_links.append({"label": "Техника", "url": products_url, "primary": False})

    offers_url = _safe_reverse("admin:catalog_offer_changelist")
    if offers_url and can_view_offers:
        quick_links.append({"label": "Предложения / остатки", "url": offers_url, "primary": False})

    guide_url = _safe_reverse("catalog:admin_guide")

    return {
        "leads_new_7d": leads_new_7d,
        "leads_in_progress": leads_in_progress,
        "products_total": products_total,
        "offers_total": offers_total,
        "quick_links": quick_links,
        "guide_url": guide_url,
        "inventory_guide_path": "docs/INVENTORY_GUIDE.md",
    }
