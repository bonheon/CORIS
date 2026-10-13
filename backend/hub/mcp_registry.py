"""
MCP 서버 레지스트리 — 서버들에서 tool 을 받아온다.

서버 출처는 두 가지다.
  - yaml : mcp_servers.yaml (배포 설정). tools 를 적지 않으면 서버의 tool 전부.
  - hub  : 화면에서 등록한 서버 (hub/mcp_store.py). 사용자가 고른 tool 만.

서버마다 따로 받아오므로 한 서버가 죽어도 나머지는 살아 있고,
죽은 서버의 tool 은 목록에서 빠져 routing 단계에서 "unavailable" 로 처리된다.
받아온 tool 은 langchain BaseTool 이라 bind_tools / ToolNode 에 그대로 들어간다
(호출 시 adapter 가 MCP call_tool 을 대신 보낸다).
"""
import asyncio
import inspect
import logging
import os
import re
from pathlib import Path
from typing import Any, Iterable, Optional

import yaml
from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient

from hub import mcp_store
from hub.store import now_iso

log = logging.getLogger("mcp")

CONFIG_PATH = Path(__file__).resolve().parent.parent / "mcp_servers.yaml"
LOAD_TIMEOUT_S = float(os.getenv("MCP_LOAD_TIMEOUT_SEC", "10"))

_ENV_RE = re.compile(r"\$\{(\w+)(?::-([^}]*))?\}")


def expand(value: Any) -> Any:
    """${VAR} / ${VAR:-default} 치환 (문자열 · dict · list 재귀)."""
    if isinstance(value, str):
        return _ENV_RE.sub(lambda m: os.getenv(m.group(1)) or (m.group(2) or ""), value)
    if isinstance(value, dict):
        return {k: expand(v) for k, v in value.items()}
    if isinstance(value, list):
        return [expand(v) for v in value]
    return value


def is_on(value: Any) -> bool:
    return str(value).lower() in ("true", "1", "yes")


def yaml_servers() -> dict[str, dict]:
    """mcp_servers.yaml 원문 (치환 전) — 꺼진 서버 포함."""
    raw = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
    return raw.get("servers") or {}


def load_config() -> dict[str, tuple[dict, Optional[set[str]], str]]:
    """켜진 서버만 {name: (connection, 가져올 tool 이름 | None=전부, 출처)}. yaml 이 앞 — 이름이 겹치면 yaml 이 이긴다."""
    servers: dict[str, tuple[dict, Optional[set[str]], str]] = {}
    for name, conf in yaml_servers().items():
        conf = expand(conf)
        allow = conf.pop("tools", None)
        if not is_on(conf.pop("enabled", True)):
            continue
        servers[name] = (conf, set(allow) if allow else None, "yaml")
    for rec in mcp_store.list_items():
        if rec.get("enabled", True) and rec["id"] not in servers:
            servers[rec["id"]] = (expand(mcp_store.connection(rec)), set(rec.get("tools") or []), "hub")
    return servers


# 마지막으로 받아온 결과 — status 는 /api/hub/meta 로 화면에 노출
_status: dict[str, dict] = {}


def _root_cause(e: BaseException) -> BaseException:
    """anyio TaskGroup 이 감싼 ExceptionGroup 에서 실제 원인(연결 거부 등)을 꺼낸다."""
    while getattr(e, "exceptions", None):
        e = e.exceptions[0]
    return e


def _error(e: BaseException) -> str:
    cause = _root_cause(e)
    return "timeout" if isinstance(cause, asyncio.TimeoutError) else f"{type(cause).__name__}: {cause}"


async def _load_one(client: MultiServerMCPClient, name: str) -> list[BaseTool]:
    return await asyncio.wait_for(client.get_tools(server_name=name), LOAD_TIMEOUT_S)


async def load_tools(always_keep: Iterable[str] = ()) -> dict[str, BaseTool]:
    """모든 서버에서 tool 을 받아 {tool 이름: tool}.

    always_keep: 고른 tool 목록과 상관없이 받아 둘 이름 — 화면 전용 tool(ui_*) 은 LLM 에 묶이지 않으므로
    사용자가 고르지 않아도 카드가 동작하도록 같이 받는다.
    """
    servers = load_config()
    keep = set(always_keep)
    client = MultiServerMCPClient({n: s[0] for n, s in servers.items()})
    names = list(servers)
    results = await asyncio.gather(*(_load_one(client, n) for n in names), return_exceptions=True)

    tools: dict[str, BaseTool] = {}
    status: dict[str, dict] = {}
    for name, res in zip(names, results):
        conn, allow, source = servers[name]
        base = {"name": name, "url": conn.get("url") or conn.get("command", ""), "source": source, "checked_at": now_iso()}
        if isinstance(res, BaseException):
            err = _error(res)
            log.warning("MCP '%s' (%s) 연결 실패 — %s", name, base["url"], err[:200])
            status[name] = base | {"status": "down", "tools": [], "offered": 0, "error": err[:300]}
            continue
        mine = []
        for t in res:
            if allow is not None and t.name not in allow and t.name not in keep:
                continue
            if t.name in tools:
                log.warning("tool '%s' 가 여러 MCP 서버에 있음 — '%s' 것은 무시", t.name, name)
                continue
            tools[t.name] = t
            mine.append(t.name)
        if allow:
            missing = sorted(allow - {t.name for t in res})
            if missing:
                log.warning("MCP '%s' 에 등록한 tool 이 서버에 없음: %s", name, ", ".join(missing))
        status[name] = base | {"status": "ok", "tools": mine, "offered": len(res), "error": None}

    _status.clear()
    _status.update(status)
    return tools


def status() -> list[dict]:
    return list(_status.values())


# ── 서버의 tool 목록 미리 보기 (등록 전 list_tools) ─────────────────

def _params(tool: BaseTool) -> list[dict]:
    schema = tool.args_schema
    if schema is not None and not isinstance(schema, dict):
        schema = schema.model_json_schema()
    schema = schema or {}
    required = set(schema.get("required") or [])
    return [
        {"name": k, "type": v.get("type") or "any", "required": k in required, "description": v.get("description", "")}
        for k, v in (schema.get("properties") or {}).items()
    ]


async def probe(conn: dict) -> list[dict]:
    """접속 정보로 서버에 붙어 tool 목록만 받아온다 (저장 · 로드 없음). 실패하면 ConnectionError."""
    client = MultiServerMCPClient({"probe": expand(conn)})
    try:
        tools = await _load_one(client, "probe")
    except Exception as e:  # noqa: BLE001 — 원인을 그대로 화면에 보여준다
        raise ConnectionError(_error(e)[:300]) from e
    return [{"name": t.name, "description": inspect.cleandoc(t.description or ""), "params": _params(t)} for t in tools]
