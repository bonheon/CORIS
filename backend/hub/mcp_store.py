"""
화면에서 등록한 MCP 서버 저장소 — 회사에서 운영 중인 MCP 서버를 주소만 넣어 붙인다.

    {id, name, description, url, transport, headers, enabled,
     tools: [가져올 tool 이름],        # 서버의 tool 중 사용자가 고른 것만 Coris 에 들어온다
     labels: {tool: 화면 표시명},
     default_on: bool,               # true 면 agent 기본 tool 에 포함 (아니면 스킬 · 직접 선택으로만)
     created_at, updated_at}

서버 하나 = tool group 하나 (id: mcp_<server id>). group 이 되므로 routing · ToolPicker · 스킬 편집이
yaml 에 적은 group 과 똑같이 다룬다.
mcp_servers.yaml 의 서버(배포 설정)와 같은 이름은 쓸 수 없다.

헤더 값(토큰)은 화면에 내려보낼 때 가린다. 수정 시 가린 값 그대로 오면 기존 값을 유지한다.
토큰을 저장하지 않으려면 값에 ${ENV_VAR} 를 쓰면 된다 — 호출 시점에 .env 에서 치환된다.
"""
import re
from typing import Optional

from hub import store

COLL = "mcp_servers"
MASK = "••••••"
GROUP_PREFIX = "mcp_"
_ID_RE = re.compile(r"^[a-z][a-z0-9_]{1,31}$")


def group_id(server_id: str) -> str:
    return GROUP_PREFIX + server_id


def list_items() -> list[dict]:
    return sorted(store.list_items(COLL), key=lambda s: s["created_at"])


def get_item(server_id: str) -> Optional[dict]:
    return store.get_item(COLL, server_id)


def mask(value: str) -> str:
    return value if not value or "${" in value else MASK


def public(rec: dict) -> dict:
    return rec | {"headers": {k: mask(v) for k, v in (rec.get("headers") or {}).items()}}


def connection(rec: dict) -> dict:
    """MultiServerMCPClient 에 넘길 접속 정보."""
    conn = {"transport": rec.get("transport") or "streamable_http", "url": rec["url"]}
    if rec.get("headers"):
        conn["headers"] = dict(rec["headers"])
    return conn


def merge_headers(new: dict[str, str], old: Optional[dict[str, str]]) -> dict[str, str]:
    """화면에서 가린 값(MASK)이 그대로 오면 기존 값 유지. 빈 키는 버린다."""
    old = old or {}
    return {k.strip(): (old.get(k, "") if v == MASK else v) for k, v in new.items() if k.strip()}


def validate_id(server_id: str, reserved: set[str]) -> None:
    if not _ID_RE.match(server_id):
        raise ValueError("ID 는 영문 소문자로 시작하고 소문자 · 숫자 · _ 만 2~32자")
    if server_id in reserved:
        raise ValueError(f"'{server_id}' 는 mcp_servers.yaml 에 있는 이름입니다")


def save(server_id: str, data: dict, *, create: bool) -> dict:
    old = get_item(server_id)
    if create and old:
        raise ValueError(f"이미 있는 ID: {server_id}")
    if not create and not old:
        raise KeyError(server_id)
    ts = store.now_iso()
    rec = (old or {"id": server_id, "created_at": ts}) | data | {
        "headers": merge_headers(data.get("headers") or {}, (old or {}).get("headers")),
        "updated_at": ts,
    }
    return store.upsert_item(COLL, rec)


def delete(server_id: str) -> bool:
    return store.delete_item(COLL, server_id)
