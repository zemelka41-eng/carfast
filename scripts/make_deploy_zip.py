"""Create a deploy ZIP archive of the Django project.

- Archives the project root (where manage.py lives), preserving paths.
- Excludes persistent/local directories and secrets (see EXCLUDED_*).

Usage:
  python scripts/make_deploy_zip.py "C:\\Users\\VLAD\\Desktop\\carfst.zip"

If output path is not provided, defaults to "../carfst.zip" relative to project root.

Python 3.11+ / stdlib only.
"""

from __future__ import annotations

import argparse
import fnmatch
import os
import sys
import zipfile
from pathlib import Path

EXCLUDED_DIR_NAMES: set[str] = {
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".git",
    ".idea",
    ".vscode",
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
    "*.log",
)


def _find_project_root(start: Path) -> Path:
    """Walk up from start until manage.py is found."""
    for candidate in (start, *start.parents):
        if (candidate / "manage.py").is_file():
            return candidate
    raise FileNotFoundError(
        "Не удалось найти корень проекта: файл 'manage.py' не найден ни в текущей директории, ни выше. "
        "Запускайте скрипт из репозитория проекта (папка 'scripts' должна быть внутри корня)."
    )


def _is_excluded_file(file_path: Path) -> bool:
    name = file_path.name
    if name in EXCLUDED_FILE_NAMES:
        return True
    return any(fnmatch.fnmatch(name, pattern) for pattern in EXCLUDED_FILE_PATTERNS)


def _iter_project_files(project_root: Path, output_zip_path: Path):
    """Yield (absolute_file_path, arcname_posix) for files to include."""
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

            arcname = file_path.relative_to(project_root).as_posix()
            yield file_path, arcname


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Создаёт ZIP-архив проекта для деплоя, исключая persistent/локальные директории и секреты. "
            "Архивируется содержимое корня проекта (где manage.py)."
        )
    )
    parser.add_argument(
        "output_zip",
        nargs="?",
        help=(
            "Путь, куда сохранить .zip (пример: C:\\Users\\VLAD\\Desktop\\carfst.zip). "
            "Если не указан — будет создан ../carfst.zip относительно корня проекта."
        ),
    )
    args = parser.parse_args(argv)

    try:
        project_root = _find_project_root(Path(__file__).resolve().parent)
    except Exception as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 2

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

    try:
        with zipfile.ZipFile(output_path, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
            for file_path, arcname in _iter_project_files(project_root, output_path):
                zf.write(file_path, arcname)
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

    try:
        size_mb = output_path.stat().st_size / (1024 * 1024)
    except OSError:
        size_mb = 0.0

    print(f"Archive: {output_path}")
    print(f"Files: {file_count}")
    print(f"Size: {size_mb:.2f} MB")

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

