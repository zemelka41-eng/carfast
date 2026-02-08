from django.db import models
from django.urls import reverse
from django.utils import timezone


class BlogPostQuerySet(models.QuerySet):
    def published(self):
        return self.filter(is_published=True, published_at__lte=timezone.now())


class BlogPost(models.Model):
    objects = BlogPostQuerySet.as_manager()

    title = models.CharField(max_length=255)
    slug = models.SlugField(unique=True, max_length=200)
    excerpt = models.TextField(blank=True)
    content_html = models.TextField()
    cover_image = models.ImageField(upload_to="blog/", blank=True, null=True)
    cover_alt = models.CharField(max_length=255, blank=True, default="")
    is_published = models.BooleanField(default=False)
    published_at = models.DateTimeField(blank=True, null=True)
    topics = models.JSONField(
        "Темы / ключевые слова",
        blank=True,
        default=list,
        help_text="Список ключевых слов для перелинковки (shacman, самосвал, тягач, лизинг и т.д.). Если пусто — используется эвристика по title/content.",
    )
    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-published_at", "-created_at"]
        verbose_name = "Статья"
        verbose_name_plural = "Статьи"

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse("blog:blog_detail", kwargs={"slug": self.slug})


class BlogPostImage(models.Model):
    post = models.ForeignKey(
        BlogPost, related_name="images", on_delete=models.CASCADE
    )
    image = models.ImageField(upload_to="blog/gallery/")
    alt = models.CharField(max_length=200, blank=True)
    caption = models.CharField(max_length=200, blank=True)
    sort_order = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["sort_order", "id"]
        verbose_name = "Изображение статьи"
        verbose_name_plural = "Изображения статьи"
