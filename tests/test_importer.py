from pathlib import Path

import openpyxl
import pytest
from PIL import Image

from catalog.importers import run_import
from catalog.models import Product, ProductImage
from catalog.services.import_products import IMPORT_HEADERS

pytestmark = pytest.mark.django_db


def _write_workbook(path: Path, rows: list[list[str | int | float | None]]) -> None:
    workbook = openpyxl.Workbook()
    worksheet = workbook.active
    worksheet.append(IMPORT_HEADERS)
    for row in rows:
        worksheet.append(row)
    workbook.save(path)


def _write_image(path: Path, size: tuple[int, int] = (2, 2), color: str = "white") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", size, color=color)
    image.save(path, format="PNG")


def test_run_import_updates_existing_product_and_normalizes_slug(tmp_path):
    file_path = tmp_path / "products.xlsx"
    _write_workbook(
        file_path,
        [
            [
                "SKU-1",
                "Slug Value",
                "Series A",
                "Category A",
                "Имя RU",
                "Name EN",
                "",
                "",
                10,
                Product.Availability.IN_STOCK,
                "",
            ],
        ],
    )

    created, updated, errors = run_import(file_path)
    assert (created, updated, errors) == (1, 0, 0)

    product = Product.objects.get(sku="SKU-1")
    assert product.slug == "slug-value"
    assert product.model_name_en == "Name EN"

    update_path = tmp_path / "products_update.xlsx"
    _write_workbook(
        update_path,
        [
            [
                "SKU-1",
                "Mixed Case Slug",
                "Series A",
                "Category A",
                "Имя RU 2",
                "Name EN 2",
                "",
                "",
                25,
                Product.Availability.ON_REQUEST,
                "",
            ],
        ],
    )

    created, updated, errors = run_import(update_path)
    assert (created, updated, errors) == (0, 1, 0)

    product.refresh_from_db()
    assert product.slug == "mixed-case-slug"
    assert product.price == 25
    assert product.availability == Product.Availability.ON_REQUEST


def test_unknown_availability_raises_error(tmp_path):
    file_path = tmp_path / "products.xlsx"
    _write_workbook(
        file_path,
        [
            [
                "SKU-ERR",
                "bad-availability",
                "Series A",
                "Category A",
                "Имя RU",
                "Name EN",
                "",
                "",
                10,
                "UNKNOWN",
                "",
            ],
        ],
    )

    created, updated, errors = run_import(file_path)

    assert (created, updated, errors) == (0, 0, 1)
    assert not Product.objects.filter(sku="SKU-ERR").exists()


def test_missing_image_is_logged_and_counts_as_error(sample_media_dir, tmp_path, settings):
    workbook_path = tmp_path / "products_with_image.xlsx"
    _write_workbook(
        workbook_path,
        [
            [
                "SKU-IMG",
                "product-image",
                "Series B",
                "Category B",
                "Имя RU",
                "Name EN",
                "",
                "",
                50,
                Product.Availability.IN_STOCK,
                "missing.jpg",
            ],
        ],
    )

    created, updated, errors = run_import(workbook_path, sample_media_dir)

    assert (created, updated, errors) == (1, 0, 1)
    assert not ProductImage.objects.filter(product__sku="SKU-IMG").exists()

    log_file = Path(settings.LOG_DIR) / "import.log"
    assert log_file.exists()
    assert "not found" in log_file.read_text(encoding="utf-8")

    product = Product.objects.get(sku="SKU-IMG")
    assert product.series.name == "Series B"
    assert product.category.name == "Category B"


def test_slug_conflict_is_reported_and_skipped(tmp_path):
    Product.objects.create(
        sku="SKU-EXIST",
        slug="existing-slug",
        model_name_ru="Name",
        model_name_en="Name",
        short_description_ru="",
        short_description_en="",
        availability=Product.Availability.IN_STOCK,
    )

    file_path = tmp_path / "products.xlsx"
    _write_workbook(
        file_path,
        [
            [
                "SKU-NEW",
                "existing-slug",
                "Series A",
                "Category A",
                "Имя RU",
                "Name EN",
                "",
                "",
                10,
                Product.Availability.IN_STOCK,
                "",
            ],
        ],
    )

    created, updated, errors = run_import(file_path)

    assert (created, updated, errors) == (0, 0, 1)
    assert not Product.objects.filter(sku="SKU-NEW").exists()


def test_relative_media_dir_is_resolved_and_image_attached(tmp_path, settings):
    source_media = tmp_path / "import_media"
    media_root = tmp_path / "media"
    source_media.mkdir()
    media_root.mkdir()

    image_path = source_media / "photo.png"
    _write_image(image_path)

    workbook_path = tmp_path / "products_with_image.xlsx"
    _write_workbook(
        workbook_path,
        [
            [
                "SKU-REL",
                "product-image-rel",
                "Series B",
                "Category B",
                "Имя RU",
                "Name EN",
                "",
                "",
                50,
                Product.Availability.IN_STOCK,
                "photo.png",
            ],
        ],
    )

    settings.MEDIA_ROOT = media_root
    created, updated, errors = run_import(workbook_path, "import_media")

    assert (created, updated, errors) == (1, 0, 0)
    product_image = ProductImage.objects.get(product__sku="SKU-REL")
    assert product_image.image.name.endswith("photo.png")


def test_disallowed_extension_is_reported_and_counts_as_error(tmp_path, settings):
    source_media = tmp_path / "import_media"
    media_root = tmp_path / "media"
    source_media.mkdir()
    media_root.mkdir()

    bad_image = source_media / "photo.txt"
    bad_image.write_text("not an image", encoding="utf-8")

    workbook_path = tmp_path / "products_with_bad_image.xlsx"
    _write_workbook(
        workbook_path,
        [
            [
                "SKU-BAD",
                "product-image-bad",
                "Series B",
                "Category B",
                "Имя RU",
                "Name EN",
                "",
                "",
                50,
                Product.Availability.IN_STOCK,
                "photo.txt",
            ],
        ],
    )

    settings.MEDIA_ROOT = media_root
    settings.MEDIA_ALLOWED_IMAGE_EXTENSIONS = ["png"]
    created, updated, errors = run_import(workbook_path, source_media)

    assert (created, updated, errors) == (1, 0, 1)
    assert not ProductImage.objects.filter(product__sku="SKU-BAD").exists()
    log_file = Path(settings.LOG_DIR) / "import.log"
    assert log_file.exists()
    assert "not allowed" in log_file.read_text(encoding="utf-8")


def test_image_too_large_is_rejected(tmp_path, settings):
    source_media = tmp_path / "import_media"
    media_root = tmp_path / "media"
    source_media.mkdir()
    media_root.mkdir()

    image_path = source_media / "photo.png"
    _write_image(image_path, size=(50, 50))

    workbook_path = tmp_path / "products_with_large_image.xlsx"
    _write_workbook(
        workbook_path,
        [
            [
                "SKU-LARGE",
                "product-image-large",
                "Series B",
                "Category B",
                "Имя RU",
                "Name EN",
                "",
                "",
                50,
                Product.Availability.IN_STOCK,
                "photo.png",
            ],
        ],
    )

    settings.MEDIA_ROOT = media_root
    settings.MAX_IMAGE_SIZE = 10
    created, updated, errors = run_import(workbook_path, source_media)

    assert (created, updated, errors) == (1, 0, 1)
    assert not ProductImage.objects.filter(product__sku="SKU-LARGE").exists()
    assert "too large" in (Path(settings.LOG_DIR) / "import.log").read_text(encoding="utf-8")
