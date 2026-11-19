"""
Jev 방식 agent 선택 — 사내 LLM 한 번 호출로 agent 를 고르고, 선택지별 확률 · 신뢰도를 얻는다.

방식 (TypeSafe Jev 의 '선택지 + 기준 → 확률 · 신뢰도 → 코드가 수용 판단' 구조를 사내 LLM 으로)
  1. 상태(state) 조립 — 코드: 최근 대화, 직전 턴 agent, 후보 agent 의 포함 · 제외 기준(catalog.yaml route_criteria)
  2. 사전 점검 — 코드: 후보가 하나면 LLM 을 부르지 않는다
  3. LLM 1회 — 선택지 기호(A, B, C …) 하나만 답하게 하고(max_tokens=1) 그 토큰의 logprobs 로 선택지별 확률을 계산
     → 근거 문장을 쓰는 Router 보다 출력이 1토큰이라 빠르다
  4. 수용 규칙 — 코드: 신뢰도(1위 확률) ≥ JEV_MIN_CONF 이면 확정, 아니면 범용 agent(첫 번째 agent, Coris) 로
     LLM 오류 · 확률을 못 받으면 같은 대체 처리. 후보 밖 값은 쓰지 않는다

설정: ROUTER_AGENT_MODE=jev | llm (llm 이면 예전 Router 가 agent 도 고른다), JEV_MODEL, JEV_MIN_CONF
사내 LLM 게이트웨이(vLLM 등 OpenAI 호환)가 logprobs · top_logprobs 를 지원해야 한다.
"""
import logging
import math
import os
import time
from dataclasses import asdict, dataclass, field
from typing import Optional

from langchain_core.messages import HumanMessage, SystemMessage

from hub import catalog
from hub.llm import chat_model

log = logging.getLogger("jev")

MODE = os.getenv("ROUTER_AGENT_MODE", "jev")
MODEL = os.getenv("JEV_MODEL") or os.getenv("ROUTER_MODEL", "gpt-4o-mini")
MIN_CONF = float(os.getenv("JEV_MIN_CONF", "0.6"))
HISTORY = 4          # 상태에 넣을 최근 메시지 수
MSG_CHARS = 300
LABELS = "ABCDEFGHIJ"

_llm = None


@dataclass
class JevResult:
    agent_id: str
    accepted: bool                     # 신뢰도 기준을 넘어 Jev 선택을 그대로 쓴 경우
    choice: Optional[str]              # Jev 가 고른 agent (수용되지 않았어도 기록)
    confidence: Optional[float]        # 1위 확률
    probabilities: dict = field(default_factory=dict)   # agent → 확률
    reason: str = ""
    ms: int = 0

    def info(self) -> dict:
        return asdict(self)


def _model():
    global _llm  # lazy — load_dotenv() 이후에 만든다
    if _llm is None:
        _llm = chat_model(MODEL, temperature=0).bind(logprobs=True, top_logprobs=10, max_tokens=1)
    return _llm


def _prompt(cands: list[str], prev: Optional[str]) -> str:
    lines = ["질문을 처리할 agent 를 고르세요. 아래 선택지의 기호 하나(예: A)만 답합니다. 다른 글자는 쓰지 않습니다.", "", "[선택지]"]
    for label, aid in zip(LABELS, cands):
        a = catalog.AGENTS_BY_ID[aid]
        crit = a.get("route_criteria") or {}
        lines.append(f"{label}. {a['name']} — {a['description']}")
        if crit.get("include"):
            lines.append(f"   포함: {crit['include']}")
        if crit.get("exclude"):
            lines.append(f"   제외: {crit['exclude']}")
    if prev in cands:
        lines += ["", f"[상태] 직전 턴은 {catalog.AGENTS_BY_ID[prev]['name']} 가 처리했습니다. "
                      "지시어 · '그거' · '계속' 같은 후속 질문이면 같은 선택지를 고릅니다."]
    return "\n".join(lines)


def _history(messages: list[dict]) -> str:
    recent = [m for m in messages if m.get("content")][-HISTORY:]
    return "\n".join(f"[{m['role']}] {m['content'][:MSG_CHARS]}" for m in recent)


def _probs(msg, by_label: dict[str, str]) -> tuple[dict[str, float], Optional[str]]:
    """첫 토큰의 top_logprobs → 선택지별 확률(선택지 밖 토큰은 버리고 다시 정규화)."""
    lp = (msg.response_metadata or {}).get("logprobs") or {}
    content = lp.get("content") or []
    text = (msg.content or "").strip()[:1].upper()
    if not content:
        return {}, by_label.get(text)
    raw: dict[str, float] = {}
    for t in content[0].get("top_logprobs") or []:
        lb = t["token"].strip().upper()[:1]
        if lb in by_label:
            raw[by_label[lb]] = raw.get(by_label[lb], 0.0) + math.exp(t["logprob"])
    total = sum(raw.values())
    probs = {k: v / total for k, v in raw.items()} if total else {}
    return probs, by_label.get(text)


async def choose(messages: list[dict], cands: list[str], prev: Optional[str]) -> JevResult:
    fallback = catalog.FALLBACK_AGENT if catalog.FALLBACK_AGENT in cands else cands[0]
    if len(cands) == 1:   # 사전 점검 — 고를 것이 없으면 부르지 않는다
        return JevResult(cands[0], True, cands[0], 1.0, {cands[0]: 1.0}, "후보 agent 가 하나뿐")
    by_label = dict(zip(LABELS, cands))
    t0 = time.perf_counter()
    try:
        msg = await _model().ainvoke([SystemMessage(content=_prompt(cands, prev)), HumanMessage(content=_history(messages))])
    except Exception as e:  # noqa: BLE001 — 분기 실패로 대화가 막히면 안 된다
        log.exception("jev failed")
        return JevResult(fallback, False, None, None, {}, f"Jev 오류({type(e).__name__}) — 기본 agent 로", 0)
    ms = round((time.perf_counter() - t0) * 1000)
    probs, text_choice = _probs(msg, by_label)
    name = lambda a: catalog.AGENTS_BY_ID[a]["name"]  # noqa: E731
    if not probs:   # 게이트웨이가 logprobs 를 주지 않음 — 답한 기호만 쓴다 (신뢰도 없음)
        if text_choice:
            return JevResult(text_choice, True, text_choice, None, {}, f"Jev: {name(text_choice)} (확률 없음)", ms)
        return JevResult(fallback, False, None, None, {}, "Jev: 선택지 밖 응답 — 기본 agent 로", ms)
    top = max(probs, key=probs.get)
    conf = probs[top]
    dist = " · ".join(f"{name(a)} {p:.2f}" for a, p in sorted(probs.items(), key=lambda x: -x[1]))
    if conf >= MIN_CONF:
        return JevResult(top, True, top, round(conf, 3), {k: round(v, 3) for k, v in probs.items()}, f"Jev: {dist}", ms)
    return JevResult(fallback, False, top, round(conf, 3), {k: round(v, 3) for k, v in probs.items()},
                     f"Jev 신뢰도 {conf:.2f} < {MIN_CONF} — {name(fallback)} 로 ({dist})", ms)
