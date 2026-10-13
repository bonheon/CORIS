"""
Hub JSON 파일 저장소 — 대화 / 스킬 사용 기록 / 이벤터 / 화면에서 등록한 MCP 서버.

사내 DB 연동 전까지 backend/data/hub.json 한 파일에 저장한다.
프로세스 하나(uvicorn 단일 worker) 기준이며, 쓰기는 lock 으로 직렬화한다.
"""
import json
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "hub.json"
# skills 는 SKILL.md 폴더로 옮겼다(hub/skills.py) — 남은 "skills" 는 이전 데이터 이관용으로만 읽는다
COLLECTIONS = ("conversations", "skills", "skill_stats", "events", "mcp_servers")

_lock = threading.Lock()
_cache: Optional[dict] = None


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def _seed() -> dict:
    """첫 기동 시 예시 이벤터 1개 (꺼진 상태) — 화면에서 형식을 보여주는 용도."""
    events = [
        {
            "id": "ev_example", "name": "주간 업무 요약 (예시)",
            "schedule": {"kind": "weekly", "time": "17:00", "weekday": 4},
            "skill_id": None, "agent_id": "auto",
            "prompt": "이번 주 등록된 공지를 요약해줘",
            "target": "팀 메일", "enabled": False, "last_run": None,
        },
    ]
    return {"conversations": [], "events": events}


def _load() -> dict:
    global _cache
    if _cache is None:
        fresh = not DATA_PATH.exists()
        _cache = _seed() if fresh else json.loads(DATA_PATH.read_text(encoding="utf-8"))
        for c in COLLECTIONS:
            _cache.setdefault(c, [])
        if fresh:
            _flush()
    return _cache


def _flush() -> None:
    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = DATA_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(_cache, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(DATA_PATH)


def list_items(coll: str) -> list[dict]:
    with _lock:
        return [dict(x) for x in _load()[coll]]


def get_item(coll: str, item_id: str) -> Optional[dict]:
    with _lock:
        for x in _load()[coll]:
            if x["id"] == item_id:
                return dict(x)
    return None


def upsert_item(coll: str, item: dict) -> dict:
    with _lock:
        items = _load()[coll]
        for i, x in enumerate(items):
            if x["id"] == item["id"]:
                items[i] = item
                break
        else:
            items.insert(0, item)
        _flush()
    return item


def delete_item(coll: str, item_id: str) -> bool:
    with _lock:
        items = _load()[coll]
        n = len(items)
        items[:] = [x for x in items if x["id"] != item_id]
        if len(items) != n:
            _flush()
            return True
    return False
