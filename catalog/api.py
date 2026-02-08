from rest_framework import generics, status
from rest_framework.response import Response

from .filters import ProductFilter
from .models import Lead, Product
from .serializers import LeadSerializer, ProductSerializer
from .utils import send_email, send_telegram_message


class ProductListAPI(generics.ListAPIView):
    queryset = (
        Product.objects.public()
        .select_related("series", "category", "model_variant")
        .prefetch_related("images")
        .with_stock_stats()
    )
    serializer_class = ProductSerializer
    filterset_class = ProductFilter


class ProductDetailAPI(generics.RetrieveAPIView):
    queryset = (
        Product.objects.public()
        .select_related("series", "category", "model_variant")
        .prefetch_related("images")
        .with_stock_stats()
    )
    serializer_class = ProductSerializer
    lookup_field = "slug"


class LeadCreateAPI(generics.CreateAPIView):
    queryset = Lead.objects.all()
    serializer_class = LeadSerializer

    def perform_create(self, serializer):
        lead = serializer.save()
        self.notify(lead)
        return lead

    def notify(self, lead: Lead):
        """
        Send email notifications to managers when a lead is created via API.
        Uses LEAD_NOTIFY_EMAILS from settings (comma-separated list).
        """
        from django.conf import settings
        from .models import SiteSettings

        subject = f"Новая заявка от {lead.name}"
        context = {"lead": lead, "request": self.request}
        
        # Get recipients from settings
        recipients = list(getattr(settings, "LEAD_NOTIFY_EMAILS", []) or [])
        
        # Also add admin email from SiteSettings if configured
        from .utils.site_settings import get_site_settings_safe
        settings_obj = get_site_settings_safe()
        if settings_obj and settings_obj.email and settings_obj.email not in recipients:
            recipients.append(settings_obj.email)
        
        if recipients:
            send_email(subject, "emails/lead_notification.html", context, recipients)
        
        text = f"Новая заявка: {lead.name}, {lead.phone}, товар: {lead.product}"
        send_telegram_message(text)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        lead = self.perform_create(serializer)
        headers = self.get_success_headers(serializer.data)
        return Response({"id": lead.id}, status=status.HTTP_201_CREATED, headers=headers)

