"""
커널 시작 시 한 번 실행되는 코드 — LLM 이 쓰는 도우미 함수를 커널 전역에 만든다.

    save_html(obj, title)  plotly Figure / DataFrame / HTML 문자열 → 결과물 저장, [ARTIFACT:id] 출력
    load_ref(ref)          다른 tool 결과의 data_ref → Coris 의 /api/ui/{ref} 로 데이터 받기
                           (Coris 공통 차트 형식이면 DataFrame: x, series, value)

이 파일은 import 하지 않고 문자열로 읽어 커널에 보낸다.
"""
import json as _json
import os as _os
import urllib.parse as _urlparse
import urllib.request as _urlreq
import uuid as _uuid

get_ipython().run_line_magic("matplotlib", "inline")  # noqa: F821 — 커널 안에서만 실행된다

_ARTIFACT_DIR = _os.environ["CI_ARTIFACT_DIR"]
_CORIS_API = _os.environ.get("CORIS_API_URL", "http://localhost:8000").rstrip("/")
_PLOTLY_SRC = _os.environ.get("CI_PLOTLY_SRC", "/vendor/plotly.min.js")


def save_html(obj, title="차트"):
    """plotly Figure · DataFrame · HTML 문자열을 화면에 보일 결과물로 저장하고 [ARTIFACT:id] 를 출력한다."""
    if hasattr(obj, "to_plotly_json"):
        if not obj.layout.height:
            obj.update_layout(height=460)
        html = obj.to_html(full_html=True, include_plotlyjs=False,
                           config={"scrollZoom": False, "displaylogo": False, "responsive": True})  # 휠은 페이지 스크롤 — 확대는 드래그
        # plotly.js 는 Coris 화면이 제공한다 (사내망 — CDN 대신)
        html = html.replace("<head>", f'<head><script src="{_PLOTLY_SRC}"></script>', 1)
    elif hasattr(obj, "to_html"):
        html = "<html><head><meta charset='utf-8'></head><body style='font-family:sans-serif'>" + obj.to_html() + "</body></html>"
    else:
        html = str(obj)
    aid = "a_" + _uuid.uuid4().hex[:12]
    with open(_os.path.join(_ARTIFACT_DIR, aid + ".html"), "w", encoding="utf-8") as f:
        f.write(html)
    with open(_os.path.join(_ARTIFACT_DIR, aid + ".json"), "w", encoding="utf-8") as f:
        _json.dump({"kind": "html", "title": str(title)}, f, ensure_ascii=False)
    print(f"[ARTIFACT:{aid}]")
    return aid


def load_ref(ref):
    """data_ref(예: 'ui_metric_trend?metric=thickness&days=30') 의 데이터를 받아온다."""
    url = f"{_CORIS_API}/api/ui/{_urlparse.quote(ref.lstrip('/'), safe='?=&/%:,._-')}"
    with _urlreq.urlopen(url, timeout=30) as r:
        data = _json.load(r)
    if isinstance(data, dict) and isinstance(data.get("series"), list):
        import pandas as pd
        rows = [{"x": p[0], "series": s.get("name"), "value": p[1]} for s in data["series"] for p in s.get("data", [])]
        df = pd.DataFrame(rows)
        if (data.get("x") or {}).get("type") == "time":
            df["x"] = pd.to_datetime(df["x"])
        df.attrs.update(title=data.get("title"), y=data.get("y"), limits=data.get("limits"))
        return df
    return data
