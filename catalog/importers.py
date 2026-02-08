"""
Legacy shim: re-export the importer service.

The actual implementation lives in catalog.services.import_products.
"""

from catalog.services.import_products import run_import

__all__ = ["run_import"]
