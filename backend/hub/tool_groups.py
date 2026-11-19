"""
화면(그룹 메뉴)에서 만든 tool 그룹 — MCP 서버와 상관없이 tool 을 골라 묶는다.

그룹 = 이름 · 설명 · 업무 영역 태그 · tool 목록. 저장은 hub.json 의 "tool_groups".
catalog.rebuild() 가 이 그룹들을 GROUPS 에 덧붙인다 (yaml 그룹 다음, 서버 그룹 앞).
agent 의 include_imported 가 켜져 있으면 허용 범위에 들어가고, default_on 이면 기본 그룹에도 들어간다.
"""
from typing import Optional

from hub import store

COLL = "tool_groups"
ID_PREFIX = "tg_"


def list_items() -> list[dict]:
    items = store.list_items(COLL)
    items.sort(key=lambda g: (g.get("order", 0), g["created_at"]))
    return items


def get_item(group_id: str) -> Optional[dict]:
    return store.get_item(COLL, group_id)


def save(group_id: Optional[str], data: dict, user_id: Optional[str] = None) -> dict:
    """data: name · description · tags · tools · default_on · enabled. tool 은 중복 없이 순서 유지."""
    old = get_item(group_id) if group_id else None
    if group_id and old is None:
        raise KeyError(group_id)
    ts = store.now_iso()
    rec = (old or {"id": store.new_id("tg"), "created_at": ts, "owner": user_id}) | {
        "name": data["name"].strip(),
        "description": (data.get("description") or "").strip(),
        "tags": list(dict.fromkeys(t.strip() for t in data.get("tags") or [] if t.strip())),
        "tools": list(dict.fromkeys(data.get("tools") or [])),
        "default_on": bool(data.get("default_on", True)),
        "enabled": bool(data.get("enabled", True)),
        "updated_at": ts,
    }
    return store.upsert_item(COLL, rec)


def delete(group_id: str) -> bool:
    return store.delete_item(COLL, group_id)
