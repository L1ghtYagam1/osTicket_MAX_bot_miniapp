import json
import sys
from pathlib import Path
from time import time


HEARTBEAT_FILE = Path(__file__).resolve().parent.parent / "data" / "bot_heartbeat.json"
MAX_AGE_SECONDS = 180


def main() -> int:
    if not HEARTBEAT_FILE.exists():
        print("heartbeat file not found")
        return 1

    try:
        payload = json.loads(HEARTBEAT_FILE.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"invalid heartbeat payload: {exc}")
        return 1

    updated_at = int(payload.get("updated_at", 0))
    age = int(time()) - updated_at
    if age > MAX_AGE_SECONDS:
        print(f"heartbeat is stale: {age}s")
        return 1

    print("ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
