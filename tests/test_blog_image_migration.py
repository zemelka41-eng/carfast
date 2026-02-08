"""
Tests for blog image migration command.
"""
import re

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from blog.models import BlogPost, BlogPostImage


def test_command_imports_without_syntax_error():
    """Command should import without SyntaxError."""
    try:
        from blog.management.commands.move_images_to_content import Command
        assert Command is not None
    except SyntaxError as e:
        pytest.fail(f"Command has syntax error: {e}")


@pytest.mark.django_db
def test_move_images_command_finds_post(client):
    """Command should find blog post by slug."""
    post = BlogPost.objects.create(
        title="Test Post",
        slug="test-post",
        excerpt="Test excerpt",
        content_html="<p>Test content</p>",
        is_published=True,
    )

    # Should not raise CommandError
    try:
        call_command("move_images_to_content", "test-post", "--dry-run")
    except CommandError as e:
        # Expected: images not found
        assert "Expected 3 images" in str(e) or "not found" in str(e)


@pytest.mark.django_db
def test_move_images_command_requires_images(client):
    """Command should fail if images are not found."""
    post = BlogPost.objects.create(
        title="Test Post",
        slug="test-post",
        excerpt="Test excerpt",
        content_html="<p>Test content</p>",
        is_published=True,
    )

    with pytest.raises(CommandError, match="Expected 3 images"):
        call_command("move_images_to_content", "test-post", "--dry-run")


@pytest.mark.django_db
def test_move_images_finds_by_base_without_prefix(client):
    """Command should find images by base name without prefix (e.g., x3000-8x4-komplektaciya).
    
    Test case: slug is 'shacman-x3000-8x4-komplektaciya', but filenames are
    'x3000-8x4-komplektaciya_2.png' (prefix 'shacman-' differs from filenames).
    """
    from django.core.files.uploadedfile import SimpleUploadedFile
    from django.utils import timezone

    post = BlogPost.objects.create(
        title="Shacman X3000 8x4 комплектация",
        slug="shacman-x3000-8x4-komplektaciya",
        excerpt="Test excerpt",
        content_html="""<h2>Для каких задач подходит X3000 8x4 (стройка/карьер)</h2>
<p>Типовые сценарии "стройка"</p>
<h2>Главный принцип выбора комплектации</h2>
<p>Короткий ответ для сниппета: чтобы выбрать комплектацию, нужно описать 5 параметров</p>
<p>1) Площадка: грунт, уклоны, сезонность</p>
<h2>Что проверить перед покупкой/выдачей: предпродажный чек-лист</h2>
<p>Чек-лист приёмки (короткий, практичный):</p>""",
        is_published=True,
        published_at=timezone.now(),
    )


@pytest.mark.django_db
def test_move_images_with_typographic_quotes(client):
    """Command should handle typographic quotes in anchor text."""
    from django.core.files.uploadedfile import SimpleUploadedFile
    from django.utils import timezone

    post = BlogPost.objects.create(
        title="Shacman X3000 8×4 комплектация",
        slug="shacman-x3000-8x4-komplektaciya",
        excerpt="Test excerpt",
        content_html="""<h2>Для каких задач подходит X3000 8x4 (стройка/карьер)</h2>
<p>Типовые сценарии «стройка» и карьер</p>
<h2>Главный принцип выбора комплектации</h2>
<p>Короткий ответ для сниппета: чтобы выбрать комплектацию, нужно описать 5 параметров: площадка, плечо, груз</p>
<p>1) Площадка: грунт, уклоны, сезонность</p>
<h2>Что проверить перед покупкой/выдачей: предпродажный чек-лист</h2>
<p>Чек-лист приёмки (короткий, практичный):</p>""",
        is_published=True,
        published_at=timezone.now(),
    )

    # Create test images
    image_data = b"fake image data"
    img2 = BlogPostImage.objects.create(
        post=post,
        image=SimpleUploadedFile(
            "x3000-8x4-komplektaciya_2.png", image_data, content_type="image/png"
        ),
        alt="Image 2",
        sort_order=1,
    )
    img3 = BlogPostImage.objects.create(
        post=post,
        image=SimpleUploadedFile(
            "x3000-8x4-komplektaciya_3.png", image_data, content_type="image/png"
        ),
        alt="Image 3",
        sort_order=2,
    )
    img4 = BlogPostImage.objects.create(
        post=post,
        image=SimpleUploadedFile(
            "x3000-8x4-komplektaciya_4.png", image_data, content_type="image/png"
        ),
        alt="Image 4",
        sort_order=3,
    )

    # Command should find insertion points despite typographic quotes and ×
    call_command("move_images_to_content", post.slug)

    # Verify images are in content_html
    post.refresh_from_db()
    assert img2.image.url in post.content_html
    assert img3.image.url in post.content_html
    assert img4.image.url in post.content_html

    # Verify content_html contains exactly 3 figure elements
    content = post.content_html
    figure_count = content.count('class="blog-inline-image"')
    assert figure_count == 3, f"Expected 3 figure elements, found {figure_count}"

    # Verify images are removed from gallery
    assert not BlogPostImage.objects.filter(id__in=[img2.id, img3.id, img4.id]).exists()

    # Verify idempotency: second run should not duplicate
    call_command("move_images_to_content", post.slug)
    post.refresh_from_db()
    figure_count_after = post.content_html.count('class="blog-inline-image"')
    assert figure_count_after == 3, f"Expected 3 figure elements after second run, found {figure_count_after}"


@pytest.mark.django_db
def test_move_images_idempotency(client):
    """Command should be idempotent - safe to run multiple times."""
    from django.core.files.uploadedfile import SimpleUploadedFile
    from django.utils import timezone

    post = BlogPost.objects.create(
        title="Shacman X3000 8x4 комплектация",
        slug="shacman-x3000-8x4-komplektaciya",
        excerpt="Test excerpt",
        content_html="""<h2>Для каких задач подходит X3000 8x4 (стройка/карьер)</h2>
<p>Типовые сценарии "стройка"</p>
<h2>Главный принцип выбора комплектации</h2>
<p>Короткий ответ для сниппета: чтобы выбрать комплектацию, нужно описать 5 параметров</p>
<p>1) Площадка: грунт, уклоны, сезонность</p>
<h2>Что проверить перед покупкой/выдачей: предпродажный чек-лист</h2>
<p>Чек-лист приёмки (короткий, практичный):</p>""",
        is_published=True,
        published_at=timezone.now(),
    )

    # Create test images with different formats
    image_data = b"fake image data"
    img2 = BlogPostImage.objects.create(
        post=post,
        image=SimpleUploadedFile(
            "x3000-8x4-komplektaciya_2.png", image_data, content_type="image/png"
        ),
        alt="Image 2",
        sort_order=1,
    )
    img3 = BlogPostImage.objects.create(
        post=post,
        image=SimpleUploadedFile(
            "x3000-8x4-komplektaciya_3.webp", image_data, content_type="image/webp"
        ),
        alt="Image 3",
        sort_order=2,
    )
    img4 = BlogPostImage.objects.create(
        post=post,
        image=SimpleUploadedFile(
            "x3000-8x4-komplektaciya_4_720.jpg", image_data, content_type="image/jpeg"
        ),
        alt="Image 4",
        sort_order=3,
    )

    # First run: should insert images
    call_command("move_images_to_content", post.slug)

    # Verify images are in content_html
    post.refresh_from_db()
    assert img2.image.url in post.content_html
    assert img3.image.url in post.content_html
    assert img4.image.url in post.content_html

    # Verify images are removed from gallery
    assert not BlogPostImage.objects.filter(id=img2.id).exists()
    assert not BlogPostImage.objects.filter(id=img3.id).exists()
    assert not BlogPostImage.objects.filter(id=img4.id).exists()

    # Second run: should be idempotent (images already in content)
    # Recreate images for second run test
    img2_again = BlogPostImage.objects.create(
        post=post,
        image=SimpleUploadedFile(
            "x3000-8x4-komplektaciya_2_720.jpg", image_data, content_type="image/jpeg"
        ),
        alt="Image 2",
        sort_order=1,
    )
    img3_again = BlogPostImage.objects.create(
        post=post,
        image=SimpleUploadedFile(
            "x3000-8x4-komplektaciya_3_720.jpg", image_data, content_type="image/jpeg"
        ),
        alt="Image 3",
        sort_order=2,
    )
    img4_again = BlogPostImage.objects.create(
        post=post,
        image=SimpleUploadedFile(
            "x3000-8x4-komplektaciya_4_720.jpg", image_data, content_type="image/jpeg"
        ),
        alt="Image 4",
        sort_order=3,
    )

    # Save original content
    original_content = post.content_html

    # Second run should detect images already in content and skip insertion
    call_command("move_images_to_content", post.slug)

    # Content should not change (idempotent)
    post.refresh_from_db()
    assert post.content_html == original_content

    # Images should be deleted (they were in gallery but already in content)
    assert not BlogPostImage.objects.filter(id=img2_again.id).exists()
    assert not BlogPostImage.objects.filter(id=img3_again.id).exists()
    assert not BlogPostImage.objects.filter(id=img4_again.id).exists()


@pytest.mark.django_db
def test_move_images_inserts_in_correct_places(client):
    """Command should insert images in correct places in content."""
    from django.core.files.uploadedfile import SimpleUploadedFile
    from django.utils import timezone

    post = BlogPost.objects.create(
        title="Shacman X3000 8x4 комплектация",
        slug="shacman-x3000-8x4-komplektaciya",
        excerpt="Test excerpt",
        content_html="""<h2>Для каких задач подходит X3000 8x4 (стройка/карьер)</h2>
<p>Типовые сценарии "стройка"</p>
<h2>Главный принцип выбора комплектации</h2>
<p>Короткий ответ для сниппета: чтобы выбрать комплектацию, нужно описать 5 параметров</p>
<p>1) Площадка: грунт, уклоны, сезонность</p>
<h2>Что проверить перед покупкой/выдачей: предпродажный чек-лист</h2>
<p>Чек-лист приёмки (короткий, практичный):</p>""",
        is_published=True,
        published_at=timezone.now(),
    )

    # Create test images with .png extension
    image_data = b"fake image data"
    img2 = BlogPostImage.objects.create(
        post=post,
        image=SimpleUploadedFile(
            "x3000-8x4-komplektaciya_2.png", image_data, content_type="image/png"
        ),
        alt="Image 2",
        sort_order=1,
    )
    img3 = BlogPostImage.objects.create(
        post=post,
        image=SimpleUploadedFile(
            "x3000-8x4-komplektaciya_3.png", image_data, content_type="image/png"
        ),
        alt="Image 3",
        sort_order=2,
    )
    img4 = BlogPostImage.objects.create(
        post=post,
        image=SimpleUploadedFile(
            "x3000-8x4-komplektaciya_4.png", image_data, content_type="image/png"
        ),
        alt="Image 4",
        sort_order=3,
    )

    call_command("move_images_to_content", post.slug)

    post.refresh_from_db()
    content = post.content_html

    # Check image 2: should be after heading, before scenarios
    img2_pos = content.find(img2.image.url)
    heading_pos = content.find("Для каких задач подходит X3000 8x4")
    scenarios_pos = content.find('Типовые сценарии "стройка"')
    assert img2_pos > heading_pos
    assert img2_pos < scenarios_pos

    # Check image 3: should be after "5 параметров", before "1) Площадка"
    img3_pos = content.find(img3.image.url)
    params_pos = content.find("5 параметров")
    first_item_pos = content.find("1) Площадка")
    assert img3_pos > params_pos
    assert img3_pos < first_item_pos

    # Check image 4: should be after acceptance heading, before checklist
    img4_pos = content.find(img4.image.url)
    acceptance_pos = content.find("Что проверить перед покупкой/выдачей")
    checklist_pos = content.find("Чек-лист приёмки")
    assert img4_pos > acceptance_pos
    assert img4_pos < checklist_pos

    # Verify images are removed from gallery
    assert not BlogPostImage.objects.filter(id__in=[img2.id, img3.id, img4.id]).exists()


@pytest.mark.django_db
def test_move_images_renders_without_errors(client):
    """Page should render without errors after image migration."""
    from django.core.files.uploadedfile import SimpleUploadedFile
    from django.utils import timezone

    post = BlogPost.objects.create(
        title="Shacman X3000 8x4 комплектация",
        slug="shacman-x3000-8x4-komplektaciya",
        excerpt="Test excerpt",
        content_html="""<h2>Для каких задач подходит X3000 8x4 (стройка/карьер)</h2>
<p>Типовые сценарии "стройка"</p>
<h2>Главный принцип выбора комплектации</h2>
<p>Короткий ответ для сниппета: чтобы выбрать комплектацию, нужно описать 5 параметров</p>
<p>1) Площадка: грунт, уклоны, сезонность</p>
<h2>Что проверить перед покупкой/выдачей: предпродажный чек-лист</h2>
<p>Чек-лист приёмки (короткий, практичный):</p>""",
        is_published=True,
        published_at=timezone.now(),
    )

    # Create test images with .png extension
    image_data = b"fake image data"
    BlogPostImage.objects.create(
        post=post,
        image=SimpleUploadedFile(
            "x3000-8x4-komplektaciya_2.png", image_data, content_type="image/png"
        ),
        alt="Image 2",
        sort_order=1,
    )
    BlogPostImage.objects.create(
        post=post,
        image=SimpleUploadedFile(
            "x3000-8x4-komplektaciya_3.png", image_data, content_type="image/png"
        ),
        alt="Image 3",
        sort_order=2,
    )
    BlogPostImage.objects.create(
        post=post,
        image=SimpleUploadedFile(
            "x3000-8x4-komplektaciya_4.png", image_data, content_type="image/png"
        ),
        alt="Image 4",
        sort_order=3,
    )

    # Run migration
    call_command("move_images_to_content", post.slug)

    # Verify page renders without errors
    response = client.get(post.get_absolute_url())
    assert response.status_code == 200

    # Verify images are in rendered content
    content = response.content.decode("utf-8")
    assert "blog-inline-image" in content
    assert "img-fluid rounded" in content
    assert "loading=\"lazy\"" in content

    # Verify gallery is empty (no remaining_images)
    # This is checked by the view logic - remaining_images should be empty
    post.refresh_from_db()
    assert post.images.count() == 0

    # Verify content_html contains exactly 3 figure elements
    content = post.content_html
    figure_count = content.count('class="blog-inline-image"')
    assert figure_count == 3, f"Expected 3 figure elements, found {figure_count}"


@pytest.mark.django_db
def test_move_images_supports_different_extensions(client):
    """Command should support different image extensions (png, jpg, jpeg, webp)."""
    from django.core.files.uploadedfile import SimpleUploadedFile
    from django.utils import timezone

    post = BlogPost.objects.create(
        title="Shacman X3000 8x4 комплектация",
        slug="shacman-x3000-8x4-komplektaciya",
        excerpt="Test excerpt",
        content_html="""<h2>Для каких задач подходит X3000 8x4 (стройка/карьер)</h2>
<p>Типовые сценарии "стройка"</p>
<h2>Главный принцип выбора комплектации</h2>
<p>Короткий ответ для сниппета: чтобы выбрать комплектацию, нужно описать 5 параметров</p>
<p>1) Площадка: грунт, уклоны, сезонность</p>
<h2>Что проверить перед покупкой/выдачей: предпродажный чек-лист</h2>
<p>Чек-лист приёмки (короткий, практичный):</p>""",
        is_published=True,
        published_at=timezone.now(),
    )

    # Create test images with different extensions
    image_data = b"fake image data"
    img2 = BlogPostImage.objects.create(
        post=post,
        image=SimpleUploadedFile(
            "x3000-8x4-komplektaciya_2.png", image_data, content_type="image/png"
        ),
        alt="Image 2",
        sort_order=1,
    )
    img3 = BlogPostImage.objects.create(
        post=post,
        image=SimpleUploadedFile(
            "x3000-8x4-komplektaciya_3_720.webp", image_data, content_type="image/webp"
        ),
        alt="Image 3",
        sort_order=2,
    )
    img4 = BlogPostImage.objects.create(
        post=post,
        image=SimpleUploadedFile(
            "x3000-8x4-komplektaciya_4.jpeg", image_data, content_type="image/jpeg"
        ),
        alt="Image 4",
        sort_order=3,
    )

    # Command should find all images despite different extensions
    call_command("move_images_to_content", post.slug)

    # Verify all images are in content_html
    post.refresh_from_db()
    assert img2.image.url in post.content_html
    assert img3.image.url in post.content_html
    assert img4.image.url in post.content_html

    # Verify images are removed from gallery
    assert not BlogPostImage.objects.filter(id__in=[img2.id, img3.id, img4.id]).exists()


@pytest.mark.django_db
def test_move_images_shows_diagnostic_info_when_not_found(client):
    """Command should show diagnostic info when images are not found."""
    from django.core.files.uploadedfile import SimpleUploadedFile
    from django.utils import timezone

    post = BlogPost.objects.create(
        title="Shacman X3000 8x4 комплектация",
        slug="shacman-x3000-8x4-komplektaciya",
        excerpt="Test excerpt",
        content_html="<p>Test content</p>",
        is_published=True,
        published_at=timezone.now(),
    )

    # Create images with wrong names (not matching pattern)
    image_data = b"fake image data"
    BlogPostImage.objects.create(
        post=post,
        image=SimpleUploadedFile(
            "other-image.jpg", image_data, content_type="image/jpeg"
        ),
        alt="Other image",
        sort_order=1,
    )
    BlogPostImage.objects.create(
        post=post,
        image=SimpleUploadedFile(
            "x3000-8x4-komplektaciya_1.png", image_data, content_type="image/png"
        ),
        alt="Image 1",
        sort_order=2,
    )

    # Command should raise error with diagnostic info
    with pytest.raises(CommandError) as exc_info:
        call_command("move_images_to_content", post.slug, "--dry-run")

    error_msg = str(exc_info.value)
    assert "Expected 3 images" in error_msg
    assert "any_prefix" in error_msg or "any prefix" in error_msg
    assert "Images found in gallery:" in error_msg
    assert "other-image.jpg" in error_msg or "x3000-8x4-komplektaciya_1.png" in error_msg


@pytest.mark.django_db
def test_move_images_with_nested_tags(client):
    """Command should handle nested HTML tags in headings/paragraphs."""
    from django.core.files.uploadedfile import SimpleUploadedFile
    from django.utils import timezone

    post = BlogPost.objects.create(
        title="Shacman X3000 8x4 комплектация",
        slug="shacman-x3000-8x4-komplektaciya",
        excerpt="Test excerpt",
        content_html="""<h2>Для каких задач подходит <strong>X3000</strong> <em>8x4</em> (стройка/карьер)</h2>
<p>Типовые сценарии <span class="highlight">"стройка"</span></p>
<h2>Главный принцип выбора комплектации</h2>
<p>Короткий ответ для сниппета: чтобы выбрать комплектацию, нужно описать <strong>5 параметров</strong>: площадка, плечо, груз</p>
<p>1) Площадка: грунт, уклоны, сезонность</p>
<h2>Что проверить перед покупкой/выдачей: предпродажный чек-лист</h2>
<p>Чек-лист приёмки (короткий, практичный):</p>""",
        is_published=True,
        published_at=timezone.now(),
    )

    # Create test images
    image_data = b"fake image data"
    img2 = BlogPostImage.objects.create(
        post=post,
        image=SimpleUploadedFile(
            "x3000-8x4-komplektaciya_2.png", image_data, content_type="image/png"
        ),
        alt="Image 2",
        sort_order=1,
    )
    img3 = BlogPostImage.objects.create(
        post=post,
        image=SimpleUploadedFile(
            "x3000-8x4-komplektaciya_3.png", image_data, content_type="image/png"
        ),
        alt="Image 3",
        sort_order=2,
    )
    img4 = BlogPostImage.objects.create(
        post=post,
        image=SimpleUploadedFile(
            "x3000-8x4-komplektaciya_4.png", image_data, content_type="image/png"
        ),
        alt="Image 4",
        sort_order=3,
    )

    # Command should find insertion points despite nested tags
    call_command("move_images_to_content", post.slug)

    # Verify images are in content_html
    post.refresh_from_db()
    assert img2.image.url in post.content_html
    assert img3.image.url in post.content_html
    assert img4.image.url in post.content_html

    # Verify content_html contains exactly 3 figure elements
    content = post.content_html
    figure_count = content.count('class="blog-inline-image"')
    assert figure_count == 3, f"Expected 3 figure elements, found {figure_count}"

    # Verify images are removed from gallery
    assert not BlogPostImage.objects.filter(id__in=[img2.id, img3.id, img4.id]).exists()


@pytest.mark.django_db
def test_move_images_dry_run_does_not_modify(client):
    """Dry-run should not modify database."""
    from django.core.files.uploadedfile import SimpleUploadedFile
    from django.utils import timezone

    post = BlogPost.objects.create(
        title="Shacman X3000 8x4 комплектация",
        slug="shacman-x3000-8x4-komplektaciya",
        excerpt="Test excerpt",
        content_html="""<h2>Для каких задач подходит X3000 8x4 (стройка/карьер)</h2>
<p>Типовые сценарии "стройка"</p>
<h2>Главный принцип выбора комплектации</h2>
<p>Короткий ответ для сниппета: чтобы выбрать комплектацию, нужно описать 5 параметров</p>
<p>1) Площадка: грунт, уклоны, сезонность</p>
<h2>Что проверить перед покупкой/выдачей: предпродажный чек-лист</h2>
<p>Чек-лист приёмки (короткий, практичный):</p>""",
        is_published=True,
        published_at=timezone.now(),
    )

    original_content = post.content_html

    # Create test images with .png extension
    image_data = b"fake image data"
    img2 = BlogPostImage.objects.create(
        post=post,
        image=SimpleUploadedFile(
            "x3000-8x4-komplektaciya_2.png", image_data, content_type="image/png"
        ),
        alt="Image 2",
        sort_order=1,
    )
    img3 = BlogPostImage.objects.create(
        post=post,
        image=SimpleUploadedFile(
            "x3000-8x4-komplektaciya_3.png", image_data, content_type="image/png"
        ),
        alt="Image 3",
        sort_order=2,
    )
    img4 = BlogPostImage.objects.create(
        post=post,
        image=SimpleUploadedFile(
            "x3000-8x4-komplektaciya_4.png", image_data, content_type="image/png"
        ),
        alt="Image 4",
        sort_order=3,
    )

    original_image_count = post.images.count()

    # Run dry-run
    call_command("move_images_to_content", post.slug, "--dry-run")

    # Verify nothing changed
    post.refresh_from_db()
    assert post.content_html == original_content
    assert post.images.count() == original_image_count
    assert BlogPostImage.objects.filter(id__in=[img2.id, img3.id, img4.id]).count() == 3
