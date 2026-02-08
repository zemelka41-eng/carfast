from django.conf import settings
from rest_framework import serializers

from .models import Lead, Product, ProductImage
from .utils import generate_whatsapp_link


class ProductImageSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductImage
        fields = ["image", "alt_ru", "alt_en", "order"]


class ProductSerializer(serializers.ModelSerializer):
    images = ProductImageSerializer(many=True, read_only=True)
    whatsapp_link = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = [
            "sku",
            "slug",
            "model_name_ru",
            "model_name_en",
            "short_description_ru",
            "short_description_en",
            "description_ru",
            "description_en",
            "price",
            "availability",
            "power_hp",
            "payload_tons",
            "dimensions",
            "options",
            "tags",
            "images",
            "whatsapp_link",
        ]

    def get_whatsapp_link(self, obj) -> str:
        """Generate WhatsApp link for the product."""
        request = self.context.get("request")
        number = getattr(getattr(request, "site_settings", None), "whatsapp_number", None) if request else None
        number = number or getattr(settings, "WHATSAPP_NUMBER", "")
        return generate_whatsapp_link(number, obj.model_name_ru)


class LeadSerializer(serializers.ModelSerializer):
    class Meta:
        model = Lead
        fields = [
            "id",
            "product",
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
        ]
