"""Восстановление установки из архива, созданного scripts/backup.py.

    python scripts/restore.py data/backups/backup-20260820-093000.tar.gz
    python scripts/restore.py <архив> --yes          # без интерактивного вопроса
    python scripts/restore.py <архив> --skip-env     # не трогать текущий .env

Перед восстановлением остановите приложение, иначе backend и бот будут писать в
базу, которую скрипт в этот момент заменяет:

    docker compose stop backend bot

Скрипт всегда сохраняет вытесняемую базу рядом (`*.replaced-<время>`), поэтому
ошибочный restore тоже обратим.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlparse

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
ENV_FILE = ROOT_DIR / ".env"
POSTGRES_SERVICE = os.getenv("POSTGRES_SERVICE", "postgres")

sys.path.insert(0, str(Path(__file__).resolve().parent))
from backup import (  # noqa: E402
    BOT_STATE_FILES,
    docker_compose_command,
    resolve_database_url,
    sqlite_path_from_url,
)


def restore_sqlite(url: str, source: Path) -> str:
    target = sqlite_path_from_url(url)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        replaced = target.with_suffix(target.suffix + f".replaced-{stamp}")
        shutil.move(str(target), replaced)
        note = f" (прежняя база сохранена как {replaced.name})"
    else:
        note = ""
    shutil.copy2(source, target)
    return f"база SQLite восстановлена в {target}{note}"


def restore_postgres(url: str, source: Path) -> str:
    parsed = urlparse(url.replace("postgresql+psycopg", "postgresql"))
    user = unquote(parsed.username or "maxsupport")
    password = unquote(parsed.password or "")
    database = (parsed.path or "/maxsupport").lstrip("/")
    host = parsed.hostname or "localhost"
    port = str(parsed.port or 5432)

    env = dict(os.environ)
    if password:
        env["PGPASSWORD"] = password

    # --clean --if-exists удаляет объекты перед загрузкой, иначе дамп ляжет поверх.
    base_args = ["--clean", "--if-exists", "--no-owner", "--no-acl", "--dbname", database]

    if shutil.which("pg_restore"):
        command = ["pg_restore", "--host", host, "--port", port, "--username", user, *base_args, str(source)]
        result = subprocess.run(command, capture_output=True, env=env, cwd=ROOT_DIR)
    else:
        compose = docker_compose_command()
        if compose is None:
            raise SystemExit("нужен pg_restore или docker compose")
        command = [*compose, "exec", "-T", POSTGRES_SERVICE, "pg_restore", "--username", user, *base_args]
        with source.open("rb") as handle:
            result = subprocess.run(command, stdin=handle, capture_output=True, env=env, cwd=ROOT_DIR)

    if result.returncode != 0:
        message = result.stderr.decode("utf-8", "replace")
        # pg_restore ругается на отсутствующие объекты при --clean на пустой базе.
        raise SystemExit(f"pg_restore завершился с ошибкой:\n{message}")
    return "база PostgreSQL восстановлена"


def main() -> int:
    parser = argparse.ArgumentParser(description="Восстановление из бэкапа")
    parser.add_argument("archive", type=Path, help="путь к архиву backup-*.tar.gz")
    parser.add_argument("--yes", action="store_true", help="не запрашивать подтверждение")
    parser.add_argument("--skip-env", action="store_true", help="не восстанавливать .env")
    parser.add_argument("--skip-uploads", action="store_true", help="не восстанавливать data/uploads")
    args = parser.parse_args()

    if not args.archive.exists():
        raise SystemExit(f"архив не найден: {args.archive}")

    with tempfile.TemporaryDirectory(prefix="osticket-restore-") as tmp:
        staging = Path(tmp)
        with tarfile.open(args.archive, "r:gz") as archive:
            for member in archive.getmembers():
                # Защита от путей вида ../ в подменённом архиве.
                if member.name.startswith("/") or ".." in Path(member.name).parts:
                    raise SystemExit(f"подозрительный путь в архиве: {member.name}")
            archive.extractall(staging)

        metadata = {}
        metadata_file = staging / "metadata.json"
        if metadata_file.exists():
            metadata = json.loads(metadata_file.read_text(encoding="utf-8"))

        print(f"Архив: {args.archive}")
        print(f"  создан:          {metadata.get('created_at', 'неизвестно')}")
        print(f"  версия кода:     {metadata.get('git_revision', 'неизвестна')}")
        print(f"  ревизия схемы:   {metadata.get('alembic_revision', 'неизвестна')}")
        print(f"  тип базы:        {metadata.get('database_kind', 'неизвестен')}")

        database_url = resolve_database_url()
        current_kind = "sqlite" if database_url.startswith("sqlite") else "postgresql"
        backup_kind = metadata.get("database_kind", current_kind)
        if backup_kind != current_kind:
            raise SystemExit(
                f"тип базы в архиве ({backup_kind}) не совпадает с текущим ({current_kind}). "
                "Приведите DATABASE_URL в соответствие и повторите."
            )

        if not args.yes:
            print("\nТекущие данные будут заменены. Приложение должно быть остановлено.")
            answer = input("Продолжить? [y/N] ").strip().lower()
            if answer not in {"y", "yes", "д", "да"}:
                print("Отменено.")
                return 1

        report = []

        sqlite_dump = staging / "database.sqlite"
        postgres_dump = staging / "database.dump"
        if sqlite_dump.exists():
            report.append(restore_sqlite(database_url, sqlite_dump))
        elif postgres_dump.exists():
            report.append(restore_postgres(database_url, postgres_dump))
        else:
            report.append("база в архиве отсутствует — пропущена")

        uploads_source = staging / "uploads"
        if uploads_source.exists() and not args.skip_uploads:
            target = DATA_DIR / "uploads"
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(uploads_source, target)
            report.append(f"uploads восстановлены в {target}")

        env_source = staging / "env"
        if env_source.exists() and not args.skip_env:
            if ENV_FILE.exists():
                stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
                shutil.copy2(ENV_FILE, ENV_FILE.with_name(f".env.replaced-{stamp}"))
            shutil.copy2(env_source, ENV_FILE)
            report.append(".env восстановлен (прежний сохранён рядом)")

        bot_state = staging / "bot_state"
        if bot_state.exists():
            restored = []
            for name in BOT_STATE_FILES:
                source = bot_state / name
                if source.exists():
                    shutil.copy2(source, DATA_DIR / name)
                    restored.append(name)
            if restored:
                report.append(f"состояние бота: {', '.join(restored)}")

    print("\nГотово:")
    for line in report:
        print(f"  - {line}")

    revision = metadata.get("git_revision", "")
    if revision and revision != "неизвестна":
        print("\nЕсли нужно вернуть и код той же версии:")
        print(f"  git checkout {revision[:12]}")
    print("\nЗапуск приложения:")
    print("  docker compose up -d")
    return 0


if __name__ == "__main__":
    sys.exit(main())
