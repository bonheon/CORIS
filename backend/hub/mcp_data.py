"""
화면 데이터 호출 — 차트 · 대시보드 API 가 MCP 의 화면 전용 tool(catalog.yaml ui_tools)을 부른다.

허브는 데이터 코드를 갖지 않는다. LLM 용 tool 과 같은 MCP 연결(catalog.TOOLS_BY_NAME)을 쓰므로
mcp_servers.yaml 의 주소만 바꾸면 화면 데이터도 같이 회사 서버로 넘어간다.
"""
import json
import logging
from typing import Any

from fastapi import HTTPException

from hub import catalog

log = logging.getLogger("mcp_data")


async def call(name: str, **args: Any) -> Any:
    """MCP tool 을 호출해 JSON 결과를 돌려준다. 서버가 없거나 실패하면 503 — 화면이 원인을 보여줄 수 있게."""
    tool = catalog.TOOLS_BY_NAME.get(name)
    if tool is None:
        raise HTTPException(503, f"MCP tool '{name}' 를 지금 쓸 수 없습니다 (서버 연결 확인)")
    try:
        result = await tool.ainvoke({k: v for k, v in args.items() if v is not None})
    except Exception as e:  # noqa: BLE001
        log.exception("MCP call failed: %s", name)
        raise HTTPException(502, f"MCP tool '{name}' 호출 실패: {str(e)[:200]}") from e
    text = result if isinstance(result, str) else "".join(
        b.get("text", "") if isinstance(b, dict) else str(b) for b in result)
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise HTTPException(502, f"MCP tool '{name}' 응답이 JSON 이 아닙니다: {text[:200]}") from e
