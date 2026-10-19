"""
예시 MCP 서버 — 새 MCP 서버를 만들 때 복사해서 쓰는 템플릿.

두 종류의 tool 을 MCP(streamable HTTP)로 노출한다.
  - LLM 용 tool   : 요약된 결과를 돌려준다 — catalog.yaml 의 groups 에 등록
  - 화면용 tool    : 카드가 쓰는 전체 데이터, 이름은 ui_ 로 시작 — catalog.yaml 의 ui_tools 에 등록
원칙: tool = 단순 데이터 조회. 판단 로직은 skill(SKILL.md) 쪽에 둔다.

허브(backend)는 이 서버를 회사 MCP 서버와 똑같은 방식(mcp_servers.yaml 의 url)으로 붙는다.

실행 (backend venv 사용):
    cd mcp_servers/example && python server.py          # http://localhost:8100/mcp
    MCP_PORT=8300 python server.py
"""
import json
import logging
import math
import os
import random
from datetime import datetime, timedelta
from typing import Literal
from urllib.parse import urlencode

from mcp.server.fastmcp import FastMCP

log = logging.getLogger("example_mcp")

HOST = os.getenv("MCP_HOST", "127.0.0.1")
PORT = int(os.getenv("MCP_PORT", "8100"))

mcp = FastMCP("coris-example", instructions="Coris 예시 tool (Mock 데이터)", host=HOST, port=PORT, stateless_http=True)

# Mock 데이터 — 실제 서버에서는 DB/API 조회로 바꾼다
NOTICES = [
    {"id": "N-001", "date": "2026-10-01", "dept": "정보보안팀", "title": "10월 보안 점검 일정 안내", "body": "10/20~10/24 PC 보안 점검을 진행합니다."},
    {"id": "N-002", "date": "2026-10-05", "dept": "인사팀", "title": "하반기 교육 신청 안내", "body": "사내 교육 포털에서 10/31 까지 신청하세요."},
    {"id": "N-003", "date": "2026-10-08", "dept": "IT운영팀", "title": "메일 서버 정기 점검", "body": "10/18(토) 02:00~06:00 메일 사용이 중단됩니다."},
    {"id": "N-004", "date": "2026-10-10", "dept": "정보보안팀", "title": "피싱 메일 주의 안내", "body": "외부 링크 클릭 전 발신자를 반드시 확인하세요."},
]


def _search(keyword: str) -> list[dict]:
    kw = keyword.strip().lower()
    return [n for n in NOTICES if not kw or kw in (n["title"] + n["body"] + n["dept"]).lower()]


def _dump(obj) -> str:
    return json.dumps(obj, ensure_ascii=False)


# ── LLM 용 ────────────────────────────────────────────────────

@mcp.tool(structured_output=False)
def get_current_time() -> str:
    """현재 서버 시각(ISO 8601)과 요일을 조회한다.

    언제 사용: '오늘', '이번 주' 처럼 날짜 기준이 필요한 질문.
    """
    now = datetime.now()
    return _dump({"now": now.isoformat(timespec="seconds"), "weekday": "월화수목금토일"[now.weekday()]})


@mcp.tool(structured_output=False)
def search_notices(keyword: str = "") -> str:
    """사내 공지를 키워드로 검색한다 (제목 · 본문 · 부서). 빈 키워드면 전체.

    언제 사용: 공지, 안내, 점검 일정 등을 묻는 질문.

    Args:
        keyword: 검색어 (예: "보안", "점검")
    """
    hits = _search(keyword)
    return _dump({"keyword": keyword, "count": len(hits),
                  "items": [{k: n[k] for k in ("id", "date", "dept", "title")} for n in hits]})


METRICS = {  # 지표 → (표시명, 단위, 기준값, 변동폭, LCL, UCL)
    "thickness":   ("막 두께", "Å", 1000.0, 6.0, 980.0, 1020.0),
    "temperature": ("챔버 온도", "°C", 65.0, 0.6, 63.0, 67.0),
    "pressure":    ("챔버 압력", "mTorr", 120.0, 1.5, 115.0, 125.0),
}
EQUIPMENTS = ["EQ-01", "EQ-02", "EQ-03"]
Metric = Literal["thickness", "temperature", "pressure"]


def _trend_rows(metric: str, days: int, equipment: str) -> dict[str, list[tuple[str, float]]]:
    """설비별 (시각, 값) — 6시간 간격. 같은 인자면 같은 값 (Mock)."""
    _, _, base, sd, lcl, ucl = METRICS[metric]
    end = datetime.now().replace(minute=0, second=0, microsecond=0)
    eqs = [equipment] if equipment in EQUIPMENTS else EQUIPMENTS
    out = {}
    for k, eq in enumerate(EQUIPMENTS):
        rnd = random.Random(f"{metric}-{eq}")
        drift = (k - 1) * sd * 0.4
        rows = []
        for i in range(days * 4, -1, -1):
            t = end - timedelta(hours=6 * i)
            v = base + drift + sd * rnd.gauss(0, 1) + sd * 0.8 * math.sin(i / 9)
            if rnd.random() < 0.025:  # 가끔 튀는 값 (OOC)
                v += rnd.choice([-1, 1]) * (ucl - lcl) * 0.7
            rows.append((t.isoformat(timespec="minutes"), round(v, 2)))
        if eq in eqs:
            out[eq] = rows
    return out


def _ref(tool: str, **args) -> str:
    return f"{tool}?{urlencode({k: v for k, v in args.items() if v not in ('', None)})}"


@mcp.tool(structured_output=False)
def get_metric_trend(metric: Metric, days: int = 30, equipment: str = "") -> str:
    """설비 공정 지표의 기간별 추이를 조회한다 (Mock). 설비별 평균 · 최소 · 최대 · 관리한계 이탈(OOC) 건수를 돌려준다.

    언제 사용: 두께 · 온도 · 압력의 추이, 이상치, 설비 간 비교를 묻는 질문.

    Args:
        metric: thickness(막 두께) | temperature(챔버 온도) | pressure(챔버 압력)
        days: 조회 기간(일), 1~90
        equipment: 설비 ID (EQ-01 · EQ-02 · EQ-03). 비우면 전체
    """
    days = max(1, min(int(days), 90))
    name, unit, _, _, lcl, ucl = METRICS[metric]
    rows = _trend_rows(metric, days, equipment)
    stats = []
    for eq, pts in rows.items():
        vals = [v for _, v in pts]
        ooc = [(t, v) for t, v in pts if v < lcl or v > ucl]
        stats.append({"equipment": eq, "points": len(vals), "mean": round(sum(vals) / len(vals), 2),
                      "min": min(vals), "max": max(vals), "ooc_count": len(ooc), "ooc_recent": ooc[-3:]})
    ref = _ref("ui_metric_trend", metric=metric, days=days, equipment=equipment)
    return _dump({"metric": name, "unit": unit, "days": days, "limits": {"LCL": lcl, "UCL": ucl},
                  "by_equipment": stats, "chart": f"[CHART:{ref}]", "data_ref": ref})


# ── INSP Wafer Map (Mock) ─────────────────────────────────────
# 300mm 웨이퍼, 중심 원점 mm 좌표. 같은 Lot ID 면 같은 데이터.
# pattern 은 INSP 자동 분류(SSA) 결과를 흉내 낸 값 — 실제 시스템 값으로 바뀐다.

WAFER_R = 150.0
DEFECT_CLASSES = ["PARTICLE", "SCRATCH", "RESIDUE", "PIT", "BRIDGE"]
DEFECT_LIMIT = 150  # 웨이퍼당 관리 기준 (Mock)
PATTERNS = ["Random", "Edge", "Center", "Scratch", "Cluster"]


def _point_in_wafer(rnd: random.Random, r_min: float = 0.0, r_max: float = WAFER_R - 3) -> tuple[float, float]:
    r = math.sqrt(rnd.uniform((r_min / r_max) ** 2, 1.0)) * r_max  # 면적 균일
    t = rnd.uniform(0, 2 * math.pi)
    return r * math.cos(t), r * math.sin(t)


def _insp_wafers(lot_id: str) -> list[dict]:
    lot = lot_id.strip().upper()
    rnd = random.Random(f"insp-{lot}")
    special = {slot: rnd.choice(PATTERNS[1:]) for slot in rnd.sample(range(1, 26), 4)}
    wafers = []
    for slot in range(1, 26):
        w = random.Random(f"insp-{lot}-{slot}")
        pattern = special.get(slot, "Random")
        defects = []
        for _ in range(w.randint(25, 70)):  # 배경 random defect
            x, y = _point_in_wafer(w)
            defects.append((x, y, w.choices(DEFECT_CLASSES, [55, 5, 20, 15, 5])[0]))
        if pattern == "Edge":
            for _ in range(w.randint(110, 170)):
                x, y = _point_in_wafer(w, 128)
                defects.append((x, y, w.choices(["PARTICLE", "RESIDUE"], [60, 40])[0]))
        elif pattern == "Center":
            for _ in range(w.randint(90, 140)):
                x, y = _point_in_wafer(w, 0, 45)
                defects.append((x, y, w.choices(["RESIDUE", "PIT"], [70, 30])[0]))
        elif pattern == "Scratch":
            x0, y0 = _point_in_wafer(w, 0, 80)
            ang, length = w.uniform(0, math.pi), w.uniform(90, 160)
            for i in range(w.randint(70, 110)):
                d = length * (i / 100 - 0.5)
                x, y = x0 + d * math.cos(ang) + w.gauss(0, 0.8), y0 + d * math.sin(ang) + w.gauss(0, 0.8)
                if x * x + y * y < (WAFER_R - 3) ** 2:
                    defects.append((x, y, "SCRATCH"))
        elif pattern == "Cluster":
            cx, cy = _point_in_wafer(w, 30, 110)
            for _ in range(w.randint(80, 120)):
                defects.append((cx + w.gauss(0, 7), cy + w.gauss(0, 7), w.choices(["PARTICLE", "BRIDGE"], [50, 50])[0]))
        wafers.append({
            "slot": slot, "pattern": pattern,
            "defects": [(round(x, 1), round(y, 1), c, round(w.lognormvariate(-0.6, 0.5), 2)) for x, y, c in defects],
        })
    return wafers


@mcp.tool(structured_output=False)
def get_insp_map(lot_id: str) -> str:
    """Lot 의 INSP(검사) Wafer Map 결과를 조회한다 (Mock). 웨이퍼별 defect 수 · 유형 · 자동 분류 패턴과 Lot 요약을 돌려준다.

    언제 사용: 특정 Lot 의 검사 결과, 웨이퍼 맵, defect 분포 · 패턴, 이상 웨이퍼를 묻는 질문.

    Args:
        lot_id: Lot ID (예: TE2FE35)
    """
    lot = lot_id.strip().upper()
    wafers = _insp_wafers(lot)
    rows = []
    for w in wafers:
        counts = {c: 0 for c in DEFECT_CLASSES}
        for *_, c, _s in w["defects"]:
            counts[c] += 1
        top = sorted(((c, n) for c, n in counts.items() if n), key=lambda t: -t[1])[:2]
        rows.append({"slot": w["slot"], "total": len(w["defects"]), "pattern": w["pattern"],
                     "top_classes": [f"{c} {n}" for c, n in top],
                     "over_limit": len(w["defects"]) > DEFECT_LIMIT})
    totals = [r["total"] for r in rows]
    by_class = {c: sum(1 for w in wafers for *_, cc, _s in w["defects"] if cc == c) for c in DEFECT_CLASSES}
    return _dump({
        "lot_id": lot, "step": "INSP-01", "wafer_count": len(rows),
        "summary": {"total_defects": sum(totals), "mean_per_wafer": round(sum(totals) / len(totals), 1),
                    "max": max(totals), "limit_per_wafer": DEFECT_LIMIT, "by_class": by_class,
                    "over_limit_slots": [r["slot"] for r in rows if r["over_limit"]],
                    "pattern_slots": {r["slot"]: r["pattern"] for r in rows if r["pattern"] != "Random"},
                    "slots_by_defect_desc": [r["slot"] for r in sorted(rows, key=lambda r: -r["total"])]},
        "wafers": rows,
        "chart": f"[WAFER_MAP:{lot}]",
    })


# ── 화면용 ────────────────────────────────────────────────────

@mcp.tool(structured_output=False)
def ui_notices(keyword: str = "") -> str:
    """[화면 전용] 공지 목록 카드 데이터 — 본문 포함."""
    return _dump({"keyword": keyword, "items": _search(keyword)})


@mcp.tool(structured_output=False)
def ui_metric_trend(metric: Metric, days: int = 30, equipment: str = "") -> str:
    """[화면 전용] 지표 추이 — Coris 공통 차트 형식(CHART 카드)."""
    days = max(1, min(int(days), 90))
    name, unit, _, _, lcl, ucl = METRICS[metric]
    rows = _trend_rows(metric, days, equipment)
    return _dump({
        "title": f"{name} 추이", "subtitle": f"최근 {days}일 · 6시간 간격 · Mock",
        "x": {"type": "time", "label": "시각"},
        "y": {"label": name, "unit": unit},
        "series": [{"name": eq, "type": "line", "data": [[t, v] for t, v in pts]} for eq, pts in rows.items()],
        "limits": [{"name": "UCL", "value": ucl}, {"name": "LCL", "value": lcl}],
    })


@mcp.tool(structured_output=False)
def ui_insp_map(lot_id: str) -> str:
    """[화면 전용] INSP Wafer Map 카드 데이터 — 웨이퍼별 defect 좌표(mm, 중심 원점)."""
    lot = lot_id.strip().upper()
    return _dump({
        "lot_id": lot, "step": "INSP-01", "wafer_diameter_mm": WAFER_R * 2, "limit_per_wafer": DEFECT_LIMIT,
        "classes": DEFECT_CLASSES,
        # defects: [x, y, class index, size(um)] — 25장 × 수백 점이라 키 없이 배열로
        "wafers": [{"slot": w["slot"], "pattern": w["pattern"], "total": len(w["defects"]),
                    "defects": [[x, y, DEFECT_CLASSES.index(c), sz] for x, y, c, sz in w["defects"]]}
                   for w in _insp_wafers(lot)],
    })


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    log.info("coris-example MCP: http://%s:%d/mcp", HOST, PORT)
    mcp.run(transport="streamable-http")
