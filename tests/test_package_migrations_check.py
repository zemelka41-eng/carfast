"""Tests for scripts/package.py migration-check handling.

makemigrations --check --dry-run returns exit code 1 when new migrations are
required (Django prints 'Migrations for \"app\":' to stdout). This module
verifies that package.py treats that case with a clear message and exit 1,
and treats other non-zero exits as unknown errors.
"""

from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

@pytest.fixture
def project_root():
    """Project root where manage.py lives (cursor_work)."""
    root = Path(__file__).resolve().parent.parent
    assert (root / "manage.py").is_file(), "manage.py not found"
    return root


def test_migrations_required_returns_1_and_clear_message(project_root):
    """When makemigrations --check returns 1 and stdout contains 'Migrations for',
    package.py must exit with 1 and print the clear error, not 'unknown error'.
    """
    from importlib.util import spec_from_file_location, module_from_spec
    spec = spec_from_file_location("package", project_root / "scripts" / "package.py")
    assert spec and spec.loader
    package = module_from_spec(spec)
    spec.loader.exec_module(package)

    fake_stdout = "Migrations for 'catalog':\n  - Add field foo to Bar\n"
    fake_stderr = ""
    result_mock = MagicMock()
    result_mock.returncode = 1
    result_mock.stdout = fake_stdout
    result_mock.stderr = fake_stderr

    stderr_capture = StringIO()
    with patch("subprocess.run", return_value=result_mock):
        with patch("sys.stderr", stderr_capture):
            exit_code = package.main(["../carfst.zip"])

    assert exit_code == 1
    err = stderr_capture.getvalue()
    assert "Обнаружены изменения моделей, создайте/добавьте миграции в репозиторий" in err
    assert "Неизвестная ошибка" not in err
    assert "Migrations for 'catalog':" in err or "Migrations for" in err


def test_migrations_check_unknown_error_returns_6(project_root):
    """When returncode != 0 and stdout does NOT contain 'Migrations for',
    package.py must treat as unknown error (exit 6) and show stdout/stderr.
    """
    from importlib.util import spec_from_file_location, module_from_spec
    spec = spec_from_file_location("package", project_root / "scripts" / "package.py")
    assert spec and spec.loader
    package = module_from_spec(spec)
    spec.loader.exec_module(package)

    result_mock = MagicMock()
    result_mock.returncode = 2
    result_mock.stdout = "Some other failure"
    result_mock.stderr = ""

    stderr_capture = StringIO()
    with patch("subprocess.run", return_value=result_mock):
        with patch("sys.stderr", stderr_capture):
            exit_code = package.main(["../carfst.zip"])

    assert exit_code == 6
    err = stderr_capture.getvalue()
    assert "Неизвестная ошибка" in err
