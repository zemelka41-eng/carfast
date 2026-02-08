import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.http import HttpResponse

from carfst_site.middleware import UploadValidationMiddleware


@pytest.fixture
def middleware():
    return UploadValidationMiddleware(lambda request: HttpResponse("ok"))


def test_allows_valid_image(rf, middleware, settings):
    settings.MEDIA_ALLOWED_IMAGE_EXTENSIONS = ["jpg", "jpeg"]
    settings.MEDIA_ALLOWED_IMAGE_MIME_TYPES = ["image/jpeg"]
    settings.MAX_IMAGE_SIZE = 1024

    upload = SimpleUploadedFile("photo.jpg", b"x" * 512, content_type="image/jpeg")
    request = rf.post("/upload", {"file": upload})

    response = middleware(request)

    assert response.status_code == 200


def test_rejects_oversized_image(rf, middleware, settings):
    settings.MEDIA_ALLOWED_IMAGE_EXTENSIONS = ["jpg"]
    settings.MEDIA_ALLOWED_IMAGE_MIME_TYPES = ["image/jpeg"]
    settings.MAX_IMAGE_SIZE = 5

    upload = SimpleUploadedFile("photo.jpg", b"x" * 6, content_type="image/jpeg")
    request = rf.post("/upload", {"file": upload})

    response = middleware(request)

    assert response.status_code == 400
    assert "exceeds" in response.content.decode()


def test_rejects_disallowed_extension(rf, middleware, settings):
    settings.MEDIA_ALLOWED_IMAGE_EXTENSIONS = ["jpg"]
    settings.MEDIA_ALLOWED_IMAGE_MIME_TYPES = ["image/jpeg"]
    settings.MAX_IMAGE_SIZE = 1024

    upload = SimpleUploadedFile("photo.gif", b"x", content_type="image/gif")
    request = rf.post("/upload", {"file": upload})

    response = middleware(request)

    assert response.status_code == 400
    assert "disallowed extension" in response.content.decode()


def test_rejects_disallowed_content_type(rf, middleware, settings):
    settings.MEDIA_ALLOWED_IMAGE_EXTENSIONS = ["jpg"]
    settings.MEDIA_ALLOWED_IMAGE_MIME_TYPES = ["image/jpeg"]
    settings.MAX_IMAGE_SIZE = 1024

    upload = SimpleUploadedFile("photo.jpg", b"x", content_type="application/octet-stream")
    request = rf.post("/upload", {"file": upload})

    response = middleware(request)

    assert response.status_code == 400
    assert "content type" in response.content.decode()
