"""
단계 실행 엔진 — SKILL.md 의 inputs · steps 를 정해진 순서대로 실행한다 (skill 실행 방식 ③).

LLM 이 tool 순서 · 인자를 정하지 않는다. 엔진이 단계마다 결과를 보관하고, 앞 결과를 다음 단계 인자로 넣는다.
LLM 은 입력값 추출(필요할 때) · judge 단계 · 문장 조건 · 자유 양식 보고에만 쓴다.

단계 종류 (skills/README.md)
  data      tool 호출. for_each 면 항목마다 동시에 (최대 STEP_CONCURRENCY)
            - id: s3 · type: data · tool: get_eqp_efficiency · for_each: s1.rows
              args: {eqp_id: "{{item.eqp_id}}", date_from: "{{item.track_in|date}}"}
  compute   코드 계산 — op: table(열 템플릿으로 표) | unique(목록 중복 제거) | filter(행 거르기)
  condition if 를 코드로 판단 (empty(x) · not empty(x) · count(x) > 0 · x == "값"), 그 밖의 문장은 LLM 예/아니오
            참이면 then 단계로 건너뛴다 (then: end 면 보고로). verdict 가 있으면 {{verdict}} 로 쓴다
  judge     from 단계 결과 요약을 보고 LLM 이 판단 — prompt · criteria · outputs(JSON 키)
  report    template 에 {{...}} 가 있으면 코드가 채우고, 없으면 LLM 이 skill 본문의 보고 양식대로 쓴다

템플릿 · 참조
  {{input.lot_id}}  {{item}}  {{item.eqp_id}}  {{s1.count}}  {{s1.summary}}  {{s1.eqp_id}}(열 → 목록)
  {{s3[i].bm_hr|first}}(for_each 결과 중 i 번째)  {{table:s6}}(표)  {{s7.text}}  {{verdict}}
  필터: date · first · last · sum · mean · min · max · count · unique · join · round
  문자열 전체가 {{…}} 하나면 원래 타입(목록 · 숫자) 그대로 — tool 인자에 목록을 넘길 수 있다

agent.stream 과 같은 이벤트를 낸다 (tool_start · tool_end · delta · trace) — 채팅 · 스케줄링이 그대로 쓴다.
"""
import asyncio
import json
import logging
import os
import re
import time
import uuid
from typing import Any, AsyncGenerator, Optional

from langchain_core.messages import HumanMessage, SystemMessage

from hub import catalog, offload, tabular
from hub.llm import chat_model

log = logging.getLogger("steps")

ENABLED = os.getenv("STEPS_ENABLED", "1") == "1"
CONCURRENCY = int(os.getenv("STEP_CONCURRENCY", "5"))
JUDGE_MODEL = os.getenv("STEP_JUDGE_MODEL") or os.getenv("AGENT_MODEL", "gpt-4o")
SMALL_MODEL = os.getenv("ROUTER_MODEL", "gpt-4o-mini")
JUDGE_TABLE_ROWS = 40      # judge 에 표를 통째로 보여줄 최대 행 수 (넘으면 열 통계 + 앞 10행)
JUDGE_TEXT_CHARS = 3000

_PH = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}")
_REF = re.compile(r"^(input|item|verdict|s\w*|[A-Za-z_]\w*)(\[i\])?((?:\.[^.|\s]+)*)$")


def has_steps(skill: Optional[dict]) -> bool:
    return bool(ENABLED and skill and (skill.get("extra") or {}).get("steps"))


class StepError(Exception):
    pass


# ── 결과 · 참조 ───────────────────────────────────────────────

def _result(text: str) -> dict:
    """tool 결과 텍스트 → 단계 결과. 표가 있으면 rows(dict 목록), JSON 이면 json 도 보관."""
    tables, rest = tabular.parse(text)
    out: dict[str, Any] = {"text": text}
    try:
        out["json"] = json.loads(text) if text.strip()[:1] in "[{" else None
    except ValueError:
        out["json"] = None
    summary, extra = tabular.json_head(rest) if rest else ("", {})
    out["summary"] = summary or (rest.strip()[:300] if rest else "")
    out["meta"] = (extra or {}).get("meta") or (out["json"] or {}).get("meta") if isinstance(out["json"], dict) else (extra or {}).get("meta")
    if tables:
        t = max(tables, key=lambda x: len(x["rows"]))   # 가장 큰 표를 기본 표로
        names = [c["name"] for c in t["columns"]]
        out |= {"table": t, "tables": tables, "columns": names,
                "rows": [dict(zip(names, r)) for r in t["rows"]], "count": len(t["rows"])}
    else:
        out |= {"table": None, "tables": [], "columns": [], "rows": [], "count": 0}
    return out


def _merge(items: list[dict]) -> dict:
    """for_each 결과 → 하나로 (rows 는 이어 붙이고 _i 로 몇 번째 항목인지 표시)."""
    rows = [r | {"_i": i} for i, it in enumerate(items) for r in it.get("rows", [])]
    cols = next((it["columns"] for it in items if it.get("columns")), [])
    return {"items": items, "rows": rows, "columns": cols + ["_i"], "count": len(rows),
            "summary": f"{len(items)}회 호출 · {len(rows)}행", "table": None, "json": None}


def _get(obj: Any, key: str) -> Any:
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        if isinstance(obj.get("rows"), list) and obj["rows"] and key in (obj.get("columns") or obj["rows"][0]):
            return [r.get(key) for r in obj["rows"]]   # 열 이름 → 그 열의 값 목록
        if isinstance(obj.get("json"), dict) and key in obj["json"]:
            return obj["json"][key]
        return None
    if isinstance(obj, list):
        if key.isdigit():
            return obj[int(key)] if int(key) < len(obj) else None
        return [_get(x, key) for x in obj]
    return None


def _num(xs) -> list[float]:
    return [float(x) for x in (xs if isinstance(xs, list) else [xs]) if isinstance(x, (int, float)) and not isinstance(x, bool)]


def _filter(v: Any, f: str) -> Any:
    name, _, arg = f.partition("(")
    arg = arg.rstrip(")")
    lst = v if isinstance(v, list) else [v]
    if name == "date":
        return [str(x)[:10] if x else x for x in v] if isinstance(v, list) else (str(v)[:10] if v else v)
    if name == "first":
        return lst[0] if lst else None
    if name == "last":
        return lst[-1] if lst else None
    if name == "count":
        return len(lst) if v is not None else 0
    if name == "unique":
        return list(dict.fromkeys(x for x in lst if x not in (None, "")))
    if name == "join":
        return (arg.strip("'\"") or ", ").join(str(x) for x in lst if x not in (None, ""))
    if name in ("sum", "mean", "min", "max"):
        nums = _num(lst)
        if not nums:
            return None
        return {"sum": sum(nums), "mean": sum(nums) / len(nums), "min": min(nums), "max": max(nums)}[name]
    if name == "round":
        n = int(arg or 1)
        return [round(x, n) if isinstance(x, float) else x for x in v] if isinstance(v, list) else (round(v, n) if isinstance(v, float) else v)
    raise StepError(f"모르는 필터 '{name}'")


class Ctx:
    def __init__(self, inputs: dict, defined: tuple = ()):
        self.inputs = inputs
        self.defined = set(defined)   # 정의된 단계 id — 조건으로 건너뛴 단계를 참조하면 오류 대신 빈 값
        self.results: dict[str, dict] = {}
        self.verdict: Optional[str] = None

    def ref(self, expr: str, item: Any = None, i: Optional[int] = None) -> Any:
        expr, *filters = [x.strip() for x in expr.split("|")]
        m = _REF.match(expr)
        if not m:
            raise StepError(f"참조 형식 오류 '{expr}'")
        head, idx, path = m.group(1), m.group(2), m.group(3)
        if head == "input":
            v: Any = self.inputs
        elif head == "item":
            v = item
        elif head == "verdict":
            v = self.verdict
        elif head in self.results:
            v = self.results[head]
            if idx:
                if i is None or "items" not in v:
                    raise StepError(f"'{expr}' — [i] 는 for_each 단계 결과에 for_each 안에서만 쓸 수 있습니다")
                v = v["items"][i] if i < len(v["items"]) else None
        elif head in self.defined:
            return None   # 건너뛴 단계
        else:
            raise StepError(f"알 수 없는 참조 '{head}' (오타이거나 아직 정의되지 않은 단계)")
        for key in [p for p in path.split(".") if p]:
            v = _get(v, key)
        for f in filters:
            v = _filter(v, f)
        return v

    def render(self, value: Any, item: Any = None, i: Optional[int] = None) -> Any:
        """템플릿 채우기. 문자열 전체가 {{x}} 하나면 원래 타입 그대로."""
        if isinstance(value, dict):
            return {k: self.render(v, item, i) for k, v in value.items()}
        if isinstance(value, list):
            return [self.render(v, item, i) for v in value]
        if not isinstance(value, str):
            return value
        whole = _PH.fullmatch(value.strip())
        if whole and not whole.group(1).startswith("table:"):
            return self.ref(whole.group(1), item, i)

        def sub(m):
            e = m.group(1)
            if e.startswith("table:"):
                return self.table_md(e[6:].strip())
            v = self.ref(e, item, i)
            if v is None:
                return "-"
            if isinstance(v, float):
                return f"{v:,.2f}".rstrip("0").rstrip(".")
            if isinstance(v, list):
                return ", ".join(str(x) for x in v)
            return str(v)
        return _PH.sub(sub, value)

    def table_md(self, sid: str) -> str:
        r = self.results.get(sid)
        if not r:
            return "(표 없음)"
        cols = [c for c in r.get("columns") or [] if c != "_i"]
        if not r.get("rows"):
            return "(해당 없음)"
        t = r.get("table") or {"columns": [{"name": c} for c in cols], "rows": [[row.get(c) for c in cols] for row in r["rows"]]}
        return tabular.to_markdown(t, labels=True)


# ── 조건식 ────────────────────────────────────────────────────

_COND = re.compile(r"^\s*(not\s+)?(empty|count)\(\s*([^)]+)\)\s*(?:(==|!=|>=|<=|>|<)\s*(-?\d+(?:\.\d+)?))?\s*$")
_EQ = re.compile(r"^\s*([\w.\[\]|]+)\s*(==|!=)\s*['\"]?(.*?)['\"]?\s*$")


def _cond_code(expr: str, ctx: Ctx) -> Optional[bool]:
    """코드로 판단할 수 있는 식이면 True/False, 아니면 None (LLM 으로)."""
    m = _COND.match(expr)
    if m:
        neg, fn, ref, op, num = m.groups()
        v = ctx.ref(ref)
        n = len(v) if isinstance(v, (list, dict)) else (0 if v in (None, "") else 1)
        if fn == "empty":
            res = n == 0
        else:
            num_v = float(num) if num is not None else 0
            res = {"==": n == num_v, "!=": n != num_v, ">=": n >= num_v, "<=": n <= num_v, ">": n > num_v,
                   "<": n < num_v, None: n > 0}[op]
        return (not res) if neg else res
    m = _EQ.match(expr)
    if m:
        try:
            v = ctx.ref(m.group(1))
        except StepError:
            return None
        res = str(v) == m.group(3)
        return res if m.group(2) == "==" else not res
    return None


# ── LLM ───────────────────────────────────────────────────────

_models: dict[str, Any] = {}


def _llm(name: str, temperature: float = 0.0):
    key = f"{name}@{temperature}"
    if key not in _models:
        _models[key] = chat_model(name, temperature=temperature)
    return _models[key]


def _json_reply(text: str) -> dict:
    s = text.strip()
    if s.startswith("```"):
        s = s.strip("`").split("\n", 1)[-1]
    a, b = s.find("{"), s.rfind("}")
    try:
        return json.loads(s[a:b + 1]) if a >= 0 else {}
    except ValueError:
        return {}


def _brief(sid: str, ctx: Ctx, steps_by_id: dict) -> str:
    """judge · 보고에 넘길 단계 결과 요약 — 표가 작으면 통째로, 크면 열 통계 + 앞 10행."""
    r = ctx.results.get(sid) or {}
    title = (steps_by_id.get(sid) or {}).get("title", sid)
    lines = [f"### {sid} · {title}"]
    if r.get("summary"):
        lines.append(str(r["summary"]))
    if r.get("items") is not None:
        for k, it in enumerate(r["items"]):
            lines.append(f"- 항목 {k}: {it.get('summary') or ''}")
            if it.get("table") and it["rows"]:
                lines.append(tabular.to_markdown(it["table"], it["table"]["rows"][:JUDGE_TABLE_ROWS], labels=True))
            elif it.get("json") is not None:
                lines.append(json.dumps(it["json"], ensure_ascii=False)[:JUDGE_TEXT_CHARS // max(1, len(r["items"]))])
    elif r.get("table") and r.get("rows"):
        t = r["table"]
        if len(t["rows"]) <= JUDGE_TABLE_ROWS:
            lines.append(tabular.to_markdown(t, labels=True))
        else:
            lines += ["열 통계:", *tabular.column_summary(t), "앞 10행:", tabular.to_markdown(t, t["rows"][:10], labels=True)]
    elif r.get("rows"):
        lines.append(ctx.table_md(sid))
    else:
        other = {k: v for k, v in r.items() if k not in ("text", "json", "table", "tables", "rows", "columns", "count", "summary", "meta")}
        lines.append(json.dumps(other or r.get("json") or r.get("text"), ensure_ascii=False, default=str)[:JUDGE_TEXT_CHARS])
    return "\n".join(lines)


async def _extract_inputs(spec: list[dict], messages: list[dict]) -> dict:
    users = [m["content"] for m in messages if m["role"] == "user"][-3:]
    fields = "\n".join(f"- {x['name']}: {x.get('label', x['name'])}" + (f" (예: {x['example']})" if x.get("example") else "") for x in spec)
    msg = await _llm(SMALL_MODEL).ainvoke([
        SystemMessage(content="사용자 말에서 아래 입력값을 찾아 JSON 하나로만 답하세요. 없으면 null. 값을 지어내지 마세요.\n" + fields),
        HumanMessage(content="\n".join(users)),
    ])
    got = _json_reply(msg.content)
    return {x["name"]: got.get(x["name"]) for x in spec}


# ── 실행 ──────────────────────────────────────────────────────

async def _call_tool(name: str, args: dict, session_id: str) -> str:
    tool = catalog.RAW_TOOLS.get(name)
    if tool is None:
        raise StepError(f"tool '{name}' 을 지금 쓸 수 없습니다 (MCP 서버 확인)")
    res = await tool.ainvoke(args, config={"configurable": {"session_id": session_id}})
    return offload._text(res)


def _ev_start(name: str, args: dict) -> dict:
    return {"type": "tool_start", "id": "st_" + uuid.uuid4().hex[:10], "name": name, "args": args}


async def run(messages: list[dict], skill: dict, session_id: str) -> AsyncGenerator[dict, None]:
    extra = skill.get("extra") or {}
    steps = list(extra.get("steps") or [])
    by_id = {s["id"]: s for s in steps}
    spec = list(extra.get("inputs") or [])

    # 1) 입력값
    inputs = {}
    if spec:
        ev = _ev_start("입력값 확인", {"항목": ", ".join(x.get("label", x["name"]) for x in spec)})
        t0 = time.perf_counter()
        yield ev
        inputs = await _extract_inputs(spec, messages)
        yield {"type": "tool_end", "id": ev["id"], "name": ev["name"], "ms": round((time.perf_counter() - t0) * 1000), "ok": True}
        missing = [x for x in spec if x.get("required") and not inputs.get(x["name"])]
        if missing:
            ask = ", ".join(f"{x.get('label', x['name'])}" + (f"(예: {x['example']})" if x.get("example") else "") for x in missing)
            yield {"type": "delta", "text": f"'{skill['name']}' 을 실행하려면 {ask} 이(가) 필요합니다. 알려주세요."}
            yield {"type": "trace", "trace": []}
            return
    ctx = Ctx(inputs, tuple(by_id))

    # 2) 단계
    final_text: Optional[str] = None
    k = 0
    while k < len(steps):
        st = steps[k]
        sid, typ, title = st["id"], st.get("type", "data"), st.get("title", st["id"])
        k += 1
        try:
            if typ == "data":
                async for ev in _run_data(st, ctx, session_id):
                    yield ev
            elif typ == "compute":
                ev = _ev_start(f"{sid} · {title}", {"op": st.get("op", "table")})
                t0 = time.perf_counter()
                yield ev
                ctx.results[sid] = _compute(st, ctx)
                yield {"type": "tool_end", "id": ev["id"], "name": ev["name"], "ms": round((time.perf_counter() - t0) * 1000), "ok": True}
            elif typ == "condition":
                ev = _ev_start(f"{sid} · {title}", {"if": st.get("if", "")})
                t0 = time.perf_counter()
                yield ev
                hit = _cond_code(st.get("if", ""), ctx)
                if hit is None:   # 문장으로 쓴 조건 — LLM 예/아니오
                    refs = sorted(set(re.findall(r"\b(s\w+)\b", st.get("if", ""))) & set(ctx.results)) or list(ctx.results)[-2:]
                    msg = await _llm(SMALL_MODEL).ainvoke([
                        SystemMessage(content="아래 결과를 보고 조건이 참인지 '예' 또는 '아니오' 한 단어로만 답하세요."),
                        HumanMessage(content="\n\n".join(_brief(r, ctx, by_id) for r in refs) + f"\n\n조건: {st.get('if')}"),
                    ])
                    hit = msg.content.strip().startswith("예")
                ctx.results[sid] = {"value": hit, "summary": f"조건 {'참' if hit else '거짓'}"}
                yield {"type": "tool_end", "id": ev["id"], "name": ev["name"], "ms": round((time.perf_counter() - t0) * 1000), "ok": True}
                if hit:
                    if st.get("verdict"):
                        ctx.verdict = st["verdict"]
                    target = st.get("then")
                    if target in (None, "end", "report"):
                        k = next((n for n, s in enumerate(steps) if s.get("type") == "report"), len(steps))
                    elif target in by_id:
                        k = next(n for n, s in enumerate(steps) if s["id"] == target)
            elif typ == "judge":
                ev = _ev_start(f"{sid} · {title}", {"근거": ", ".join(st.get("from") or [])})
                t0 = time.perf_counter()
                yield ev
                ctx.results[sid] = await _judge(st, ctx, by_id, skill)
                if ctx.results[sid].get("verdict"):
                    ctx.verdict = ctx.results[sid]["verdict"]
                yield {"type": "tool_end", "id": ev["id"], "name": ev["name"], "ms": round((time.perf_counter() - t0) * 1000), "ok": True}
            elif typ == "report":
                ev = _ev_start(f"{sid} · {title}", {})
                t0 = time.perf_counter()
                yield ev
                final_text = await _report(st, ctx, by_id, skill, messages)
                yield {"type": "tool_end", "id": ev["id"], "name": ev["name"], "ms": round((time.perf_counter() - t0) * 1000), "ok": True}
                break
            else:
                raise StepError(f"모르는 단계 종류 '{typ}'")
        except Exception as e:  # noqa: BLE001 — 실패한 단계를 밝히고 멈춘다
            log.exception("step %s failed", sid)
            yield {"type": "delta", "text": f"⚠️ {sid} · {title} 단계에서 멈췄습니다 — {e}\n"}
            yield {"type": "trace", "trace": []}
            return

    if final_text is None:   # report 단계가 없으면 — 마지막 judge 의 글 또는 단계 요약
        last = next((ctx.results[s["id"]] for s in reversed(steps) if s.get("type") == "judge" and s["id"] in ctx.results), None)
        final_text = (last or {}).get("text") or "\n\n".join(_brief(s["id"], ctx, by_id) for s in steps if s["id"] in ctx.results)
    yield {"type": "delta", "text": final_text}
    # 다음 턴이 이번 결과를 이어 쓰도록 — 단계 요약을 한 덩어리로 남긴다
    digest = "\n\n".join(_brief(s["id"], ctx, by_id) for s in steps if s["id"] in ctx.results)[:6000]
    yield {"type": "trace", "trace": [
        {"role": "tool_calls", "content": "", "tool_calls": [{"id": "steps", "name": "skill_steps", "args": {"skill": skill["id"]}}]},
        {"role": "tool", "tool_call_id": "steps", "name": "skill_steps", "content": digest},
    ]}


async def _run_data(st: dict, ctx: Ctx, session_id: str) -> AsyncGenerator[dict, None]:
    sid, name = st["id"], st["tool"]
    if st.get("for_each"):
        items = ctx.ref(st["for_each"])
        items = items if isinstance(items, list) else ([] if items is None else [items])
        sem = asyncio.Semaphore(CONCURRENCY)
        calls = [(i, it, ctx.render(st.get("args") or {}, it, i)) for i, it in enumerate(items)]
        starts = [_ev_start(name, args) for _, _, args in calls]
        for ev in starts:
            yield ev
        t0 = time.perf_counter()

        async def one(args):
            async with sem:
                return await _call_tool(name, args, session_id)
        outs = await asyncio.gather(*(one(a) for _, _, a in calls), return_exceptions=True)
        ms = round((time.perf_counter() - t0) * 1000)
        results = []
        for ev, out in zip(starts, outs):
            ok = not isinstance(out, BaseException)
            yield {"type": "tool_end", "id": ev["id"], "name": name, "ms": ms, "ok": ok}
            results.append(_result(out) if ok else {"error": str(out)[:200], "rows": [], "columns": [], "count": 0, "summary": f"실패: {out}"})
        ctx.results[sid] = _merge(results)
        return
    args = ctx.render(st.get("args") or {})
    ev = _ev_start(name, args)
    yield ev
    t0 = time.perf_counter()
    out = await _call_tool(name, args, session_id)
    yield {"type": "tool_end", "id": ev["id"], "name": name, "ms": round((time.perf_counter() - t0) * 1000), "ok": True}
    ctx.results[sid] = _result(out)


def _compute(st: dict, ctx: Ctx) -> dict:
    op = st.get("op", "table")
    if op == "unique":
        vals = _filter(ctx.ref(st["of"]), "unique")
        return {"values": vals, "rows": [{"value": v} for v in vals], "columns": ["value"], "count": len(vals),
                "summary": f"{len(vals)}개: {', '.join(map(str, vals))}"}
    if op == "filter":   # of: 행 목록 참조, column + (in | equals | not_empty)
        src = ctx.ref(st["of"])
        rows = src if isinstance(src, list) else (src or {}).get("rows", [])
        col = st["column"]
        if st.get("not_empty"):
            keep = [r for r in rows if r.get(col) not in (None, "")]
        else:
            allowed = [str(x) for x in (st.get("in") or [st.get("equals")])]
            keep = [r for r in rows if str(r.get(col)) in allowed]
        cols = list(keep[0].keys()) if keep else []
        return {"rows": keep, "columns": cols, "count": len(keep), "summary": f"{len(keep)}행"}
    if op == "table":
        cols: dict = st.get("columns") or {}
        if st.get("for_each"):
            items = ctx.ref(st["for_each"])
            items = items if isinstance(items, list) else []
            rows = [{c: ctx.render(tpl, it, i) for c, tpl in cols.items()} for i, it in enumerate(items)]
        else:
            rows = [{c: ctx.render(tpl) for c, tpl in cols.items()}]
        names = list(cols)
        table = {"name": st.get("title", st["id"]), "columns": [{"name": n, "type": "string"} for n in names],
                 "rows": [[r[n] for n in names] for r in rows]}
        return {"rows": rows, "columns": names, "count": len(rows), "table": table, "summary": f"표 {len(rows)}행"}
    raise StepError(f"모르는 compute op '{op}'")


async def _judge(st: dict, ctx: Ctx, by_id: dict, skill: dict) -> dict:
    srcs = st.get("from") or list(ctx.results)
    outputs = list(st.get("outputs") or [])
    crit = st.get("criteria") or []
    crit_txt = "\n".join(f"- {c.get('verdict')}: {c.get('when')}" for c in crit if isinstance(c, dict))
    outputs = [o for o in outputs if o != "verdict"]
    # 기준이 있으면 checks(기준마다 참/거짓) 를 verdict 보다 먼저 쓰게 한다 — 먼저 고르고 근거를 끼워 맞추지 않게
    keys = (["checks", "verdict"] if crit else []) + outputs + ["text"]
    sys = (f"당신은 '{skill['name']}' 절차의 판단 단계를 맡았습니다. 아래 결과만 근거로 판단합니다. 수치는 결과 값 그대로 씁니다. 한국어로 씁니다.\n"
           f"단계: {st.get('title', st['id'])}\n" + (f"지시: {st['prompt']}\n" if st.get("prompt") else "")
           + (f"판정 기준:\n{crit_txt}\n기준을 위에서부터 하나씩 결과와 대조해 checks 에 [{{\"verdict\": 판정, \"met\": true|false, \"why\": 근거 수치}}] 로 적고, "
              "met 이 처음 true 인 판정을 verdict 로 고릅니다.\n" if crit_txt else "")
           + f"\nJSON 하나로만, 키 순서대로 답합니다: {', '.join(keys)} — text 는 판단 근거를 사람이 읽을 문장으로(마크다운 가능).")
    msg = await _llm(JUDGE_MODEL, 0.2).ainvoke([SystemMessage(content=sys),
                                               HumanMessage(content="\n\n".join(_brief(s, ctx, by_id) for s in srcs if s in ctx.results))])
    out = _json_reply(msg.content)
    if not out:
        out = {"text": msg.content}
    checks = out.get("checks") if isinstance(out.get("checks"), list) else []
    first = next((c.get("verdict") for c in checks if isinstance(c, dict) and c.get("met") is True), None)
    if crit and first and out.get("verdict") != first:   # 고른 판정과 checks 가 어긋나면 checks 를 따른다 (규칙: 처음 참인 것)
        log.warning("judge %s: verdict '%s' → checks 기준 '%s' 로 고침", st["id"], out.get("verdict"), first)
        out["verdict"] = first
    out.setdefault("text", "")
    out["summary"] = (out.get("verdict") or "") + (" — " if out.get("verdict") else "") + str(out.get("text", ""))[:200]
    return out


async def _report(st: dict, ctx: Ctx, by_id: dict, skill: dict, messages: list[dict]) -> str:
    tpl = st.get("template") or ""
    if _PH.search(tpl):   # 코드가 채운다 — 표 · 수치가 항상 같은 모양
        return ctx.render(tpl)
    # 자유 양식 — skill 본문의 보고 양식대로 LLM 이 쓴다 (단계 결과 요약만 근거)
    body = skill.get("instructions") or ""
    form = body[body.find("## 보고 양식"):] if "## 보고 양식" in body else (tpl or body)
    msg = await _llm(JUDGE_MODEL, 0.2).ainvoke([
        SystemMessage(content=f"'{skill['name']}' 의 마지막 보고 단계입니다. 아래 단계 결과만 근거로, 보고 양식 그대로 씁니다. "
                              f"수치는 결과 값 그대로, 양식의 제목 · 순서를 바꾸지 않습니다.\n\n입력값: {json.dumps(ctx.inputs, ensure_ascii=False)}"
                              + (f"\n판정: {ctx.verdict}" if ctx.verdict else "") + f"\n\n{form}"),
        HumanMessage(content="\n\n".join(_brief(s["id"], ctx, by_id) for s in by_id.values() if s["id"] in ctx.results)),
    ])
    return msg.content


# ── 검사 (저장 전) ────────────────────────────────────────────

TYPES = ("data", "compute", "condition", "judge", "report")


def validate(steps_: list[dict], inputs: list[dict], known_tools: set[str]) -> list[str]:
    """단계 정의 검사 — 저장 전에 고칠 수 있게 사람이 읽을 오류 목록을 돌려준다 (비어 있으면 통과)."""
    errs: list[str] = []
    names = [x.get("name") for x in inputs]
    if any(not n or not re.match(r"^[A-Za-z_]\w*$", str(n)) for n in names):
        errs.append("입력값 이름은 영문 · 숫자 · _ 로 (예: lot_id)")
    seen: list[str] = []
    for n, st in enumerate(steps_, 1):
        sid, typ = st.get("id"), st.get("type")
        where = f"{n}번 단계({sid or '?'})"
        if not sid or not re.match(r"^[A-Za-z_]\w*$", str(sid)):
            errs.append(f"{where}: id 는 영문 · 숫자 · _ 로 (예: s1)")
        elif sid in seen:
            errs.append(f"{where}: id '{sid}' 가 겹칩니다")
        if typ not in TYPES:
            errs.append(f"{where}: 종류는 {', '.join(TYPES)} 중 하나")
        if typ == "data" and st.get("tool") not in known_tools:
            errs.append(f"{where}: tool '{st.get('tool')}' 이 없습니다")
        if typ == "condition" and not st.get("if"):
            errs.append(f"{where}: 조건(if)을 적어 주세요")
        if typ == "condition" and st.get("then") not in (None, "", "end", "report", *[x.get("id") for x in steps_]):
            errs.append(f"{where}: 건너뛸 단계 '{st.get('then')}' 이 없습니다")
        if typ == "compute" and st.get("op", "table") == "table" and not st.get("columns"):
            errs.append(f"{where}: 표 열(columns)을 하나 이상")
        if typ == "judge" and not (st.get("prompt") or st.get("criteria")):
            errs.append(f"{where}: 판단 지시(prompt)를 적어 주세요")
        # 참조는 앞 단계 · 입력값만 — 뒤 단계를 참조하면 아직 결과가 없다
        text = json.dumps({k: v for k, v in st.items() if k not in ("id", "title")}, ensure_ascii=False)
        ids = [x.get("id") for x in steps_]
        for ref in set(re.findall(r"\{\{\s*(s\w*)(?:\[i\])?[.|\s}]", text)) | set(re.findall(r"^\s*(?:not\s+)?\w+\(\s*(s\w*)\.", str(st.get("if") or st.get("for_each") or st.get("of") or ""))) | set(st.get("from") or []):
            if ref not in ids:
                errs.append(f"{where}: 정의되지 않은 단계 '{ref}' 를 참조합니다")
            elif ref not in seen and typ != "report":
                errs.append(f"{where}: 뒤 단계 '{ref}' 를 참조합니다 — 앞 단계 결과만 쓸 수 있습니다")
        for ref in re.findall(r"input\.(\w+)", text):
            if ref not in names:
                errs.append(f"{where}: 입력값 '{ref}' 가 정의되지 않았습니다")
        if sid:
            seen.append(sid)
    if steps_ and sum(1 for s in steps_ if s.get("type") == "report") > 1:
        errs.append("보고(report) 단계는 하나만")
    return errs
