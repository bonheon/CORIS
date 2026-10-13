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


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    log.info("coris-example MCP: http://%s:%d/mcp", HOST, PORT)
    mcp.run(transport="streamable-http")
