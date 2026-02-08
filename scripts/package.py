"""Create a deploy ZIP archive with auto-generated BUILD_ID.

- Generates BUILD_ID in format YYYYMMDD_HHMMSS (local time)
- Archives only cursor_work/** directory
- Excludes: .venv, __pycache__, .pytest_cache, .mypy_cache, .ruff_cache, .idea, .vscode, *.pyc, *.pyo, *.log
- Saves ZIP to specified path or ../carfst.zip by default
- Prints: build_id, zip path, zip size

Usage:
  python scripts/package.py [output_path]

Python 3.11+ / stdlib only.
"""

from __future__ import annotations

import argparse
import fnmatch
import os
import re
import secrets
import subprocess
import sys
import zipfile
from datetime import datetime
from pathlib import Path

EXCLUDED_DIR_NAMES: set[str] = {
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".idea",
    ".vscode",
    ".git",
    "media",
    "staticfiles",
    "logs",
}

EXCLUDED_FILE_NAMES: set[str] = {
    ".env",
    "db.sqlite3",
    ".DS_Store",
}

EXCLUDED_FILE_PATTERNS: tuple[str, ...] = (
    "*.pyc",
    "*.pyo",
    "*.log",
)


def _find_project_root(start: Path) -> Path:
    """Walk up from start until manage.py is found."""
    for candidate in (start, *start.parents):
        if (candidate / "manage.py").is_file():
            return candidate
    raise FileNotFoundError(
        "Не удалось найти корень проекта: файл 'manage.py' не найден. "
        "Запускайте скрипт из репозитория проекта."
    )


def _generate_build_id() -> str:
    """Generate BUILD_ID in format YYYYMMDD_HHMMSS."""
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _write_build_id(project_root: Path, build_id: str) -> None:
    """Write BUILD_ID to file in project root."""
    build_id_file = project_root / "BUILD_ID"
    try:
        build_id_file.write_text(build_id, encoding="utf-8")
    except OSError as exc:
        print(f"Предупреждение: не удалось записать BUILD_ID в {build_id_file}: {exc}", file=sys.stderr)


def _is_excluded_file(file_path: Path) -> bool:
    name = file_path.name
    if name in EXCLUDED_FILE_NAMES:
        return True
    return any(fnmatch.fnmatch(name, pattern) for pattern in EXCLUDED_FILE_PATTERNS)


def _iter_project_files(project_root: Path, output_zip_path: Path):
    """Yield (absolute_file_path, arcname_posix) for files to include.
    All files are prefixed with 'cursor_work/' in the archive.
    """
    try:
        output_resolved = output_zip_path.resolve()
    except OSError:
        output_resolved = output_zip_path.absolute()

    for dirpath, dirnames, filenames in os.walk(project_root):
        # Prevent walking into excluded directories
        dirnames[:] = [d for d in dirnames if d not in EXCLUDED_DIR_NAMES]

        for filename in filenames:
            file_path = Path(dirpath) / filename

            if _is_excluded_file(file_path):
                continue

            # Avoid archiving the resulting zip if user places it inside the project
            try:
                if file_path.resolve() == output_resolved:
                    continue
            except OSError:
                if file_path.absolute() == output_resolved:
                    continue

            # Only archive regular files
            if not file_path.is_file():
                continue

            # Prefix all paths with 'cursor_work/'
            relative_path = file_path.relative_to(project_root).as_posix()
            arcname = f"cursor_work/{relative_path}"
            yield file_path, arcname


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Создаёт ZIP-архив проекта с автогенерацией BUILD_ID. "
            "Архивируется содержимое корня проекта (где manage.py)."
        )
    )
    parser.add_argument(
        "output_zip",
        nargs="?",
        help=(
            "Путь, куда сохранить .zip (пример: ../carfst.zip). "
            "Если не указан — будет создан ../carfst.zip относительно корня проекта."
        ),
    )
    args = parser.parse_args(argv)

    try:
        project_root = _find_project_root(Path(__file__).resolve().parent)
    except Exception as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 2

    # Pre-flight checks: migrations and required files
    print("Проверка миграций перед упаковкой...", file=sys.stderr)

    # Check 1: makemigrations --check --dry-run
    # Use settings_packaging (SimpleAdminConfig) to avoid admin autodiscover failures on Windows
    env = os.environ.copy()
    env["DJANGO_SETTINGS_MODULE"] = "carfst_site.settings_packaging"
    secret_key = env.get("DJANGO_SECRET_KEY") or env.get("SECRET_KEY", "")
    if not secret_key or secret_key == "dev-secret-key" or len(secret_key) < 50:
        temp_key = "packaging-" + secrets.token_urlsafe(32)
        env["DJANGO_SECRET_KEY"] = temp_key
        env.pop("SECRET_KEY", None)
        print("Используется временный SECRET_KEY для проверки миграций", file=sys.stderr)

    # makemigrations --check --dry-run: exit 0 = no changes, exit 1 = new migrations required
    try:
        result = subprocess.run(
            [sys.executable, "manage.py", "makemigrations", "--check", "--dry-run"],
            cwd=project_root,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        output_combined = result.stdout + "\n" + result.stderr
        output_lower = output_combined.lower()

        # returncode != 0: either "migrations required" (stdout contains "Migrations for") or config error or unknown
        if result.returncode != 0:
            # Config error (traceback, ImproperlyConfigured, etc.) — prefer over drift
            config_error_indicators = [
                "improperlyconfigured",
                "django.core.exceptions.improperlyconfigured",
                "traceback (most recent call last)",
                "modulenotfounderror",
                "importerror",
                "no module named",
            ]
            if any(indicator in output_lower for indicator in config_error_indicators):
                print(
                    "ОШИБКА: Ошибка конфигурации Django при проверке миграций",
                    file=sys.stderr,
                )
                print("=" * 60, file=sys.stderr)
                # Full stderr/stdout (no truncation) so real ImportError/NameError/traceback is visible
                if result.stdout.strip():
                    print("STDOUT:", file=sys.stderr)
                    print(result.stdout, file=sys.stderr)
                if result.stderr.strip():
                    print("STDERR:", file=sys.stderr)
                    print(result.stderr, file=sys.stderr)
                print("=" * 60, file=sys.stderr)
                print(
                    "Диагноз: Django не смог загрузить settings или модели.",
                    file=sys.stderr,
                )
                print(
                    "Используется carfst_site.settings_packaging (SimpleAdminConfig). "
                    "Убедитесь, что DJANGO_SECRET_KEY задан при необходимости.",
                    file=sys.stderr,
                )
                return 9

            # Маркер "Migrations for" в stdout (case-insensitive) — требуются новые миграции.
            # makemigrations --check --dry-run возвращает 1 в этом случае (Django печатает список в stdout).
            if re.search(r"migrations\s+for\s+", result.stdout, re.I):
                print(
                    "ОШИБКА: Обнаружены изменения моделей, создайте/добавьте миграции в репозиторий.",
                    file=sys.stderr,
                )
                print("=" * 60, file=sys.stderr)
                if result.stdout.strip():
                    print(result.stdout, file=sys.stderr)
                if result.stderr.strip():
                    print(result.stderr, file=sys.stderr)
                print("=" * 60, file=sys.stderr)
                print("Решение: python manage.py makemigrations", file=sys.stderr)
                return 1

            # Нет маркера — реальная неизвестная ошибка (полный вывод без обрезки)
            print(
                f"ОШИБКА: Неизвестная ошибка при проверке миграций (код: {result.returncode})",
                file=sys.stderr,
            )
            print("=" * 60, file=sys.stderr)
            if result.stdout.strip():
                print("STDOUT:", file=sys.stderr)
                print(result.stdout, file=sys.stderr)
            if result.stderr.strip():
                print("STDERR:", file=sys.stderr)
                print(result.stderr, file=sys.stderr)
            print("=" * 60, file=sys.stderr)
            return 6

        # Success case: verify "No changes detected" (locale/format agnostic)
        stdout_lower = result.stdout.lower()
        if not re.search(r"no\s+changes\s+detected", stdout_lower):
            print(
                "ОШИБКА: makemigrations --check не вернул 'No changes detected' (код 0)",
                file=sys.stderr,
            )
            print("STDOUT:", file=sys.stderr)
            print(result.stdout, file=sys.stderr)
            if result.stderr.strip():
                print("STDERR:", file=sys.stderr)
                print(result.stderr, file=sys.stderr)
            return 6

        print("✓ Проверка миграций: No changes detected", file=sys.stderr)
    except subprocess.TimeoutExpired:
        print("ОШИБКА: makemigrations --check превысил таймаут (30 секунд)", file=sys.stderr)
        return 6
    except FileNotFoundError:
        print(
            "ПРЕДУПРЕЖДЕНИЕ: python не найден, пропускаем проверку миграций",
            file=sys.stderr,
        )
    except Exception as exc:
        print(
            f"ОШИБКА при проверке миграций: {exc}",
            file=sys.stderr,
        )
        import traceback
        traceback.print_exc(file=sys.stderr)
        return 6

    # Check 1b: compileall — catch SyntaxError/IndentationError before packaging
    print("Проверка синтаксиса Python-файлов (compileall)...", file=sys.stderr)
    try:
        compile_result = subprocess.run(
            [sys.executable, "-m", "compileall", "-q", "catalog", "blog", "carfst_site"],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if compile_result.returncode != 0:
            print("ОШИБКА: Синтаксические ошибки в Python-файлах!", file=sys.stderr)
            print("=" * 60, file=sys.stderr)
            if compile_result.stdout.strip():
                print("STDOUT:", file=sys.stderr)
                print(compile_result.stdout, file=sys.stderr)
            if compile_result.stderr.strip():
                print("STDERR:", file=sys.stderr)
                print(compile_result.stderr, file=sys.stderr)
            print("=" * 60, file=sys.stderr)
            return 1
        print("✓ Проверка синтаксиса: OK (compileall)", file=sys.stderr)
    except subprocess.TimeoutExpired:
        print("ОШИБКА: compileall превысил таймаут (60 секунд)", file=sys.stderr)
        return 6
    except Exception as exc:
        print(f"ПРЕДУПРЕЖДЕНИЕ: compileall не удался: {exc}", file=sys.stderr)

    # Check 1c: Django system check (catches AlreadyRegistered, import errors, etc.)
    print("Проверка Django (manage.py check)...", file=sys.stderr)
    try:
        check_env = os.environ.copy()
        check_env["DJANGO_SETTINGS_MODULE"] = "carfst_site.settings"
        check_env["DJANGO_DEBUG"] = "1"
        # Ensure valid SECRET_KEY for Django check
        if not check_env.get("DJANGO_SECRET_KEY") or len(check_env.get("DJANGO_SECRET_KEY", "")) < 50:
            check_env["DJANGO_SECRET_KEY"] = "django-check-secret-key-min-50-chars-xxxxxxxxxxxxxxxx"
        check_result = subprocess.run(
            [sys.executable, "manage.py", "check"],
            cwd=project_root,
            env=check_env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if check_result.returncode != 0:
            print("ОШИБКА: Django check выявил ошибки (AlreadyRegistered, импорт и т.п.)!", file=sys.stderr)
            print("=" * 60, file=sys.stderr)
            if check_result.stdout.strip():
                print("STDOUT:", file=sys.stderr)
                print(check_result.stdout, file=sys.stderr)
            if check_result.stderr.strip():
                print("STDERR:", file=sys.stderr)
                print(check_result.stderr, file=sys.stderr)
            print("=" * 60, file=sys.stderr)
            return 1
        print("✓ Проверка Django: System check identified no issues", file=sys.stderr)
    except subprocess.TimeoutExpired:
        print("ОШИБКА: manage.py check превысил таймаут (60 секунд)", file=sys.stderr)
        return 6
    except Exception as exc:
        print(f"ПРЕДУПРЕЖДЕНИЕ: manage.py check не удался: {exc}", file=sys.stderr)

    # Check 1d: seo_content_audit (catches FieldError, import issues in SEO audit code)
    # Note: OperationalError (missing tables) is OK on Windows dev machine; we only care about code errors
    print("Проверка SEO Content Audit (manage.py seo_content_audit)...", file=sys.stderr)
    try:
        audit_env = os.environ.copy()
        audit_env["DJANGO_SETTINGS_MODULE"] = "carfst_site.settings_packaging"
        if not audit_env.get("DJANGO_SECRET_KEY") or len(audit_env.get("DJANGO_SECRET_KEY", "")) < 50:
            audit_env["DJANGO_SECRET_KEY"] = "seo-audit-secret-key-min-50-chars-xxxxxxxxxxxxxxxx"
        audit_result = subprocess.run(
            [sys.executable, "manage.py", "seo_content_audit", "--format=json", "--no-product-stats"],
            cwd=project_root,
            env=audit_env,
            capture_output=True,
            text=True,
            timeout=120,
        )
        output_combined = (audit_result.stdout + "\n" + audit_result.stderr).lower()
        # OperationalError (no such table) is OK on dev machine; fatal errors are FieldError, ImportError, etc.
        code_error_indicators = ["fielderror", "importerror", "nameerror", "attributeerror", "alreadyregistered"]
        is_code_error = any(ind in output_combined for ind in code_error_indicators)
        is_db_error = "operationalerror" in output_combined and "no such table" in output_combined
        
        if audit_result.returncode != 0:
            if is_db_error and not is_code_error:
                print("✓ Проверка SEO Content Audit: OK (код корректен, ошибка БД игнорируется на dev)", file=sys.stderr)
            else:
                print("ОШИБКА: seo_content_audit выявил ошибки (FieldError, импорт и т.п.)!", file=sys.stderr)
                print("=" * 60, file=sys.stderr)
                if audit_result.stdout.strip():
                    print("STDOUT:", file=sys.stderr)
                    print(audit_result.stdout, file=sys.stderr)
                if audit_result.stderr.strip():
                    print("STDERR:", file=sys.stderr)
                    print(audit_result.stderr, file=sys.stderr)
                print("=" * 60, file=sys.stderr)
                return 1
        else:
            print("✓ Проверка SEO Content Audit: OK", file=sys.stderr)
    except subprocess.TimeoutExpired:
        print("ОШИБКА: seo_content_audit превысил таймаут (120 секунд)", file=sys.stderr)
        return 6
    except Exception as exc:
        print(f"ПРЕДУПРЕЖДЕНИЕ: seo_content_audit не удался: {exc}", file=sys.stderr)

    # Check 2: Required migration file exists
    required_migration = project_root / "catalog" / "migrations" / "0026_alter_seo_faq_fields.py"
    if not required_migration.is_file():
        print(
            f"ОШИБКА: Обязательная миграция отсутствует: {required_migration.relative_to(project_root)}",
            file=sys.stderr,
        )
        return 7
    print(f"✓ Проверка: {required_migration.relative_to(project_root)} найден", file=sys.stderr)

    # Check 3: CSS build marker (cards-eqheight) — must be present before packaging
    CSS_BUILD_MARKER = "build: cards-eqheight-20251224"
    styles_css = project_root / "static" / "css" / "styles.css"
    if not styles_css.is_file():
        print(
            f"ОШИБКА: Файл не найден: {styles_css.relative_to(project_root)}",
            file=sys.stderr,
        )
        return 1
    try:
        styles_content = styles_css.read_text(encoding="utf-8", errors="ignore")
    except OSError as exc:
        print(
            f"ОШИБКА: Не удалось прочитать {styles_css.relative_to(project_root)}: {exc}",
            file=sys.stderr,
        )
        return 1
    if CSS_BUILD_MARKER not in styles_content:
        print(
            f"ОШИБКА: В {styles_css.relative_to(project_root)} отсутствует маркер сборки '{CSS_BUILD_MARKER}'.",
            file=sys.stderr,
        )
        print(
            "Добавьте первой строкой: /* build: cards-eqheight-20251224 */",
            file=sys.stderr,
        )
        return 1
    LINK_MARKER = "build: links-global-20260129"
    if LINK_MARKER not in styles_content:
        print(
            f"ОШИБКА: В {styles_css.relative_to(project_root)} отсутствует маркер ссылок '{LINK_MARKER}' (--bs-link-color, a:visited).",
            file=sys.stderr,
        )
        return 1
    SEO_ZONES_MARKER = "build: links-seo-zones-20260131"
    if SEO_ZONES_MARKER not in styles_content:
        print(
            f"ОШИБКА: В {styles_css.relative_to(project_root)} отсутствует маркер SEO-зон '{SEO_ZONES_MARKER}'.",
            file=sys.stderr,
        )
        return 1
    print(f"✓ Проверка: маркеры '{CSS_BUILD_MARKER}', '{LINK_MARKER}', '{SEO_ZONES_MARKER}' в styles.css", file=sys.stderr)

    # Check 4 (optional): product card template — expected blocks, no inline style=
    product_card_tpl = project_root / "templates" / "catalog" / "_product_card.html"
    if product_card_tpl.is_file():
        try:
            tpl_content = product_card_tpl.read_text(encoding="utf-8", errors="ignore")
        except OSError as exc:
            print(
                f"ОШИБКА: Не удалось прочитать {product_card_tpl.relative_to(project_root)}: {exc}",
                file=sys.stderr,
            )
            return 1
        for token in ("product-card__body", "product-card__footer", "product-card__actions"):
            n = tpl_content.count(token)
            if n != 1:
                print(
                    f"ОШИБКА: В {product_card_tpl.relative_to(project_root)} ожидается ровно одно вхождение '{token}', найдено {n}.",
                    file=sys.stderr,
                )
                return 1
        if "style=" in tpl_content:
            print(
                f"ОШИБКА: В {product_card_tpl.relative_to(project_root)} обнаружены inline-стили (style=), недопустимо для стабильной высоты карточек.",
                file=sys.stderr,
            )
            return 1
        print(f"✓ Проверка: шаблон карточки товара (блоки + без style=)", file=sys.stderr)

    # Generate and write BUILD_ID
    build_id = _generate_build_id()
    _write_build_id(project_root, build_id)

    if args.output_zip:
        output_path = Path(args.output_zip).expanduser()
        if not output_path.is_absolute():
            output_path = (Path.cwd() / output_path).resolve()
    else:
        output_path = (project_root.parent / "carfst.zip").resolve()

    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
    except PermissionError as exc:
        print(
            f"Ошибка: нет прав создать каталог '{output_path.parent}': {exc}",
            file=sys.stderr,
        )
        return 3
    except OSError as exc:
        print(f"Ошибка: не удалось подготовить путь '{output_path}': {exc}", file=sys.stderr)
        return 3

    file_count = 0
    zip_paths = []

    try:
        with zipfile.ZipFile(output_path, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
            for file_path, arcname in _iter_project_files(project_root, output_path):
                zf.write(file_path, arcname)
                zip_paths.append(arcname)
                file_count += 1
    except PermissionError as exc:
        print(f"Ошибка: нет прав записать архив '{output_path}': {exc}", file=sys.stderr)
        return 4
    except FileNotFoundError as exc:
        print(f"Ошибка: путь недоступен: {exc}", file=sys.stderr)
        return 4
    except OSError as exc:
        print(f"Ошибка ввода/вывода при создании архива: {exc}", file=sys.stderr)
        return 4
    except zipfile.BadZipFile as exc:
        print(f"Ошибка ZIP: {exc}", file=sys.stderr)
        return 4

    # Self-check: verify cursor_work/BUILD_ID exists and show first 10 paths
    zip_paths.sort()
    print("Первые 10 путей в архиве:", file=sys.stderr)
    for path in zip_paths[:10]:
        print(f"  {path}", file=sys.stderr)
    
    build_id_in_zip = "cursor_work/BUILD_ID"
    if build_id_in_zip not in zip_paths:
        print(f"ОШИБКА: в архиве отсутствует '{build_id_in_zip}'", file=sys.stderr)
        return 5
    
    print(f"✓ Проверка: {build_id_in_zip} найден в архиве", file=sys.stderr)
    
    # Check 5: Required migration file is in archive
    required_migration_in_zip = "cursor_work/catalog/migrations/0026_alter_seo_faq_fields.py"
    if required_migration_in_zip not in zip_paths:
        print(
            f"ОШИБКА: в архиве отсутствует обязательная миграция '{required_migration_in_zip}'",
            file=sys.stderr,
        )
        return 8
    
    print(f"✓ Проверка: {required_migration_in_zip} найден в архиве", file=sys.stderr)

    try:
        size_bytes = output_path.stat().st_size
        size_mb = size_bytes / (1024 * 1024)
    except OSError:
        size_bytes = 0
        size_mb = 0.0

    # Print required output: build_id, zip path, zip size
    print(build_id)
    print(str(output_path))
    print(f"{size_bytes}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
