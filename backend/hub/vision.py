"""
첨부 이미지 해석 — 사내 VLM(vLLM) 연동.

VISION_MODE
  describe (기본)  VLM 이 이미지를 텍스트로 해석 → 그 텍스트를 사용자 메시지에 붙여 agent 에 넘긴다.
                   agent 모델이 텍스트 전용(사내 LLM)이어도 동작하고, 해석 결과가 캐시돼 다음 턴에도 쓰인다.
  direct           agent 모델에 이미지를 그대로 넣는다 (agent 모델이 비전을 지원할 때). 이전 턴 이미지는 이름만.
  off              이미지를 해석하지 않는다 (볼 수 없다고 알린다).

chat 라우터가 prepare() 를 부르고, 해석 진행은 tool 처럼 화면 실행 기록에 'image_analysis' 로 보인다.
"""
import logging
import os
import time
from typing import AsyncGenerator, Optional

from langchain_core.messages import HumanMessage, SystemMessage

from hub import uploads
from hub.llm import vision_model

log = logging.getLogger("vision")

MODE = os.getenv("VISION_MODE", "describe")
TOOL_NAME = "image_analysis"

DESCRIBE_PROMPT = """당신은 이미지 해석 담당입니다. 결과는 이미지를 볼 수 없는 다른 AI 가 읽고 사용자 질문에 답하는 데 쓰입니다.
그 AI 가 이미지를 보지 않고도 답할 수 있게 정리하세요.

- 첫 줄: 무엇의 이미지인지 (화면 캡처 · 사진 · 차트 · 표 · 문서 · 오류 화면 등)
- 보이는 텍스트 · 수치 · 라벨 · 단위는 빠짐없이 원문 그대로 옮깁니다. 표는 markdown 표로.
- 차트: 축 이름과 눈금 범위, 범례, 계열별 추세, 눈에 띄는 이상치 · 관리선 이탈
  · 이미지에 숫자로 적힌 값(라벨 · 표 · 관리선 값)만 확정값으로 씁니다
  · 점 위치를 눈금으로 읽은 값은 반드시 '약 1,024 (눈금 추정)' 처럼 쓰고, 관리선 근처라 이탈 여부가 애매하면 애매하다고 씁니다
- 오류 화면: 오류 메시지 원문, 발생 위치(프로그램 · 화면 이름)
- 사용자 질문과 관련된 부분은 더 자세히
- 확실하지 않은 내용은 '(추정)' 으로 표시합니다. 이미지에 없는 내용은 만들지 않습니다."""

_llm = None


def _model():
    global _llm  # lazy — load_dotenv() 이후
    if _llm is None:
        _llm = vision_model()
    return _llm


async def describe(meta: dict, question: str) -> str:
    if meta.get("description"):
        return meta["description"]
    msg = await _model().ainvoke([
        SystemMessage(content=DESCRIBE_PROMPT),
        HumanMessage(content=[
            {"type": "text", "text": f"사용자 질문: {question or '(질문 없음 — 이미지 내용을 해석)'}"},
            {"type": "image_url", "image_url": {"url": uploads.data_url(meta)}},
        ]),
    ])
    text = msg.content if isinstance(msg.content, str) else str(msg.content)
    uploads.set_description(meta["id"], text)
    return text


def _note(i: int, meta: dict) -> str:
    if meta.get("description"):
        return f"[첨부 이미지 {i}: {meta['name']} — 이미지 해석 결과]\n{meta['description']}"
    if MODE == "off":
        return f"[첨부 이미지 {i}: {meta['name']} — 이미지 해석이 꺼져 있어 내용을 볼 수 없습니다]"
    return f"[첨부 이미지 {i}: {meta['name']}]"


async def prepare(messages: list[dict]) -> AsyncGenerator[dict, None]:
    """messages 의 attachments(업로드 id) 를 agent 입력으로 바꾼다. 진행 이벤트를 yield 하고,
    마지막에 {"type": "prepared", "messages", "attachments"} 를 돌려준다.

    attachments: 이번(마지막) 사용자 메시지의 첨부 — 대화 저장용 [{id, name, mime}]
    """
    last_user = max((i for i, m in enumerate(messages) if m["role"] == "user"), default=-1)
    out: list[dict] = []
    current: list[dict] = []
    for idx, m in enumerate(messages):
        ids = m.get("attachments") or []
        metas = [meta for meta in (uploads.get(i) for i in ids) if meta]
        m = {k: v for k, v in m.items() if k != "attachments"}
        if not metas:
            out.append(m)
            continue
        if idx == last_user:
            current = [uploads.public(x) for x in metas]
            if MODE == "describe":
                for meta in metas:
                    if meta.get("description"):
                        continue
                    run_id = f"img_{meta['id']}"
                    t0 = time.perf_counter()
                    yield {"type": "tool_start", "id": run_id, "name": TOOL_NAME, "args": {"image": meta["name"]}}
                    ok = True
                    try:
                        meta["description"] = await describe(meta, m["content"])
                    except Exception as e:  # noqa: BLE001 — 해석 실패여도 질문은 계속 처리
                        log.exception("image describe failed: %s", meta["id"])
                        meta["description"] = f"(이미지 해석 실패: {str(e)[:200]})"
                        ok = False
                    yield {"type": "tool_end", "id": run_id, "name": TOOL_NAME,
                           "ms": round((time.perf_counter() - t0) * 1000), "ok": ok}
            elif MODE == "direct":
                m["images"] = [uploads.data_url(x) for x in metas]
        notes = "\n\n".join(_note(i + 1, x) for i, x in enumerate(metas) if not (MODE == "direct" and idx == last_user))
        m["content"] = (m["content"] + ("\n\n" + notes if notes else "")).strip()
        out.append(m)
    yield {"type": "prepared", "messages": out, "attachments": current}
