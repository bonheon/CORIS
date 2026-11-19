"""
커널 시작 시 한 번 실행되는 코드 — LLM 이 쓰는 도우미 함수를 커널 전역에 만든다.

    save_html(obj, title)  plotly Figure / DataFrame / HTML 문자열 → 결과물 저장, [ARTIFACT:id] 출력
    trend_chart(df, ...)   날짜별 데이터 → 월 · 주 · 일 단위 추이 차트 (지표마다 서브플롯) + 구간별 값 표 출력
    load_ref(ref)          다른 tool 결과의 data_ref → DataFrame
                             'dr_...'  : 큰 tool 결과를 Coris 가 저장소에 보관한 것 (/api/hub/data/{ref}, 이 대화 것만)
                                         열 타입(int · float · date · datetime)을 살려서, 한 번 받으면 커널에 캐시
                             그 밖      : 화면 전용 tool 호출 (/api/ui/{ref}) — 차트 형식이면 DataFrame(x, series, value)

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


def _coris_template():
    """Coris 차트 테마 — 모든 plotly 차트의 기본값. 밝은 바탕 · 옅은 격자 · 위쪽 가로 범례 · 브랜드 팔레트.
    다크 모드 색 전환은 화면(ArtifactCard)이 iframe 에 테마를 알려 relayout 한다."""
    try:
        import plotly.graph_objects as go
        import plotly.io as pio
    except ImportError:
        return
    ink, sub, grid, line = "#2b302c", "#6b716c", "#eeece6", "#d9d5ca"
    axis = dict(gridcolor=grid, linecolor=line, tickcolor=line, ticks="outside", ticklen=4, showline=True,
                zeroline=False, title=dict(font=dict(size=12, color=sub), standoff=10), tickfont=dict(size=11, color=sub),
                automargin=True)
    t = go.layout.Template()
    t.layout = go.Layout(
        font=dict(family="Pretendard, 'Apple SD Gothic Neo', 'Malgun Gothic', -apple-system, sans-serif", size=12, color=ink),
        paper_bgcolor="#ffffff", plot_bgcolor="#ffffff",
        colorway=["#2f7d5b", "#3b7dd8", "#e0873a", "#8a63d2", "#d1495b", "#1f9e9e", "#b89b2e", "#6b7280"],
        title=dict(x=0, xanchor="left", y=0.98, yanchor="top", font=dict(size=15, color=ink), pad=dict(l=4)),
        margin=dict(l=56, r=24, t=72, b=48),
        legend=dict(orientation="h", x=0, xanchor="left", y=1.0, yanchor="bottom", bgcolor="rgba(0,0,0,0)",
                    font=dict(size=11.5, color=sub), title=dict(text="")),
        hovermode="x unified",
        hoverlabel=dict(bgcolor="#ffffff", bordercolor=line, font=dict(size=12, color=ink)),
        xaxis=axis, yaxis=axis, bargap=0.28, bargroupgap=0.08,
        colorscale=dict(sequential=[[0, "#e8f3ee"], [0.5, "#5aa883"], [1, "#1f5c42"]]),
    )
    t.data.scatter = [go.Scatter(line=dict(width=2.2), marker=dict(size=6, line=dict(width=0)))]
    t.data.bar = [go.Bar(marker=dict(line=dict(width=0)), opacity=0.92)]
    pio.templates["coris"] = t
    pio.templates.default = "coris"


_coris_template()


def _patch_plotly_json():
    """pandas Period · Interval 등 plotly 가 JSON 으로 못 바꾸는 값을 문자열로 — 월별 집계(dt.to_period) 차트가 그대로 그려지게."""
    try:
        import pandas as _pd
        from _plotly_utils.utils import PlotlyJSONEncoder as _Enc
    except ImportError:
        return
    _orig = _Enc.default

    def _default(self, obj):
        if isinstance(obj, (_pd.Period, _pd.Interval)):
            return str(obj)
        return _orig(self, obj)

    _Enc.default = _default


_patch_plotly_json()


def save_html(obj, title="차트"):
    """plotly Figure · DataFrame · HTML 문자열을 화면에 보일 결과물로 저장하고 [ARTIFACT:id] 를 출력한다."""
    if hasattr(obj, "to_plotly_json"):
        if not obj.layout.height:
            obj.update_layout(height=400)   # 대화 본문 폭(약 760px)에 맞춘 기본 높이
        obj.for_each_annotation(lambda a: a.update(font=dict(size=12, color="#6b716c")))   # facet 제목
        html = obj.to_html(full_html=True, include_plotlyjs=False, default_width="100%",
                           config={"scrollZoom": False, "displaylogo": False, "responsive": True,   # 휠은 페이지 스크롤 — 확대는 드래그
                                   "displayModeBar": "hover",
                                   "modebarButtonsToRemove": ["select2d", "lasso2d", "autoScale2d", "toggleSpikelines"]})
        html = html.replace("<head>", '<head><style>html,body{margin:0;background:#fff}</style>', 1)
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


_FREQ_NAME = {"MS": "월", "M": "월", "W": "주", "W-MON": "주", "D": "일"}


def trend_chart(df, date_col, values, by=None, freq="MS", agg="mean", title="추이"):
    """추이(Trend) 차트 — 구간(freq)별로 묶어 지표마다 서브플롯을 그리고, 구간별 값 표를 print 한다.

    df       : 원본 DataFrame (load_ref 결과 그대로)
    date_col : 날짜 열 이름 (예: "일자", "Track In")
    values   : 지표 열 이름 하나 또는 목록 (예: "가동률(%)" 또는 ["가동률(%)", "OEE(%)"])
    by       : 색으로 나눌 열 (예: "장비") — 없으면 전체 하나
    freq     : "MS" 월 · "W" 주 · "D" 일
    agg      : "mean" · "sum" · "median" 등
    구간이 3개 미만이면 그 사실을 출력하고, 더 촘촘한 단위로 한 장을 더 그린다.
    """
    import pandas as pd
    import plotly.express as px

    values = [values] if isinstance(values, str) else list(values)
    orig_values, orig_by = list(values), by
    d = df.copy()
    d[date_col] = pd.to_datetime(d[date_col], errors="coerce")
    grp = (pd.Grouper(key=date_col, freq="W-MON", label="left", closed="left") if freq in ("W", "W-MON")   # 주 = 월요일 시작
           else pd.Grouper(key=date_col, freq=freq))
    keys = [grp] + ([by] if by else [])
    g = d.groupby(keys)[values].agg(agg).reset_index()
    # 표시 이름 — load_ref 가 붙인 한글 label · 단위가 있으면 그것으로 (utilization_pct → 가동률(%))
    labels, units = df.attrs.get("labels") or {}, df.attrs.get("units") or {}
    disp = lambda c: f"{labels.get(c, c)}({units[c]})" if c in units else labels.get(c, c)
    g = g.rename(columns={c: disp(c) for c in values + ([by] if by else [])})
    values, by_d = [disp(c) for c in values], (disp(by) if by else None)
    long = g.melt(id_vars=[date_col] + ([by_d] if by_d else []), value_vars=values, var_name="지표", value_name="값")
    n = g[date_col].nunique()
    unit = _FREQ_NAME.get(freq, freq)
    fig = px.line(long, x=date_col, y="값", color=by_d, facet_row="지표" if len(values) > 1 else None, markers=True,
                  title=f"{title} ({unit}별 {agg})")
    fig.update_yaxes(matches=None, title_text="")
    fig.for_each_annotation(lambda a: a.update(text=a.text.split("=")[-1]))
    fig.update_layout(height=max(340, 210 * len(values) + 110), xaxis_title=None)
    if len(values) == 1:
        fig.update_yaxes(title_text=values[0])
    fig.update_traces(hovertemplate="%{y:,.2f}")
    if freq in ("MS", "M"):
        fig.update_xaxes(dtick="M1", tickformat="%Y-%m", hoverformat="%Y-%m")
    elif freq in ("W", "W-MON"):
        fig.update_xaxes(tickformat="%m/%d", hoverformat="%Y-%m-%d 주")
    else:
        fig.update_xaxes(tickformat="%m/%d", hoverformat="%Y-%m-%d")
    table = g.pivot_table(index=date_col, columns=by_d, values=values, aggfunc="first") if by_d else g.set_index(date_col)
    if freq in ("MS", "M"):
        table.index = table.index.strftime("%Y-%m")
    print(f"[{unit}별 {agg} — 구간 {n}개]")
    print(table.round(2).to_string())
    aid = save_html(fig, f"{title} ({unit}별)")
    if n < 3 and freq != "D":
        finer = "W" if freq in ("MS", "M") else "D"
        print(f"※ {unit} 단위 구간이 {n}개뿐이라 추이를 보기 어렵습니다 — {_FREQ_NAME[finer]}별 차트를 함께 그립니다.")
        trend_chart(df, date_col, orig_values, by=orig_by, freq=finer, agg=agg, title=title)
    return aid


_SESSION = _os.environ.get("CI_SESSION_ID", "")
_REF_CACHE = {}


def _load_stored(ref):
    """보관된 tool 결과(dr_...) → DataFrame. 열 타입 · 단위 · 출처(tool, args)는 df.attrs 에."""
    import pandas as pd
    if ref in _REF_CACHE:
        return _REF_CACHE[ref].copy()
    req = _urlreq.Request(f"{_CORIS_API}/api/hub/data/{ref}", headers={"X-Coris-Session": _SESSION})
    try:
        with _urlreq.urlopen(req, timeout=60) as r:
            rec = _json.load(r)
    except _urlreq.HTTPError as e:
        raise RuntimeError(f"load_ref('{ref}') 실패 — HTTP {e.code}: 이 대화에서 만든 data_ref 인지 확인하세요") from None
    t = rec["table"]
    df = pd.DataFrame(t["rows"], columns=[c["name"] for c in t["columns"]])
    for c in t["columns"]:
        if c["type"] in ("date", "datetime"):
            df[c["name"]] = pd.to_datetime(df[c["name"]], errors="coerce")
        elif c["type"] == "int":
            df[c["name"]] = pd.to_numeric(df[c["name"]], errors="coerce").astype("Int64")
        elif c["type"] == "float":
            df[c["name"]] = pd.to_numeric(df[c["name"]], errors="coerce")
    df.attrs.update(name=t.get("name"), tool=rec.get("tool"), args=rec.get("args"),
                    units={c["name"]: c["unit"] for c in t["columns"] if c.get("unit")},
                    labels={c["name"]: c["label"] for c in t["columns"] if c.get("label")})
    _REF_CACHE[ref] = df
    return df.copy()


def load_ref(ref):
    """data_ref 의 데이터를 받아온다.
    'dr_...' → 보관된 tool 결과 DataFrame / 'ui_metric_trend?metric=thickness&days=30' 같은 화면 tool 호출."""
    ref = str(ref).strip().strip('"\'')
    if ref.startswith("dr_"):
        return _load_stored(ref)
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
