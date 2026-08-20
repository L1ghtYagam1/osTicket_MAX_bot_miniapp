"""Полный бэкап установки перед обновлением.

Складывает в один архив всё, что нельзя восстановить из репозитория:

* базу данных (SQLite или PostgreSQL — определяется по DATABASE_URL);
* загруженные файлы `data/uploads` (иконки брендинга);
* `.env` с токенами и паролями;
* состояние диалогов бота и маркер long-polling;
* метку версии кода и ревизию Alembic — чтобы знать, куда откатываться.

Запуск:

    python scripts/backup.py                 # обычный бэкап
    python scripts/backup.py --keep 10       # оставить 10 последних архивов
    python scripts/backup.py --out /mnt/nas  # положить архив в другой каталог

Скрипт безопасно работает на живой системе: SQLite копируется штатным
online-backup API, PostgreSQL выгружается через pg_dump.
"""
import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlparse

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
BACKUP_DIR = DATA_DIR / "backups"
ENV_FILE = ROOT_DIR / ".env"

# Имя сервиса БД в docker-compose.yml — на случай, когда pg_dump есть только в контейнере.
POSTGRES_SERVICE = os.getenv("POSTGRES_SERVICE", "postgres")

BOT_STATE_FILES = ("conversation_state.json", "updates_marker.json")


def read_env_file() -> dict[str, str]:
    """Читает .env без внешних зависимостей — скрипт должен работать и вне venv."""
    values: dict[str, str] = {}
    if not ENV_FILE.exists():
        return values
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def resolve_database_url() -> str:
    return os.getenv("DATABASE_URL") or read_env_file().get("DATABASE_URL") or "sqlite:///./data/app.db"


def sqlite_path_from_url(url: str) -> Path:
    raw = url.split("///", 1)[-1]
    path = Path(raw)
    return path if path.is_absolute() else (ROOT_DIR / raw).resolve()


def backup_sqlite(url: str, target: Path) -> str:
    source = sqlite_path_from_url(url)
    if not source.exists():
        raise SystemExit(f"файл базы не найден: {source}")

    # Online backup API забирает согласованный снимок даже во время записи,
    # в отличие от простого копирования файла. Соединения закрываем явно:
    # контекстный менеджер sqlite3 только коммитит транзакцию, файл остаётся занят.
    src = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    dst = sqlite3.connect(target)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    return f"sqlite: {source.name} ({target.stat().st_size} байт)"


def postgres_dump_command(url: str) -> tuple[list[str], dict[str, str], bool]:
    parsed = urlparse(url.replace("postgresql+psycopg", "postgresql"))
    user = unquote(parsed.username or "maxsupport")
    password = unquote(parsed.password or "")
    database = (parsed.path or "/maxsupport").lstrip("/")
    host = parsed.hostname or "localhost"
    port = str(parsed.port or 5432)

    env = dict(os.environ)
    if password:
        env["PGPASSWORD"] = password

    if shutil.which("pg_dump"):
        command = [
            "pg_dump", "--format=custom", "--no-owner", "--no-acl",
            "--host", host, "--port", port, "--username", user, database,
        ]
        return command, env, False

    # Хост «postgres» резолвится только внутри docker-сети, поэтому идём в контейнер.
    compose = docker_compose_command()
    if compose is None:
        raise SystemExit(
            "нужен pg_dump или docker compose: установите postgresql-client "
            "или запускайте скрипт на хосте с docker"
        )
    command = [
        *compose, "exec", "-T", POSTGRES_SERVICE,
        "pg_dump", "--format=custom", "--no-owner", "--no-acl",
        "--username", user, database,
    ]
    return command, env, True


def docker_compose_command() -> list[str] | None:
    for candidate in (["docker", "compose"], ["docker-compose"]):
        if shutil.which(candidate[0]) is None:
            continue
        probe = subprocess.run([*candidate, "version"], capture_output=True)
        if probe.returncode == 0:
            return candidate
    return None


def backup_postgres(url: str, target: Path) -> str:
    command, env, via_docker = postgres_dump_command(url)
    with target.open("wb") as handle:
        result = subprocess.run(command, stdout=handle, stderr=subprocess.PIPE, env=env, cwd=ROOT_DIR)
    if result.returncode != 0:
        raise SystemExit(f"pg_dump завершился с ошибкой:\n{result.stderr.decode('utf-8', 'replace')}")
    where = "через docker compose" if via_docker else "локальным pg_dump"
    return f"postgresql: дамп снят {where} ({target.stat().st_size} байт)"


def current_alembic_revision(url: str) -> str:
    """Ревизия схемы — по ней понятно, нужен ли downgrade при откате."""
    if not url.startswith("sqlite"):
        return "неизвестна (PostgreSQL: см. alembic current)"
    source = sqlite_path_from_url(url)
    if not source.exists():
        return "нет"
    connection = None
    try:
        connection = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
        row = connection.execute("SELECT version_num FROM alembic_version").fetchone()
        return row[0] if row else "нет"
    except sqlite3.Error:
        # Таблицы нет — значит база ещё не переведена на миграции.
        return "нет (схема от create_all)"
    finally:
        if connection is not None:
            connection.close()


def git_revision() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=ROOT_DIR
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except OSError:
        pass
    return "неизвестна"


def rotate_backups(keep: int, directory: Path) -> list[str]:
    if keep <= 0:
        return []
    archives = sorted(directory.glob("backup-*.tar.gz"), key=lambda item: item.name)
    removed = []
    for old in archives[:-keep] if len(archives) > keep else []:
        old.unlink()
        removed.append(old.name)
    return removed


def main() -> int:
    parser = argparse.ArgumentParser(description="Полный бэкап установки")
    parser.add_argument("--out", type=Path, default=BACKUP_DIR, help="каталог для архива")
    parser.add_argument("--keep", type=int, default=0, help="сколько последних архивов оставить (0 — не удалять)")
    args = parser.parse_args()

    database_url = resolve_database_url()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    args.out.mkdir(parents=True, exist_ok=True)
    archive_path = args.out / f"backup-{timestamp}.tar.gz"

    report: list[str] = []

    with tempfile.TemporaryDirectory(prefix="osticket-backup-") as tmp:
        staging = Path(tmp)

        if database_url.startswith("sqlite"):
            report.append(backup_sqlite(database_url, staging / "database.sqlite"))
        else:
            report.append(backup_postgres(database_url, staging / "database.dump"))

        uploads = DATA_DIR / "uploads"
        if uploads.exists() and any(uploads.iterdir()):
            shutil.copytree(uploads, staging / "uploads")
            report.append(f"uploads: файлов {len(list(uploads.rglob('*')))}")

        if ENV_FILE.exists():
            shutil.copy2(ENV_FILE, staging / "env")
            report.append(".env: сохранён")
        else:
            report.append(".env: не найден — пропущен")

        bot_state = staging / "bot_state"
        bot_state.mkdir()
        saved_state = []
        for name in BOT_STATE_FILES:
            source = DATA_DIR / name
            if source.exists():
                shutil.copy2(source, bot_state / name)
                saved_state.append(name)
        report.append(f"состояние бота: {', '.join(saved_state) if saved_state else 'нет файлов'}")

        metadata = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "git_revision": git_revision(),
            "alembic_revision": current_alembic_revision(database_url),
            "database_kind": "sqlite" if database_url.startswith("sqlite") else "postgresql",
            "hostname": os.uname().nodename if hasattr(os, "uname") else os.getenv("COMPUTERNAME", ""),
        }
        (staging / "metadata.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        with tarfile.open(archive_path, "w:gz") as archive:
            for item in sorted(staging.iterdir()):
                archive.add(item, arcname=item.name)

    # .env внутри архива содержит секреты — доступ только владельцу.
    try:
        archive_path.chmod(0o600)
    except OSError:
        pass

    print(f"Бэкап создан: {archive_path}")
    print(f"Размер: {archive_path.stat().st_size / 1024:.1f} КБ")
    for line in report:
        print(f"  - {line}")
    print(f"  - версия кода: {metadata['git_revision'][:12]}")
    print(f"  - ревизия схемы: {metadata['alembic_revision']}")

    removed = rotate_backups(args.keep, args.out)
    if removed:
        print(f"Удалены старые архивы: {', '.join(removed)}")

    print("\nВосстановление:")
    print(f"  python scripts/restore.py {archive_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
