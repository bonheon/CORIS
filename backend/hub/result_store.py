"""
큰 tool 결과 분리 — 결과가 INLINE_CHARS 를 넘으면 원본은 파일로 두고 LLM 에는 줄인 결과 + data_ref 만 넘긴다.

    tool 결과(원본, 수만 행)
        ├─ 원본  → data/results/<id>.json        ← run_python 의 load_ref("result/<id>") 가 전부 읽는다
        └─ LLM  → {"data_ref": "result/<id>", ... 건수 · 열 · 숫자 열 통계 · 앞 3행 ...}

LLM 이 원본을 직접 읽지 않으므로 길이 한도(429)에 걸리지 않고, 집계 · 필터는 코드가 전체 행으로 하므로
행 수를 잘라 넘길 때 생기는 누락이 없다. MCP tool 을 고칠 필요 없이 모든 LLM 용 tool 에 적용된다
(catalog.refresh 가 wrap_all 로 감싼다). 화면 전용(ui_*) tool 과 run_python 은 감싸지 않는다.

줄이는 규칙 (shrink)
  - 길이가 PREVIEW_ROWS 를 넘는 list → {"_rows", "_columns", "_stats", "_preview"} 로 바꾼다
  - 그 밖의 값(tool 이 스스로 넣은 요약 · 한계값 등)은 그대로 둔다 — tool 의 요약은 살리고 큰 덩어리만 뺀다
  - 그래도 길면 미리보기 행 수 → 통계 순으로 줄이고, JSON 이 아니면 앞부분만 남긴다
"""
import json
import logging
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any, Optional

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, StructuredTool

from hub import store

log = logging.getLogger("result_store")

RESULT_DIR = Path(os.getenv("RESULT_DIR") or store.DATA_PATH.parent / "results")
INLINE_CHARS = int(os.getenv("RESULT_INLINE_CHARS", "8000"))   # 이보다 긴 결과만 분리한다 (약 3~4천 토큰)
COMPACT_CHARS = int(os.getenv("RESULT_COMPACT_CHARS", "2500"))  # 줄인 결과의 목표 길이 — trace 저장 한도(3000)보다 작게
TTL_SEC = float(os.getenv("RESULT_TTL_HOURS", "24")) * 3600
PREVIEW_ROWS = 3
STAT_COLUMNS = 12
TEXT_HEAD = 1500
REF_PREFIX = "result/"
SKIP = {"run_python"}  # 출력 길이를 스스로 제한하고, 분리하면 traceback · 결과물 태그가 잘린다

_ID_RE = re.compile(r"^r_[0-9a-f]{16}$")
_last_sweep = 0.0

NOTE = ("결과가 커서 원본은 따로 저장했습니다. 여기 보이는 것은 건수 · 통계 · 앞 몇 행뿐입니다. "
        "행 단위 값 · 집계 · 필터가 필요하면 run_python 에서 load_ref(\"{ref}\") 로 원본 전체를 받아 계산하세요 "
        "(_rows 로 표시된 자리가 원본에서는 list 입니다 — pd.DataFrame(load_ref(ref){path}) ). "
        "미리보기만 보고 전체를 추정하지 마세요. run_python 을 쓸 수 없으면 조건을 좁혀 다시 조회하거나, "
        "전체 분석에는 Python 실행 tool 이 필요하다고 사용자에게 알리세요.")


# ── 줄이기 ───────────────────────────────────────────────────

def _num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _stats(rows: list[dict], columns: list[str]) -> dict:
    out = {}
    for c in columns:
        vals = [r[c] for r in rows if isinstance(r, dict) and _num(r.get(c))]
        if vals and len(out) < STAT_COLUMNS:
            out[c] = {"min": min(vals), "max": max(vals), "mean": round(sum(vals) / len(vals), 4)}
    return out


def _shrink(obj: Any, preview: int, stats: bool, paths: list[str], path: str = "") -> Any:
    if isinstance(obj, dict):
        return {k: _shrink(v, preview, stats, paths, f'{path}["{k}"]') for k, v in obj.items()}
    if isinstance(obj, list):
        if len(obj) <= PREVIEW_ROWS:
            return [_shrink(v, preview, stats, paths, f"{path}[{i}]") for i, v in enumerate(obj)]
        paths.append(path)  # 미리보기 행 안쪽의 list 는 버리는 목록으로 받는다 (아래 _preview)
        out: dict = {"_rows": len(obj)}
        if all(isinstance(r, dict) for r in obj[:50]):
            cols = list(dict.fromkeys(k for r in obj[:50] for k in r))
            out["_columns"] = cols
            if stats and (st := _stats(obj, cols)):
                out["_stats"] = st
        elif stats and all(_num(v) for v in obj[:50]):
            vals = [v for v in obj if _num(v)]
            out["_stats"] = {"min": min(vals), "max": max(vals), "mean": round(sum(vals) / len(vals), 4)}
        if preview:
            out["_preview"] = [_shrink(v, min(preview, 1), False, [], f"{path}[{i}]") for i, v in enumerate(obj[:preview])]
        return out
    if isinstance(obj, str) and len(obj) > 400:
        return obj[:400] + f"…(전체 {len(obj)}자)"
    return obj


def compact(text: str, ref: str) -> str:
    """원본 text → LLM 에 넘길 줄인 결과. data_ref 를 맨 앞에 둔다 (trace 가 잘려도 남도록)."""
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, RecursionError):
        data = None
    if isinstance(data, (dict, list)):
        for preview, stats in ((PREVIEW_ROWS, True), (1, True), (1, False), (0, False)):
            paths: list[str] = []
            body = _shrink(data, preview, stats, paths)
            out = json.dumps({"data_ref": ref, "_truncated": True, "_size_chars": len(text),
                              "_note": NOTE.format(ref=ref, path=paths[0] if paths else ""),
                              "result": body}, ensure_ascii=False)
            if len(out) <= COMPACT_CHARS + len(NOTE):
                return out
    return json.dumps({"data_ref": ref, "_truncated": True, "_size_chars": len(text),
                       "_note": NOTE.format(ref=ref, path=""),
                       "head": text[:TEXT_HEAD]}, ensure_ascii=False)


# ── 저장 · 읽기 ──────────────────────────────────────────────

def _sweep() -> None:
    """TTL 지난 파일 정리 — 저장할 때 10분에 한 번."""
    global _last_sweep
    now = time.time()
    if now - _last_sweep < 600:
        return
    _last_sweep = now
    for p in RESULT_DIR.glob("r_*.json"):
        try:
            if now - p.stat().st_mtime > TTL_SEC:
                p.unlink()
        except OSError:
            pass


def save(text: str, tool: str = "", session_id: str = "") -> str:
    """원본을 저장하고 data_ref('result/<id>') 를 돌려준다."""
    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    _sweep()
    rid = "r_" + uuid.uuid4().hex[:16]
    (RESULT_DIR / f"{rid}.json").write_text(
        json.dumps({"tool": tool, "session_id": session_id, "created_at": store.now_iso(), "text": text},
                   ensure_ascii=False), encoding="utf-8")
    return REF_PREFIX + rid


def load(rid: str) -> Optional[dict]:
    """{"tool", "session_id", "created_at", "text"} — 없거나 id 형식이 틀리면 None."""
    if not _ID_RE.match(rid):
        return None
    path = RESULT_DIR / f"{rid}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


# ── tool 감싸기 ──────────────────────────────────────────────

def _text(result: Any) -> Optional[str]:
    if isinstance(result, str):
        return result
    if isinstance(result, list) and all(isinstance(b, dict) and b.get("type") == "text" for b in result):
        return "".join(b.get("text", "") for b in result)
    return None  # 이미지 등 — 건드리지 않는다


def offload(result: Any, tool: str, session_id: str = "") -> Any:
    """결과가 크면 저장하고 줄인 결과를, 아니면 그대로 돌려준다."""
    text = _text(result)
    if text is None or len(text) <= INLINE_CHARS:
        return result
    ref = save(text, tool, session_id)
    out = compact(text, ref)
    log.info("tool 결과 분리: %s %d자 → %d자 (%s)", tool, len(text), len(out), ref)
    return out


def wrap(tool: BaseTool) -> BaseTool:
    async def _arun(config: RunnableConfig, **kwargs):
        sid = (config.get("configurable") or {}).get("session_id") or ""
        return offload(await tool.ainvoke(kwargs, config), tool.name, sid)

    return StructuredTool(name=tool.name, description=tool.description, args_schema=tool.args_schema, coroutine=_arun)


def wrap_all(tools: dict[str, BaseTool], skip: set[str]) -> dict[str, BaseTool]:
    """skip — 화면 전용 tool(전체 데이터를 화면 · load_ref 가 그대로 받아야 한다)."""
    return {name: t if name in skip or name in SKIP else wrap(t) for name, t in tools.items()}
