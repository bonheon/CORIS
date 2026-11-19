"""
tool 결과 텍스트 → 표(table) 목록. 외부 의존성 없음 (pandas 는 커널 쪽에서만 쓴다).

받아들이는 형식
  JSON  : 공통 형식 {"columns": [...], "rows": [[...]]} · 행 목록 [{...}] · 컬럼별 배열 {"col": [...]}
          · dict 안의 행 목록 ({"data": [{...}]}, 키 여러 개면 표 여러 개) · 차트 형식 {"series": [...]}
  마크다운: 파이프 표 (| a | b |\n|---|---|) — 한 결과에 여러 개 가능, 표 밖의 글은 text 로 남긴다

표 = {"name", "columns": [{"name", "type", "unit"}], "rows": [[값, ...]]}
  type: int | float | datetime | date | bool | string — 문자열 값은 타입을 추정해 바꾼다
        ('1,234' → 1234, '12.3nm' → 12.3 + unit nm, '-' · 'N/A' · '' → None)
"""
import json
import re
from typing import Any, Optional

NULLS = {"", "-", "—", "n/a", "na", "null", "none", "nan"}
_INT = re.compile(r"^[+-]?(\d{1,3}(,\d{3})+|\d+)$")
_FLOAT = re.compile(r"^[+-]?(\d{1,3}(,\d{3})+|\d*)(\.\d+)?([eE][+-]?\d+)?$")
_UNIT = re.compile(r"^([+-]?[\d,]*\.?\d+)\s*([A-Za-z%°µμ/]+)$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DATETIME = re.compile(r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?$")


# ── 타입 추정 ─────────────────────────────────────────────────

def _is_null(v: Any) -> bool:
    return v is None or (isinstance(v, str) and v.strip().lower() in NULLS)


def _num(s: str) -> float:
    return float(s.replace(",", ""))


def _infer(values: list) -> tuple[str, Optional[str]]:
    """열 값들 → (type, unit). 빈 값을 뺀 모든 값이 같은 형식일 때만 그 타입, 아니면 string."""
    vals = [v for v in values if not _is_null(v)]
    if not vals:
        return "string", None
    if all(isinstance(v, bool) for v in vals):
        return "bool", None
    if all(isinstance(v, int) and not isinstance(v, bool) for v in vals):
        return "int", None
    if all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in vals):
        return "float", None
    if not all(isinstance(v, str) for v in vals):
        return "string", None
    s = [v.strip() for v in vals]
    if all(_INT.match(x) for x in s):
        return "int", None
    if all(_FLOAT.match(x) and any(c.isdigit() for c in x) for x in s):
        return "float", None
    units = [_UNIT.match(x) for x in s]
    if all(units) and len({m.group(2) for m in units}) == 1:
        return "float", units[0].group(2)
    if all(_DATE.match(x) for x in s):
        return "date", None
    if all(_DATETIME.match(x) for x in s):
        return "datetime", None
    return "string", None


def _convert(v: Any, typ: str, unit: Optional[str]) -> Any:
    if _is_null(v):
        return None
    if not isinstance(v, str):
        return v
    x = v.strip()
    if typ == "int":
        return int(_num(x))
    if typ == "float":
        return _num(_UNIT.match(x).group(1)) if unit else _num(x)
    if typ == "datetime":
        return x.replace(" ", "T")
    return x


def _finish(name: str, labels: list[str], rows: list[list]) -> dict:
    """열 이름 정리(중복 · 빈 이름) + 열마다 타입 추정 · 변환."""
    names, seen = [], {}
    for i, lb in enumerate(labels):
        n = str(lb).strip() or f"col{i + 1}"
        if n in seen:
            seen[n] += 1
            n = f"{n}_{seen[n]}"
        else:
            seen[n] = 1
        names.append(n)
    width = len(names)
    rows = [(list(r) + [None] * width)[:width] for r in rows]
    cols = []
    for i, n in enumerate(names):
        typ, unit = _infer([r[i] for r in rows])
        for r in rows:
            r[i] = _convert(r[i], typ, unit)
        cols.append({"name": n, "type": typ} | ({"unit": unit} if unit else {}))
    return {"name": name, "columns": cols, "rows": rows}


# ── JSON ──────────────────────────────────────────────────────

def _records(name: str, items: list[dict]) -> dict:
    keys: dict[str, None] = {}
    for it in items:
        keys.update(dict.fromkeys(it))
    labels = list(keys)
    return _finish(name, labels, [[_cell(it.get(k)) for k in labels] for it in items])


def _cell(v: Any) -> Any:
    """중첩된 값은 표에 넣을 수 있게 JSON 문자열로."""
    return json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v


def _from_json(obj: Any, name: str = "data") -> tuple[list[dict], list[str]]:
    tables, text = [], []
    if isinstance(obj, list):
        if obj and all(isinstance(x, dict) for x in obj):
            tables.append(_records(name, obj))
        elif obj and all(isinstance(x, list) for x in obj):
            tables.append(_finish(name, [f"col{i + 1}" for i in range(max(map(len, obj)))], obj))
        return tables, text
    if not isinstance(obj, dict):
        return tables, [str(obj)]

    if isinstance(obj.get("rows"), list) and isinstance(obj.get("columns"), list):   # 공통 형식
        labels = [c.get("name") if isinstance(c, dict) else c for c in obj["columns"]]
        rows = obj["rows"]
        if rows and isinstance(rows[0], dict):
            rows = [[r.get(lb) for lb in labels] for r in rows]
        t = _finish(obj.get("name") or name, labels, [[_cell(v) for v in r] for r in rows])
        for c, src in zip(t["columns"], obj["columns"]):   # 선언된 타입 · 단위가 있으면 우선
            if isinstance(src, dict):
                c.update({k: src[k] for k in ("type", "unit", "label", "description") if src.get(k)})
        tables.append(t)
        rest = {k: v for k, v in obj.items() if k not in ("columns", "rows")}
        return tables, [json.dumps(rest, ensure_ascii=False)] if rest else []

    if isinstance(obj.get("series"), list) and all(isinstance(s, dict) for s in obj["series"]):   # 차트 형식
        rows = [[p[0], s.get("name"), p[1]] for s in obj["series"] for p in s.get("data") or [] if isinstance(p, list) and len(p) >= 2]
        tables.append(_finish(obj.get("title") or name, ["x", "series", "value"], rows))
        rest = {k: v for k, v in obj.items() if k != "series"}
        return tables, [json.dumps(rest, ensure_ascii=False)] if rest else []

    lists = {k: v for k, v in obj.items() if isinstance(v, list) and v and all(not isinstance(x, (dict, list)) for x in v)}
    if len(lists) >= 2 and len({len(v) for v in lists.values()}) == 1 and len(lists) == len(obj):   # 컬럼별 배열
        labels = list(lists)
        n = len(next(iter(lists.values())))
        tables.append(_finish(name, labels, [[lists[k][i] for k in labels] for i in range(n)]))
        return tables, text

    scalars = {}
    for k, v in obj.items():   # dict 안의 행 목록 · 중첩 dict
        if isinstance(v, (list, dict)):
            sub_t, sub_x = _from_json(v, k)
            tables += sub_t
            if not sub_t:
                scalars[k] = v
            text += sub_x if sub_t else []
        else:
            scalars[k] = v
    if scalars:
        text.insert(0, json.dumps(scalars, ensure_ascii=False))
    return tables, text


# ── 마크다운 ──────────────────────────────────────────────────

_SEP = re.compile(r"^\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")


def _cells(line: str) -> list[str]:
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|") and not s.endswith("\\|"):
        s = s[:-1]
    return [c.strip().replace("\\|", "|") for c in re.split(r"(?<!\\)\|", s)]


def _from_markdown(text: str) -> tuple[list[dict], list[str]]:
    lines = text.splitlines()
    tables, rest, i = [], [], 0
    last_heading = None
    while i < len(lines):
        ln = lines[i]
        if ln.lstrip().startswith("|") and i + 1 < len(lines) and _SEP.match(lines[i + 1].strip()):
            labels = _cells(ln)
            j, rows = i + 2, []
            while j < len(lines) and lines[j].lstrip().startswith("|"):
                rows.append(_cells(lines[j]))
                j += 1
            name = last_heading or f"table_{len(tables) + 1}"
            tables.append(_finish(name, labels, rows))
            i = j
            continue
        if ln.strip().startswith("#"):
            last_heading = ln.strip().lstrip("#").strip()
        rest.append(ln)
        i += 1
    return tables, ["\n".join(rest).strip()] if "\n".join(rest).strip() else []


# ── 진입점 ────────────────────────────────────────────────────

def parse(text: str) -> tuple[list[dict], str]:
    """tool 결과 → (표 목록, 표 밖의 글). 표로 볼 수 없으면 ([], 원문)."""
    s = text.strip()
    if s[:1] in "[{":
        try:
            tables, rest = _from_json(json.loads(s))
            return tables, "\n".join(rest)
        except (ValueError, TypeError):
            pass
    if "|" in s:
        tables, rest = _from_markdown(s)
        return tables, "\n".join(rest)
    return [], text


# ── 요약 (LLM 에 보낼 미리보기) ───────────────────────────────

def _fmt(v: Any) -> str:
    if isinstance(v, float):
        return f"{v:,.4g}" if abs(v) < 1e6 else f"{v:,.0f}"
    if isinstance(v, int) and not isinstance(v, bool):
        return f"{v:,}"
    return str(v)


def column_summary(t: dict) -> list[str]:
    """열마다 한 줄 — 타입, 빈 값 수, 숫자는 최소/평균/최대, 날짜는 범위, 문자는 고유값."""
    out = []
    for i, c in enumerate(t["columns"]):
        vals = [r[i] for r in t["rows"] if r[i] is not None]
        nulls = len(t["rows"]) - len(vals)
        label = f" {c['label']}" if c.get("label") and c["label"] != c["name"] else ""
        head = f"- `{c['name']}`{label} ({c['type']}{', 단위 ' + c['unit'] if c.get('unit') else ''})"
        if nulls:
            head += f" · 빈 값 {nulls}"
        if not vals:
            out.append(head + " · 모두 비어 있음")
        elif c["type"] in ("int", "float"):
            out.append(f"{head} · 최소 {_fmt(min(vals))} / 평균 {_fmt(sum(vals) / len(vals))} / 최대 {_fmt(max(vals))}")
        elif c["type"] in ("date", "datetime"):
            out.append(f"{head} · {min(vals)} ~ {max(vals)}")
        else:
            uniq: dict[str, int] = {}
            for v in vals:
                uniq[str(v)] = uniq.get(str(v), 0) + 1
            if len(uniq) <= 12:
                top = ", ".join(f"{k}({n})" for k, n in sorted(uniq.items(), key=lambda x: -x[1]))
                out.append(f"{head} · 값 {len(uniq)}종: {top}")
            else:
                sample = ", ".join(list(uniq)[:5])
                out.append(f"{head} · 고유값 {len(uniq)}개 (예: {sample} …)")
    return out


def header(c: dict) -> str:
    """표 머리 — 한글 이름이 있으면 '가동률(%)', 없으면 열 이름."""
    name = c.get("label") or c["name"]
    return f"{name}({c['unit']})" if c.get("unit") else name


def to_markdown(t: dict, rows: Optional[list[list]] = None, labels: bool = False) -> str:
    rows = t["rows"] if rows is None else rows
    head = "| " + " | ".join(header(c) if labels else c["name"] for c in t["columns"]) + " |"
    sep = "|" + "|".join("---" for _ in t["columns"]) + "|"
    body = ["| " + " | ".join("-" if v is None else _fmt(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else str(v)
                              for v in r) + " |" for r in rows]
    return "\n".join([head, sep, *body])


def json_head(rest: str) -> tuple[str, dict]:
    """표 밖의 JSON(공통 형식의 summary · meta 등) → (summary, 나머지 dict). JSON 이 아니면 (원문, {})."""
    try:
        obj = json.loads(rest) if rest.strip().startswith("{") else None
    except ValueError:
        obj = None
    if not isinstance(obj, dict):
        return rest.strip(), {}
    return str(obj.pop("summary", "") or ""), obj
