"""
Hub 카탈로그 — tool 원천, tool 그룹, agent 정의, 포탈 목록.

agent/group/표시명/포탈 정의는 catalog.yaml 에 있다 (기준: group = 데이터 영역, agent = 업무 방식).
화면에서 등록한 MCP 서버(hub/mcp_store.py)는 서버 하나가 group 하나로 덧붙는다 (imported group).
agent 에 include_imported: true 가 있으면 imported group 을 허용 범위에 넣고,
서버의 default_on 이 true 면 기본 group 에도 넣는다.

tool 원천은 MCP 서버다. refresh() 가 group 을 다시 만들고 서버에서 tool 을 다시 받아와
GROUPS · TOOLS_BY_NAME 등을 제자리에서 갱신한다 — 다른 모듈이 import 한 참조가 그대로 유효하도록.
"""
import logging
from pathlib import Path

import yaml

from hub import mcp_registry, mcp_store, session_tools

log = logging.getLogger("catalog")

CATALOG_PATH = Path(__file__).resolve().parent / "catalog.yaml"
GUIDES_PATH = Path(__file__).resolve().parent / "tool_guides.yaml"
AUTO = "auto"


# MCP 에서 받아온 tool — refresh() 전에는 비어 있다.
# 서버 장애로 빠진 tool 은 여기 없으므로 routing 에서 자동으로 "unavailable" 이 된다.
TOOLS_BY_NAME: dict = {}
VERSION = 0  # refresh 마다 증가 — agent 그래프 캐시 키에 포함해 낡은 tool 객체를 버린다

def _load_catalog() -> tuple[list[dict], list[dict], set[str], dict[str, str], list[dict], list[str]]:
    raw = yaml.safe_load(CATALOG_PATH.read_text(encoding="utf-8"))
    groups, agents, ui_tools = raw["groups"], raw["agents"], set(raw.get("ui_tools") or [])
    areas = [str(a) for a in raw.get("areas") or []]
    for g in groups:
        g["tags"] = [str(t) for t in g.get("tags") or []]
    labels, portals = raw.get("tool_labels") or {}, raw.get("portals") or []
    group_ids = {g["id"] for g in groups}
    reserved = [gid for gid in group_ids if gid.startswith(mcp_store.GROUP_PREFIX)]
    if reserved:
        raise ValueError(f"'{mcp_store.GROUP_PREFIX}' 로 시작하는 group id 는 화면 등록 서버용: {', '.join(reserved)}")
    for a in agents:
        for gid in a["allowed_groups"] + a["default_groups"]:
            if gid not in group_ids:
                raise ValueError(f"agent '{a['id']}': unknown group '{gid}'")
        if not set(a["default_groups"]) <= set(a["allowed_groups"]):
            raise ValueError(f"agent '{a['id']}': default_groups 는 allowed_groups 안에 있어야 함")
    in_group = {n for g in groups for n in g["tools"]} & ui_tools
    if in_group:
        raise ValueError(f"화면 전용 tool 은 group 에 넣을 수 없음 (LLM 에 묶이면 안 됨): {', '.join(sorted(in_group))}")
    return groups, agents, ui_tools, labels, portals, areas


_STATIC_GROUPS, AGENTS, UI_TOOLS, _STATIC_LABELS, PORTALS, AREAS = _load_catalog()
AGENTS_BY_ID = {a["id"]: a for a in AGENTS}
FALLBACK_AGENT = AGENTS[0]["id"]


def reload_yaml() -> None:
    """catalog.yaml · tool_guides.yaml 을 다시 읽는다 — 서버 재시작 없이 group · agent · 안내를 고칠 수 있게.
    다른 모듈이 import 한 참조가 유효하도록 제자리에서 바꾼다. yaml 이 잘못됐으면 기존 값을 유지한다."""
    global _STATIC_GROUPS, _STATIC_LABELS, FALLBACK_AGENT
    try:
        groups, agents, ui_tools, labels, portals, areas = _load_catalog()
        guides = yaml.safe_load(GUIDES_PATH.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001
        log.exception("catalog.yaml / tool_guides.yaml 다시 읽기 실패 — 기존 설정 유지")
        return
    _STATIC_GROUPS, _STATIC_LABELS = groups, labels
    AGENTS[:] = agents
    AGENTS_BY_ID.clear()
    AGENTS_BY_ID.update({a["id"]: a for a in agents})
    FALLBACK_AGENT = agents[0]["id"]
    UI_TOOLS.clear()
    UI_TOOLS.update(ui_tools)
    PORTALS[:] = portals
    AREAS[:] = areas
    TOOL_GUIDES.clear()
    TOOL_GUIDES.update(guides)

# 아래는 rebuild() 가 제자리에서 갱신한다 (yaml group + 화면에서 등록한 서버 group)
GROUPS: list[dict] = []
GROUPS_BY_ID: dict[str, dict] = {}
GROUPED_TOOLS: list[str] = []
TOOL_LABELS: dict[str, str] = {}   # tool 이름 → 화면 표시명 (없으면 이름 그대로)
_GROUP_OF: dict[str, str] = {}     # tool → 소속 group (화면 분류용, 여러 group 에 속하면 첫 번째)


def _imported_groups() -> list[dict]:
    return [
        {"id": mcp_store.group_id(s["id"]), "name": s["name"], "description": s.get("description") or s["url"],
         "tags": [str(t) for t in s.get("tags") or []],
         "tools": [n for n in s.get("tools") or [] if n not in UI_TOOLS],
         "imported": True, "default_on": s.get("default_on", True)}
        for s in mcp_store.list_items() if s.get("enabled", True)
    ]


def rebuild() -> None:
    """group · 표시명을 다시 만든다 — 화면에서 MCP 서버를 등록 · 수정 · 삭제한 뒤 refresh() 가 부른다."""
    servers = mcp_store.list_items()
    GROUPS[:] = _STATIC_GROUPS + _imported_groups()
    GROUPS_BY_ID.clear()
    GROUPS_BY_ID.update({g["id"]: g for g in GROUPS})
    GROUPED_TOOLS[:] = list(dict.fromkeys(n for g in GROUPS for n in g["tools"]))
    TOOL_LABELS.clear()
    for srv in servers:
        TOOL_LABELS.update({k: v for k, v in (srv.get("labels") or {}).items() if v})
    TOOL_LABELS.update(_STATIC_LABELS)  # yaml 이 우선
    _GROUP_OF.clear()
    for g in GROUPS:
        for n in g["tools"]:
            _GROUP_OF.setdefault(n, g["id"])


rebuild()

# tool 이름 → 프롬프트 안내 (차트 태그 · 결과 정리 방식). 켜진 tool 것만 프롬프트에 붙는다.
TOOL_GUIDES: dict[str, str] = yaml.safe_load(GUIDES_PATH.read_text(encoding="utf-8")) or {}
_unknown_guides = [n for n in TOOL_GUIDES if n not in _GROUP_OF]
if _unknown_guides:
    log.warning("tool_guides.yaml 에 group 에 없는 tool 이 있음 — 프롬프트에 붙지 않음: %s", ", ".join(_unknown_guides))


def _check_tools() -> None:
    """yaml 과 MCP 가 어긋나면 기동은 하되 경고를 남긴다."""
    # 서버가 내려가 있으면 refresh 마다 반복되므로 한 줄로 모아서 남긴다
    missing = [n for n in GROUPED_TOOLS if n not in TOOLS_BY_NAME]
    if missing:
        log.warning("catalog.yaml 의 tool %d개를 MCP 에서 찾지 못함 — 사용 불가로 취급: %s", len(missing), ", ".join(missing))
    ui_missing = sorted(n for n in UI_TOOLS if n not in TOOLS_BY_NAME)
    if ui_missing:
        log.warning("화면 전용 tool %d개를 MCP 에서 찾지 못함 — 해당 차트/대시보드 API 는 503: %s", len(ui_missing), ", ".join(ui_missing))
    ungrouped = [n for n in TOOLS_BY_NAME if n not in _GROUP_OF and n not in UI_TOOLS]
    if ungrouped:
        log.warning("어떤 group 에도 없는 MCP tool — agent 가 쓰려면 catalog.yaml group 에 추가하거나 화면(MCP)에서 선택: %s", ", ".join(ungrouped))


async def refresh() -> dict:
    """catalog.yaml 을 다시 읽고 MCP 서버에서 tool 을 다시 받아온다. 서버가 전부 죽어 있어도 예외 없이 빈 목록으로 동작."""
    global VERSION
    reload_yaml()
    rebuild()
    tools = session_tools.wrap_all(await mcp_registry.load_tools(always_keep=UI_TOOLS))
    TOOLS_BY_NAME.clear()
    TOOLS_BY_NAME.update(tools)
    VERSION += 1
    _check_tools()
    log.info("MCP tool %d개 로드 (%s)", len(tools),
             ", ".join(f"{s['name']}={s['status']}" for s in mcp_registry.status()))
    return {"tools": len(tools), "servers": mcp_registry.status()}


def group_tools(group_ids) -> list[str]:
    """group 들의 tool 을 정의 순서대로, 중복 없이."""
    seen: dict[str, None] = {}
    for gid in group_ids:
        for name in GROUPS_BY_ID[gid]["tools"] if gid in GROUPS_BY_ID else []:
            seen.setdefault(name)
    return list(seen)


def agent_groups(agent_id: str, key: str) -> list[str]:
    """key = allowed_groups | default_groups. include_imported 면 화면에서 등록한 서버 group 을 덧붙인다."""
    a = AGENTS_BY_ID[agent_id]
    ids = list(a[key])
    if a.get("include_imported"):
        ids += [g["id"] for g in GROUPS if g.get("imported") and (key == "allowed_groups" or g["default_on"])]
    return ids


def agent_pool(agent_id: str) -> list[str]:
    """agent 가 쓸 수 있는 tool 전체 (allowed_groups)."""
    return group_tools(agent_groups(agent_id, "allowed_groups"))


def agent_defaults(agent_id: str) -> list[str]:
    return group_tools(agent_groups(agent_id, "default_groups"))


def _server_of(name: str):
    return next((s["name"] for s in mcp_registry.status() if name in s["tools"]), None)


def tool_info(name: str) -> dict:
    tool = TOOLS_BY_NAME.get(name)
    # docstring 첫 문단만 — Args 등은 화면에 불필요
    desc = (tool.description or "").strip().split("\n\n")[0].split("\n")[0] if tool else ""
    gid = _GROUP_OF.get(name)
    return {
        "name": name, "label": TOOL_LABELS.get(name, name),
        "group": gid, "category": GROUPS_BY_ID[gid]["name"] if gid else "기타",
        "description": desc, "available": tool is not None, "server": _server_of(name),
    }


def _agent_view(a: dict) -> dict:
    return {
        "id": a["id"], "name": a["name"], "description": a["description"],
        "tools": agent_pool(a["id"]),
        "allowed_groups": agent_groups(a["id"], "allowed_groups"),
        "default_groups": agent_groups(a["id"], "default_groups"),
    }


async def meta() -> dict:
    auto = {
        "id": AUTO, "name": "자동 선택", "description": "질문을 보고 agent 를 고릅니다",
        "tools": GROUPED_TOOLS, "allowed_groups": [g["id"] for g in GROUPS], "default_groups": [],
    }
    # 그룹에 없는 MCP tool 도 보여준다 (group=None, "기타") — catalog.yaml 에 추가하라는 신호
    names = GROUPED_TOOLS + [n for n in TOOLS_BY_NAME if n not in _GROUP_OF and n not in UI_TOOLS]
    return {
        "agents": [auto] + [_agent_view(a) for a in AGENTS],
        "groups": GROUPS,
        "tools": [tool_info(n) for n in names],
        "portals": PORTALS,
        "areas": AREAS,
        "mcp_servers": mcp_registry.status(),
    }
