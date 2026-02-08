from pathlib import Path
import re

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, IntegerField, Min, Q, Sum, Value
from django.db.models.functions import Coalesce, Lower
from django.urls import reverse
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _

PUBLIC_HIDDEN_BRAND_SLUGS: tuple[str, ...] = ("sitrak",)
PUBLIC_HIDDEN_BRAND_KEYWORDS: tuple[str, ...] = ("sitrak",)

CATEGORY_NAME_SLUG_MAP: dict[str, str] = {
    "самосвалы": "samosval",
    "самосвал": "samosval",
    "седельные тягачи": "tyagach",
    "тягачи": "tyagach",
    "автобетоносмесители": "avtobetonosmesitel",
    "шасси": "shassi",
    "кму": "kmu",
    "кдм": "kdm",
    "сортиментовозы": "sortimentovoz",
    "мусоровозы": "musorovoz",
    "бортовые грузовики": "bortovoy-gruzovik",
    "мультилифты": "multilift",
    "атз": "atz",
    "мкду": "mkdu",
    "ломовозы": "lomovoz",
}


class RichTextField(models.TextField):
    """Простая заглушка RichText."""


class SeriesQuerySet(models.QuerySet):
    def public(self):
        """Series visible on the public site (exclude hidden brands)."""
        qs = self
        for slug in PUBLIC_HIDDEN_BRAND_SLUGS:
            qs = qs.exclude(slug__iexact=slug)
        return qs


class Series(models.Model):
    objects = SeriesQuerySet.as_manager()

    name = models.CharField("Название бренда", max_length=255)
    slug = models.SlugField("URL", unique=True)
    description_ru = RichTextField(blank=True)
    description_en = RichTextField(blank=True)
    history = models.TextField("История бренда", blank=True, default="")
    logo = models.ImageField(
        upload_to="brands/",
        blank=True,
        null=True,
        verbose_name="Логотип",
        help_text=(
            "Форматы: .jpg/.jpeg/.png/.webp (.jfif тоже поддерживается как JPEG). "
            "Рекомендуем: PNG с прозрачностью, 512×512 (квадрат) или 512×256 (широкий)."
        ),
    )
    logo_alt_ru = models.CharField(
        "ALT (RU)",
        max_length=255,
        blank=True,
        default="",
        help_text="Текст для атрибута alt. Если пусто — будет использовано название бренда.",
    )
    seo_description = models.TextField(
        blank=True,
        verbose_name="SEO описание (витрина бренда)",
        help_text="Короткое описание для витрины бренда. Если пусто — блок не показывается.",
    )
    seo_faq = models.TextField(
        blank=True,
        verbose_name="SEO FAQ (витрина бренда)",
        help_text=(
            "FAQ для страницы /catalog/series/<slug>/ в формате JSON-LD FAQPage schema. "
            "Формат: один вопрос-ответ на строку, разделитель «|». "
            "Пример:\n"
            "Какие сроки поставки?|Сроки зависят от наличия техники.\n"
            "Какие варианты оплаты?|Работаем с различными вариантами оплаты."
        ),
    )
    seo_intro_html = models.TextField(
        blank=True,
        default="",
        verbose_name="SEO-интро (над карточками)",
        help_text="Короткий блок над сеткой карточек. Допускаются теги: p, strong, em, a, ul, ol, li.",
    )
    seo_body_html = models.TextField(
        blank=True,
        default="",
        verbose_name="SEO-блок под карточками",
        help_text="Развёрнутый блок под сеткой карточек. Допускаются теги: p, strong, em, a, ul, ol, li, h2, h3.",
    )

    class Meta:
        ordering = ["name"]
        verbose_name = "Бренд"
        verbose_name_plural = "Бренды"
        constraints = [
            models.UniqueConstraint(
                Lower("slug"), name="series_slug_ci_unique"
            )
        ]

    def __str__(self):
        return self.name

    def clean(self):
        errors = {}
        self.slug = (self.slug or "").strip()
        normalized_slug = slugify(self.slug or "")

        if not self.slug:
            errors["slug"] = _("Slug is required.")
        elif normalized_slug != (self.slug or ""):
            errors["slug"] = _("Slug must contain only URL-safe characters.")
        if (
            self.slug
            and Series.objects.exclude(pk=self.pk)
            .filter(slug__iexact=self.slug)
            .exists()
        ):
            errors["slug"] = _("Slug must be unique.")
        if errors:
            raise ValidationError(errors)


class Category(models.Model):
    name = models.CharField("Название категории", max_length=255)
    slug = models.SlugField("URL", unique=True, max_length=80)
    seo_description = models.TextField(
        blank=True,
        verbose_name="SEO описание (витрина категории)",
        help_text="Короткое описание для витрины категории. Если пусто — блок не показывается.",
    )
    seo_faq = models.TextField(
        blank=True,
        verbose_name="SEO FAQ (витрина категории)",
        help_text=(
            "FAQ для страницы /catalog/category/<slug>/ в формате JSON-LD FAQPage schema. "
            "Формат: один вопрос-ответ на строку, разделитель «|». "
            "Пример:\n"
            "Какие сроки поставки?|Сроки зависят от наличия техники.\n"
            "Какие варианты оплаты?|Работаем с различными вариантами оплаты."
        ),
    )
    seo_intro_html = models.TextField(
        blank=True,
        default="",
        verbose_name="SEO-интро (над карточками)",
        help_text="Короткий блок над сеткой карточек. Допускаются теги: p, strong, em, a, ul, ol, li.",
    )
    seo_body_html = models.TextField(
        blank=True,
        default="",
        verbose_name="SEO-блок под карточками",
        help_text="Развёрнутый блок под сеткой карточек. Допускаются теги: p, strong, em, a, ul, ol, li, h2, h3.",
    )
    cover_image = models.ImageField(
        upload_to="categories/",
        blank=True,
        null=True,
        verbose_name="Титульное фото",
        help_text=(
            "Форматы: .jpg/.jpeg/.png/.webp (.jfif тоже поддерживается как JPEG). "
            "Рекомендуем: 16:9, 1600×900 (оптимально) или 1600×600, минимум 1200×675. "
            "JPG качество 80–85 или WebP, ≤500 KB."
        ),
    )
    cover_alt_ru = models.CharField(
        "ALT (RU)",
        max_length=255,
        blank=True,
        default="",
        help_text="Текст для атрибута alt. Если пусто — будет использовано название категории.",
    )

    class Meta:
        ordering = ["name"]
        verbose_name = "Категория Техники"
        verbose_name_plural = "Категории Техники"
        constraints = [
            models.UniqueConstraint(
                Lower("slug"), name="category_slug_ci_unique"
            )
        ]

    def __str__(self):
        return self.name

    def clean(self):
        errors = {}
        self.slug = (self.slug or "").strip()
        normalized_slug = slugify(self.slug or "")

        if not self.slug:
            errors["slug"] = _("Slug is required.")
        elif normalized_slug != (self.slug or ""):
            errors["slug"] = _("Slug must contain only URL-safe characters.")
        if (
            self.slug
            and Category.objects.exclude(pk=self.pk)
            .filter(slug__iexact=self.slug)
            .exists()
        ):
            errors["slug"] = _("Slug must be unique.")
        if errors:
            raise ValidationError(errors)


class SeriesCategorySEO(models.Model):
    """SEO-контент для landing pages series+category."""
    series = models.ForeignKey(
        Series,
        verbose_name="Бренд",
        on_delete=models.CASCADE,
        related_name="series_category_seo",
    )
    category = models.ForeignKey(
        Category,
        verbose_name="Категория",
        on_delete=models.CASCADE,
        related_name="series_category_seo",
    )
    seo_description = models.TextField(
        blank=True,
        verbose_name="SEO описание",
        help_text="Короткое описание для витрины series+category. Если пусто — блок не показывается.",
    )
    seo_faq = models.TextField(
        blank=True,
        verbose_name="SEO FAQ",
        help_text=(
            "FAQ для страницы /catalog/series/<series>/<category>/ в формате JSON-LD FAQPage schema. "
            "Формат: один вопрос-ответ на строку, разделитель «|». "
            "Пример:\n"
            "Какие сроки поставки?|Сроки зависят от наличия техники.\n"
            "Какие варианты оплаты?|Работаем с различными вариантами оплаты."
        ),
    )
    seo_intro_html = models.TextField(
        blank=True,
        default="",
        verbose_name="SEO-интро (над карточками)",
        help_text="Короткий блок над сеткой карточек. Допускаются теги: p, strong, em, a, ul, ol, li.",
    )
    seo_body_html = models.TextField(
        blank=True,
        default="",
        verbose_name="SEO-блок под карточками",
        help_text="Развёрнутый блок под сеткой карточек. Допускаются теги: p, strong, em, a, ul, ol, li, h2, h3.",
    )

    class Meta:
        ordering = ["series__name", "category__name"]
        verbose_name = "SEO контент (series+category)"
        verbose_name_plural = "SEO контент (series+category)"
        constraints = [
            models.UniqueConstraint(
                fields=["series", "category"],
                name="series_category_seo_unique",
            )
        ]

    def __str__(self):
        return f"{self.series.name} — {self.category.name}"


class ShacmanHubSEO(models.Model):
    """
    SEO-контент для посадочных страниц /shacman/* (редактируемый из админки).
    Один объект на тип хаба: главный, в наличии, категория, категория в наличии,
    формула/двигатель/линейка (фасеты) — для фасетов задаётся facet_key.
    """
    class HubType(models.TextChoices):
        MAIN = "main", _("Главный хаб /shacman/")
        IN_STOCK = "in_stock", _("В наличии /shacman/in-stock/")
        CATEGORY = "category", _("Категория /shacman/<category>/")
        CATEGORY_IN_STOCK = "category_in_stock", _("Категория в наличии /shacman/<category>/in-stock/")
        FORMULA = "formula", _("Формула /shacman/formula/<formula>/")
        FORMULA_IN_STOCK = "formula_in_stock", _("Формула в наличии /shacman/formula/<formula>/in-stock/")
        ENGINE = "engine", _("Двигатель /shacman/engine/<engine>/")
        ENGINE_IN_STOCK = "engine_in_stock", _("Двигатель в наличии /shacman/engine/<engine>/in-stock/")
        LINE = "line", _("Линейка /shacman/line/<line>/")
        LINE_IN_STOCK = "line_in_stock", _("Линейка в наличии /shacman/line/<line>/in-stock/")
        # Combo hubs (category+line, line+formula, category+formula explicit)
        CATEGORY_LINE = "category_line", _("Категория + линейка /shacman/category/<cat>/line/<line>/")
        CATEGORY_LINE_IN_STOCK = "category_line_in_stock", _("Категория + линейка в наличии")
        LINE_FORMULA = "line_formula", _("Линейка + формула /shacman/line/<line>/formula/<formula>/")
        LINE_FORMULA_IN_STOCK = "line_formula_in_stock", _("Линейка + формула в наличии")
        CATEGORY_FORMULA_EXPLICIT = "category_formula_explicit", _("Категория + формула /shacman/category/<cat>/formula/<formula>/")
        CATEGORY_FORMULA_EXPLICIT_IN_STOCK = "category_formula_explicit_in_stock", _("Категория + формула в наличии")
        # Category + line + formula
        CATEGORY_LINE_FORMULA = "category_line_formula", _("Категория + линейка + формула /shacman/category/<cat>/line/<line>/formula/<formula>/")
        CATEGORY_LINE_FORMULA_IN_STOCK = "category_line_formula_in_stock", _("Категория + линейка + формула в наличии")
        # Model code (SX…)
        MODEL_CODE = "model_code", _("Код модели /shacman/model/<model_code_slug>/")
        MODEL_CODE_IN_STOCK = "model_code_in_stock", _("Код модели в наличии")

    hub_type = models.CharField(
        "Тип хаба",
        max_length=50,
        choices=HubType.choices,
    )
    category = models.ForeignKey(
        Category,
        verbose_name="Категория",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="shacman_hub_seo",
        help_text="Только для типа «категория» / «категория в наличии».",
    )
    facet_key = models.CharField(
        "Фасет (formula / engine_slug / line_slug / line:formula)",
        max_length=255,
        blank=True,
        default="",
        help_text="Для formula/engine/line: формула, slug двигателя или линейки. Для combo: line_slug (category_line), «line:formula» (line_formula, category_line_formula), formula (category_formula_explicit).",
    )
    meta_title = models.CharField(
        "SEO Title",
        max_length=255,
        blank=True,
        default="",
    )
    meta_description = models.CharField(
        "Meta Description",
        max_length=500,
        blank=True,
        default="",
    )
    seo_text = RichTextField(
        "SEO-текст (900–1500 слов)",
        blank=True,
        default="",
        help_text="Блоки: Купить SHACMAN, В наличии, Лизинг, Доставка, Гарантия/сервис, Как получить КП, FAQ. HTML допускается.",
    )
    seo_intro_html = RichTextField(
        "SEO-интро (над карточками)",
        blank=True,
        default="",
        help_text="Короткий блок над листингом. Допускаются теги: p, strong, em, a, ul, ol, li.",
    )
    seo_body_html = RichTextField(
        "SEO-блок под карточками",
        blank=True,
        default="",
        help_text="Развёрнутый блок под листингом. Допускаются теги: p, strong, em, a, ul, ol, li, h2, h3.",
    )
    faq = models.TextField(
        "FAQ (вопрос | ответ на строку)",
        blank=True,
        default="",
        help_text="Один вопрос-ответ на строку, разделитель «|». Пример: Какие сроки?|Сроки зависят от наличия.",
    )
    also_search_line = models.CharField(
        "Варианты написания (1 строка)",
        max_length=255,
        blank=True,
        default="",
        help_text="Например: Также ищут: Шакман / Shacman / Shaanxi",
    )
    force_index = models.BooleanField(
        "Индексировать при малом числе товаров",
        default=False,
        help_text="Если включено и контент достаточный (текст/body ≥1500 символов или FAQ ≥3), хаб с 1 товаром может быть index,follow и в sitemap.",
    )

    class Meta:
        ordering = ["hub_type", "facet_key", "category__name"]
        verbose_name = "SEO хаб SHACMAN"
        verbose_name_plural = "SEO хабы SHACMAN"
        constraints = [
            models.UniqueConstraint(
                fields=["hub_type", "category"],
                condition=Q(facet_key=""),
                name="shacman_hub_seo_type_category_unique",
            ),
            models.UniqueConstraint(
                fields=["hub_type", "category", "facet_key"],
                condition=~Q(facet_key=""),
                name="shacman_hub_seo_type_combo_unique",
            ),
        ]

    def __str__(self):
        if self.category:
            return f"SHACMAN {self.get_hub_type_display()} — {self.category.name}"
        if self.facet_key:
            return f"SHACMAN {self.get_hub_type_display()} — {self.facet_key}"
        return f"SHACMAN {self.get_hub_type_display()}"

    def clean(self):
        combo_category_types = (
            self.HubType.CATEGORY_LINE, self.HubType.CATEGORY_LINE_IN_STOCK,
            self.HubType.CATEGORY_FORMULA_EXPLICIT, self.HubType.CATEGORY_FORMULA_EXPLICIT_IN_STOCK,
            self.HubType.CATEGORY_LINE_FORMULA, self.HubType.CATEGORY_LINE_FORMULA_IN_STOCK,
        )
        combo_facet_only = (self.HubType.LINE_FORMULA, self.HubType.LINE_FORMULA_IN_STOCK)
        combo_category_line_formula = (self.HubType.CATEGORY_LINE_FORMULA, self.HubType.CATEGORY_LINE_FORMULA_IN_STOCK)
        if self.hub_type in (self.HubType.CATEGORY, self.HubType.CATEGORY_IN_STOCK) and not self.category_id:
            raise ValidationError({"category": _("Для типа «категория» / «категория в наличии» укажите категорию.")})
        if self.hub_type in (self.HubType.MAIN, self.HubType.IN_STOCK) and self.category_id:
            raise ValidationError({"category": _("Для главного хаба и «в наличии» категория не задаётся.")})
        facet_types = (self.HubType.FORMULA, self.HubType.FORMULA_IN_STOCK, self.HubType.ENGINE, self.HubType.ENGINE_IN_STOCK, self.HubType.LINE, self.HubType.LINE_IN_STOCK, self.HubType.MODEL_CODE, self.HubType.MODEL_CODE_IN_STOCK)
        if self.hub_type in facet_types and not (self.facet_key or "").strip():
            raise ValidationError({"facet_key": _("Для фасетного типа укажите facet_key (формула, engine_slug или line_slug).")})
        if self.hub_type in facet_types and self.category_id:
            raise ValidationError({"category": _("Для фасетного типа категория не задаётся.")})
        if self.hub_type in combo_category_types and not self.category_id:
            raise ValidationError({"category": _("Для комбо-типа категория+линейка/формула укажите категорию.")})
        if self.hub_type in combo_category_types and not (self.facet_key or "").strip():
            raise ValidationError({"facet_key": _("Для комбо-типа укажите facet_key (line_slug или formula).")})
        if self.hub_type in combo_facet_only and (self.category_id or not (self.facet_key or "").strip()):
            if self.category_id:
                raise ValidationError({"category": _("Для линейка+формула категория не задаётся.")})
            raise ValidationError({"facet_key": _("Для линейка+формула укажите facet_key в формате line_slug:formula (например x3000:6x4).")})
        if self.hub_type in combo_category_line_formula:
            if not self.category_id:
                raise ValidationError({"category": _("Для категория+линейка+формула укажите категорию.")})
            fk = (self.facet_key or "").strip()
            if ":" not in fk or len(fk.split(":", 1)) != 2:
                raise ValidationError({"facet_key": _("Для категория+линейка+формула укажите facet_key в формате line_slug:formula (например x3000:8x4).")})


class ModelVariant(models.Model):
    """
    Модель/модификация техники (для бренда): линейка + колёсная формула.

    Пример: X6000 6x4 (slug: x6000-6x4)
    """

    brand = models.ForeignKey(
        Series,
        verbose_name="Бренд",
        on_delete=models.CASCADE,
        related_name="model_variants",
    )
    name = models.CharField("Название модели", max_length=255)
    slug = models.SlugField("URL", unique=True)
    line = models.CharField("Линейка", max_length=50)
    wheel_formula = models.CharField("Колёсная формула", max_length=50)
    sort_order = models.IntegerField("Порядок", default=0)

    class Meta:
        ordering = ["sort_order", "name"]
        verbose_name = "Модель / модификация"
        verbose_name_plural = "Модели / модификации"
        constraints = [
            models.UniqueConstraint(
                Lower("slug"), name="modelvariant_slug_ci_unique"
            ),
            models.UniqueConstraint(
                Lower("name"),
                models.F("brand"),
                name="modelvariant_brand_name_ci_unique",
            ),
        ]

    def __str__(self) -> str:
        return self.name

    def clean(self):
        errors = {}
        self.slug = (self.slug or "").strip()
        self.name = (self.name or "").strip()
        self.line = (self.line or "").strip()
        self.wheel_formula = (self.wheel_formula or "").strip()

        normalized_slug = slugify(self.slug or "")

        if not self.brand_id:
            errors["brand"] = _("Brand is required.")
        if not self.name:
            errors["name"] = _("Name is required.")
        if not self.slug:
            errors["slug"] = _("Slug is required.")
        elif normalized_slug != (self.slug or ""):
            errors["slug"] = _("Slug must contain only URL-safe characters.")
        if not self.line:
            errors["line"] = _("Line is required.")
        if not self.wheel_formula:
            errors["wheel_formula"] = _("Wheel formula is required.")

        if (
            self.slug
            and ModelVariant.objects.exclude(pk=self.pk)
            .filter(slug__iexact=self.slug)
            .exists()
        ):
            errors["slug"] = _("Slug must be unique.")

        if (
            self.brand_id
            and self.name
            and ModelVariant.objects.exclude(pk=self.pk)
            .filter(brand_id=self.brand_id, name__iexact=self.name)
            .exists()
        ):
            errors["name"] = _("Name must be unique within the brand.")

        if errors:
            raise ValidationError(errors)


class City(models.Model):
    name = models.CharField("Город", max_length=255)
    slug = models.SlugField("URL", unique=True)
    sort_order = models.IntegerField("Порядок", default=0)
    is_active = models.BooleanField("Активен", default=True)

    class Meta:
        ordering = ["sort_order", "name"]
        verbose_name = "Город"
        verbose_name_plural = "Города"
        constraints = [
            models.UniqueConstraint(Lower("slug"), name="city_slug_ci_unique"),
        ]

    def __str__(self) -> str:
        return self.name

    def clean(self):
        errors = {}
        self.slug = (self.slug or "").strip()
        normalized_slug = slugify(self.slug or "")

        if not self.slug:
            errors["slug"] = _("Slug is required.")
        elif normalized_slug != (self.slug or ""):
            errors["slug"] = _("Slug must contain only URL-safe characters.")
        if (
            self.slug
            and City.objects.exclude(pk=self.pk)
            .filter(slug__iexact=self.slug)
            .exists()
        ):
            errors["slug"] = _("Slug must be unique.")
        if errors:
            raise ValidationError(errors)


class ProductQuerySet(models.QuerySet):
    def with_stock_stats(self):
        """
        Annotate:
        - total_qty: SUM(qty) по активным предложениям
        - min_price: MIN(price) по активным предложениям (price != NULL)
        - display_price: цена для отображения (min_price, fallback на Product.price)
        """
        return self.annotate(
            total_qty=Coalesce(
                Sum("offers__qty", filter=Q(offers__is_active=True)),
                Value(0),
                output_field=IntegerField(),
            ),
            min_price=Min(
                "offers__price",
                filter=Q(offers__is_active=True, offers__price__isnull=False),
            ),
        ).annotate(display_price=Coalesce(F("min_price"), F("price")))

    def public(self):
        """Products visible on the public site (published + active + no hidden brands)."""
        qs = self.filter(published=True, is_active=True)
        for slug in PUBLIC_HIDDEN_BRAND_SLUGS:
            qs = qs.exclude(series__slug__iexact=slug)
        for keyword in PUBLIC_HIDDEN_BRAND_KEYWORDS:
            qs = (
                qs.exclude(sku__icontains=keyword)
                .exclude(model_name_ru__icontains=keyword)
                .exclude(model_name_en__icontains=keyword)
                .exclude(short_description_ru__icontains=keyword)
                .exclude(short_description_en__icontains=keyword)
            )
        return qs


class Product(models.Model):
    class Availability(models.TextChoices):
        IN_STOCK = "IN_STOCK", _("В наличии")
        ON_REQUEST = "ON_REQUEST", _("Под заказ")

    objects = ProductQuerySet.as_manager()

    sku = models.CharField("Артикул", max_length=100, unique=True)
    slug = models.SlugField("URL", unique=True, max_length=80)

    series = models.ForeignKey(
        Series,
        verbose_name="Бренд",
        on_delete=models.SET_NULL,
        null=True,
        related_name="products",
    )

    model_code = models.CharField(
        "Код модели", max_length=120, db_index=True, blank=True, default=""
    )
    config = models.TextField("Комплектация (норм.)", blank=True, default="")
    is_active = models.BooleanField("Активен", default=True)
    is_used = models.BooleanField(
        "Б/у",
        default=False,
        help_text="Товар с пробегом; отображается на странице /used/ и с бейджем «Б/у».",
    )

    category = models.ForeignKey(
        Category,
        verbose_name="Категория",
        on_delete=models.SET_NULL,
        null=True,
        related_name="products",
    )

    model_variant = models.ForeignKey(
        ModelVariant,
        verbose_name="Модель",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="products",
    )

    model_name_ru = models.CharField("Модель (RU)", max_length=255)
    model_name_en = models.CharField("Модель (EN)", max_length=255)

    short_description_ru = models.CharField(
        "Краткое описание (RU)", max_length=500, blank=True
    )
    short_description_en = models.CharField(
        "Краткое описание (EN)", max_length=500, blank=True
    )

    description_ru = RichTextField("Описание (RU)", blank=True)
    description_en = RichTextField("Описание (EN)", blank=True)

    price = models.DecimalField(
        "Цена", max_digits=12, decimal_places=2, null=True, blank=True
    )

    availability = models.CharField(
        "Наличие",
        max_length=20,
        choices=Availability.choices,
        default=Availability.IN_STOCK,
    )

    engine_model = models.CharField("Модель двигателя", max_length=255, blank=True)
    power_hp = models.IntegerField("Мощность, л.с.", null=True, blank=True)
    wheel_formula = models.CharField("Колёсная формула", max_length=50, blank=True)
    wheelbase_mm = models.PositiveIntegerField("Колёсная база, мм", null=True, blank=True)
    payload_tons = models.DecimalField(
        "Грузоподъёмность, т", max_digits=8, decimal_places=2, null=True, blank=True
    )
    dimensions = models.CharField("Габариты", max_length=255, blank=True)

    options = models.JSONField("Опции", blank=True, default=dict)
    tags = models.JSONField("Теги", blank=True, default=list)

    published = models.BooleanField("Опубликован", default=True)
    views_count = models.PositiveIntegerField("Просмотры", default=0)

    # SEO overrides: if set, used instead of auto-generated title/description/text/FAQ
    seo_title_override = models.CharField(
        "SEO title (переопределение)", max_length=255, blank=True, default=""
    )
    seo_description_override = models.CharField(
        "SEO description (переопределение)", max_length=500, blank=True, default=""
    )
    seo_text_override = RichTextField(
        "SEO текст (переопределение)", blank=True, default=""
    )
    seo_faq_override = models.TextField(
        "SEO FAQ (переопределение)",
        blank=True,
        default="",
        help_text=(
            "Формат: один вопрос-ответ на строку, разделитель «|». "
            "Пример: Какие сроки поставки?|Сроки зависят от наличия."
        ),
    )

    # Canonical / redirect for duplicate product pages (301 to canonical or hub)
    canonical_product = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="aliases",
        verbose_name="Канонический товар",
        help_text="Если задан — страница этого товара отдаёт 301 на канонический. В sitemap не попадает.",
    )
    redirect_to_url = models.URLField(
        "Редирект на URL",
        blank=True,
        default="",
        max_length=500,
        help_text="Если задан — страница отдаёт 301 на этот URL (хаб/внешняя страница). В sitemap не попадает.",
    )

    created_at = models.DateTimeField("Создан", auto_now_add=True)
    updated_at = models.DateTimeField("Обновлён", auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(
                fields=["availability"], name="product_availability_idx"
            ),
            models.Index(
                fields=["published", "-created_at"],
                name="product_published_created_idx",
            ),
            models.Index(
                fields=["category", "published"],
                name="product_category_published_idx",
            ),
            models.Index(
                fields=["series", "published"], name="product_series_published_idx"
            ),
            models.Index(
                fields=["model_variant", "published"],
                name="product_modelvar_pub_idx",
            ),
            models.Index(
                fields=["is_used", "published"],
                name="product_is_used_published_idx",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                Lower("slug"), name="product_slug_ci_unique"
            ),
            models.UniqueConstraint(
                Lower("sku"), name="product_sku_ci_unique"
            ),
        ]
        verbose_name = "Единица Техники"
        verbose_name_plural = "Техника"

    def __str__(self):
        return f"{self.sku} - {self.model_name_ru}"

    def clean(self):
        errors = {}
        self.slug = (self.slug or "").strip()
        if self.slug:
            normalized_slug = slugify(self.slug or "")
            if normalized_slug != (self.slug or ""):
                errors["slug"] = _("Slug must contain only URL-safe characters.")
            if (
                self.slug
                and Product.objects.exclude(pk=self.pk)
                .filter(slug__iexact=self.slug)
                .exists()
            ):
                errors["slug"] = _("Slug must be unique.")
        if self.canonical_product_id and self.canonical_product_id == self.pk:
            errors["canonical_product"] = _("Канонический товар не может указывать на себя.")
        if self.canonical_product_id and (self.redirect_to_url or "").strip():
            errors["redirect_to_url"] = _(
                "Задайте только одно: либо канонический товар, либо редирект на URL."
            )
        if (self.redirect_to_url or "").strip() and self.canonical_product_id:
            errors["canonical_product"] = _(
                "Задайте только одно: либо канонический товар, либо редирект на URL."
            )
        if errors:
            raise ValidationError(errors)

    @staticmethod
    def _normalize_wheel_formula(value: str | None) -> str:
        if not value:
            return ""
        raw = str(value).strip().lower()
        raw = raw.replace("×", "x").replace("х", "x")
        raw = raw.replace(" ", "")
        return re.sub(r"[^0-9x]", "", raw)

    @staticmethod
    def _safe_slugify(value: str | None) -> str:
        return slugify(value) if value else ""

    def _build_auto_slug(self) -> str:
        max_len = self._meta.get_field("slug").max_length
        brand_slug = ""
        if self.series:
            brand_slug = self.series.slug or self.series.name
        brand_slug = self._safe_slugify(brand_slug)

        type_slug = ""
        if self.category:
            if self.category.slug:
                type_slug = self._safe_slugify(self.category.slug)
            else:
                name_key = (self.category.name or "").strip().lower()
                mapped = CATEGORY_NAME_SLUG_MAP.get(name_key, "")
                type_slug = self._safe_slugify(mapped)

        if not type_slug:
            raise ValidationError(
                {"slug": _("Type slug is required to build product URL.")}
            )

        line_slug = ""
        if self.model_variant and self.model_variant.line:
            line_slug = self._safe_slugify(self.model_variant.line)

        wheel_formula = self._normalize_wheel_formula(
            self.wheel_formula
            or (self.model_variant.wheel_formula if self.model_variant else "")
        )
        wheel_slug = self._safe_slugify(wheel_formula)

        model_code_slug = self._safe_slugify((self.model_code or "").lower())

        def build_slug(parts: list[str]) -> str:
            return "-".join([p for p in parts if p])

        prefix_parts = [brand_slug, type_slug, line_slug]
        full_slug = build_slug([*prefix_parts, wheel_slug, model_code_slug])
        if full_slug and len(full_slug) <= max_len:
            return full_slug

        no_wheel_slug = build_slug([*prefix_parts, model_code_slug])
        if no_wheel_slug and len(no_wheel_slug) <= max_len:
            return no_wheel_slug

        if model_code_slug:
            base_prefix = build_slug(prefix_parts)
            available = max_len - len(base_prefix) - (1 if base_prefix else 0)
            if available < 1:
                raise ValidationError(
                    {"slug": _("Slug could not be generated from available fields.")}
                )
            trimmed_code = model_code_slug[:available]
            if not trimmed_code:
                raise ValidationError(
                    {"slug": _("Slug could not be generated from available fields.")}
                )
            trimmed_slug = build_slug([*prefix_parts, trimmed_code])
            if trimmed_slug and len(trimmed_slug) <= max_len:
                return trimmed_slug

        raise ValidationError(
            {"slug": _("Slug could not be generated from available fields.")}
        )

    def _ensure_unique_slug(self, slug: str) -> str:
        if not slug:
            return ""
        base = slug
        counter = 2
        max_len = self._meta.get_field("slug").max_length
        while Product.objects.exclude(pk=self.pk).filter(slug__iexact=slug).exists():
            suffix = f"-{counter}"
            if len(base) + len(suffix) > max_len:
                trimmed = base[: max_len - len(suffix)].rstrip("-")
                slug = f"{trimmed}{suffix}"
            else:
                slug = f"{base}{suffix}"
            counter += 1
        return slug

    def save(self, *args, **kwargs):
        if self.slug:
            if (
                Product.objects.exclude(pk=self.pk)
                .filter(slug__iexact=self.slug)
                .exists()
            ):
                raise ValidationError({"slug": _("Slug must be unique.")})
        else:
            generated = self._build_auto_slug()
            self.slug = self._ensure_unique_slug(generated)
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("catalog:product_detail", kwargs={"slug": self.slug})

    @property
    def title(self) -> str:
        return self.model_name_ru

    @property
    def main_image(self):
        cache = getattr(self, "_prefetched_objects_cache", {}) or {}
        images = cache.get("images")
        if images is not None:
            return images[0] if images else None
        return self.images.order_by("order", "id").first()

    def to_schemaorg(self, request=None):
        from catalog.utils.text_cleaner import clean_text

        total_qty = getattr(self, "total_qty", None)
        if total_qty is None:
            total_qty = (
                self.offers.filter(is_active=True).aggregate(
                    total=Coalesce(Sum("qty"), Value(0), output_field=IntegerField())
                )["total"]
                or 0
            )
        is_in_stock = bool(total_qty and total_qty > 0)

        build_url = request.build_absolute_uri if request else (lambda url: url)
        
        # Collect all images
        images = []
        if self.main_image and getattr(self.main_image, "image", None):
            images.append(build_url(self.main_image.image.url))
        # Add other images
        for img in self.images.order_by("order", "id")[1:5]:  # Limit to 5 images total
            if img.image:
                images.append(build_url(img.image.url))
        
        price_value = getattr(self, "min_price", None)
        if price_value is None:
            price_value = self.price
        
        # Build offer with proper schema.org structure
        offer = {
            "@type": "Offer",
            "priceCurrency": "RUB",
            "availability": "https://schema.org/InStock"
            if is_in_stock
            else "https://schema.org/PreOrder",
            "url": build_url(self.get_absolute_url()),
            "seller": {
                "@type": "Organization",
                "@id": "https://carfst.ru/#organization",
                "name": "CARFAST",
            },
        }
        if price_value is not None:
            offer["price"] = str(float(price_value))
        
        name = clean_text(self.model_name_ru)
        desc_raw = self.short_description_ru or self.description_ru or ""
        description = clean_text(desc_raw)[:500]

        # Build product data
        data = {
            "@context": "https://schema.org",
            "@type": "Product",
            "sku": self.sku,
            "name": name,
            "description": description,
            "url": build_url(self.get_absolute_url()),
            "offers": offer,
        }
        if self.model_code:
            data["mpn"] = clean_text(self.model_code)
        
        # Add category if available
        if self.category:
            data["category"] = clean_text(self.category.name)
        
        # Add brand if available
        if self.series:
            data["brand"] = {
                "@type": "Brand",
                "name": clean_text(self.series.name),
            }
        
        # Add images (single image or array)
        if images:
            if len(images) == 1:
                data["image"] = images[0]
            else:
                data["image"] = images
        
        return data

    def clean(self):
        errors = {}
        self.sku = (self.sku or "").strip()
        self.slug = (self.slug or "").strip()

        if not self.sku:
            errors["sku"] = _("SKU is required.")
        if not self.slug:
            errors["slug"] = _("Slug is required.")

        normalized_slug = slugify(self.slug or "")
        if self.slug and normalized_slug != self.slug:
            errors["slug"] = _("Slug must contain only URL-safe characters.")

        if self.availability and self.availability not in dict(self.Availability.choices):
            errors["availability"] = _("Unknown availability value.")

        if (
            self.sku
            and Product.objects.exclude(pk=self.pk)
            .filter(sku__iexact=self.sku)
            .exists()
        ):
            errors["sku"] = _("SKU must be unique.")

        if (
            self.slug
            and Product.objects.exclude(pk=self.pk)
            .filter(slug__iexact=self.slug)
            .exists()
        ):
            errors["slug"] = _("Slug must be unique.")

        if self.options is None:
            self.options = {}
        if not isinstance(self.options, dict):
            errors["options"] = _("Options must be a mapping.")

        if self.tags is None:
            self.tags = []
        if not isinstance(self.tags, list):
            errors["tags"] = _("Tags must be a list.")

        # Валидация консистентности с ModelVariant
        if self.model_variant_id:
            try:
                model_variant = self.model_variant
            except ModelVariant.DoesNotExist:
                model_variant = None

            if model_variant:
                # Проверка и автоподстановка series (brand)
                if not self.series_id:
                    # Автоподстановка: series = model_variant.brand
                    self.series = model_variant.brand
                elif self.series_id != model_variant.brand_id:
                    errors["series"] = _(
                        "Бренд товара должен совпадать с брендом выбранной модели. "
                        "Выбранная модель относится к бренду: %(brand)s"
                    ) % {"brand": model_variant.brand.name}

                # Проверка и автоподстановка wheel_formula
                wheel_formula_raw = self.wheel_formula or ""
                normalized_product = self._normalize_wheel_formula(wheel_formula_raw)
                normalized_model = self._normalize_wheel_formula(
                    model_variant.wheel_formula or ""
                )
                if not normalized_product:
                    # Автоподстановка: wheel_formula = model_variant.wheel_formula
                    self.wheel_formula = normalized_model or wheel_formula_raw.strip()
                elif normalized_model and normalized_product != normalized_model:
                    errors["wheel_formula"] = _(
                        "Колёсная формула товара должна совпадать с колёсной формулой выбранной модели. "
                        "Колёсная формула модели: %(formula)s"
                    ) % {"formula": model_variant.wheel_formula}
                else:
                    self.wheel_formula = normalized_product

        if errors:
            raise ValidationError(errors)


class Offer(models.Model):
    product = models.ForeignKey(
        Product, related_name="offers", on_delete=models.CASCADE, verbose_name="Товар"
    )
    city = models.ForeignKey(
        City, related_name="offers", on_delete=models.PROTECT, verbose_name="Город"
    )

    qty = models.PositiveIntegerField("Количество", default=0)
    price = models.DecimalField(
        "Цена", max_digits=12, decimal_places=2, null=True, blank=True
    )
    currency = models.CharField("Валюта", max_length=10, default="RUB", blank=True)
    vat = models.CharField("НДС", max_length=50, blank=True, default="с НДС")
    year = models.PositiveSmallIntegerField("Год", null=True, blank=True)

    source_file = models.CharField("Файл-источник", max_length=255, blank=True, default="")
    source_row_hash = models.CharField(
        "Хэш строки", max_length=64, db_index=True, blank=True, default=""
    )
    batch_token = models.CharField(
        "Токен импорта", max_length=64, db_index=True, blank=True, default=""
    )

    updated_at = models.DateTimeField("Обновлено", auto_now=True)
    is_active = models.BooleanField("Активно", default=True)

    class Meta:
        ordering = ["city__sort_order", "city__name", "-updated_at", "-id"]
        verbose_name = "Предложение / Остаток"
        verbose_name_plural = "Предложения / Остатки"
        indexes = [
            models.Index(fields=["product", "is_active"], name="offer_product_active_idx"),
            models.Index(fields=["city", "is_active"], name="offer_city_active_idx"),
            models.Index(fields=["source_file", "batch_token"], name="offer_source_batch_idx"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["product", "city", "price", "year", "vat"],
                condition=Q(price__isnull=False),
                name="uniq_offer_key",
            ),
            models.UniqueConstraint(
                fields=["product", "city", "year", "vat"],
                condition=Q(price__isnull=True),
                name="uniq_offer_key_null_price",
            ),
        ]

    def __str__(self) -> str:
        price = f"{self.price} {self.currency}" if self.price is not None else "без цены"
        return f"{self.product} — {self.city}: {self.qty} шт., {price}"


class Lead(models.Model):
    product = models.ForeignKey(
        Product, on_delete=models.SET_NULL, null=True, blank=True, related_name="leads"
    )
    name = models.CharField(max_length=255)
    phone = models.CharField(max_length=50)
    email = models.EmailField(blank=True)
    message = models.TextField(blank=True)
    source = models.CharField(max_length=255, blank=True)
    utm_source = models.CharField(max_length=255, blank=True)
    utm_medium = models.CharField(max_length=255, blank=True)
    utm_campaign = models.CharField(max_length=255, blank=True)
    utm_term = models.CharField(max_length=255, blank=True)
    utm_content = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    processed = models.BooleanField(default=False)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Заявка"
        verbose_name_plural = "Заявки"

    def __str__(self):
        return f"{self.name} ({self.phone})"


class CatalogLandingSEO(models.Model):
    """
    SEO-контент для каталожных посадочных страниц: /catalog/in-stock/ и др.
    Одна запись на landing_key. Управляемые intro/body/FAQ и переопределение meta из админки.
    """

    class LandingKey(models.TextChoices):
        CATALOG_IN_STOCK = "catalog_in_stock", "/catalog/in-stock/"

    landing_key = models.CharField(
        "Ключ посадочной страницы",
        max_length=50,
        choices=LandingKey.choices,
        unique=True,
        help_text="Уникальный ключ страницы: catalog_in_stock.",
    )
    meta_title = models.CharField(
        "Meta Title (переопределение)",
        max_length=255,
        blank=True,
        default="",
        help_text="Если заполнен — переопределяет title страницы.",
    )
    meta_description = models.CharField(
        "Meta Description (переопределение)",
        max_length=500,
        blank=True,
        default="",
        help_text="Если заполнен — переопределяет meta description страницы.",
    )
    seo_intro_html = models.TextField(
        "SEO-интро (над карточками)",
        blank=True,
        default="",
        help_text="Короткий блок над листингом. HTML допускается.",
    )
    seo_body_html = models.TextField(
        "SEO-блок под карточками",
        blank=True,
        default="",
        help_text="Развёрнутый блок под листингом. HTML допускается.",
    )
    faq_items = models.TextField(
        "FAQ (вопрос | ответ на строку)",
        blank=True,
        default="",
        help_text=(
            "Один вопрос-ответ на строку, разделитель «|». "
            "Пример: Какие сроки поставки?|Сроки зависят от наличия. "
            "Рекомендуется 5–10 вопросов для FAQPage schema."
        ),
    )

    class Meta:
        verbose_name = "SEO каталожной посадочной"
        verbose_name_plural = "SEO каталожных посадочных"
        ordering = ["landing_key"]

    def __str__(self):
        return self.get_landing_key_display()


class StaticPageSEO(models.Model):
    """
    SEO-контент для статических info-страниц: /leasing/, /used/, /service/, /parts/, /payment-delivery/.
    Одна запись на страницу по slug. Управляемые intro/body/FAQ и переопределение meta из админки.
    """
    slug = models.SlugField(
        "Slug страницы",
        max_length=100,
        unique=True,
        help_text="Совпадает со slug страницы: leasing, used, service, parts, payment-delivery.",
    )
    meta_title = models.CharField(
        "Meta Title (переопределение)",
        max_length=255,
        blank=True,
        default="",
    )
    meta_description = models.CharField(
        "Meta Description (переопределение)",
        max_length=500,
        blank=True,
        default="",
    )
    seo_intro_html = models.TextField(
        "SEO-интро (над контентом)",
        blank=True,
        default="",
        help_text="Короткий блок над основным контентом страницы. HTML допускается.",
    )
    seo_body_html = models.TextField(
        "SEO-блок внизу страницы",
        blank=True,
        default="",
        help_text="Развёрнутый блок внизу страницы. HTML допускается.",
    )
    faq_items = models.TextField(
        "FAQ (вопрос | ответ на строку)",
        blank=True,
        default="",
        help_text=(
            "Один вопрос-ответ на строку, разделитель «|». "
            "Пример: Какие сроки поставки?|Сроки зависят от наличия. "
            "Рекомендуется 5–10 вопросов для FAQPage schema."
        ),
    )

    class Meta:
        verbose_name = "SEO статической страницы"
        verbose_name_plural = "SEO статических страниц"
        ordering = ["slug"]

    def __str__(self):
        return self.slug


class SiteSettings(models.Model):
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=50, blank=True)
    address = models.CharField(
        max_length=255,
        blank=True,
        verbose_name="Адрес",
        help_text="Адрес офиса или склада. Если пусто — блок адреса на странице контактов не отображается.",
    )
    work_hours = models.CharField(
        max_length=255,
        blank=True,
        verbose_name="Режим работы",
        help_text="Например: Пн-Пт: 9:00-18:00",
    )
    map_embed = models.TextField(
        blank=True,
        verbose_name="Код карты (iframe)",
        help_text="HTML-код для встраивания карты (iframe). Опционально.",
    )
    telegram_bot_token = models.CharField(max_length=255, blank=True)
    telegram_chat_id = models.CharField(max_length=255, blank=True)
    whatsapp_number = models.CharField(max_length=50, blank=True)
    analytics_code = models.TextField(blank=True)
    inn = models.CharField(
        max_length=20,
        blank=True,
        verbose_name="ИНН",
        help_text="ИНН организации",
    )
    ogrn = models.CharField(
        max_length=20,
        blank=True,
        verbose_name="ОГРН",
        help_text="ОГРН организации",
    )
    legal_address = models.TextField(
        blank=True,
        verbose_name="Юридический адрес",
        help_text="Полный юридический адрес организации",
    )
    office_address_1 = models.TextField(
        blank=True,
        verbose_name="Фактический адрес 1",
        help_text="Первый фактический адрес (офис/склад)",
    )
    office_address_2 = models.TextField(
        blank=True,
        verbose_name="Фактический адрес 2",
        help_text="Второй фактический адрес (офис/склад)",
    )
    in_stock_seo_description = models.TextField(
        blank=True,
        verbose_name="SEO описание: В наличии",
    )
    in_stock_seo_faq = models.TextField(
        blank=True,
        verbose_name="SEO FAQ: В наличии",
        help_text=(
            "FAQ для страницы /catalog/in-stock/ в формате JSON-LD FAQPage schema. "
            "Формат: один вопрос-ответ на строку, разделитель «|». "
            "Пример:\n"
            "Какие сроки поставки?|Сроки зависят от наличия техники.\n"
            "Какие варианты оплаты?|Работаем с различными вариантами оплаты.\n"
            "Как оформить заказ?|Заполните форму на сайте или свяжитесь с нами."
        ),
    )

    class Meta:
        verbose_name = "Настройки сайта"
        verbose_name_plural = "Настройки сайта"

    def __str__(self):
        return "Настройки"

    def save(self, *args, **kwargs):
        if not self.pk:
            self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def get_solo(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj
class ProductImage(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="images")
    image = models.ImageField(upload_to="products/")
    order = models.PositiveIntegerField(default=0)
    alt_ru = models.CharField(max_length=255, blank=True)
    alt_en = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["order", "id"]
        indexes = [
            models.Index(fields=["product", "order"], name="productimage_order_idx")
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["product", "order"], name="product_image_order_unique"
            )
        ]
        verbose_name = "Изображение товара"
        verbose_name_plural = "Изображения товаров"

    def __str__(self):
        return f"{self.product} [{self.order}]"

    def clean(self):
        errors = {}
        if self.product_id and ProductImage.objects.filter(
            product_id=self.product_id, order=self.order
        ).exclude(pk=self.pk).exists():
            errors["order"] = _("Order value must be unique per product.")
        if not self.image:
            errors["image"] = _("Image file is required.")
        if errors:
            raise ValidationError(errors)

    @classmethod
    def find_orphaned_media(cls):
        """
        Return file paths that are referenced in DB but missing on disk and files
        on disk under products/ that have no DB reference.
        """
        media_dir = Path(settings.MEDIA_ROOT) / "products"
        if not media_dir.exists():
            return {"missing_files": [], "unreferenced_files": []}

        referenced_paths = set()
        for rel_path in cls.objects.values_list("image", flat=True):
            if rel_path:
                referenced_paths.add((Path(settings.MEDIA_ROOT) / rel_path).resolve())

        missing_files = sorted(
            str(path) for path in referenced_paths if not path.exists()
        )
        existing_files = {
            path.resolve()
            for path in media_dir.rglob("*")
            if path.is_file() and not path.name.startswith(".")
        }
        unreferenced_files = sorted(
            str(path) for path in existing_files if path not in referenced_paths
        )

        return {"missing_files": missing_files, "unreferenced_files": unreferenced_files}


