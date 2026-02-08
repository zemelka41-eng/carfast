import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from blog.models import BlogPost, BlogPostImage


pytestmark = pytest.mark.django_db


def test_blog_gallery_renders_images(client, tmp_path, settings):
    settings.MEDIA_ROOT = tmp_path
    post = BlogPost.objects.create(
        title="Галерея в блоге",
        slug="blog-gallery-test",
        excerpt="Описание",
        content_html="<p>Контент</p>",
        is_published=True,
        published_at=timezone.now(),
    )
    img1 = SimpleUploadedFile("one.jpg", b"file1", content_type="image/jpeg")
    img2 = SimpleUploadedFile("two.jpg", b"file2", content_type="image/jpeg")
    BlogPostImage.objects.create(post=post, image=img1, alt="alt one", sort_order=1)
    BlogPostImage.objects.create(post=post, image=img2, alt="alt two", sort_order=2)

    response = client.get(post.get_absolute_url())
    content = response.content.decode("utf-8")
    assert response.status_code == 200
    assert 'data-blog-gallery' in content
    assert content.count("<img") >= 2
