"""
큰 tool 결과 자동 보관 — 데이터는 저장소(hub/storage.py)에, LLM 에는 요약 + data_ref 만.

tool 결과가 OFFLOAD_CHARS 자를 넘고 표(hub/tabular.py)로 읽히면, OFFLOAD_MIN_ROWS 행 이상인 표를 저장소에 넣고
LLM 에는 행 수 · 열 구조 · 열별 통계 · 앞 몇 행 · data_ref 를 돌려준다. LLM 은 계산이 필요하면
run_python 에서 df = load_ref("dr_...") 로 원본을 불러 pandas 로 계산한다 (값을 눈으로 읽어 옮기지 않게).

작은 결과는 그대로 넘기되, 공통 형식 JSON(columns · rows) 이면 '요약 + 마크다운 표' 로 바꿔 넘긴다 (토큰 · 가독성).
표로 볼 수 없는 결과는 그대로. 회사 MCP 서버는 고칠 필요가 없다 (Coris 가 감싼다).

저장 key: tool-results/<ref>.json.gz — {"ref", "tool", "args", "session", "created_at", "table"}
data_ref 는 그 대화(session)에서만 불러올 수 있다 (GET /api/hub/data/{ref}, X-Coris-Session 헤더 확인).
"""
import gzip
import json
import logging
import os
import re
import uuid
from typing import Any, Optional

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, StructuredTool

from hub import storage, store, tabular

log = logging.getLogger("offload")

ENABLED = os.getenv("OFFLOAD_ENABLED", "1") == "1"
MIN_CHARS = int(os.getenv("OFFLOAD_CHARS", "6000"))        # 이보다 짧은 결과는 그대로
MIN_ROWS = int(os.getenv("OFFLOAD_MIN_ROWS", "20"))        # 이보다 작은 표는 미리보기에 그대로 둔다
PREVIEW_ROWS = int(os.getenv("OFFLOAD_PREVIEW_ROWS", "5"))
EXCLUDE = {x.strip() for x in os.getenv("OFFLOAD_EXCLUDE", "run_python").split(",") if x.strip()}
PREFIX = "tool-results/"
_REF = re.compile(r"^dr_[0-9a-f]{12}$")
_SID = re.compile(r"[^A-Za-z0-9_-]")   # code interpreter 커널 세션 이름 규칙과 같게


def session_key(sid: str) -> str:
    return _SID.sub("_", sid or "default")[:64] or "default"


def _key(ref: str) -> str:
    return f"{PREFIX}{ref}.json.gz"


def _text(result: Any) -> str:
    """MCP tool 결과(문자열 · content block 목록) → 문자열."""
    if isinstance(result, str):
        return result
    if isinstance(result, list):
        return "\n".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in result)
    return str(result)


def save(table: dict, tool: str, args: dict, session: str) -> str:
    ref = f"dr_{uuid.uuid4().hex[:12]}"
    rec = {"ref": ref, "tool": tool, "args": args, "session": session_key(session),
           "created_at": store.now_iso(), "table": table}
    storage.put(_key(ref), gzip.compress(json.dumps(rec, ensure_ascii=False).encode()), "application/gzip")
    return ref


def load(ref: str) -> Optional[dict]:
    if not _REF.match(ref):
        return None
    raw = storage.get(_key(ref))
    return json.loads(gzip.decompress(raw)) if raw else None


def _preview(tool: str, text: str, rest: str, stored: list[tuple[str, dict]], small: list[dict]) -> str:
    total = sum(len(t["rows"]) for _, t in stored)
    out = [f"[큰 결과 보관] {tool} 결과 원문 {len(text):,}자 · 표 {len(stored)}개({total:,}행)는 저장소에 보관했습니다. "
           "아래는 구조 요약입니다."]
    summary, extra = tabular.json_head(rest)
    if summary:
        out += ["", f"요약: {summary}"[:800]]
    if extra:
        out += [f"부가 정보: {json.dumps(extra, ensure_ascii=False)}"[:800]]
    for ref, t in stored:
        n = len(t["rows"])
        if t["name"] in ("data", "") or t["name"].startswith("table_"):
            t["name"] = tool
        out += ["", f"## 표 '{t['name']}' — data_ref=\"{ref}\" · {n:,}행 × {len(t['columns'])}열",
                "열 (이름 · 타입 · 통계):", *tabular.column_summary(t),
                f"앞 {min(PREVIEW_ROWS, n)}행 (미리보기 — 전체가 아님):", tabular.to_markdown(t, t["rows"][:PREVIEW_ROWS])]
    for t in small:
        out += ["", f"## 표 '{t['name']}' (전체 {len(t['rows'])}행)", tabular.to_markdown(t, labels=True)]
    refs = ", ".join(f'load_ref("{r}")' for r, _ in stored)
    out += ["", "사용 방법:",
            f"- 집계 · 평균 · 순위 · 필터 · 비교 · 추이 등 행을 계산해야 하는 질문은 run_python 에서 df = {refs} 로 "
            "원본을 불러 pandas 로 계산한다. 열 이름은 위 목록의 `백틱` 안 이름 그대로 쓴다 (옆의 한글은 표시용).",
            "- 미리보기 행이나 통계 값을 보고 다른 수치를 어림하거나, 값을 코드에 옮겨 적지 않는다.",
            "- 이 표에 필요한 행이 모두 들어 있다. 장비 · 기간별로 나눠 tool 을 다시 부르지 말고 df 를 필터 · groupby 한다.",
            "- 추이 · 증감은 첫 값과 끝 값이 아니라 구간 평균(예: 기간 전반 vs 후반, 주별 평균)과 변화율로 판단한다.",
            "- 위 통계(최소 · 평균 · 최대, 값 분포)만으로 답할 수 있는 질문은 그대로 답해도 된다.",
            "- run_python 을 쓸 수 없으면 조건(장비 · 기간 · Lot 등)을 좁혀 tool 을 다시 조회한다."]
    return "\n".join(out)


def _small_view(text: str) -> str:
    """작은 결과 — 공통 형식 JSON(columns · rows) 이면 LLM 이 읽기 좋게 '요약 + 표' 로 바꾼다.
    JSON 은 행마다 따옴표 · 괄호가 붙어 토큰이 많고 읽기 어렵다. 다른 형식(차트 태그 · data_ref 를 담은 JSON 등)은 그대로."""
    s = text.strip()
    if not (s.startswith("{") and '"columns"' in s and '"rows"' in s):
        return text
    try:
        tables, rest = tabular.parse(s)
    except Exception:  # noqa: BLE001
        return text
    if len(tables) != 1:
        return text
    t = tables[0]
    summary, extra = tabular.json_head(rest)
    out = [summary] if summary else []
    if extra:
        out.append(f"부가 정보: {json.dumps(extra, ensure_ascii=False)}")
    out.append(tabular.to_markdown(t, labels=True) if t["rows"] else "(행 없음)")
    return "\n\n".join(out)


def maybe_offload(text: str, tool: str, args: dict, session: str) -> str:
    if not ENABLED:
        return text
    if len(text) < MIN_CHARS:
        return _small_view(text)
    try:
        tables, rest = tabular.parse(text)
    except Exception:  # noqa: BLE001 — 변환 실패면 원문 그대로 (기존 동작)
        log.exception("tool '%s' 결과 표 변환 실패 — 원문 그대로 전달", tool)
        return text
    big = [t for t in tables if len(t["rows"]) >= MIN_ROWS]
    if not big:
        return text
    try:
        stored = [(save(t, tool, args, session), t) for t in big]
    except Exception:  # noqa: BLE001 — 저장소 장애면 원문 그대로
        log.exception("tool '%s' 결과 저장 실패 — 원문 그대로 전달", tool)
        return text
    small = [t for t in tables if len(t["rows"]) < MIN_ROWS]
    preview = _preview(tool, text, rest, stored, small)
    log.info("tool '%s' 결과 보관: %s (%d자 → 요약 %d자)", tool,
             ", ".join(f"{r}={len(t['rows'])}행" for r, t in stored), len(text), len(preview))
    return preview


def _schema(tool: BaseTool) -> dict:
    s = tool.args_schema
    if s is None:
        return {"type": "object", "properties": {}}
    return s if isinstance(s, dict) else s.model_json_schema()


def wrap(tool: BaseTool) -> BaseTool:
    async def _arun(config: RunnableConfig, **kwargs):
        # configurable(session_id) 만 넘긴다 — callbacks 까지 넘기면 안쪽 tool 실행이 화면에 한 번 더 잡힌다
        result = await tool.ainvoke(kwargs, config={"configurable": config.get("configurable") or {}})
        sid = (config.get("configurable") or {}).get("session_id") or "default"
        return maybe_offload(_text(result), tool.name, kwargs, sid)

    return StructuredTool(name=tool.name, description=tool.description, args_schema=_schema(tool), coroutine=_arun)


def wrap_all(tools: dict[str, BaseTool], skip: set[str]) -> dict[str, BaseTool]:
    """skip(화면 전용 tool 등) · EXCLUDE 는 감싸지 않는다."""
    return {n: t if n in skip or n in EXCLUDE else wrap(t) for n, t in tools.items()}
