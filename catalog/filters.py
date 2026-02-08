import django_filters
from django.core.exceptions import ValidationError
from django.db.models import Q

from .models import Product


class ProductFilter(django_filters.FilterSet):
    # В каталоге цена показывается как "от" (min_price по предложениям).
    price_min = django_filters.NumberFilter(field_name="min_price", lookup_expr="gte")
    price_max = django_filters.NumberFilter(field_name="min_price", lookup_expr="lte")
    series = django_filters.CharFilter(field_name="series__slug", lookup_expr="iexact")
    category = django_filters.CharFilter(field_name="category__slug", lookup_expr="iexact")
    model = django_filters.CharFilter(
        field_name="model_variant__slug", lookup_expr="iexact"
    )
    availability = django_filters.CharFilter(method="filter_availability")
    q = django_filters.CharFilter(method="filter_q")

    class Meta:
        model = Product
        fields = ["series", "category", "model", "availability"]

    def filter_q(self, queryset, name, value):
        if not value:
            return queryset
        value = value.strip()
        if not value:
            return queryset
        search = (
            Q(model_name_ru__icontains=value)
            | Q(model_name_en__icontains=value)
            | Q(sku__icontains=value)
            | Q(slug__icontains=value)
            | Q(series__name__icontains=value)
            | Q(category__name__icontains=value)
            | Q(short_description_ru__icontains=value)
            | Q(short_description_en__icontains=value)
        )
        return queryset.filter(search)

    def filter_availability(self, queryset, name, value):
        normalized_raw = (value or "").strip()
        normalized = normalized_raw.upper().replace("-", "_")
        if not normalized_raw:
            return queryset

        # Для фильтра по наличию опираемся на суммарный qty по активным предложениям.
        queryset = queryset.with_stock_stats()

        normalized_lower = normalized_raw.strip().lower().replace("-", "_")
        if normalized_lower in {"in_stock", "instock", "1", "true", "yes", "y", "да"}:
            return queryset.filter(total_qty__gt=0)
        if normalized_lower in {"on_request", "onrequest", "0", "false", "no", "n", "нет"}:
            return queryset.filter(total_qty__lte=0)

        # Backward compatibility: старые значения Product.Availability.
        if normalized in Product.Availability.values:
            if normalized == Product.Availability.IN_STOCK:
                return queryset.filter(total_qty__gt=0)
            if normalized == Product.Availability.ON_REQUEST:
                return queryset.filter(total_qty__lte=0)

        raise ValidationError(
            {"availability": f"Unknown availability value '{value}'. Use 'in_stock'."}
        )

