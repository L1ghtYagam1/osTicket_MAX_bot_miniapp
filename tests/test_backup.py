"""Резервное копирование и восстановление."""
import importlib.util
import json
import sqlite3
import sys
import tarfile
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"


def load_script(name: str):
    """scripts/ не пакет — подгружаем модуль по пути."""
    sys.path.insert(0, str(SCRIPTS_DIR))
    spec = importlib.util.spec_from_file_location(name, SCRIPTS_DIR / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


backup = load_script("backup")
restore = load_script("restore")


@pytest.fixture
def sqlite_db(tmp_path):
    """База с одной таблицей и предсказуемым содержимым."""
    path = tmp_path / "app.db"
    connection = sqlite3.connect(path)
    try:
        connection.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT)")
        connection.execute("INSERT INTO users (email) VALUES ('user@example.com')")
        connection.commit()
    finally:
        connection.close()
    return path


def read_emails(path: Path) -> list[str]:
    connection = sqlite3.connect(path)
    try:
        return [row[0] for row in connection.execute("SELECT email FROM users")]
    finally:
        connection.close()


class TestSqliteBackup:
    def test_backup_and_restore_roundtrip(self, sqlite_db, tmp_path, monkeypatch):
        url = f"sqlite:///{sqlite_db.as_posix()}"
        dump = tmp_path / "database.sqlite"
        backup.backup_sqlite(url, dump)
        assert read_emails(dump) == ["user@example.com"]

        # Данные потеряны.
        connection = sqlite3.connect(sqlite_db)
        try:
            connection.execute("DELETE FROM users")
            connection.commit()
        finally:
            connection.close()
        assert read_emails(sqlite_db) == []

        monkeypatch.setattr(restore, "ROOT_DIR", tmp_path)
        restore.restore_sqlite(url, dump)
        assert read_emails(sqlite_db) == ["user@example.com"]

    def test_previous_database_is_kept_aside(self, sqlite_db, tmp_path):
        url = f"sqlite:///{sqlite_db.as_posix()}"
        dump = tmp_path / "database.sqlite"
        backup.backup_sqlite(url, dump)
        restore.restore_sqlite(url, dump)
        # Ошибочный restore тоже должен быть обратим.
        replaced = list(tmp_path.glob("app.db.replaced-*"))
        assert len(replaced) == 1
        assert read_emails(replaced[0]) == ["user@example.com"]

    def test_backup_of_missing_database_fails_loudly(self, tmp_path):
        url = f"sqlite:///{(tmp_path / 'нет.db').as_posix()}"
        with pytest.raises(SystemExit, match="файл базы не найден"):
            backup.backup_sqlite(url, tmp_path / "out.sqlite")

    def test_backup_works_while_database_is_open(self, sqlite_db, tmp_path):
        # Бэкап снимается на живой системе — соединение приложения остаётся открытым.
        busy = sqlite3.connect(sqlite_db)
        try:
            busy.execute("INSERT INTO users (email) VALUES ('second@example.com')")
            busy.commit()
            dump = tmp_path / "database.sqlite"
            backup.backup_sqlite(f"sqlite:///{sqlite_db.as_posix()}", dump)
        finally:
            busy.close()
        assert sorted(read_emails(dump)) == ["second@example.com", "user@example.com"]


class TestEnvParsing:
    def test_reads_values_and_ignores_comments(self, tmp_path, monkeypatch):
        env = tmp_path / ".env"
        env.write_text(
            "# комментарий\n"
            "DATABASE_URL=sqlite:///./data/app.db\n"
            "\n"
            'QUOTED="значение"\n'
            "EMPTY=\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(backup, "ENV_FILE", env)
        values = backup.read_env_file()
        assert values["DATABASE_URL"] == "sqlite:///./data/app.db"
        assert values["QUOTED"] == "значение"
        assert values["EMPTY"] == ""

    def test_missing_env_is_not_an_error(self, tmp_path, monkeypatch):
        monkeypatch.setattr(backup, "ENV_FILE", tmp_path / "нет.env")
        assert backup.read_env_file() == {}

    def test_environment_wins_over_env_file(self, tmp_path, monkeypatch):
        env = tmp_path / ".env"
        env.write_text("DATABASE_URL=sqlite:///./from-file.db\n", encoding="utf-8")
        monkeypatch.setattr(backup, "ENV_FILE", env)
        monkeypatch.setenv("DATABASE_URL", "sqlite:///./from-environment.db")
        assert backup.resolve_database_url() == "sqlite:///./from-environment.db"


class TestRotation:
    def test_keeps_requested_number_of_archives(self, tmp_path):
        for stamp in ("20260101-000000", "20260102-000000", "20260103-000000"):
            (tmp_path / f"backup-{stamp}.tar.gz").write_bytes(b"x")
        removed = backup.rotate_backups(2, tmp_path)
        remaining = sorted(item.name for item in tmp_path.glob("backup-*.tar.gz"))
        assert removed == ["backup-20260101-000000.tar.gz"]
        assert remaining == ["backup-20260102-000000.tar.gz", "backup-20260103-000000.tar.gz"]

    def test_zero_keeps_everything(self, tmp_path):
        (tmp_path / "backup-20260101-000000.tar.gz").write_bytes(b"x")
        assert backup.rotate_backups(0, tmp_path) == []
        assert len(list(tmp_path.glob("backup-*.tar.gz"))) == 1


class TestArchiveSafety:
    def test_restore_rejects_path_traversal(self, tmp_path, monkeypatch, capsys):
        """Архив с путями вида ../ не должен писать файлы за пределы проекта."""
        evil_file = tmp_path / "payload"
        evil_file.write_text("вредонос", encoding="utf-8")
        archive_path = tmp_path / "backup-evil.tar.gz"
        with tarfile.open(archive_path, "w:gz") as archive:
            archive.add(evil_file, arcname="../../escaped.txt")

        monkeypatch.setattr(sys, "argv", ["restore.py", str(archive_path), "--yes"])
        with pytest.raises(SystemExit, match="подозрительный путь"):
            restore.main()


class TestMetadata:
    def test_alembic_revision_is_read_from_database(self, tmp_path):
        path = tmp_path / "app.db"
        connection = sqlite3.connect(path)
        try:
            connection.execute("CREATE TABLE alembic_version (version_num TEXT)")
            connection.execute("INSERT INTO alembic_version VALUES ('0002')")
            connection.commit()
        finally:
            connection.close()
        assert backup.current_alembic_revision(f"sqlite:///{path.as_posix()}") == "0002"

    def test_database_without_alembic_is_reported(self, sqlite_db):
        # База, созданная старым create_all, — важный признак при откате.
        revision = backup.current_alembic_revision(f"sqlite:///{sqlite_db.as_posix()}")
        assert "create_all" in revision

    def test_archive_contains_expected_members(self, sqlite_db, tmp_path, monkeypatch):
        monkeypatch.setattr(backup, "DATA_DIR", tmp_path / "data")
        monkeypatch.setattr(backup, "ENV_FILE", tmp_path / ".env")
        (tmp_path / ".env").write_text("DATABASE_URL=x\n", encoding="utf-8")
        (tmp_path / "data").mkdir()
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{sqlite_db.as_posix()}")
        monkeypatch.setattr(sys, "argv", ["backup.py", "--out", str(tmp_path / "archives")])

        assert backup.main() == 0

        archives = list((tmp_path / "archives").glob("backup-*.tar.gz"))
        assert len(archives) == 1
        with tarfile.open(archives[0]) as archive:
            names = set(archive.getnames())
            assert {"database.sqlite", "env", "metadata.json"} <= names
            metadata = json.loads(archive.extractfile("metadata.json").read().decode("utf-8"))
        assert metadata["database_kind"] == "sqlite"
        assert "created_at" in metadata
