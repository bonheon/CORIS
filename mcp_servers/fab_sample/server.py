"""
FAB 샘플 MCP 서버 — Lot 공정 진행 이력 · 장비별 일 효율 (각 약 1,000행 CSV, gen_data.py 로 생성).

결과는 Coris tool 결과 공통 형식(JSON) 으로 돌려준다 — 회사 MCP tool 표준안:
    {"summary": "한두 줄 요약",
     "columns": [{"name": "eqp_id", "label": "장비", "type": "string|int|float|date|datetime", "unit": "%"}],
     "rows": [[...], ...],            # 조건에 맞는 전체 행 (요약 · 일부만 주지 않는다)
     "meta": {"source", "query", "row_count", "truncated", "as_of"}}
LLM 이 질문에서 뽑은 인자(Lot · 제품 · 공정 영역 · step · 장비 · 상태 · 기간)로 걸러서 조회한다.
인자를 비우면 그 조건으로는 거르지 않는다 — 조건 없이 부르면 전체(약 1,000행)가 나온다 (큰 결과 시험용).

실행 (backend venv 사용):
    cd mcp_servers/fab_sample && python gen_data.py    # 데이터가 없을 때 한 번
    python server.py                                     # http://localhost:8130/mcp
"""
import csv
import json
import logging
import os
from pathlib import Path
from typing import Optional

from mcp.server.fastmcp import FastMCP

log = logging.getLogger("fab_sample_mcp")

HOST = os.getenv("MCP_HOST", "127.0.0.1")
PORT = int(os.getenv("MCP_PORT", "8130"))
DATA = Path(__file__).resolve().parent / "data"
AS_OF = "2026-11-19 09:00"   # 샘플 데이터 기준 시각

mcp = FastMCP("coris-fab-sample", instructions="FAB 샘플 데이터 (Lot 진행 이력 · 장비 효율, Mock)",
              host=HOST, port=PORT, stateless_http=True)


def _load(name: str) -> list[dict]:
    path = DATA / name
    if not path.exists():
        raise FileNotFoundError(f"{path} 없음 — 먼저 python gen_data.py 를 실행하세요")
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


LOTS = _load("lot_history.csv")
EFF = _load("eqp_efficiency.csv")


# ── 공통 ──────────────────────────────────────────────────────

def _list(v: Optional[str]) -> list[str]:
    """'ETCH-01, ETCH-02' → ['ETCH-01', 'ETCH-02'] (대문자, 빈 값 제외)."""
    return [x.strip().upper() for x in (v or "").split(",") if x.strip()]


def _in_range(day: str, date_from: Optional[str], date_to: Optional[str]) -> bool:
    """day = 'YYYY-MM-DD...' 앞 10자리로 비교. 날짜가 없는 행(대기 Lot 등)은 기간 조건이 있으면 제외."""
    if not (date_from or date_to):
        return True
    if not day:
        return False
    d = day[:10]
    return (not date_from or d >= date_from[:10]) and (not date_to or d <= date_to[:10])


def _cast(v: str, typ: str):
    """CSV 문자열 → JSON 값 (빈 값은 null)."""
    if v is None or v == "":
        return None
    if typ == "int":
        return int(float(v))
    if typ == "float":
        return float(v)
    return v


def _result(summary: str, cols: list[tuple], rows: list[dict], source: str, query: dict, **meta) -> str:
    """공통 형식 JSON. cols = (name, label, type, unit)."""
    return json.dumps({
        "summary": summary,
        "columns": [{"name": n, "label": lb, "type": t} | ({"unit": u} if u else {}) for n, lb, t, u in cols],
        "rows": [[_cast(r.get(n, ""), t) for n, _, t, _ in cols] for r in rows],
        "meta": {"source": source, "query": {k: v for k, v in query.items() if v}, "row_count": len(rows),
                 "truncated": False} | meta,
    }, ensure_ascii=False)


def _cond(**kw) -> str:
    parts = [f"{k}={v}" for k, v in kw.items() if v]
    return ", ".join(parts) if parts else "전체 (조건 없음)"


# ── LLM 용 ────────────────────────────────────────────────────

# (name, label, type, unit)
LOT_COLS = [
    ("lot_id", "Lot ID", "string", None), ("product", "제품", "string", None), ("step_seq", "Step", "int", None),
    ("step_name", "공정명", "string", None), ("area", "영역", "string", None), ("eqp_id", "장비", "string", None),
    ("recipe", "Recipe", "string", None), ("qty", "수량", "int", "wafer"), ("track_in", "Track In", "datetime", None),
    ("track_out", "Track Out", "datetime", None), ("wait_min", "대기", "int", "분"), ("proc_min", "처리", "int", "분"),
    ("status", "상태", "string", None), ("hold_reason", "Hold 사유", "string", None), ("hold_min", "Hold", "int", "분"),
]


@mcp.tool(structured_output=False)
def get_lot_history(
    lot_id: Optional[str] = None,
    product: Optional[str] = None,
    area: Optional[str] = None,
    step: Optional[str] = None,
    eqp_id: Optional[str] = None,
    status: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> str:
    """Lot 의 공정 · 장비 진행 이력을 조회한다 (step 별 1행: 장비, Recipe, Track In/Out, 대기 · 처리 시간, 상태, Hold).

    언제 사용: 특정 Lot 이 어디까지 진행됐는지, 어떤 장비를 거쳤는지, 대기가 길었던 step,
    HOLD · 진행 중 · 대기 Lot(재공) 현황, 특정 장비 · 공정을 지나간 Lot 목록.

    인자는 질문에 나온 것만 채운다 (비우면 그 조건으로 거르지 않음). 여러 값은 쉼표로.
      lot_id   : 'D160012.1' 또는 앞부분 'D160012' (부분 일치)
      product  : DRAM-16G | NAND-1T | LOGIC-5N
      area     : WET | DIFF | CVD | PHOTO | ETCH | IMP | CMP | PVD | MEAS
      step     : step 번호(예: 600) 또는 공정명 일부(예: 'GATE ETCH', 'CMP')
      eqp_id   : 예) ETCH-03, CVD-02
      status   : DONE(완료) | RUNNING(진행 중) | WAIT(지금 다음 step 도착 전) | HOLD
                 ※ '대기 시간 · 처리 시간' 분석은 status 를 비운다 — 모든 step 행에 wait_min · proc_min 이 있다.
                   status=WAIT 는 '지금 시점에 다음 step 을 기다리는 Lot' 만 (대기 시간 값 없음)
      date_from, date_to : YYYY-MM-DD — Track In 날짜 기준
    데이터 기준 시각: 2026-11-19 09:00.
    """
    lots, products, areas = _list(lot_id), _list(product), _list(area)
    eqps, statuses = _list(eqp_id), _list(status)
    step_q = (step or "").strip().upper()
    rows = [
        r for r in LOTS
        if (not lots or any(r["lot_id"].upper().startswith(x) for x in lots))
        and (not products or r["product"].upper() in products)
        and (not areas or r["area"] in areas)
        and (not step_q or r["step_seq"] == step_q or step_q in r["step_name"].upper())
        and (not eqps or r["eqp_id"].upper() in eqps)
        and (not statuses or r["status"] in statuses)
        and _in_range(r["track_in"], date_from, date_to)
    ]
    query = dict(lot_id=lot_id, product=product, area=area, step=step, eqp_id=eqp_id, status=status,
                 date_from=date_from, date_to=date_to)
    if rows:
        st: dict[str, int] = {}
        for r in rows:
            st[r["status"]] = st.get(r["status"], 0) + 1
        summary = (f"Lot 공정 진행 이력 {len(rows)}건 (Lot {len({r['lot_id'] for r in rows})}개) · 조건: {_cond(**query)} · "
                   "상태 " + ", ".join(f"{k} {v}" for k, v in sorted(st.items(), key=lambda x: -x[1])))
    else:
        summary = f"Lot 공정 진행 이력 — 조건({_cond(**query)})에 맞는 결과가 없습니다"
    return _result(summary, LOT_COLS, rows, "FAB 샘플 lot_history", query, as_of=AS_OF)


EFF_COLS = [
    ("date", "일자", "date", None), ("eqp_id", "장비", "string", None), ("area", "영역", "string", None),
    ("run_hr", "가동", "float", "h"), ("idle_hr", "유휴", "float", "h"), ("pm_hr", "PM", "float", "h"),
    ("bm_hr", "BM", "float", "h"), ("down_hr", "비가동", "float", "h"), ("availability_pct", "가용률", "float", "%"),
    ("utilization_pct", "가동률", "float", "%"), ("wph", "WPH", "float", "wafer/h"), ("wafers_out", "처리 매수", "int", "wafer"),
    ("oee_pct", "OEE", "float", "%"),
]


@mcp.tool(structured_output=False)
def get_eqp_efficiency(
    eqp_id: Optional[str] = None,
    area: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> str:
    """장비별 일 단위 효율을 날짜 순으로 조회한다 (가동 · 유휴 · PM · BM 시간, 가용률, 가동률, WPH, 처리 매수, OEE).

    언제 사용: 장비 가동률 · 효율 추이, 고장(BM) · 정기 보전(PM) 이력, 장비 간 비교, 처리량(WPH) 하락 확인.

    인자는 질문에 나온 것만 채운다 (비우면 그 조건으로 거르지 않음). 여러 값은 쉼표로.
      eqp_id : 예) ETCH-03, CVD-02 (장비 24대: WET-01~03, DIFF-01~03, CVD-01~03, PHOTO-01~03,
               ETCH-01~04, IMP-01~02, CMP-01~02, PVD-01~02, MEAS-01~02)
      area   : WET | DIFF | CVD | PHOTO | ETCH | IMP | CMP | PVD | MEAS
      date_from, date_to : YYYY-MM-DD (데이터 기간 2026-10-08 ~ 2026-11-18)
    용어: 가용률 = (24h - PM - BM) / 24h, 가동률 = 가동 / 24h, WPH = 시간당 처리 wafer, OEE = 가동률 × 성능 × 품질.
    """
    eqps, areas = _list(eqp_id), _list(area)
    rows = [
        r for r in EFF
        if (not eqps or r["eqp_id"].upper() in eqps)
        and (not areas or r["area"] in areas)
        and _in_range(r["date"], date_from, date_to)
    ]
    rows.sort(key=lambda r: (r["date"], r["eqp_id"]))
    query = dict(eqp_id=eqp_id, area=area, date_from=date_from, date_to=date_to)
    summary = (f"장비 일 효율 {len(rows)}건 (장비 {len({r['eqp_id'] for r in rows})}대, {rows[0]['date']} ~ {rows[-1]['date']}) · "
               f"조건: {_cond(**query)}") if rows else \
              f"장비 일 효율 — 조건({_cond(**query)})에 맞는 결과가 없습니다 (데이터 기간 2026-10-08 ~ 2026-11-18)"
    return _result(summary, EFF_COLS, rows, "FAB 샘플 eqp_efficiency", query, period="2026-10-08 ~ 2026-11-18")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    log.info("coris-fab-sample MCP: http://%s:%d/mcp (lot_history %d행, eqp_efficiency %d행)", HOST, PORT, len(LOTS), len(EFF))
    mcp.run(transport="streamable-http")
