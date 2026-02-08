import argparse
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

import django

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(BASE_DIR))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "carfst_site.settings")
django.setup()

from catalog.importers import run_import  # noqa: E402

logs_dir = BASE_DIR / "logs"
logs_dir.mkdir(exist_ok=True)
log_file = logs_dir / f"import_{datetime.now():%Y%m%d}.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler(log_file), logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="Импорт товаров из XLSX")
    parser.add_argument("--file", required=True, help="Путь к XLSX")
    parser.add_argument("--media-dir", required=False, help="Каталог с изображениями")
    args = parser.parse_args()

    created, updated, errors = run_import(args.file, args.media_dir)
    logger.info("Создано: %s, обновлено: %s, ошибок: %s", created, updated, errors)
    if errors:
        logger.info("Для крупных файлов используйте Celery задачу (placeholder).")


if __name__ == "__main__":
    main()






