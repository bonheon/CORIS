"""
분기점(agent · skill 선택) + 최종 tool 계산.

1) candidates(): 사용자가 고른 tool · skill 필수 tool 을 모두 쓸 수 있는 agent 만 후보로 남긴다.
   → Router 가 사용자 선택과 어긋난 agent 를 고를 수 없다.
   skill_candidates(): 사용자가 skill 을 고르지 않았으면, 필수 tool 을 후보 agent 가 쓸 수 있는
   skill 만 후보로 남긴다.
2) route(): agent 후보가 여럿이거나 skill 후보가 있을 때만 LLM 한 번 — agent 와 skill 을 같이 고른다.
   직전 턴의 agent · skill 을 유지하는 쪽으로 기울인다(sticky) — 여러 턴짜리 workflow 가
   중간에 사용자 답("2번 공정", "계속")을 받아도 끊기지 않게.
   단발 조회 질문이면 skill 은 고르지 않는다(none).
3) plan_tools(): 최종 tool 을 규칙으로 계산 — LLM 이 아니라 코드가 정한다.

     기본   = 사용자가 고른 group·tool  (없으면 skill tool, 그것도 없으면 agent 기본 group)
     최종   = (기본 ∪ skill 필수 tool) − 사용자가 끈 tool(필수 tool 제외)
              ∩ agent 허용 범위 ∩ 현재 사용 가능한 tool
   빠진 tool 은 이유와 함께 dropped 로 돌려준다 (route 이벤트 · 프롬프트에 노출).
"""
import logging
import os
from dataclasses import asdict, dataclass, field
from typing import Literal, Optional

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field, create_model

from hub import catalog, skills
from hub.llm import chat_model

log = logging.getLogger("routing")

ROUTER_MODEL = os.getenv("ROUTER_MODEL", "gpt-4o-mini")
MAX_TOOLS = 15          # 이 이상이면 선택 정확도가 눈에 띄게 떨어진다 — 경고만
ROUTER_HISTORY = 6      # Router 에 보여줄 최근 메시지 수
ROUTER_MSG_CHARS = 400  # 메시지당 길이 제한 (차트 태그 · 표가 긴 답변 대비)
SKILL_DESC_CHARS = 300  # Router 에 보여줄 skill 설명 길이
AUTO_SKILL = os.getenv("AUTO_SKILL", "1") != "0"  # 0 이면 사용자가 고른 skill 만 쓴다
NO_SKILL = "none"


class ToolSelection(BaseModel):
    groups: list[str] = []
    tools: list[str] = []
    exclude: list[str] = []


@dataclass
class Plan:
    agent_id: str
    route_mode: str                      # manual | single | sticky | router | fallback
    route_reason: str
    tools: list[str]
    locked: list[str]                    # skill 필수 tool — 끌 수 없음
    dropped: list[dict] = field(default_factory=list)   # {name, reason}
    warnings: list[str] = field(default_factory=list)
    skill_id: Optional[str] = None
    skill_name: Optional[str] = None
    skill_mode: str = "none"             # none | manual | router | sticky

    @property
    def unavailable(self) -> list[str]:
        return [d["name"] for d in self.dropped if d["reason"] == "unavailable"]

    def summary(self) -> dict:
        agent = catalog.AGENTS_BY_ID[self.agent_id]
        return {"agent_name": agent["name"]} | asdict(self)

    def event(self) -> dict:
        return {"type": "route"} | self.summary()


# ── 선택 해석 ──────────────────────────────────────────────────

def _expand(sel: ToolSelection, warnings: list[str]) -> list[str]:
    unknown_g = [g for g in sel.groups if g not in catalog.GROUPS_BY_ID]
    if unknown_g:
        warnings.append(f"알 수 없는 group 무시: {', '.join(unknown_g)}")
    picked = catalog.group_tools(g for g in sel.groups if g in catalog.GROUPS_BY_ID)
    return list(dict.fromkeys(picked + sel.tools))


def skill_tools(skill: Optional[dict]) -> list[str]:
    return list(skill["tools"]) if skill and skill.get("tools") else []


def candidates(sel: ToolSelection, skill: Optional[dict]) -> list[str]:
    """요청된 tool(사용자 선택 + skill 필수)을 모두 허용하는 agent. 하나도 없으면 fallback 하나."""
    need = set(_expand(sel, [])) | set(skill_tools(skill))
    ok = [a["id"] for a in catalog.AGENTS if need <= set(catalog.agent_pool(a["id"]))]
    return ok or [catalog.FALLBACK_AGENT]


def skill_candidates(agent_ids: list[str], pool: Optional[list[dict]] = None) -> list[dict]:
    """필수 tool 을 후보 agent 중 하나라도 모두 쓸 수 있는 skill. pool 이 없으면 전체 skill 중에서."""
    pools = [set(catalog.agent_pool(a)) for a in agent_ids]
    items = skills.list_items() if pool is None else pool
    return [s for s in items if any(set(s["tools"]) <= p for p in pools)]


def plan_tools(agent_id: str, sel: ToolSelection, skill: Optional[dict],
               route_mode: str = "manual", route_reason: str = "", skill_mode: Optional[str] = None) -> Plan:
    warnings: list[str] = []
    locked = skill_tools(skill)
    picked = _expand(sel, warnings)

    base = picked or locked or catalog.agent_defaults(agent_id)
    wanted = list(dict.fromkeys(base + locked))

    blocked = [n for n in sel.exclude if n in locked]
    if blocked:
        warnings.append(f"skill 필수 tool 은 끌 수 없음: {', '.join(blocked)}")
    excluded = set(sel.exclude) - set(locked)
    pool = set(catalog.agent_pool(agent_id))

    tools, dropped = [], []
    for name in wanted:
        if name in excluded:
            dropped.append({"name": name, "reason": "excluded"})
        elif name not in catalog.TOOLS_BY_NAME:
            dropped.append({"name": name, "reason": "unavailable"})
        elif name not in pool:
            dropped.append({"name": name, "reason": "not_allowed"})
        else:
            tools.append(name)

    outside = [d["name"] for d in dropped if d["reason"] == "not_allowed" and d["name"] in picked]
    if outside:
        warnings.append(f"선택한 tool 중 이 agent 허용 범위 밖이라 제외됨: {', '.join(outside)}")
    if not tools:
        warnings.append("켜진 tool 이 없어 조회 없이 답변합니다")
    if any(d["name"] in locked and d["reason"] != "excluded" for d in dropped):
        warnings.append("skill 필수 tool 일부를 쓸 수 없어 절차가 끝까지 진행되지 않을 수 있음")
    if len(tools) > MAX_TOOLS:
        warnings.append(f"tool {len(tools)}개 — {MAX_TOOLS}개를 넘으면 선택 정확도가 떨어집니다")
    return Plan(agent_id, route_mode, route_reason, tools, locked, dropped, warnings,
                skill_id=skill["id"] if skill else None, skill_name=skill["name"] if skill else None,
                skill_mode=(skill_mode or "manual") if skill else "none")


# ── Router (분기점) ────────────────────────────────────────────

def _choice_model(cands: list[str], skill_ids: list[str]) -> type[BaseModel]:
    """응답 스키마를 후보 id 의 enum 으로 만든다 — 프롬프트로 부탁하는 대신 후보 밖 값을 구조적으로 막는다."""
    return create_model(
        "RouteChoice",
        agent_id=(Literal[tuple(cands)], Field(description="처리할 agent")),
        skill_id=(Literal[tuple(skill_ids + [NO_SKILL])], Field(description=f"적용할 skill, 해당 없으면 '{NO_SKILL}'")),
        reason=(str, Field(description="한 문장 근거")),
    )


@dataclass
class Route:
    agent_id: str
    mode: str                 # single | router | sticky | fallback
    skill: Optional[dict]
    skill_mode: str           # none | router | sticky
    reason: str


_router_llm = None


def _llm(schema: type[BaseModel]):
    global _router_llm  # lazy — load_dotenv() 이후에 만든다
    if _router_llm is None:
        _router_llm = chat_model(ROUTER_MODEL, temperature=0)
    return _router_llm.with_structured_output(schema)  # 후보가 턴마다 달라 스키마도 매번 만든다


def _router_prompt(cands: list[str], prev: Optional[str], skill: Optional[dict],
                   skill_cands: list[dict], prev_skill: Optional[str]) -> str:
    agents = "\n\n".join(
        f"- id: {a['id']} ({a['name']})\n  {a['route_hint'].strip()}"
        for a in catalog.AGENTS if a["id"] in cands
    )
    lines = []
    if len(cands) > 1:
        lines += ["사용자의 마지막 질문을 처리할 agent 하나를 고르세요. 아래 후보 id 중 하나만 답합니다.", "", agents, ""]
    else:
        lines += [f"agent 는 '{cands[0]}' 로 정해져 있습니다. skill 만 고르면 됩니다.", ""]
    if prev in cands and len(cands) > 1:
        lines.append(
            f"직전 턴은 '{prev}' 가 처리했습니다. 후속 질문(지시어, 같은 대상, '그거', '더 보여줘' 등)이면 "
            f"반드시 '{prev}' 를 유지하고, 주제가 분명히 바뀐 경우에만 바꾸세요."
        )
    if skill:
        lines.append(f"사용자가 선택한 skill: {skill['name']} — {skill.get('description', '')}")
    if skill_cands:
        cards = "\n".join(
            f"- id: {s['id']} ({s['name']})\n  {s['description'][:SKILL_DESC_CHARS]}" for s in skill_cands
        )
        lines += [
            "", "[skill] 업무 workflow 절차입니다. 질문이 아래 skill 의 업무를 해 달라는 요청일 때만 그 id 를 고르세요.",
            f"특정 데이터 하나만 묻는 단발 조회, 일반 질문, 애매한 경우는 '{NO_SKILL}' 입니다.", "", cards,
        ]
        prev_card = next((s for s in skill_cands if s["id"] == prev_skill), None)
        if prev_card:
            lines.append(
                f"\n직전 턴은 skill '{prev_card['id']}' ({prev_card['name']}) 절차를 진행 중이었습니다. 사용자의 말이 "
                f"그 절차의 후속(되물은 것에 대한 답, 선택지 고르기, '계속', '다음 단계')이면 반드시 유지하고, "
                f"다른 업무로 바뀌었을 때만 바꾸거나 '{NO_SKILL}' 로 답하세요."
            )
    return "\n".join(lines)


def _history(messages: list[dict]) -> str:
    recent = [m for m in messages if m.get("content")][-ROUTER_HISTORY:]
    return "\n".join(f"[{m['role']}] {m['content'][:ROUTER_MSG_CHARS]}" for m in recent)


def _allows(agent_id: str, skill: dict) -> bool:
    return set(skill["tools"]) <= set(catalog.agent_pool(agent_id))


async def route(messages: list[dict], prev: Optional[str], cands: list[str], skill: Optional[dict] = None,
                skill_cands: Optional[list[dict]] = None, prev_skill: Optional[str] = None) -> Route:
    skill_cands = skill_cands or []
    if len(cands) == 1 and not skill_cands:
        return Route(cands[0], "single", None, "none", "선택한 tool/skill 을 처리할 수 있는 agent 가 하나뿐")
    fallback = prev if prev in cands else (catalog.FALLBACK_AGENT if catalog.FALLBACK_AGENT in cands else cands[0])
    by_id = {s["id"]: s for s in skill_cands}
    try:
        choice = await _llm(_choice_model(cands, list(by_id))).ainvoke([
            SystemMessage(content=_router_prompt(cands, prev, skill, skill_cands, prev_skill)),
            HumanMessage(content=_history(messages)),
        ])
    except Exception:  # noqa: BLE001 — 분기 실패로 대화가 막히면 안 된다
        log.exception("router failed")
        kept = by_id.get(prev_skill)  # 진행 중이던 workflow 는 끊지 않는다
        if kept and not _allows(fallback, kept):
            kept = None
        return Route(fallback, "fallback", kept, "sticky" if kept else "none", "Router 오류 — 기본 agent 로 처리")

    agent_id, reason = choice.agent_id, choice.reason
    mode = "single" if len(cands) == 1 else ("sticky" if agent_id == prev else "router")
    if agent_id not in cands:
        agent_id, mode = fallback, "fallback"
        reason = f"Router 가 후보 밖 '{choice.agent_id}' 를 골라 기본 agent 로 처리"

    picked = by_id.get(choice.skill_id)
    if choice.skill_id not in (NO_SKILL, "", None) and picked is None:
        log.warning("Router 가 후보 밖 skill '%s' 를 골라 무시", choice.skill_id)
    if picked and not _allows(agent_id, picked):
        # skill 이 우선 — 그 skill 을 실행할 수 있는 agent 로 옮긴다 (agent 가 고정이면 skill 을 버린다)
        alt = next((a for a in cands if _allows(a, picked)), None)
        if alt and len(cands) > 1:
            agent_id, mode = alt, "router"
        else:
            picked = None
    skill_mode = "none" if not picked else ("sticky" if picked["id"] == prev_skill else "router")
    return Route(agent_id, mode, picked, skill_mode, reason)


async def resolve(messages: list[dict], agent_id: Optional[str], skill: Optional[dict],
                  sel: Optional[ToolSelection], prev_agent: Optional[str], prev_skill: Optional[str] = None,
                  skill_pool: Optional[list[dict]] = None, pool_explicit: bool = False) -> Plan:
    """skill 을 사용자가 하나 골랐으면 그대로(manual), 아니면 Router 가 skill_pool 안에서 고른다.

    skill_pool: Router 가 고를 수 있는 skill (사용자에게 보이는 것만). 없으면 전체.
    pool_explicit: 사용자가 여러 개를 직접 켜 둔 경우 — AUTO_SKILL 이 꺼져 있어도 그 안에서는 고른다.
    """
    sel = sel or ToolSelection()
    manual_agent = agent_id in catalog.AGENTS_BY_ID
    # auto, 또는 옛 agent id(line/defect/yield 등) — 자동 분기로 처리
    cands = [agent_id] if manual_agent else candidates(sel, skill)
    skill_cands = skill_candidates(cands, skill_pool) if not skill and (pool_explicit or AUTO_SKILL) else []
    r = await route(messages, prev_agent, cands, skill, skill_cands, prev_skill)
    if manual_agent:
        reason = "사용자가 agent 를 지정" + (f" · {r.reason}" if r.skill else "")
        return plan_tools(agent_id, sel, skill or r.skill, "manual", reason, "manual" if skill else r.skill_mode)
    return plan_tools(r.agent_id, sel, skill or r.skill, r.mode, r.reason, "manual" if skill else r.skill_mode)
