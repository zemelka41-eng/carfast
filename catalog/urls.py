from django.urls import path

from . import views

app_name = "catalog"

urlpatterns = [
    # Build/version marker (kept here as a fallback in case ROOT_URLCONF differs)
    path("__version__/", views.version_view, name="version_public"),
    path("", views.home, name="home"),
    path("catalog/", views.catalog_list, name="catalog_list"),
    path("catalog/series/<slug:slug>/", views.catalog_series, name="catalog_series"),
    path(
        "catalog/series/<slug:series_slug>/<slug:category_slug>/",
        views.catalog_series_category,
        name="catalog_series_category",
    ),
    path("catalog/category/<slug:slug>/", views.catalog_category, name="catalog_category"),
    path("catalog/in-stock/", views.catalog_in_stock, name="catalog_in_stock"),
    path("brands/", views.brand_list, name="brand_list"),
    path("brands/<slug:slug>/", views.brand_detail, name="brand_detail"),
    path("product/<slug:slug>/", views.product_detail, name="product_detail"),
    # SHACMAN SEO hubs: registered in carfst_site/urls.py (root urlpatterns)
    path("about/", views.simple_page, {"slug": "about"}, name="about"),
    path("service/", views.info_page, {"slug": "service"}, name="service"),
    path("parts/", views.info_page, {"slug": "parts"}, name="parts"),
    path("leasing/", views.info_page, {"slug": "leasing"}, name="leasing"),
    path("used/", views.info_page, {"slug": "used"}, name="used"),
    path(
        "payment-delivery/",
        views.info_page,
        {"slug": "payment-delivery"},
        name="payment_delivery",
    ),
    path("privacy/", views.simple_page, {"slug": "privacy"}, name="privacy"),
    path("contacts/", views.contacts, name="contacts"),
    path("admin-guide/", views.admin_guide, name="admin_guide"),
    path("news/", views.simple_page, {"slug": "news"}, name="news"),
    path("lead/", views.lead_page, name="lead_page"),
    path("lead/thank-you/", views.lead_thank_you, name="lead_thank_you"),
]
