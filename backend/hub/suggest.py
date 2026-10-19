"""
추천 후속 질문 — 답변이 끝나면 가벼운 모델(SUGGEST_MODEL)이 다음에 물어볼 만한 질문 3개를 만든다.

화면은 답변 아래에 칩으로 보여주고, 누르면 그 질문이 바로 전송된다.
실패하거나 시간이 걸리면 빈 목록 — 답변 자체에는 영향이 없다 (화면은 카드 태그 기반 고정 추천으로 대체).
"""
import asyncio
import logging
import os

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from hub import catalog
from hub.llm import chat_model

log = logging.getLogger("suggest")

ENABLED = os.getenv("SUGGEST_ENABLED", "1") != "0"
MODEL = os.getenv("SUGGEST_MODEL") or os.getenv("ROUTER_MODEL", "gpt-4o-mini")
TIMEOUT_S = float(os.getenv("SUGGEST_TIMEOUT_SEC", "8"))
COUNT = 3
ANSWER_CHARS = 1500

PROMPT = """당신은 사내 업무 어시스턴트 Coris 의 '추천 질문' 담당입니다.
방금 끝난 대화를 보고, 사용자가 이어서 누르기만 하면 되는 후속 질문 {n}개를 만듭니다.

규칙
- 사용자 입장의 한국어 질문/요청문. 25자 안팎으로 짧게. (예: "EQ-03만 일별 평균 표로 보여줘")
- 방금 답변의 대상(설비 · 지표 · 기간 · 문서 등)을 이어받아 구체적으로. "더 알려줘" 같은 막연한 문장 금지
- 서로 다른 방향으로: ① 더 깊이(세부 · 원인) ② 다른 각도(비교 · 다른 지표/기간) ③ 다음 행동(정리 · 표 · 차트)
- 아래 [쓸 수 있는 기능] 으로 답할 수 있는 것만. 없는 데이터나 기능은 묻지 않는다
- 답변에서 이미 한 것과 똑같은 요청은 하지 않는다
  답변 속 [CHART:...] · [ARTIFACT:...] 태그는 이미 화면에 차트를 보여줬다는 뜻 — 같은 차트를 다시 그려 달라고 하지 않는다"""


class Suggestions(BaseModel):
    questions: list[str] = Field(description=f"후속 질문 {COUNT}개")


_llm = None


def _model():
    global _llm  # lazy — load_dotenv() 이후
    if _llm is None:
        _llm = chat_model(MODEL, temperature=0.4).with_structured_output(Suggestions)
    return _llm


def _capabilities(tools: list[str]) -> str:
    lines = []
    for name in tools:
        info = catalog.tool_info(name)
        lines.append(f"- {info['label']}: {info['description']}")
    return "\n".join(lines) or "- (tool 없음 — 일반 대화)"


async def generate(question: str, answer: str, tools: list[str]) -> list[str]:
    if not ENABLED or not answer.strip():
        return []
    try:
        out = await asyncio.wait_for(_model().ainvoke([
            SystemMessage(content=PROMPT.format(n=COUNT) + "\n\n[쓸 수 있는 기능]\n" + _capabilities(tools)),
            HumanMessage(content=f"[사용자 질문]\n{question}\n\n[답변]\n{answer[:ANSWER_CHARS]}"),
        ]), TIMEOUT_S)
    except Exception:  # noqa: BLE001 — 추천은 부가 기능, 실패해도 대화는 정상
        log.warning("추천 질문 생성 실패", exc_info=True)
        return []
    seen, result = set(), []
    for q in out.questions:
        q = " ".join(q.split()).strip("\"' ")
        if q and q not in seen and q != question.strip():
            seen.add(q)
            result.append(q[:80])
    return result[:COUNT]
