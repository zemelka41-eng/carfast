from django import forms

from .models import Lead, Product, ProductImage
from .utils.contacts import digits


class LeadForm(forms.ModelForm):
    """Форма лида с honeypot и скрытым продуктом."""

    honeypot = forms.CharField(required=False, widget=forms.HiddenInput)

    class Meta:
        model = Lead
        fields = ["name", "phone", "email", "message", "product", "source"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control", "required": True}),
            "phone": forms.TextInput(
                attrs={"class": "form-control", "required": True, "type": "tel"}
            ),
            "email": forms.EmailInput(
                attrs={"class": "form-control", "type": "email", "required": False}
            ),
            "message": forms.Textarea(attrs={"class": "form-control", "rows": 4, "required": False}),
            "product": forms.HiddenInput(),
            "source": forms.HiddenInput(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["product"].required = False
        self.fields["email"].required = False
        self.fields["message"].required = False
        self.fields["source"].required = False
        self.fields["name"].label = "Имя"
        self.fields["phone"].label = "Телефон"
        self.fields["email"].label = "Почта"
        self.fields["message"].label = "Сообщение"
        # Hide honeypot field with CSS
        self.fields["honeypot"].widget.attrs.update({
            "style": "position: absolute; left: -9999px;",
            "tabindex": "-1",
            "autocomplete": "off",
        })

    def clean_honeypot(self):
        value = self.cleaned_data.get("honeypot")
        if value:
            raise forms.ValidationError("Spam detected")
        return value


class LeadResponseForm(forms.ModelForm):
    class Meta:
        model = Lead
        fields = "__all__"


class ContactsLeadForm(forms.Form):
    """Форма лида для страницы контактов (без дублирования LeadForm)."""

    honeypot = forms.CharField(required=False, widget=forms.HiddenInput)

    name = forms.CharField(
        required=False,
        label="Имя",
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": "Имя (необязательно)",
                "autocomplete": "name",
            }
        ),
    )
    phone = forms.CharField(
        required=True,
        label="Телефон",
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "type": "tel",
                "placeholder": "Телефон *",
                "autocomplete": "tel",
            }
        ),
    )
    city = forms.CharField(
        required=False,
        label="Город",
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": "Город (необязательно)",
                "autocomplete": "address-level2",
            }
        ),
    )
    message = forms.CharField(
        required=False,
        label="Сообщение",
        widget=forms.Textarea(
            attrs={
                "class": "form-control",
                "rows": 4,
                "placeholder": "Сообщение (необязательно)",
            }
        ),
    )
    consent = forms.BooleanField(
        required=True,
        label="",
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
        error_messages={"required": "Нужно согласие на обработку персональных данных."},
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Hide honeypot field with CSS (extra safety)
        self.fields["honeypot"].widget.attrs.update(
            {
                "style": "position: absolute; left: -9999px;",
                "tabindex": "-1",
                "autocomplete": "off",
            }
        )

    def clean_honeypot(self):
        value = self.cleaned_data.get("honeypot")
        if value:
            raise forms.ValidationError("Spam detected")
        return value

    def clean_name(self):
        return (self.cleaned_data.get("name") or "").strip()

    def clean_city(self):
        return (self.cleaned_data.get("city") or "").strip()

    def clean_message(self):
        return (self.cleaned_data.get("message") or "").strip()

    def clean_phone(self):
        raw = self.cleaned_data.get("phone")
        d = digits(raw)
        if len(d) < 10:
            raise forms.ValidationError("Укажите корректный телефон (минимум 10 цифр).")
        return d

class ProductAdminForm(forms.ModelForm):
    """
    Одноязычная (RU) админ-форма для Product:
    - EN-поля скрыты и не требуются
    - при сохранении автозаполняются из RU
    """

    class Meta:
        model = Product
        fields = "__all__"
        labels = {
            "sku": "Артикул (SKU)",
            "slug": "URL (slug)",
            "series": "Бренд",
            "category": "Категория",
            "model_name_ru": "Название (RU)",
            "short_description_ru": "Короткое описание",
            "price": "Цена, ₽",
            "availability": "Наличие",
        }
        help_texts = {
            "sku": "Уникальный артикул. Пример: SHAC-X5000-6x4-ABN-2023-001.",
            "slug": "Рекомендуемый формат: brand-type-line-wheel-modelcode. "
            "Если оставить пустым — будет сгенерирован автоматически.",
            "series": "Бренд для каталога и карточки товара.",
            "category": "Категория для фильтров и навигации.",
            "model_name_ru": "Название для карточки в каталоге. Пример: Автобетоносмеситель SHACMAN X5000 6x4, 2023.",
            "short_description_ru": "Короткий текст для карточки. Пример: 2023 г., 336 л.с., 6x4, в Москве.",
            "power_hp": "Мощность, л.с. Пример: 336",
            "wheel_formula": "Колёсная формула. Пример: 6x4",
            "wheelbase_mm": "Колёсная база, мм",
            "description_ru": "Полное описание для страницы товара.",
            "price": "Базовая цена (если нет активных предложений/офферов).",
            "availability": "Статус (в каталоге наличие также считается по офферам).",
            "options": "JSON-словарь характеристик. Пример: {\"Грузоподъёмность\": \"25 т\", \"Колёса\": [\"6x4\", \"8x4\"]}.",
            "config": "Комплектация: каждый пункт с новой строки.",
        }
        widgets = {
            "model_name_en": forms.HiddenInput(),
            "short_description_en": forms.HiddenInput(),
            "description_en": forms.HiddenInput(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ("model_name_en", "short_description_en", "description_en"):
            if name in self.fields:
                self.fields[name].required = False
        if "slug" in self.fields:
            self.fields["slug"].required = False

        # "Пример заполнения" без миграций: показываем плейсхолдеры (не сохраняются в БД).
        placeholders = {
            "model_name_ru": "Автобетоносмеситель SHACMAN X5000 6x4, 2023",
            "short_description_ru": "2023 г., 336 л.с., 6x4, в Москве.",
            "sku": "SHAC-X5000-6x4-ABN-2023-001",
            "power_hp": "336",
            "wheel_formula": "6x4",
            "wheelbase_mm": "3775",
            "description_ru": (
                "Пример структуры описания:\n"
                "— Год: 2023\n"
                "— Мощность: 336 л.с.\n"
                "— Колёсная формула: 6x4\n"
                "— Локация: Москва\n"
                "— Комплектация/опции: ...\n"
                "— Условия/цена: ..."
            ),
        }
        for field_name, value in placeholders.items():
            if field_name in self.fields:
                self.fields[field_name].widget.attrs.setdefault("placeholder", value)

    def clean(self):
        cleaned_data = super().clean()

        model_name_ru = (cleaned_data.get("model_name_ru") or "").strip()
        model_name_en = (cleaned_data.get("model_name_en") or "").strip()
        if not model_name_en:
            existing = (getattr(self.instance, "model_name_en", "") or "").strip()
            cleaned_data["model_name_en"] = existing or model_name_ru

        short_ru = (cleaned_data.get("short_description_ru") or "").strip()
        short_en = (cleaned_data.get("short_description_en") or "").strip()
        if not short_en:
            existing = (getattr(self.instance, "short_description_en", "") or "").strip()
            cleaned_data["short_description_en"] = existing or short_ru

        desc_ru = cleaned_data.get("description_ru") or ""
        desc_en = (cleaned_data.get("description_en") or "").strip()
        if not desc_en:
            existing = (getattr(self.instance, "description_en", "") or "").strip()
            cleaned_data["description_en"] = existing or desc_ru

        return cleaned_data

    def clean_options(self):
        options = self.cleaned_data.get("options")
        if not isinstance(options, dict):
            return options
        cleaned = {}
        for key, value in options.items():
            label = str(key).strip()
            if not label:
                continue
            if isinstance(value, (list, tuple)):
                if len(value) == 3 and str(value[0]).strip().lower() == "pair":
                    value_str = str(value[2]).strip()
                    if value_str:
                        cleaned[label] = value_str
                    continue
                items = [str(item).strip() for item in value if str(item).strip()]
                if items:
                    cleaned[label] = items
                continue
            value_str = str(value).strip()
            if value_str:
                cleaned[label] = value_str
        return cleaned


class ProductImageInlineForm(forms.ModelForm):
    """RU-форма для инлайна ProductImage (скрываем alt_en)."""

    class Meta:
        model = ProductImage
        fields = "__all__"
        labels = {
            "image": "Фото",
            "alt_ru": "Подпись (alt, RU)",
            "order": "Порядок",
        }
        help_texts = {
            "image": "Форматы: .jpg/.jpeg/.png/.webp (.jfif тоже поддерживается как JPEG). Рекомендуем: 4:3, 1600×1200.",
            "alt_ru": "Текст для атрибута alt (если пусто — подставим название товара).",
            "order": "Сортировка фото (меньше = выше).",
        }
        widgets = {
            "alt_en": forms.HiddenInput(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if "alt_en" in self.fields:
            self.fields["alt_en"].required = False

    def clean(self):
        cleaned_data = super().clean()
        alt_ru = (cleaned_data.get("alt_ru") or "").strip()
        alt_en = (cleaned_data.get("alt_en") or "").strip()
        if "alt_en" in cleaned_data and not alt_en:
            existing = (getattr(self.instance, "alt_en", "") or "").strip()
            cleaned_data["alt_en"] = existing or alt_ru
        return cleaned_data
