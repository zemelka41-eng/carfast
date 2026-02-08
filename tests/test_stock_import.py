from __future__ import annotations

from io import BytesIO

import openpyxl
import pytest

from catalog.models import City, Offer, Product
from catalog.services.import_stock import import_stock

pytestmark = pytest.mark.django_db


def _build_karfast_workbook(rows: list[list[object]]):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Table 1"

    headers = [
        "Наименование",  # A
        "Модель",  # B
        "Фото",  # C
        "Комплектация",  # D
        "",  # E
        "",  # F
        "",  # G
        "",  # H
        "",  # I
        "Цена с НДС, руб.",  # J
        "Наличие",  # K
    ]
    ws.append(headers)
    for row in rows:
        # Ensure the row has at least 11 columns (A-K)
        padded = list(row) + [""] * (11 - len(row))
        ws.append(padded[:11])

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


def test_import_stock_karfast_aggregates_qty_and_is_idempotent():
    buf = _build_karfast_workbook(
        [
            ["САМОСВАЛЫ SHACMAN", "", "", ""],
            [
                "Самосвал SHACMAN X3000",
                "X3000",
                "",
                "Комплектация: базовая 2023",
                "",
                "",
                "",
                "",
                "",
                "8 590 000 ₽",
                "г.Москва",
            ],
            [
                "Самосвал SHACMAN X3000",
                "X3000",
                "",
                "Комплектация: базовая 2023",
                "",
                "",
                "",
                "",
                "",
                "8 590 000 ₽",
                "г.Москва",
            ],
            [
                "Самосвал SHACMAN X3000",
                "X3000",
                "",
                "Комплектация: базовая 2023",
                "",
                "",
                "",
                "",
                "",
                "8 590 000 ₽",
                "г. Саратов",
            ],
        ]
    )

    report1 = import_stock(file=buf, file_name="karfast.xlsx", sheet="Table 1")
    assert report1.created_products == 1
    assert report1.created_offers == 2
    assert Product.objects.count() == 1
    assert Offer.objects.count() == 2

    moskva = City.objects.get(slug="moskva")
    saratov = City.objects.get(slug="saratov")

    product = Product.objects.first()
    assert product is not None

    offer_moscow = Offer.objects.get(product=product, city=moskva)
    offer_saratov = Offer.objects.get(product=product, city=saratov)

    assert offer_moscow.qty == 2
    assert offer_saratov.qty == 1

    # Second import should not create duplicates.
    buf.seek(0)
    report2 = import_stock(file=buf, file_name="karfast.xlsx", sheet="Table 1")
    assert Product.objects.count() == 1
    assert Offer.objects.count() == 2
    assert report2.created_offers == 0

    offer_moscow.refresh_from_db()
    offer_saratov.refresh_from_db()
    assert offer_moscow.qty == 2
    assert offer_saratov.qty == 1


def test_import_stock_deactivate_missing_offers():
    buf1 = _build_karfast_workbook(
        [
            ["САМОСВАЛЫ SHACMAN", "", "", ""],
            [
                "Самосвал SHACMAN X3000",
                "X3000",
                "",
                "Комплектация: базовая 2023",
                "",
                "",
                "",
                "",
                "",
                "8 590 000 ₽",
                "г.Москва",
            ],
            [
                "Самосвал SHACMAN X3000",
                "X3000",
                "",
                "Комплектация: базовая 2023",
                "",
                "",
                "",
                "",
                "",
                "8 590 000 ₽",
                "г. Саратов",
            ],
        ]
    )
    import_stock(file=buf1, file_name="karfast.xlsx", sheet="Table 1")

    # Now import a new version with only Moscow and deactivate missing.
    buf2 = _build_karfast_workbook(
        [
            ["САМОСВАЛЫ SHACMAN", "", "", ""],
            [
                "Самосвал SHACMAN X3000",
                "X3000",
                "",
                "Комплектация: базовая 2023",
                "",
                "",
                "",
                "",
                "",
                "8 590 000 ₽",
                "г.Москва",
            ],
        ]
    )
    report = import_stock(
        file=buf2,
        file_name="karfast.xlsx",
        sheet="Table 1",
        deactivate_missing=True,
    )
    assert report.deactivated_offers == 1

    product = Product.objects.first()
    assert product is not None

    moskva = City.objects.get(slug="moskva")
    saratov = City.objects.get(slug="saratov")

    assert Offer.objects.get(product=product, city=moskva).is_active is True
    assert Offer.objects.get(product=product, city=saratov).is_active is False
