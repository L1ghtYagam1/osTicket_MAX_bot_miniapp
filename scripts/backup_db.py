from datetime import datetime
from pathlib import Path
import shutil


ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
DB_FILE = DATA_DIR / "app.db"
BACKUP_DIR = DATA_DIR / "backups"


def main() -> int:
    if not DB_FILE.exists():
        print(f"database file not found: {DB_FILE}")
        return 1

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    backup_path = BACKUP_DIR / f"app-{timestamp}.db"
    shutil.copy2(DB_FILE, backup_path)
    print(f"backup created: {backup_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
