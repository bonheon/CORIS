"""
화면 카드 데이터 — MCP 의 화면 전용 tool(catalog.yaml ui_tools)을 그대로 중계한다.

    GET /api/ui/{tool}?arg=value&...
    GET /api/ui/result/{id}          큰 tool 결과의 원본 (hub/result_store.py) — run_python 의 load_ref 가 받는다

카드를 새로 붙일 때 백엔드 라우터를 만들 필요 없이 MCP 서버에 ui_* tool 을 추가하고
catalog.yaml 의 ui_tools 에 이름만 등록하면 된다. 등록되지 않은 tool 은 404 — LLM 용 tool 을
화면에서 임의로 부르지 못하게.
"""
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from hub import catalog, result_store
from hub.mcp_data import call

router = APIRouter(prefix="/api/ui", tags=["ui"])


def _coerce(v: str):
    """쿼리스트링은 전부 문자열 — 정수처럼 보이면 정수로 넘긴다 (MCP 입력 스키마 검증 대비)."""
    return int(v) if v.lstrip("-").isdigit() else v


@router.get("/{name}")
async def ui_data(name: str, request: Request):
    if name not in catalog.UI_TOOLS:
        raise HTTPException(404, f"화면 전용 tool 이 아닙니다: {name}")
    return await call(name, **{k: _coerce(v) for k, v in request.query_params.items()})


@router.get("/result/{rid}")
def stored_result(rid: str):
    """분리해 둔 tool 결과 원본을 그대로 — JSON 이면 JSON, 아니면 텍스트."""
    item = result_store.load(rid)
    if item is None:
        raise HTTPException(404, "저장된 결과가 없습니다 (보관 기간이 지났거나 잘못된 id) — tool 을 다시 호출하세요")
    text = item["text"]
    is_json = text.lstrip()[:1] in ("{", "[")
    return Response(text, media_type="application/json" if is_json else "text/plain; charset=utf-8")
