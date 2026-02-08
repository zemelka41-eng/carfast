from django.contrib import admin

from .models import BlogPost, BlogPostImage


class BlogPostImageInline(admin.TabularInline):
    model = BlogPostImage
    fields = ("image", "alt", "caption", "sort_order")
    extra = 7
    max_num = 20
    can_delete = True


@admin.register(BlogPost)
class BlogPostAdmin(admin.ModelAdmin):
    prepopulated_fields = {"slug": ("title",)}
    list_display = ("title", "is_published", "published_at", "updated_at")
    list_filter = ("is_published",)
    search_fields = ("title", "slug")
    ordering = ("-published_at", "-updated_at")
    readonly_fields = ("created_at", "updated_at")
    inlines = (BlogPostImageInline,)
    fields = (
        "title",
        "slug",
        "excerpt",
        "content_html",
        "topics",
        ("cover_image", "cover_alt"),
        ("is_published", "published_at"),
        "created_at",
        "updated_at",
    )
