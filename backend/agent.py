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
"""
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
from hub import catalog, routing, skills, store
from hub.routing import Plan

MODEL = os.getenv("AGENT_MODEL", "gpt-4o")
TEMPERATURE = float(os.getenv("AGENT_TEMPERATURE", "0.2"))
MAX_TOOL_ROUNDS = int(os.getenv("AGENT_MAX_TOOL_ROUNDS", "8"))  # 한 질문에서 tool 을 부르는 최대 횟수(라운드)
RECURSION_LIMIT = MAX_TOOL_ROUNDS * 2 + 6  # 안전장치 — 정상이면 MAX_TOOL_ROUNDS 에서 먼저 정리된다
HISTORY_TURNS = int(os.getenv("AGENT_HISTORY_TURNS", "10"))     # 원문으로 넣을 최근 턴 수
DIGEST_CHARS = 120         # 오래된 턴 요지의 메시지당 길이
TRACE_RESULT_CHARS = 3000  # 저장할 tool 결과 길이 — 큰 조회 결과가 매 턴 토큰을 먹지 않도록
TRACE_TURNS = 3            # 최근 몇 턴의 trace 를 다시 넣을지

SYSTEM_PROMPT = """당신은 사내 업무 AI 어시스턴트 Coris 입니다.
사용자의 질문에 맞는 도구를 사용해 데이터를 조회 · 분석하고, 명확하고 전문적인 답변을 제공합니다.

[원칙]
- 사용자가 요청하는 기능은 순서 없이 즉시 실행하세요. 안내에 적힌 순서는 권장일 뿐 강제가 아닙니다.
- 조회가 필요하면 "잠시만 기다려 주세요" 같은 안내 없이 바로 tool 을 호출하세요. tool 을 부르지 않고 턴을 끝내면 사용자는 아무 결과도 받지 못합니다.
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
    prompt = SYSTEM_PROMPT + f"\n\n{_now_line()}\n\n[에이전트: {agent['name']}]\n{agent['prompt'].strip()}"
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
    return prompt


def _tool_rounds(messages: list[BaseMessage]) -> int:
    """마지막 사용자 질문 이후 tool 을 부른 횟수 — 이전 턴의 trace 는 세지 않는다."""
    n = 0
    for m in reversed(messages):
        if isinstance(m, HumanMessage):
            break
        if isinstance(m, AIMessage) and m.tool_calls:
            n += 1
    return n


def _build_graph(tools: list):
    llm = chat_model(MODEL, temperature=TEMPERATURE, streaming=True)
    llm_with_tools = llm.bind_tools(tools) if tools else llm
    # 한도 도달 시 — tool 정의는 그대로 두고 호출만 막는다 (tool 메시지가 있는 대화를 거부하는 서버 대비)
    llm_wrap_up = llm.bind_tools(tools, tool_choice="none") if tools else llm

    # config 를 반드시 전달해야 astream_events 가 on_chat_model_stream 을 잡는다
    def agent_node(state: MessagesState, config: RunnableConfig):
        msgs = state["messages"]
        if tools and _tool_rounds(msgs) >= MAX_TOOL_ROUNDS:
            return {"messages": [llm_wrap_up.invoke(msgs + [SystemMessage(content=WRAP_UP)], config)]}
        return {"messages": [llm_with_tools.invoke(msgs, config)]}

    graph = StateGraph(MessagesState)
    graph.add_node("agent", agent_node)
    graph.set_entry_point("agent")
    if tools:
        graph.add_node("tools", ToolNode(tools))
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
    graph = _get_graph(plan.tools)
    started: dict[str, float] = {}
    inputs = to_lc_messages(build_prompt(plan, skill, user_memory), messages, with_trace=bool(plan.tools))

    async for ev in graph.astream_events(
        {"messages": inputs},
        # session_id — 대화별 상태가 필요한 tool(code interpreter 등)이 쓴다 (hub/session_tools.py)
        {"recursion_limit": RECURSION_LIMIT, "configurable": {"session_id": session_id}},
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
