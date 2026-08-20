"""Применение миграций Alembic при старте backend.

Проект долго жил на `Base.metadata.create_all`, поэтому на работающих серверах уже
есть схема, но нет таблицы `alembic_version`. Чтобы обновление сводилось к обычному
`git pull && docker compose up`, состояние определяется автоматически:

* пустая база          -> прогоняем все миграции с нуля;
* база от create_all   -> штампуем подходящую ревизию и накатываем только дельту;
* база под Alembic     -> обычный upgrade head.
"""
import logging
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

from .database import engine


logger = logging.getLogger(__name__)

ROOT_DIR = Path(__file__).resolve().parent.parent
ALEMBIC_INI = ROOT_DIR / "alembic.ini"
MIGRATIONS_DIR = ROOT_DIR / "backend" / "migrations"

# Таблица, по наличию которой опознаём схему, созданную до перехода на миграции.
LEGACY_MARKER_TABLE = "users"


def build_alembic_config() -> Config:
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    return config


def _baseline_revision_for(existing_tables: set[str]) -> str:
    """Ревизия, до которой существующая схема уже доведена."""
    columns = {column["name"] for column in inspect(engine).get_columns("email_verifications")} \
        if "email_verifications" in existing_tables else set()
    # `attempts` появляется в 0002 — если колонка уже есть, схема соответствует head.
    return "head" if "attempts" in columns else "0001"


def run_migrations() -> None:
    config = build_alembic_config()
    existing_tables = set(inspect(engine).get_table_names())

    if "alembic_version" not in existing_tables and LEGACY_MARKER_TABLE in existing_tables:
        revision = _baseline_revision_for(existing_tables)
        logger.info("Существующая база без истории Alembic — штампуем ревизию %s", revision)
        command.stamp(config, revision)

    command.upgrade(config, "head")
    logger.info("Миграции применены")
