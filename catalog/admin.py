import io
from pathlib import Path

import openpyxl
from django import forms
from django.conf import settings
from django.contrib import admin, messages
from django.db.models import Q
from django.forms.models import BaseInlineFormSet
from django.http import HttpResponse
from django.template.response import TemplateResponse
from django.urls import path
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy as _

from . import importers
from .forms import LeadResponseForm, ProductAdminForm, ProductImageInlineForm
from .models import (
    CatalogLandingSEO,
    Category,
    City,
    Lead,
    ModelVariant,
    Offer,
    Product,
    ProductImage,
    Series,
    SeriesCategorySEO,
    ShacmanHubSEO,
    SiteSettings,
    StaticPageSEO,
)
from .seo_html import deduplicate_additional_info_heading
from .services.import_stock import import_stock
from .utils import send_email


class ProductImageInline(admin.TabularInline):
    model = ProductImage
    form = ProductImageInlineForm
    extra = 1
    fields = ("image", "alt_ru", "order")
    ordering = ("order",)


class OfferInlineFormSet(BaseInlineFormSet):
    """
    Дефолты для новых строк офферов в карточке товара:
    - Активно = True
    - Количество = 1 (чтобы товар сразу считался "в наличии")
    - Город = Москва (если есть)
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        active_cities_qs = City.objects.filter(is_active=True).order_by("sort_order", "name")
        moskva = active_cities_qs.filter(slug__iexact="moskva").first()

        # Дефолты — только для новых (extra) форм и только когда форма не связана POST-данными.
        if not self.is_bound:
            for form in self.extra_forms:
                form.initial.setdefault("is_active", True)
                form.initial.setdefault("qty", 1)
                if moskva:
                    form.initial.setdefault("city", moskva.pk)

        # В выпадающем списке показываем только активные города (и текущий город, если он неактивен).
        for form in self.forms:
            if "city" not in form.fields:
                continue
            qs = active_cities_qs
            if form.instance and form.instance.pk and form.instance.city_id:
                qs = City.objects.filter(Q(is_active=True) | Q(pk=form.instance.city_id)).order_by(
                    "sort_order",
                    "name",
                )
            form.fields["city"].queryset = qs


class OfferInline(admin.TabularInline):
    model = Offer
    extra = 1
    fields = ("city", "qty", "price", "year", "is_active")
    autocomplete_fields = ("city",)
    formset = OfferInlineFormSet

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "city":
            kwargs["queryset"] = City.objects.filter(is_active=True).order_by(
                "sort_order", "name"
            )
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    form = ProductAdminForm
    list_display = (
        "model_name_ru",
        "sku",
        "series",
        "category",
        "canonical_redirect_display",
        "total_qty",
        "min_price",
        "published",
        "is_active",
        "updated_at",
    )
    list_filter = (
        "series",
        "category",
        "published",
        "is_active",
        "is_used",
        "canonical_product",  # "Пусто" = канонические, "Есть" = алиасы
    )
    search_fields = (
        "model_name_ru",
        "sku",
        "slug",
        "model_code",
    )
    prepopulated_fields = {"slug": ("model_name_ru",)}
    readonly_fields = ("created_at", "updated_at", "views_count")
    list_select_related = ("series", "category", "model_variant", "canonical_product")
    autocomplete_fields = ("series", "category", "model_variant", "canonical_product")
    ordering = ("-updated_at", "-id")
    inlines = [ProductImageInline, OfferInline]
    actions = ["make_published", "make_unpublished", "export_xlsx", "import_sample"]
    list_display_links = ("model_name_ru",)
    list_editable = ("published", "is_active")

    fieldsets = (
        (
            "Основное",
            {
                "description": mark_safe(
                    "<p><strong>Мини‑гайд по заполнению (пример: автобетоносмеситель)</strong></p>"
                    "<ul>"
                    "<li><strong>Бренд (Series)</strong>: выберите бренд техники (например, SHACMAN)</li>"
                    "<li><strong>Категория (Category)</strong>: выберите тип техники (например, Грузовики)</li>"
                    "<li><strong>Модель (ModelVariant)</strong>: выберите модель/модификацию — при выборе автоматически подставится бренд и колёсная формула. "
                    "Модель содержит серию/линейку (например, X3000/X5000/X6000) и колёсную формулу</li>"
                    "<li><strong>Название</strong>: Автобетоносмеситель SHACMAN X5000 6x4, 2023</li>"
                    "<li><strong>Короткое описание</strong>: 2023 г., 336 л.с., 6x4, в Москве</li>"
                    "<li><strong>Артикул (SKU)</strong>: SHAC-X5000-6x4-ABN-2023-001</li>"
                    "<li><strong>Офферы</strong>: добавьте хотя бы один оффер (qty=1, город=Москва) — "
                    "так товар появится как «в наличии»</li>"
                    "</ul>"
                ),
                "fields": (
                    ("series", "category", "model_variant"),
                    ("model_name_ru", "sku"),
                    ("model_code", "slug"),
                    ("price", "availability", "is_used"),
                    ("engine_model", "power_hp"),
                    ("wheel_formula", "wheelbase_mm"),
                    ("payload_tons",),
                    "dimensions",
                )
            },
        ),
        (
            "Описание",
            {
                "fields": (
                    "short_description_ru",
                    "description_ru",
                    "options",
                    "config",
                )
            },
        ),
        (
            _("SEO (переопределения)"),
            {
                "classes": ("collapse",),
                "description": _(
                    "Если заполнено — используется вместо автогенерируемых title/description/текста/FAQ на карточке товара."
                ),
                "fields": (
                    "seo_title_override",
                    "seo_description_override",
                    "seo_text_override",
                    "seo_faq_override",
                )
            },
        ),
        (
            _("Канонический товар / редирект"),
            {
                "classes": ("collapse",),
                "description": _(
                    "Алиасы и редиректы: страница отдаёт 301, в sitemap не попадает. "
                    "Задайте canonical_product (редирект на другой товар) или redirect_to_url (редирект на хаб/внешний URL). "
                    "Не задавайте оба поля сразу. Не указывайте себя как канонический товар."
                ),
                "fields": ("canonical_product", "redirect_to_url"),
            },
        ),
        (
            "Публикация",
            {
                "fields": (
                    "published",
                    "is_active",
                )
            },
        ),
        (
            "Служебное",
            {
                "classes": ("collapse",),
                "fields": (
                    "views_count",
                    "created_at",
                    "updated_at",
                ),
            },
        ),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).with_stock_stats()

    @admin.display(description="Редирект")
    def canonical_redirect_display(self, obj: Product):
        if (obj.redirect_to_url or "").strip():
            return "→ URL"
        if obj.canonical_product_id:
            return "→ канон."
        return "—"

    @admin.display(description="Остаток", ordering="total_qty")
    def total_qty(self, obj: Product) -> int:
        return int(getattr(obj, "total_qty", 0) or 0)

    @admin.display(description="Цена от", ordering="min_price")
    def min_price(self, obj: Product):
        value = getattr(obj, "min_price", None)
        return value if value is not None else "—"

    @admin.action(description="Опубликовать")
    def make_published(self, request, queryset):
        updated = queryset.update(published=True)
        self.message_user(request, f"Опубликовано: {updated}", messages.SUCCESS)

    @admin.action(description="Снять с публикации")
    def make_unpublished(self, request, queryset):
        updated = queryset.update(published=False)
        self.message_user(request, f"Снято с публикации: {updated}", messages.WARNING)

    @admin.action(description="Импортировать sample XLSX")
    def import_sample(self, request, queryset):
        file_path = Path(settings.BASE_DIR) / "data" / "sample_products.xlsx"
        media_dir = Path(settings.MEDIA_ROOT) / "import_images"
        created, updated, errors = importers.run_import(file_path, media_dir)
        self.message_user(
            request,
            f"Импорт завершён. Создано: {created}, обновлено: {updated}, ошибок: {errors}",
            messages.INFO,
        )

    @admin.action(description="Экспорт в XLSX")
    def export_xlsx(self, request, queryset):
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(
            [
                "sku",
                "slug",
                "series",
                "category",
                "model_name_ru",
                "model_name_en",
                "short_description_ru",
                "short_description_en",
                "price",
                "availability",
            ]
        )
        for product in queryset:
            ws.append(
                [
                    product.sku,
                    product.slug,
                    product.series.name if product.series else "",
                    product.category.name if product.category else "",
                    product.model_name_ru,
                    product.model_name_en,
                    product.short_description_ru,
                    product.short_description_en,
                    product.price,
                    product.availability,
                ]
            )
        output = io.BytesIO()
        wb.save(output)
        output.seek(0)
        response = HttpResponse(
            output.read(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response["Content-Disposition"] = 'attachment; filename="products.xlsx"'
        return response


@admin.register(Lead)
class LeadAdmin(admin.ModelAdmin):
    list_display = ("name", "phone", "email", "product", "source", "created_at", "processed")
    list_filter = (
        "processed",
        ("created_at", admin.DateFieldListFilter),
        "source",
        "utm_source",
        "utm_campaign",
    )
    search_fields = (
        "name",
        "phone",
        "email",
        "message",
        "source",
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_term",
        "utm_content",
        "product__sku",
        "product__model_name_ru",
    )
    list_select_related = ("product",)
    actions = ["mark_processed", "mark_unprocessed", "send_reply"]
    readonly_fields = ("created_at",)
    form = LeadResponseForm
    date_hierarchy = "created_at"
    ordering = ("-created_at", "-id")

    @admin.action(description="Отметить как обработанные")
    def mark_processed(self, request, queryset):
        count = queryset.update(processed=True)
        self.message_user(request, f"Обработано: {count}", messages.SUCCESS)

    @admin.action(description="Отметить как НЕ обработанные")
    def mark_unprocessed(self, request, queryset):
        count = queryset.update(processed=False)
        self.message_user(request, f"Снято с обработки: {count}", messages.WARNING)

    @admin.action(description="Отправить ответ по email")
    def send_reply(self, request, queryset):
        sent = 0
        for lead in queryset:
            if lead.email:
                send_email(
                    subject="Спасибо за обращение",
                    template="emails/lead_notification.html",
                    context={"lead": lead},
                    recipients=[lead.email],
                )
                sent += 1
        self.message_user(request, f"Отправлено: {sent}", messages.INFO)


@admin.register(Series)
class SeriesAdmin(admin.ModelAdmin):
    prepopulated_fields = {"slug": ("name",)}
    list_display = ("logo_thumbnail", "name", "slug", "has_logo", "has_intro", "has_body", "has_faq", "intro_len", "body_len", "faq_count")
    list_filter = (
        ("seo_intro_html", admin.EmptyFieldListFilter),
        ("seo_body_html", admin.EmptyFieldListFilter),
        ("seo_faq", admin.EmptyFieldListFilter),
    )
    search_fields = ("name",)
    readonly_fields = ("logo_preview",)
    fields = (
        "name",
        "slug",
        (
            "logo",
            "logo_alt_ru",
        ),
        "logo_preview",
        "history",
        "description_ru",
        "description_en",
        "seo_description",
        "seo_intro_html",
        "seo_body_html",
        "seo_faq",
    )
    actions = ["generate_draft_seo_content"]
    
    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        if "logo" in form.base_fields:
            form.base_fields["logo"].help_text = mark_safe(
                "Форматы: .jpg/.jpeg/.png/.webp (.jfif тоже поддерживается как JPEG). "
                "Рекомендуем: PNG/WebP с прозрачностью, 512×512 или 600×300, ≤200 KB. "
                "Подробнее: <a href='/admin-guide/' target='_blank'>Гайд по фото</a>"
            )
        for name, h in (
            ("seo_intro_html", "Короткий блок над карточками. Объём: 1–3 абзаца."),
            ("seo_body_html", "Развёрнутый блок под карточками. Допускаются подзаголовки h2/h3."),
            ("seo_faq", "5–10 вопросов. Формат: вопрос|ответ, по одному на строку."),
        ):
            if name in form.base_fields:
                form.base_fields[name].help_text = (form.base_fields[name].help_text or "") + " " + h
        return form

    @admin.display(description="Интро", boolean=True)
    def has_intro(self, obj: Series) -> bool:
        return bool((obj.seo_intro_html or "").strip())

    @admin.display(description="Body", boolean=True)
    def has_body(self, obj: Series) -> bool:
        return bool((obj.seo_body_html or "").strip())

    @admin.display(description="FAQ", boolean=True)
    def has_faq(self, obj: Series) -> bool:
        return bool((obj.seo_faq or "").strip())

    @admin.display(description="Intro len")
    def intro_len(self, obj: Series) -> int:
        return len((obj.seo_intro_html or "").strip())

    @admin.display(description="Body len")
    def body_len(self, obj: Series) -> int:
        return len((obj.seo_body_html or "").strip())

    @admin.display(description="FAQ count")
    def faq_count(self, obj: Series) -> int:
        lines = [(obj.seo_faq or "").strip()]
        return len([line for line in lines[0].split("\n") if "|" in line])

    def save_model(self, request, obj, form, change):
        if getattr(obj, "seo_body_html", None) is not None:
            raw = (obj.seo_body_html or "").strip()
            if raw:
                obj.seo_body_html = deduplicate_additional_info_heading(raw)
        super().save_model(request, obj, form, change)

    @admin.action(description="Generate draft SEO content (safe: no overwrite)")
    def generate_draft_seo_content(self, request, queryset):
        updated = 0
        for obj in queryset:
            changed = False
            if not (obj.seo_intro_html or "").strip():
                obj.seo_intro_html = self._generate_intro_draft(obj)
                changed = True
            if not (obj.seo_body_html or "").strip():
                obj.seo_body_html = self._generate_body_draft(obj)
                changed = True
            if not (obj.seo_faq or "").strip():
                obj.seo_faq = self._generate_faq_draft(obj)
                changed = True
            if changed:
                obj.save()
                updated += 1
        self.message_user(request, f"Создано черновиков: {updated} из {queryset.count()}")

    def _generate_intro_draft(self, obj: Series) -> str:
        return f"<p>Техника {obj.name} в наличии и под заказ.</p>\n<p>Конкурентные цены, лизинг, гарантия.</p>"

    def _generate_body_draft(self, obj: Series) -> str:
        return (
            f"<h2>Почему выбирают {obj.name}</h2>\n"
            f"<p>Надёжность, доступная стоимость владения, быстрая окупаемость.</p>\n"
            f"<h2>Как получить коммерческое предложение</h2>\n"
            f'<p>Оставьте заявку — подготовим КП с учётом региона и способа оплаты. <a href="/leasing/">Лизинг</a> доступен.</p>'
        )

    def _generate_faq_draft(self, obj: Series) -> str:
        return (
            f"Какие модели {obj.name} есть в наличии?|Актуальный список в каталоге обновляется ежедневно.\n"
            f"Какие сроки поставки техники под заказ?|Сроки зависят от модели и комплектации, уточним в КП.\n"
            f"Работаете ли вы с лизингом?|Да, помогаем оформить лизинг через партнёров.\n"
            f"Как оформить заказ?|Оставьте заявку на сайте или позвоните — подготовим КП.\n"
            f"Есть ли гарантия?|Да, на всю технику распространяется заводская гарантия.\n"
            f"Доставка в регионы?|Доставляем по всей России, условия уточняются индивидуально."
        )

    @admin.display(description="Логотип")
    def logo_thumbnail(self, obj: Series):
        if not getattr(obj, "logo", None):
            return "—"
        try:
            return format_html(
                '<img src="{}" style="height:32px; width:auto; object-fit:contain;" alt="">',
                obj.logo.url,
            )
        except Exception:  # noqa: BLE001
            return "—"

    @admin.display(description="Логотип", boolean=True)
    def has_logo(self, obj: Series) -> bool:
        return bool(getattr(obj, "logo", None))

    @admin.display(description="Превью логотипа")
    def logo_preview(self, obj: Series):
        if not getattr(obj, "logo", None):
            return "—"
        try:
            return format_html(
                '<img src="{}" style="max-height:160px; width:auto; object-fit:contain; background:#111; padding:8px; border-radius:8px;" alt="">',
                obj.logo.url,
            )
        except Exception:  # noqa: BLE001
            return "—"


@admin.register(ModelVariant)
class ModelVariantAdmin(admin.ModelAdmin):
    prepopulated_fields = {"slug": ("name",)}
    list_display = ("name", "slug", "brand", "line", "wheel_formula", "sort_order")
    list_filter = ("brand", "line", "wheel_formula")
    search_fields = ("name", "slug", "line", "wheel_formula", "brand__name")
    ordering = ("brand__name", "sort_order", "name")
    autocomplete_fields = ("brand",)


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    prepopulated_fields = {"slug": ("name",)}
    list_display = ("cover_thumbnail", "name", "slug", "has_cover", "has_intro", "has_body", "has_faq", "intro_len", "body_len", "faq_count")
    list_filter = (
        ("seo_intro_html", admin.EmptyFieldListFilter),
        ("seo_body_html", admin.EmptyFieldListFilter),
        ("seo_faq", admin.EmptyFieldListFilter),
    )
    search_fields = ("name", "slug")
    readonly_fields = ("cover_preview",)
    fields = (
        "name",
        "slug",
        ("cover_image", "cover_alt_ru"),
        "cover_preview",
        "seo_description",
        "seo_intro_html",
        "seo_body_html",
        "seo_faq",
    )
    actions = ["generate_draft_seo_content"]
    
    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        if "cover_image" in form.base_fields:
            form.base_fields["cover_image"].help_text = mark_safe(
                "Форматы: .jpg/.jpeg/.png/.webp (.jfif тоже поддерживается как JPEG). "
                "Рекомендуем: 16:9, 1600×900 (оптимально) или 1600×600, минимум 1200×675. "
                "JPG quality 80–85 или WebP, ≤500 KB. "
                "Подробнее: <a href='/admin-guide/' target='_blank'>Гайд по фото</a>"
            )
        for name, h in (
            ("seo_intro_html", "Короткий блок над карточками. Объём: 1–3 абзаца."),
            ("seo_body_html", "Развёрнутый блок под карточками. Допускаются подзаголовки h2/h3."),
            ("seo_faq", "5–10 вопросов. Формат: вопрос|ответ, по одному на строку."),
        ):
            if name in form.base_fields:
                form.base_fields[name].help_text = (form.base_fields[name].help_text or "") + " " + h
        return form

    @admin.display(description="Интро", boolean=True)
    def has_intro(self, obj: Category) -> bool:
        return bool((obj.seo_intro_html or "").strip())

    @admin.display(description="Body", boolean=True)
    def has_body(self, obj: Category) -> bool:
        return bool((obj.seo_body_html or "").strip())

    @admin.display(description="FAQ", boolean=True)
    def has_faq(self, obj: Category) -> bool:
        return bool((obj.seo_faq or "").strip())

    @admin.display(description="Intro len")
    def intro_len(self, obj: Category) -> int:
        return len((obj.seo_intro_html or "").strip())

    @admin.display(description="Body len")
    def body_len(self, obj: Category) -> int:
        return len((obj.seo_body_html or "").strip())

    @admin.display(description="FAQ count")
    def faq_count(self, obj: Category) -> int:
        lines = [(obj.seo_faq or "").strip()]
        return len([line for line in lines[0].split("\n") if "|" in line])

    def save_model(self, request, obj, form, change):
        if getattr(obj, "seo_body_html", None) is not None:
            raw = (obj.seo_body_html or "").strip()
            if raw:
                obj.seo_body_html = deduplicate_additional_info_heading(raw)
        super().save_model(request, obj, form, change)

    @admin.action(description="Generate draft SEO content (safe: no overwrite)")
    def generate_draft_seo_content(self, request, queryset):
        updated = 0
        for obj in queryset:
            changed = False
            if not (obj.seo_intro_html or "").strip():
                obj.seo_intro_html = self._generate_intro_draft(obj)
                changed = True
            if not (obj.seo_body_html or "").strip():
                obj.seo_body_html = self._generate_body_draft(obj)
                changed = True
            if not (obj.seo_faq or "").strip():
                obj.seo_faq = self._generate_faq_draft(obj)
                changed = True
            if changed:
                obj.save()
                updated += 1
        self.message_user(request, f"Создано черновиков: {updated} из {queryset.count()}")

    def _generate_intro_draft(self, obj: Category) -> str:
        return f"<p>Техника категории {obj.name} в наличии и под заказ.</p>\n<p>Конкурентные цены, лизинг, гарантия.</p>"

    def _generate_body_draft(self, obj: Category) -> str:
        return (
            f"<h2>Почему выбирают {obj.name}</h2>\n"
            f"<p>Надёжность, производительность, доступная стоимость владения.</p>\n"
            f"<h2>Как получить коммерческое предложение</h2>\n"
            f'<p>Оставьте заявку — подготовим КП с учётом региона и способа оплаты. <a href="/leasing/">Лизинг</a> доступен.</p>'
        )

    def _generate_faq_draft(self, obj: Category) -> str:
        return (
            f"Какие модели {obj.name} есть в наличии?|Актуальный список в каталоге обновляется ежедневно.\n"
            f"Какие сроки поставки техники под заказ?|Сроки зависят от модели и комплектации, уточним в КП.\n"
            f"Работаете ли вы с лизингом?|Да, помогаем оформить лизинг через партнёров.\n"
            f"Как оформить заказ?|Оставьте заявку на сайте или позвоните — подготовим КП.\n"
            f"Есть ли гарантия?|Да, на всю технику распространяется заводская гарантия.\n"
            f"Доставка в регионы?|Доставляем по всей России, условия уточняются индивидуально."
        )

    @admin.display(description="Фото")
    def cover_thumbnail(self, obj: Category):
        if not getattr(obj, "cover_image", None):
            return "—"
        try:
            return format_html(
                '<img src="{}" style="height:32px; width:56px; object-fit:cover; border-radius:6px;" alt="">',
                obj.cover_image.url,
            )
        except Exception:  # noqa: BLE001
            return "—"

    @admin.display(description="Фото", boolean=True)
    def has_cover(self, obj: Category) -> bool:
        return bool(getattr(obj, "cover_image", None))

    @admin.display(description="Превью фото")
    def cover_preview(self, obj: Category):
        if not getattr(obj, "cover_image", None):
            return "—"
        try:
            return format_html(
                '<img src="{}" style="max-width:420px; width:100%; height:auto; aspect-ratio:16/9; object-fit:cover; border-radius:10px;" alt="">',
                obj.cover_image.url,
            )
        except Exception:  # noqa: BLE001
            return "—"


@admin.register(SeriesCategorySEO)
class SeriesCategorySEOAdmin(admin.ModelAdmin):
    list_display = ("series", "category", "has_description", "has_intro", "has_body", "has_faq", "intro_len", "body_len", "faq_count")
    list_filter = (
        "series",
        "category",
        ("seo_intro_html", admin.EmptyFieldListFilter),
        ("seo_body_html", admin.EmptyFieldListFilter),
        ("seo_faq", admin.EmptyFieldListFilter),
    )
    search_fields = ("series__name", "category__name", "seo_description", "seo_faq")
    autocomplete_fields = ("series", "category")
    fields = ("series", "category", "seo_description", "seo_intro_html", "seo_body_html", "seo_faq")
    actions = ["generate_draft_seo_content"]

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        for name, h in (
            ("seo_intro_html", "Короткий блок над карточками. Объём: 1–3 абзаца."),
            ("seo_body_html", "Развёрнутый блок под карточками. Допускаются подзаголовки h2/h3."),
            ("seo_faq", "5–10 вопросов. Формат: вопрос|ответ, по одному на строку."),
        ):
            if name in form.base_fields:
                form.base_fields[name].help_text = (form.base_fields[name].help_text or "") + " " + h
        return form

    @admin.display(description="Описание", boolean=True)
    def has_description(self, obj: SeriesCategorySEO) -> bool:
        return bool(obj.seo_description and obj.seo_description.strip())
    
    @admin.display(description="Интро", boolean=True)
    def has_intro(self, obj: SeriesCategorySEO) -> bool:
        return bool((obj.seo_intro_html or "").strip())

    @admin.display(description="Body", boolean=True)
    def has_body(self, obj: SeriesCategorySEO) -> bool:
        return bool((obj.seo_body_html or "").strip())
    
    @admin.display(description="FAQ", boolean=True)
    def has_faq(self, obj: SeriesCategorySEO) -> bool:
        return bool(obj.seo_faq and obj.seo_faq.strip())

    @admin.display(description="Intro len")
    def intro_len(self, obj: SeriesCategorySEO) -> int:
        return len((obj.seo_intro_html or "").strip())

    @admin.display(description="Body len")
    def body_len(self, obj: SeriesCategorySEO) -> int:
        return len((obj.seo_body_html or "").strip())

    @admin.display(description="FAQ count")
    def faq_count(self, obj: SeriesCategorySEO) -> int:
        lines = [(obj.seo_faq or "").strip()]
        return len([line for line in lines[0].split("\n") if "|" in line])

    def save_model(self, request, obj, form, change):
        if getattr(obj, "seo_body_html", None) is not None:
            raw = (obj.seo_body_html or "").strip()
            if raw:
                obj.seo_body_html = deduplicate_additional_info_heading(raw)
        super().save_model(request, obj, form, change)

    @admin.action(description="Generate draft SEO content (safe: no overwrite)")
    def generate_draft_seo_content(self, request, queryset):
        updated = 0
        for obj in queryset:
            changed = False
            if not (obj.seo_intro_html or "").strip():
                obj.seo_intro_html = self._generate_intro_draft(obj)
                changed = True
            if not (obj.seo_body_html or "").strip():
                obj.seo_body_html = self._generate_body_draft(obj)
                changed = True
            if not (obj.seo_faq or "").strip():
                obj.seo_faq = self._generate_faq_draft(obj)
                changed = True
            if changed:
                obj.save()
                updated += 1
        self.message_user(request, f"Создано черновиков: {updated} из {queryset.count()}")

    def _generate_intro_draft(self, obj: SeriesCategorySEO) -> str:
        series_url = f'<a href="/catalog/series/{obj.series.slug}/">{obj.series.name}</a>'
        cat_url = f'<a href="/catalog/category/{obj.category.slug}/">{obj.category.name}</a>'
        return f"<p>Техника {series_url} категории {cat_url} в наличии и под заказ.</p>\n<p>Конкурентные цены, гибкие условия, лизинг.</p>"

    def _generate_body_draft(self, obj: SeriesCategorySEO) -> str:
        series_url = f'<a href="/catalog/series/{obj.series.slug}/">{obj.series.name}</a>'
        cat_url = f'<a href="/catalog/category/{obj.category.slug}/">{obj.category.name}</a>'
        return (
            f"<h2>Почему выбирают {obj.series.name} {obj.category.name}</h2>\n"
            f"<p>Техника {series_url} категории {cat_url} сочетает надёжность, производительность и доступную стоимость владения.</p>\n"
            f"<h2>Как получить коммерческое предложение</h2>\n"
            f'<p>Оставьте заявку или позвоните — подготовим КП с учётом региона и способа оплаты. <a href="/leasing/">Лизинг</a> доступен.</p>'
        )

    def _generate_faq_draft(self, obj: SeriesCategorySEO) -> str:
        return (
            f"Какие модели {obj.series.name} {obj.category.name} есть в наличии?|Актуальный список в каталоге обновляется ежедневно.\n"
            f"Какие сроки поставки техники под заказ?|Сроки зависят от модели и комплектации, уточним в КП.\n"
            f"Работаете ли вы с лизингом?|Да, помогаем оформить лизинг через партнёров.\n"
            f"Как оформить заказ?|Оставьте заявку на сайте или позвоните — подготовим КП.\n"
            f"Есть ли гарантия?|Да, на всю технику распространяется заводская гарантия.\n"
            f"Доставка в регионы?|Доставляем по всей России, условия уточняются индивидуально."
        )



@admin.register(ShacmanHubSEO)
class ShacmanHubSEOAdmin(admin.ModelAdmin):
    list_display = (
        "hub_type", "facet_key", "category", "force_index",
        "has_title", "has_text", "has_intro", "has_body", "has_faq",
        "intro_len", "body_len", "faq_count",
    )
    list_filter = (
        "hub_type",
        "force_index",
        ("seo_intro_html", admin.EmptyFieldListFilter),
        ("seo_body_html", admin.EmptyFieldListFilter),
        ("faq", admin.EmptyFieldListFilter),
    )
    search_fields = ("meta_title", "meta_description", "seo_text", "faq", "facet_key")
    autocomplete_fields = ("category",)
    fields = (
        "hub_type",
        "facet_key",
        "category",
        "force_index",
        "meta_title",
        "meta_description",
        "seo_intro_html",
        "seo_body_html",
        "seo_text",
        "faq",
        "also_search_line",
    )
    actions = ["generate_draft_seo_content"]

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        for name, h in (
            ("seo_intro_html", "Короткий блок над карточками. Объём: 1–3 абзаца."),
            ("seo_body_html", "Развёрнутый блок под карточками. Допускаются подзаголовки h2/h3."),
            ("faq", "5–10 вопросов. Формат: вопрос|ответ, по одному на строку."),
        ):
            if name in form.base_fields:
                form.base_fields[name].help_text = (form.base_fields[name].help_text or "") + " " + h
        return form

    @admin.display(description="Title", boolean=True)
    def has_title(self, obj: ShacmanHubSEO) -> bool:
        return bool(obj.meta_title and obj.meta_title.strip())

    @admin.display(description="Текст", boolean=True)
    def has_text(self, obj: ShacmanHubSEO) -> bool:
        return bool(obj.seo_text and obj.seo_text.strip())

    @admin.display(description="Интро", boolean=True)
    def has_intro(self, obj: ShacmanHubSEO) -> bool:
        return bool(getattr(obj, "seo_intro_html", None) and str(obj.seo_intro_html).strip())

    @admin.display(description="Блок под", boolean=True)
    def has_body(self, obj: ShacmanHubSEO) -> bool:
        return bool(getattr(obj, "seo_body_html", None) and str(obj.seo_body_html).strip())

    @admin.display(description="FAQ", boolean=True)
    def has_faq(self, obj: ShacmanHubSEO) -> bool:
        return bool(obj.faq and obj.faq.strip())

    @admin.display(description="Intro len")
    def intro_len(self, obj: ShacmanHubSEO) -> int:
        return len((obj.seo_intro_html or "").strip())

    @admin.display(description="Body len")
    def body_len(self, obj: ShacmanHubSEO) -> int:
        return len((obj.seo_body_html or "").strip())

    @admin.display(description="FAQ count")
    def faq_count(self, obj: ShacmanHubSEO) -> int:
        lines = [(obj.faq or "").strip()]
        return len([line for line in lines[0].split("\n") if "|" in line])

    def save_model(self, request, obj, form, change):
        if getattr(obj, "seo_body_html", None) is not None:
            raw = (obj.seo_body_html or "").strip()
            if raw:
                obj.seo_body_html = deduplicate_additional_info_heading(raw)
        super().save_model(request, obj, form, change)

    @admin.action(description="Generate draft SEO content (safe: no overwrite)")
    def generate_draft_seo_content(self, request, queryset):
        updated = 0
        for obj in queryset:
            changed = False
            if not (obj.seo_intro_html or "").strip():
                obj.seo_intro_html = self._generate_intro_draft(obj)
                changed = True
            if not (obj.seo_body_html or "").strip():
                obj.seo_body_html = self._generate_body_draft(obj)
                changed = True
            if not (obj.faq or "").strip():
                obj.faq = self._generate_faq_draft(obj)
                changed = True
            if changed:
                obj.save()
                updated += 1
        self.message_user(request, f"Создано черновиков: {updated} из {queryset.count()}")

    def _generate_intro_draft(self, obj: ShacmanHubSEO) -> str:
        context = self._get_context_label(obj)
        return f"<p>Техника SHACMAN {context} в наличии и под заказ.</p>\n<p>Конкурентные цены, лизинг, доставка по России.</p>"

    def _generate_body_draft(self, obj: ShacmanHubSEO) -> str:
        context = self._get_context_label(obj)
        return (
            f"<h2>Почему выбирают SHACMAN {context}</h2>\n"
            f"<p>Надёжность, доступная стоимость владения, быстрая окупаемость.</p>\n"
            f"<h2>Как получить коммерческое предложение</h2>\n"
            f'<p>Оставьте заявку — подготовим КП с учётом региона и способа оплаты. <a href="/leasing/">Лизинг</a> доступен.</p>'
        )

    def _generate_faq_draft(self, obj: ShacmanHubSEO) -> str:
        context = self._get_context_label(obj)
        return (
            f"Какие модели SHACMAN {context} есть в наличии?|Актуальный список в каталоге обновляется ежедневно.\n"
            f"Какие сроки поставки техники под заказ?|Сроки зависят от модели и комплектации, уточним в КП.\n"
            f"Работаете ли вы с лизингом?|Да, помогаем оформить лизинг через партнёров.\n"
            f"Как оформить заказ?|Оставьте заявку на сайте или позвоните — подготовим КП.\n"
            f"Есть ли гарантия?|Да, на всю технику распространяется заводская гарантия.\n"
            f"Доставка в регионы?|Доставляем по всей России, условия уточняются индивидуально."
        )

    def _get_context_label(self, obj: ShacmanHubSEO) -> str:
        """Returns contextual label like '8x4' or 'самосвалы' for draft generation."""
        if obj.facet_key:
            return obj.facet_key
        if obj.category:
            return obj.category.name
        return ""



@admin.register(StaticPageSEO)
class StaticPageSEOAdmin(admin.ModelAdmin):
    list_display = ("slug", "has_meta_title", "has_intro", "has_body", "has_faq", "intro_len", "body_len", "faq_count")
    list_filter = (
        "slug",
        ("seo_intro_html", admin.EmptyFieldListFilter),
        ("seo_body_html", admin.EmptyFieldListFilter),
        ("faq_items", admin.EmptyFieldListFilter),
    )
    search_fields = ("slug", "meta_title", "meta_description", "seo_intro_html", "seo_body_html", "faq_items")
    fields = ("slug", "meta_title", "meta_description", "seo_intro_html", "seo_body_html", "faq_items")
    actions = ["generate_draft_seo_content"]

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        for name, h in (
            ("seo_intro_html", "Короткий блок над контентом страницы. 1–3 абзаца."),
            ("seo_body_html", "Развёрнутый блок внизу страницы. Допускаются подзаголовки h2/h3."),
            ("faq_items", "5–10 вопросов. Формат: вопрос|ответ, по одному на строку. Используется для FAQPage schema."),
        ):
            if name in form.base_fields:
                form.base_fields[name].help_text = (form.base_fields[name].help_text or "") + " " + h
        return form

    @admin.display(description="Title", boolean=True)
    def has_meta_title(self, obj: StaticPageSEO) -> bool:
        return bool(obj.meta_title and obj.meta_title.strip())

    @admin.display(description="Интро", boolean=True)
    def has_intro(self, obj: StaticPageSEO) -> bool:
        return bool(obj.seo_intro_html and obj.seo_intro_html.strip())

    @admin.display(description="Body", boolean=True)
    def has_body(self, obj: StaticPageSEO) -> bool:
        return bool(obj.seo_body_html and obj.seo_body_html.strip())

    @admin.display(description="FAQ", boolean=True)
    def has_faq(self, obj: StaticPageSEO) -> bool:
        return bool(obj.faq_items and obj.faq_items.strip())

    @admin.display(description="Intro len")
    def intro_len(self, obj: StaticPageSEO) -> int:
        return len((obj.seo_intro_html or "").strip())

    @admin.display(description="Body len")
    def body_len(self, obj: StaticPageSEO) -> int:
        return len((obj.seo_body_html or "").strip())

    @admin.display(description="FAQ count")
    def faq_count(self, obj: StaticPageSEO) -> int:
        lines = [(obj.faq_items or "").strip()]
        return len([line for line in lines[0].split("\n") if "|" in line])

    def save_model(self, request, obj, form, change):
        if getattr(obj, "seo_body_html", None) is not None:
            raw = (obj.seo_body_html or "").strip()
            if raw:
                obj.seo_body_html = deduplicate_additional_info_heading(raw)
        super().save_model(request, obj, form, change)

    @admin.action(description="Generate draft SEO content (safe: no overwrite)")
    def generate_draft_seo_content(self, request, queryset):
        updated = 0
        for obj in queryset:
            changed = False
            if not (obj.seo_intro_html or "").strip():
                obj.seo_intro_html = self._generate_intro_draft(obj)
                changed = True
            if not (obj.seo_body_html or "").strip():
                obj.seo_body_html = self._generate_body_draft(obj)
                changed = True
            if not (obj.faq_items or "").strip():
                obj.faq_items = self._generate_faq_draft(obj)
                changed = True
            if changed:
                obj.save()
                updated += 1
        self.message_user(request, f"Создано черновиков: {updated} из {queryset.count()}")

    def _generate_intro_draft(self, obj: StaticPageSEO) -> str:
        labels = {
            "leasing": "Лизинг спецтехники",
            "used": "Б/у техника",
            "service": "Сервис и обслуживание",
            "parts": "Запчасти",
            "payment-delivery": "Оплата и доставка",
        }
        label = labels.get(obj.slug, obj.slug.capitalize())
        return f"<p>{label} от CARFAST: профессиональный подход и прозрачные условия.</p>\n<p>Консультация и расчёт по телефону или через форму на сайте.</p>"

    def _generate_body_draft(self, obj: StaticPageSEO) -> str:
        labels = {
            "leasing": "лизинг",
            "used": "б/у технику",
            "service": "сервис",
            "parts": "запчасти",
            "payment-delivery": "оплату и доставку",
        }
        service = labels.get(obj.slug, obj.slug)
        return (
            f"<h2>Преимущества работы с CARFAST</h2>\n"
            f"<p>Профессиональная консультация, индивидуальный подход, гибкие условия.</p>\n"
            f"<h2>Как оформить {service}</h2>\n"
            f'<p>Оставьте заявку на сайте или позвоните — подготовим расчёт и ответим на вопросы. <a href="/catalog/in-stock/">Техника в наличии</a>.</p>'
        )

    def _generate_faq_draft(self, obj: StaticPageSEO) -> str:
        return (
            f"Какие условия?|Условия уточняются индивидуально при обращении.\n"
            f"Как оформить заявку?|Оставьте контакты на сайте или позвоните.\n"
            f"Сроки оформления?|Зависит от услуги, уточним при обращении.\n"
            f"Работаете с юридическими лицами?|Да, работаем как с юр., так и с физ. лицами.\n"
            f"Доступна ли консультация?|Да, консультируем по всем вопросам.\n"
            f"Где вы находитесь?|Контакты и адрес указаны на странице контактов."
        )



@admin.register(CatalogLandingSEO)
class CatalogLandingSEOAdmin(admin.ModelAdmin):
    list_display = ("landing_key", "has_meta_title", "has_intro", "has_body", "has_faq", "intro_len", "body_len", "faq_count")
    list_filter = (
        "landing_key",
        ("seo_intro_html", admin.EmptyFieldListFilter),
        ("seo_body_html", admin.EmptyFieldListFilter),
        ("faq_items", admin.EmptyFieldListFilter),
    )
    search_fields = ("meta_title", "meta_description", "seo_intro_html", "seo_body_html", "faq_items")
    fields = ("landing_key", "meta_title", "meta_description", "seo_intro_html", "seo_body_html", "faq_items")
    actions = ["generate_draft_seo_content"]

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        for name, h in (
            ("seo_intro_html", "Короткий блок над карточками. 1–3 абзаца."),
            ("seo_body_html", "Развёрнутый блок под карточками. Допускаются подзаголовки h2/h3."),
            ("faq_items", "5–10 вопросов. Формат: вопрос|ответ, по одному на строку. Используется для FAQPage schema."),
        ):
            if name in form.base_fields:
                form.base_fields[name].help_text = (form.base_fields[name].help_text or "") + " " + h
        return form

    @admin.display(description="Title", boolean=True)
    def has_meta_title(self, obj: CatalogLandingSEO) -> bool:
        return bool(obj.meta_title and obj.meta_title.strip())

    @admin.display(description="Интро", boolean=True)
    def has_intro(self, obj: CatalogLandingSEO) -> bool:
        return bool(obj.seo_intro_html and obj.seo_intro_html.strip())

    @admin.display(description="Body", boolean=True)
    def has_body(self, obj: CatalogLandingSEO) -> bool:
        return bool(obj.seo_body_html and obj.seo_body_html.strip())

    @admin.display(description="FAQ", boolean=True)
    def has_faq(self, obj: CatalogLandingSEO) -> bool:
        return bool(obj.faq_items and obj.faq_items.strip())

    @admin.display(description="Intro len")
    def intro_len(self, obj: CatalogLandingSEO) -> int:
        return len((obj.seo_intro_html or "").strip())

    @admin.display(description="Body len")
    def body_len(self, obj: CatalogLandingSEO) -> int:
        return len((obj.seo_body_html or "").strip())

    @admin.display(description="FAQ count")
    def faq_count(self, obj: CatalogLandingSEO) -> int:
        lines = [(obj.faq_items or "").strip()]
        return len([line for line in lines[0].split("\n") if "|" in line])

    def save_model(self, request, obj, form, change):
        if getattr(obj, "seo_body_html", None) is not None:
            raw = (obj.seo_body_html or "").strip()
            if raw:
                obj.seo_body_html = deduplicate_additional_info_heading(raw)
        super().save_model(request, obj, form, change)

    @admin.action(description="Generate draft SEO content (safe: no overwrite)")
    def generate_draft_seo_content(self, request, queryset):
        updated = 0
        for obj in queryset:
            changed = False
            if not (obj.seo_intro_html or "").strip():
                obj.seo_intro_html = self._generate_intro_draft(obj)
                changed = True
            if not (obj.seo_body_html or "").strip():
                obj.seo_body_html = self._generate_body_draft(obj)
                changed = True
            if not (obj.faq_items or "").strip():
                obj.faq_items = self._generate_faq_draft(obj)
                changed = True
            if changed:
                obj.save()
                updated += 1
        self.message_user(request, f"Создано черновиков: {updated} из {queryset.count()}")

    def _generate_intro_draft(self, obj: CatalogLandingSEO) -> str:
        return "<p>Техника в наличии на складе CARFAST — готова к отгрузке и осмотру.</p>\n<p>Конкурентные цены, лизинг, гарантия.</p>"

    def _generate_body_draft(self, obj: CatalogLandingSEO) -> str:
        return (
            "<h2>Почему выбирают технику в наличии</h2>\n"
            "<p>Минимум ожидания, прозрачные условия, возможность осмотра.</p>\n"
            "<h2>Как получить коммерческое предложение</h2>\n"
            '<p>Оставьте заявку — подготовим КП с учётом региона и способа оплаты. <a href="/leasing/">Лизинг</a> доступен.</p>'
        )

    def _generate_faq_draft(self, obj: CatalogLandingSEO) -> str:
        return (
            "Какие сроки отгрузки техники в наличии?|Техника на складе готова к отгрузке: сроки зависят от региона доставки.\n"
            "Можно ли осмотреть технику перед покупкой?|Да, организуем осмотр по договорённости.\n"
            "Какие варианты оплаты?|Работаем по предоплате и в лизинг — уточняем в КП.\n"
            "Как оформить заказ?|Оставьте заявку на сайте или позвоните — подготовим КП.\n"
            "Есть ли гарантия?|Да, на всю технику распространяется заводская гарантия.\n"
            "Доставка в регионы?|Доставляем по всей России, условия уточняются индивидуально."
        )


@admin.register(City)
class CityAdmin(admin.ModelAdmin):
    prepopulated_fields = {"slug": ("name",)}
    list_display = ("name", "slug", "sort_order", "is_active")
    list_editable = ("sort_order", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name", "slug")
    ordering = ("sort_order", "name")

    def get_search_results(self, request, queryset, search_term):
        queryset, use_distinct = super().get_search_results(request, queryset, search_term)
        if (
            request.GET.get("app_label") == "catalog"
            and request.GET.get("model_name") == "offer"
            and request.GET.get("field_name") == "city"
        ):
            queryset = queryset.filter(is_active=True)
        return queryset, use_distinct


@admin.register(Offer)
class OfferAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "product",
        "city",
        "qty",
        "price",
        "vat",
        "year",
        "is_active",
        "updated_at",
        "source_file",
    )
    list_filter = ("is_active", "city", "vat", "source_file")
    search_fields = ("product__sku", "product__model_name_ru", "city__name", "city__slug")
    list_select_related = ("product", "city")
    ordering = ("-updated_at", "-id")
    list_editable = ("qty", "price", "is_active")

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj=obj, **kwargs)
        if "city" in form.base_fields:
            qs = City.objects.filter(is_active=True)
            if obj and obj.city_id:
                qs = City.objects.filter(Q(is_active=True) | Q(pk=obj.city_id))
            form.base_fields["city"].queryset = qs.order_by("sort_order", "name")
        return form


@admin.register(ProductImage)
class ProductImageAdmin(admin.ModelAdmin):
    list_display = ("image_thumbnail", "product", "order", "image_preview")
    list_filter = ("product",)
    search_fields = ("product__sku", "product__model_name_ru", "alt_ru", "alt_en")
    ordering = ("product", "order")
    readonly_fields = ("image_preview",)
    
    @admin.display(description="Фото")
    def image_thumbnail(self, obj: ProductImage):
        if not getattr(obj, "image", None):
            return "—"
        try:
            return format_html(
                '<img src="{}" style="height:32px; width:auto; object-fit:contain;" alt="">',
                obj.image.url,
            )
        except Exception:  # noqa: BLE001
            return "—"
    
    @admin.display(description="Превью")
    def image_preview(self, obj: ProductImage):
        if not getattr(obj, "image", None):
            return "—"
        try:
            return format_html(
                '<img src="{}" style="max-height:160px; width:auto; object-fit:contain; background:#111; padding:8px; border-radius:8px;" alt="">',
                obj.image.url,
            )
        except Exception:  # noqa: BLE001
            return "—"


@admin.register(SiteSettings)
class SiteSettingsAdmin(admin.ModelAdmin):
    fieldsets = (
        (
            "Контакты",
            {
                "fields": ("phone", "email", "whatsapp_number"),
            },
        ),
        (
            "Реквизиты организации",
            {
                "fields": ("inn", "ogrn", "legal_address"),
                "description": mark_safe(
                    "<p><strong>Реквизиты организации:</strong></p>"
                    "<ul>"
                    "<li><strong>ИНН</strong> — идентификационный номер налогоплательщика</li>"
                    "<li><strong>ОГРН</strong> — основной государственный регистрационный номер</li>"
                    "<li><strong>Юридический адрес</strong> — полный юридический адрес организации</li>"
                    "</ul>"
                ),
            },
        ),
        (
            "Фактические адреса",
            {
                "fields": ("office_address_1", "office_address_2"),
                "description": mark_safe(
                    "<p><strong>Фактические адреса офисов/складов:</strong></p>"
                    "<ul>"
                    "<li><strong>Фактический адрес 1</strong> — первый адрес (офис/склад)</li>"
                    "<li><strong>Фактический адрес 2</strong> — второй адрес (офис/склад), опционально</li>"
                    "</ul>"
                ),
            },
        ),
        (
            "Адрес и карта",
            {
                "fields": ("address", "work_hours", "map_embed"),
                "description": "Если адрес не указан, блок адреса на странице контактов не отображается.",
            },
        ),
        (
            "Мессенджеры",
            {
                "fields": ("telegram_bot_token", "telegram_chat_id"),
            },
        ),
        (
            "Прочее",
            {
                "fields": ("analytics_code",),
            },
        ),
        (
            "SEO: В наличии",
            {
                "fields": ("in_stock_seo_description", "in_stock_seo_faq"),
                "description": "SEO-контент для страницы /catalog/in-stock/",
            },
        ),
    )
    
    def has_add_permission(self, request):
        try:
            return not SiteSettings.objects.exists()
        except Exception:  # noqa: BLE001
            # If database schema mismatch (e.g., migration not applied), allow add
            return True

    def has_delete_permission(self, request, obj=None):
        # Prevent deletion of the singleton
        return False

    def get_queryset(self, request):
        return super().get_queryset(request).filter(pk=1)

    def changelist_view(self, request, extra_context=None):
        # Redirect to the singleton's change page
        obj, created = SiteSettings.objects.get_or_create(pk=1)
        from django.shortcuts import redirect
        from django.urls import reverse
        return redirect(reverse("admin:catalog_sitesettings_change", args=[obj.pk]))

    def change_view(self, request, object_id=None, form_url="", extra_context=None):
        try:
            obj, created = SiteSettings.objects.get_or_create(pk=1)
            if created:
                from django.contrib import messages
                messages.info(request, "Настройки сайта созданы. Заполните необходимые поля.")
        except Exception:  # noqa: BLE001
            # If database schema mismatch (e.g., migration not applied), continue anyway
            # The form will handle the error gracefully
            pass
        object_id = object_id or "1"
        return super().change_view(request, object_id, form_url, extra_context)


admin.site.site_header = "CARFAST — Админ-панель"
admin.site.site_title = "CARFAST Admin"
admin.site.index_title = "Управление сайтом"


class StockImportForm(forms.Form):
    file = forms.FileField(label="XLSX файл")
    sheet = forms.CharField(
        label="Лист (опционально)",
        required=False,
        help_text='Если не указать — используется активный лист. Например: "Table 1".',
    )
    dry_run = forms.BooleanField(label="Dry-run (без записи)", required=False, initial=True)
    deactivate_missing = forms.BooleanField(
        label="Deactivate-missing (деактивировать отсутствующие)",
        required=False,
        initial=False,
        help_text="Если включено: предложения из этого же файла, которых нет в новом импорте, станут неактивными.",
    )


def import_stock_admin_view(request):
    context = admin.site.each_context(request)
    report = None

    if request.method == "POST":
        form = StockImportForm(request.POST, request.FILES)
        if form.is_valid():
            uploaded = form.cleaned_data["file"]
            try:
                report = import_stock(
                    file=uploaded,
                    file_name=getattr(uploaded, "name", None) or "uploaded.xlsx",
                    sheet=form.cleaned_data.get("sheet") or None,
                    dry_run=bool(form.cleaned_data.get("dry_run")),
                    deactivate_missing=bool(form.cleaned_data.get("deactivate_missing")),
                )
                if form.cleaned_data.get("dry_run"):
                    messages.info(request, "Dry-run выполнен. База данных не изменялась.")
                else:
                    messages.success(request, "Импорт выполнен.")
            except Exception as exc:  # noqa: BLE001
                messages.error(request, f"Ошибка импорта: {exc}")
    else:
        form = StockImportForm()

    context.update(
        {
            "title": "Импорт остатков XLSX",
            "form": form,
            "report": report,
        }
    )
    return TemplateResponse(request, "admin_custom/import_stock.html", context)


def _register_stock_import_url():
    original_get_urls = admin.site.get_urls

    def get_urls():
        urls = original_get_urls()
        custom_urls = [
            path(
                "import-stock/",
                admin.site.admin_view(import_stock_admin_view),
                name="import_stock",
            )
        ]
        return custom_urls + urls

    admin.site.get_urls = get_urls


_register_stock_import_url()

