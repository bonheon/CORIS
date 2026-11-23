"""
LangGraph 에이전트 실행부 — chat(스트리밍)과 이벤터(일괄 실행)가 함께 쓴다.

어떤 agent 와 tool 로 실행할지는 hub.routing 이 정하고(Plan), 여기서는 그대로 실행만 한다.
tool 부분집합마다 그래프를 따로 컴파일해 캐시한다.
LLM 이 보는 tool 목록 자체를 줄여야 선택 정확도가 오르기 때문에,
프롬프트로 "이 tool 만 써라" 라고 하는 대신 bind_tools 대상을 바꾼다.

이전 턴의 tool 호출 · 결과(trace)는 대화 기록에 저장해 두었다가 다음 턴에 tool 메시지로
다시 넣는다. 텍스트 답변만 넘기면 "그중 두 번째만 다시 보여줘" 같은 후속 질문에서
LLM 이 앞서 조회한 데이터를 보지 못해 다시 조회하거나 값을 지어낸다.

답변 품질 장치
  - temperature 를 낮게 고정 (AGENT_TEMPERATURE) — 조회 결과 정리가 매번 달라지지 않게
  - 프롬프트에 현재 날짜 · 시각 — "어제", "이번 주" 를 지어내지 않게
  - 대화 기록은 최근 HISTORY_TURNS 턴만 원문으로, 그 이전은 한 줄 요지로 — 긴 대화에서 길이 한도 방지
  - tool 호출이 MAX_TOOL_ROUNDS 번을 넘으면 tool 없이 지금까지 결과로 정리 — 오류로 끊기지 않게

속도 장치 (ReAct 순환 횟수 줄이기)
  - 동시 호출: 서로 의존하지 않는 조회는 한 응답에서 함께 부르라고 프롬프트에 둔다.
    한 응답에 tool 호출이 여럿이면 ToolNode 가 동시에 실행한다 → LLM 왕복이 그만큼 준다.
  - 반복 차단: 같은 질문 안에서 같은 tool · 같은 인자를 다시 부르면 실행하지 않고 안내만 돌려준다
    (오류가 났던 호출은 DUP_ERROR_RETRY 번까지 다시 허용). 대화 상태를 쓰는 tool(run_python 등)과
    AGENT_DUP_EXCLUDE 는 빼고 판단한다. 반복만 하는 라운드가
    DUP_WRAP_ROUNDS 번이면 더 돌지 않고 정리한다.
"""
import json
import logging
import os
import time
from datetime import datetime
from collections import OrderedDict
from typing import AsyncGenerator, Optional

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import StateGraph, MessagesState
from langgraph.prebuilt import ToolNode, tools_condition

from hub.catalog import AGENTS_BY_ID, TOOLS_BY_NAME
from hub.llm import chat_model
from hub import catalog, routing, skills, store, steps, timing
from hub.session_tools import is_session
from hub.routing import Plan

MODEL = os.getenv("AGENT_MODEL", "gpt-4o")
TEMPERATURE = float(os.getenv("AGENT_TEMPERATURE", "0.2"))
MAX_TOOL_ROUNDS = int(os.getenv("AGENT_MAX_TOOL_ROUNDS", "8"))  # 한 질문에서 tool 을 부르는 최대 횟수(라운드)
RECURSION_LIMIT = MAX_TOOL_ROUNDS * 2 + 6  # 안전장치 — 정상이면 MAX_TOOL_ROUNDS 에서 먼저 정리된다
HISTORY_TURNS = int(os.getenv("AGENT_HISTORY_TURNS", "10"))     # 원문으로 넣을 최근 턴 수
DIGEST_CHARS = 120         # 오래된 턴 요지의 메시지당 길이
TRACE_RESULT_CHARS = 3000  # 저장할 tool 결과 길이 — 큰 조회 결과가 매 턴 토큰을 먹지 않도록
TRACE_TURNS = 3            # 최근 몇 턴의 trace 를 다시 넣을지
DUP_ERROR_RETRY = int(os.getenv("AGENT_DUP_ERROR_RETRY", "1"))  # 오류 난 같은 호출을 다시 허용할 횟수 (일시 장애 대비)
DUP_WRAP_ROUNDS = int(os.getenv("AGENT_DUP_WRAP_ROUNDS", "2"))  # 반복 호출만 한 라운드가 이만큼이면 정리
DUP_EXCLUDE = {x.strip() for x in os.getenv("AGENT_DUP_EXCLUDE", "").split(",") if x.strip()}  # 반복 차단에서 뺄 tool
DUP_MARK = "[반복 호출 — 실행하지 않음]"

log = logging.getLogger("agent")

SYSTEM_PROMPT = """당신은 사내 업무 AI 어시스턴트 Coris 입니다.
사용자의 질문에 맞는 도구를 사용해 데이터를 조회 · 분석하고, 명확하고 전문적인 답변을 제공합니다.

[원칙]
- 사용자가 요청하는 기능은 순서 없이 즉시 실행하세요. 안내에 적힌 순서는 권장일 뿐 강제가 아닙니다.
- 조회가 필요하면 "잠시만 기다려 주세요" 같은 안내 없이 바로 tool 을 호출하세요. tool 을 부르지 않고 턴을 끝내면 사용자는 아무 결과도 받지 못합니다.
- 서로 결과에 의존하지 않는 조회(여러 장비 · 여러 Lot · 여러 지표 등)는 한 번의 응답에서 tool 을 여러 개 함께 호출하세요. 하나씩 차례로 부르면 그만큼 답변이 늦어집니다. 앞 결과가 있어야 인자를 정할 수 있는 조회만 차례로 호출합니다.
- 이번 질문에서 이미 같은 인자로 조회한 tool 은 다시 부르지 말고 받은 결과를 쓰세요. 결과가 비었거나 부족하면 인자(기간 · 조건)를 바꾸거나, 확인하지 못했다고 답하세요.
- 아래 [tool 안내] 에 차트 태그가 있는 tool 을 썼다면, 그 형식 그대로 태그를 응답에 포함해 시각화하세요.
- 항상 한국어로 응답합니다."""

WRAP_UP = """[tool 호출 한도 도달]
이번 질문에서 tool 을 더 호출할 수 없습니다. 지금까지 조회한 결과만으로 답변을 정리하세요.
확인하지 못한 부분은 무엇인지 분명히 밝히고, 이어서 확인하려면 어떻게 물어보면 되는지 한 줄로 안내하세요."""

WEEKDAYS = "월화수목금토일"


def _now_line() -> str:
    now = datetime.now()
    return f"[현재 시각] {now:%Y-%m-%d} ({WEEKDAYS[now.weekday()]}) {now:%H:%M} — 날짜 · 요일 · '오늘 · 어제 · 이번 주' 계산은 tool 을 부르지 말고 이 값을 씁니다."


def build_prompt(plan: Plan, skill: Optional[dict], user_memory: str = "") -> str:
    agent = AGENTS_BY_ID[plan.agent_id]
    # 잘 안 바뀌는 것 → 자주 바뀌는 것 순서. LLM 서버의 프롬프트 캐시는 앞부분이 같을 때만 맞으므로
    # 분 단위로 바뀌는 현재 시각은 맨 끝에 둔다 (앞에 두면 그 뒤 agent 프롬프트 · tool 안내까지 캐시가 깨진다)
    prompt = SYSTEM_PROMPT + f"\n\n[에이전트: {agent['name']}]\n{agent['prompt'].strip()}"
    guides = [f"■ {n}\n{catalog.TOOL_GUIDES[n].strip()}" for n in plan.tools if n in catalog.TOOL_GUIDES]
    if guides:  # 켜진 tool 의 안내만 — 꺼진 tool 의 설명이 들어가면 없는 tool 을 부르려 한다
        prompt += "\n\n[tool 안내]\n" + "\n\n".join(guides)
    if skill:
        prompt += (
            f"\n\n[스킬: {skill['name']}]\n{skill['description']}\n"
            f"아래 절차를 따르세요. 사용자가 특정 데이터 하나만 요청하면 해당 tool 만 호출하고 끝냅니다.\n"
            f"{skill['instructions']}"
        )
    prompt += user_memory  # hub.memory.for_prompt() 결과 — 없으면 빈 문자열
    if plan.unavailable:
        # 빠진 tool 을 알리지 않으면 LLM 이 데이터 없이 답을 지어낸다
        prompt += (
            f"\n\n[사용 불가 tool] {', '.join(plan.unavailable)} — 지금 응답하지 않는 tool 입니다. "
            f"이 데이터가 필요한 질문이면 조회할 수 없다고 분명히 알리고 추정으로 채우지 마세요."
        )
    return prompt + f"\n\n{_now_line()}"


def _tool_rounds(messages: list[BaseMessage]) -> int:
    """마지막 사용자 질문 이후 tool 을 부른 횟수 — 이전 턴의 trace 는 세지 않는다."""
    n = 0
    for m in reversed(messages):
        if isinstance(m, HumanMessage):
            break
        if isinstance(m, AIMessage) and m.tool_calls:
            n += 1
    return n


def _this_question(messages: list[BaseMessage]) -> list[BaseMessage]:
    """마지막 사용자 질문 이후 메시지 — 이전 턴 trace 는 반복 판단에 넣지 않는다 (데이터가 바뀌었을 수 있다)."""
    for i in range(len(messages) - 1, -1, -1):
        if isinstance(messages[i], HumanMessage):
            return messages[i + 1:]
    return messages


def _call_key(name: str, args: dict) -> str:
    return name + json.dumps(args or {}, sort_keys=True, ensure_ascii=False, default=str)


def _past_calls(messages: list[BaseMessage]) -> dict[str, dict]:
    """이번 질문에서 실행한 호출 — key → {ok: 성공 횟수, err: 오류 횟수}. 반복 안내로 끝난 호출은 세지 않는다."""
    calls: dict[str, str] = {}  # tool_call_id → key
    seen: dict[str, dict] = {}
    for m in _this_question(messages):
        if isinstance(m, AIMessage):
            for c in m.tool_calls:
                calls[c["id"]] = _call_key(c["name"], c["args"])
        elif isinstance(m, ToolMessage) and m.tool_call_id in calls:
            if isinstance(m.content, str) and m.content.startswith(DUP_MARK):
                continue
            s = seen.setdefault(calls[m.tool_call_id], {"ok": 0, "err": 0})
            s["err" if m.status == "error" else "ok"] += 1
    return seen


def _dup_only_rounds(messages: list[BaseMessage]) -> int:
    """이번 질문에서 모든 결과가 반복 안내뿐이었던 라운드 수."""
    n, results = 0, None
    for m in _this_question(messages) + [None]:
        if m is None or isinstance(m, AIMessage):
            if results and all(isinstance(r.content, str) and r.content.startswith(DUP_MARK) for r in results):
                n += 1
            results = []
        elif isinstance(m, ToolMessage) and results is not None:
            results.append(m)
    return n


def _dup_note(name: str, past: dict) -> str:
    if past["ok"]:
        return (f"{DUP_MARK} {name} 을(를) 이번 질문에서 같은 인자로 이미 조회했습니다. 앞의 결과를 그대로 쓰세요. "
                f"부족하면 인자(기간 · 조건)를 바꿔 조회하거나, 지금까지 결과로 답변하세요.")
    return (f"{DUP_MARK} {name} 을(를) 같은 인자로 {past['err']}번 호출했는데 모두 오류였습니다. "
            f"같은 호출은 다시 하지 말고, 인자를 바꾸거나 확인하지 못했다고 답변하세요.")


def _make_tools_node(tools: list):
    tool_node = ToolNode(tools)
    # 대화 상태를 쓰는 tool(run_python 등)은 같은 입력이라도 결과가 달라질 수 있다 — 반복 차단에서 뺀다
    exempt = DUP_EXCLUDE | {t.name for t in tools if is_session(t)}

    async def tools_node(state: MessagesState, config: RunnableConfig):
        msgs = state["messages"]
        last = msgs[-1]
        past = _past_calls(msgs[:-1])
        run, skipped, batch = [], {}, set()
        for c in last.tool_calls:
            key = _call_key(c["name"], c["args"])
            p = past.get(key)
            repeated = key in batch or (p and (p["ok"] or p["err"] > DUP_ERROR_RETRY))
            if repeated and c["name"] not in exempt:
                # 같은 응답 안 중복은 첫 호출 결과를 쓰게 한다
                skipped[c["id"]] = ToolMessage(content=_dup_note(c["name"], p or {"ok": 1, "err": 0}),
                                               tool_call_id=c["id"], name=c["name"])
            else:
                batch.add(key)
                run.append(c)
        if skipped:
            log.info("반복 호출 %d건 실행 안 함: %s", len(skipped), ", ".join(m.name for m in skipped.values()))
        if not run:
            return {"messages": list(skipped.values())}
        if not skipped:
            return await tool_node.ainvoke(state, config)
        # 새 호출만 실행 — 응답 순서는 원래 호출 순서대로 맞춘다
        out = await tool_node.ainvoke({"messages": msgs[:-1] + [last.model_copy(update={"tool_calls": run})]}, config)
        done = {m.tool_call_id: m for m in out["messages"]}
        return {"messages": [skipped.get(c["id"]) or done[c["id"]] for c in last.tool_calls]}

    return tools_node


def _build_graph(tools: list):
    llm = chat_model(MODEL, temperature=TEMPERATURE, streaming=True)
    llm_with_tools = llm.bind_tools(tools) if tools else llm
    # 한도 도달 시 — tool 정의는 그대로 두고 호출만 막는다 (tool 메시지가 있는 대화를 거부하는 서버 대비)
    llm_wrap_up = llm.bind_tools(tools, tool_choice="none") if tools else llm

    # config 를 반드시 전달해야 astream_events 가 on_chat_model_stream 을 잡는다
    async def agent_node(state: MessagesState, config: RunnableConfig):
        msgs = state["messages"]
        if tools and (_tool_rounds(msgs) >= MAX_TOOL_ROUNDS or _dup_only_rounds(msgs) >= DUP_WRAP_ROUNDS):
            return {"messages": [await llm_wrap_up.ainvoke(msgs + [SystemMessage(content=WRAP_UP)], config)]}
        return {"messages": [await llm_with_tools.ainvoke(msgs, config)]}

    graph = StateGraph(MessagesState)
    graph.add_node("agent", agent_node)
    graph.set_entry_point("agent")
    if tools:
        graph.add_node("tools", _make_tools_node(tools))
        graph.add_conditional_edges("agent", tools_condition)
        graph.add_edge("tools", "agent")
    return graph.compile()


# lazy — main.py 의 load_dotenv() 이후 첫 요청 시점에 만든다
# 사용자가 tool 을 자유롭게 조합하므로 조합 수가 계속 늘 수 있다 — LRU 로 상한
GRAPH_CACHE_MAX = 32
_graphs: "OrderedDict[tuple[str, ...], object]" = OrderedDict()
_graphs_version = 0


def _get_graph(tool_names: list[str]):
    global _graphs_version
    if _graphs_version != catalog.VERSION:  # MCP 를 다시 받아왔으면 낡은 tool 객체를 쥔 그래프는 버린다
        _graphs.clear()
        _graphs_version = catalog.VERSION
    key = tuple(sorted(tool_names))
    if key in _graphs:
        _graphs.move_to_end(key)
    else:
        _graphs[key] = _build_graph([TOOLS_BY_NAME[n] for n in key])
        if len(_graphs) > GRAPH_CACHE_MAX:
            _graphs.popitem(last=False)
    return _graphs[key]


# ── trace: 한 턴 안에서 오간 tool 호출 · 결과 ──────────────────────

def _truncate(text: str) -> str:
    if len(text) <= TRACE_RESULT_CHARS:
        return text
    return text[:TRACE_RESULT_CHARS] + "\n…(이하 생략 — 전체가 필요하면 tool 을 다시 호출)"


def to_trace(new_messages: list[BaseMessage]) -> list[dict]:
    """그래프가 이번 턴에 만든 메시지 중 tool 호출 · 결과만 저장용 dict 로. 최종 답변은 따로 저장된다."""
    trace: list[dict] = []
    for m in new_messages:
        if isinstance(m, AIMessage) and m.tool_calls:
            trace.append({"role": "tool_calls", "content": m.content if isinstance(m.content, str) else "",
                          "tool_calls": [{"id": c["id"], "name": c["name"], "args": c["args"]} for c in m.tool_calls]})
        elif isinstance(m, ToolMessage):
            content = m.content if isinstance(m.content, str) else str(m.content)
            trace.append({"role": "tool", "tool_call_id": m.tool_call_id, "name": m.name, "content": _truncate(content)})
    return trace


def _from_trace(trace: list[dict]) -> list[BaseMessage]:
    """저장된 trace → LangChain 메시지. 호출과 결과 짝이 안 맞는 묶음은 버린다 (API 가 거부한다)."""
    out: list[BaseMessage] = []
    i = 0
    while i < len(trace):
        t = trace[i]
        i += 1
        if t.get("role") != "tool_calls":
            continue
        ids = [c["id"] for c in t["tool_calls"]]
        results = []
        while i < len(trace) and trace[i].get("role") == "tool":
            results.append(trace[i])
            i += 1
        if {r["tool_call_id"] for r in results} != set(ids):
            continue
        out.append(AIMessage(content=t.get("content") or "",
                             tool_calls=[{"id": c["id"], "name": c["name"], "args": c["args"]} for c in t["tool_calls"]]))
        out += [ToolMessage(content=r["content"], tool_call_id=r["tool_call_id"], name=r.get("name")) for r in results]
    return out


def _split_history(messages: list[dict]) -> tuple[list[dict], list[dict]]:
    """(오래된 메시지, 최근 HISTORY_TURNS 턴). 턴 = 사용자 메시지 하나부터 다음 사용자 메시지 전까지."""
    starts = [i for i, m in enumerate(messages) if m["role"] == "user"]
    if len(starts) <= HISTORY_TURNS:
        return [], messages
    cut = starts[-HISTORY_TURNS]
    return messages[:cut], messages[cut:]


def _clip(text: str) -> str:
    text = " ".join(text.split())
    return text[:DIGEST_CHARS] + ("…" if len(text) > DIGEST_CHARS else "")


def _digest(old: list[dict]) -> str:
    """오래된 턴을 한 줄씩 — LLM 호출 없이 앞부분만 잘라 붙인다. 수치가 필요하면 tool 로 다시 조회하게 한다."""
    lines = [f"- {'사용자' if m['role'] == 'user' else '답변'}: {_clip(m['content'])}" for m in old if m.get("content")]
    return (
        f"[앞선 대화 요지 — 오래된 {len(lines)}개 메시지를 줄였습니다. 원문이 아니므로 수치 · 세부 내용이 필요하면 tool 로 다시 확인하세요]\n"
        + "\n".join(lines)
    )


def to_lc_messages(system_prompt: str, messages: list[dict], with_trace: bool = True) -> list:
    """messages 의 assistant 항목에 trace 가 있으면 최근 TRACE_TURNS 턴만 tool 메시지로 펼친다.

    with_trace=False — 이번 턴에 tool 이 하나도 없으면 tool 메시지를 넣지 않는다
    (tool 정의 없이 tool 메시지가 오면 거부하는 모델/서버가 있다).
    """
    lc: list = [SystemMessage(content=system_prompt)]
    old, messages = _split_history(messages)
    if old:
        lc.append(SystemMessage(content=_digest(old)))
    traced = [i for i, m in enumerate(messages) if m["role"] == "assistant" and m.get("trace")][-TRACE_TURNS:]
    for i, m in enumerate(messages):
        if m["role"] == "user":
            if m.get("images"):  # VISION_MODE=direct — 이미지를 agent 모델에 그대로
                lc.append(HumanMessage(content=[{"type": "text", "text": m["content"]}]
                                       + [{"type": "image_url", "image_url": {"url": u}} for u in m["images"]]))
            else:
                lc.append(HumanMessage(content=m["content"]))
        elif m["role"] == "assistant" and m["content"]:
            if with_trace and i in traced:
                lc += _from_trace(m["trace"])
            lc.append(AIMessage(content=m["content"]))
    return lc


async def stream(messages: list[dict], plan: Plan, skill: Optional[dict],
                 user_memory: str = "", session_id: str = "") -> AsyncGenerator[dict, None]:
    """에이전트 실행 이벤트를 순서대로 yield. plan 은 hub.routing.resolve() 결과.

    {"type": "delta", "text": ...}
    {"type": "tool_start", "id", "name", "args"}
    {"type": "tool_end", "id", "name", "ms", "ok"}
    {"type": "trace", "trace": [...]}   마지막 1회 — 저장해 두었다가 다음 턴 messages 에 붙여 넘긴다
    """
    # 단계가 정의된 skill — 단계 실행 엔진이 정해진 순서로 실행한다 (LLM 은 판단 · 보고만)
    if steps.has_steps(skill):
        async for ev in steps.run(messages, skill, session_id):
            yield ev
        return

    graph = _get_graph(plan.tools)
    started: dict[str, float] = {}
    inputs = to_lc_messages(build_prompt(plan, skill, user_memory), messages, with_trace=bool(plan.tools))

    async for ev in graph.astream_events(
        {"messages": inputs},
        # session_id — 대화별 상태가 필요한 tool(code interpreter 등)이 쓴다 (hub/session_tools.py)
        {"recursion_limit": RECURSION_LIMIT, "configurable": {"session_id": session_id},
         "callbacks": timing.callbacks()},  # 응답 시간 측정 — 보통 비어 있다 (hub/timing.py)
        version="v2",
    ):
        kind = ev["event"]
        if kind == "on_chain_end" and not ev.get("parent_ids"):  # 그래프 전체 종료 — 최종 state
            output = ev["data"].get("output") or {}
            new = output.get("messages", [])[len(inputs):] if isinstance(output, dict) else []
            yield {"type": "trace", "trace": to_trace(new)}
            continue
        if kind == "on_chat_model_stream":
            chunk = ev["data"]["chunk"]
            if chunk.content:
                yield {"type": "delta", "text": chunk.content}
        elif kind == "on_tool_start":
            started[ev["run_id"]] = time.perf_counter()
            args = ev["data"].get("input") or {}
            yield {"type": "tool_start", "id": ev["run_id"], "name": ev["name"],
                   "args": args if isinstance(args, dict) else {"input": str(args)}}
        elif kind in ("on_tool_end", "on_tool_error"):
            t0 = started.pop(ev["run_id"], time.perf_counter())
            yield {"type": "tool_end", "id": ev["run_id"], "name": ev["name"],
                   "ms": round((time.perf_counter() - t0) * 1000), "ok": kind == "on_tool_end"}


async def run(messages: list[dict], agent_id: Optional[str], skill_id: Optional[str]) -> tuple[str, list[dict], Plan]:
    """스트리밍 없이 끝까지 실행 — (최종 텍스트, tool 실행 기록, 실행 계획)."""
    skill = skills.get_item(skill_id)
    plan = await routing.resolve(messages, agent_id, skill, None, None)
    skill = skill or skills.get_item(plan.skill_id)  # Router 가 고른 skill
    text: list[str] = []
    runs: dict[str, dict] = {}
    async for ev in stream(messages, plan, skill, session_id=store.new_id("ev")):
        if ev["type"] == "delta":
            text.append(ev["text"])
        elif ev["type"] == "tool_start":
            runs[ev["id"]] = {"name": ev["name"], "args": ev["args"], "ms": None, "ok": None}
        elif ev["type"] == "tool_end" and ev["id"] in runs:
            runs[ev["id"]].update(ms=ev["ms"], ok=ev["ok"])
    return "".join(text), list(runs.values()), plan
