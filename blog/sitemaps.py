from django.contrib.sitemaps import Sitemap
from django.urls import reverse
from django.utils import timezone

from .models import BlogPost


class BlogPostSitemap(Sitemap):
    changefreq = "monthly"
    priority = 0.6

    def items(self):
        return BlogPost.objects.published().order_by("pk")

    def location(self, obj):
        return obj.get_absolute_url()

    def lastmod(self, obj):
        return obj.updated_at


class BlogIndexSitemap(Sitemap):
    changefreq = "monthly"
    priority = 0.6

    def items(self):
        return ["blog_index"]

    def location(self, obj):
        return reverse("blog:blog_list")

    def lastmod(self, obj):
        # Use latest post update or now
        latest = BlogPost.objects.published().order_by("-updated_at").values_list("updated_at", flat=True).first()
        return latest or timezone.now()
