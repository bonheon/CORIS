"""
사용자 메모리 — 사용자마다 markdown 문서 1개를 DB 에 두고 대화가 끝날 때마다 고쳐 쓴다.

  읽기: 대화 시작 시 for_prompt() 가 시스템 프롬프트에 붙인다.
  쓰기: 응답이 끝난 뒤 update_after_turn() 을 백그라운드로 — 응답 지연 없음.
        LLM 이 "현재 문서 + 이번 턴" 을 보고 문서 전체를 다시 쓴다. 결과가 형식/길이 검사를
        통과하지 못하면 기존 문서를 그대로 둔다. 이전 내용은 history 테이블에 남는다.

문서 섹션을 고정해 두면 매 턴 다시 써도 구조가 흐트러지지 않고, 사용자가 화면에서 직접 고칠 수도 있다.
"""
import asyncio
import logging
import os
import re
from typing import Optional

from langchain_core.messages import HumanMessage, SystemMessage

from db import user_store
from hub.llm import chat_model

log = logging.getLogger("memory")

ENABLED = os.getenv("MEMORY_ENABLED", "1") != "0"
MODEL = os.getenv("MEMORY_MODEL", "gpt-4o-mini")
MAX_CHARS = int(os.getenv("MEMORY_MAX_CHARS", "3000"))
ANSWER_CHARS = 1500  # 업데이트 LLM 에 넘기는 답변 길이 — 표/차트 설명이 길어도 요지만

SECTIONS = ["프로필", "자주 보는 대상", "선호 · 작업 방식", "진행 중인 이슈", "최근 대화"]

UPDATE_PROMPT = f"""당신은 사내 업무 어시스턴트 Coris 의 '사용자 메모리' 관리자입니다.
현재 메모리 문서와 방금 끝난 대화 한 턴을 보고, 갱신된 메모리 문서 전체를 markdown 으로만 출력합니다.

규칙
- 첫 줄은 '# ' 제목 그대로, 섹션은 아래 순서의 '## ' 제목만 사용: {", ".join(SECTIONS)}
- 사용자가 말했거나 대화에서 분명히 드러난 사실만 적습니다. 추측 · 데이터 수치 · 답변 내용 자체는 적지 않습니다.
  (예: "품질팀 데이터 분석 담당" 은 O, "어제 조회한 수치 8건" 은 X)
- 프로필: 사용자가 밝힌 담당/역할을 적습니다. (예: "나 품질팀 분석 담당이야" → '- 담당: 품질팀 분석')
- 자주 보는 대상: 자주 다루는 시스템 · 프로젝트 · 지표 · 문서를 '- 대상 (메모)' 형태로, 반복해서 나오면 앞으로.
- 선호 · 작업 방식: 답변 형식이나 진행 방식에 대한 요청은 반드시 적습니다.
  (예: "앞으로 표로 정리해줘" → '- 결과는 표로 정리', "결론부터 말해줘" → '- 결론 먼저')
- 진행 중인 이슈: 아직 결론이 안 난 조사만. 해결된 것은 지웁니다.
- 최근 대화: '- YYYY-MM-DD 한 줄 요약' 형식, 시간순(새 줄은 맨 아래). 8줄을 넘으면 맨 위(가장 오래된 줄)부터 지웁니다.
- 비밀번호 · 토큰 · 개인 연락처 등 민감 정보는 절대 적지 않습니다.
- 새로 알게 된 것이 없으면 '최근 대화' 한 줄만 추가합니다.
- 전체 {MAX_CHARS}자 이내. 넘치면 오래되고 덜 중요한 항목부터 줄입니다.
- 코드블록(```)으로 감싸지 말고 문서만 출력합니다."""

_TAG_RE = re.compile(r"\[[A-Z_]+:[^\]]+\]")
_locks: dict[str, asyncio.Lock] = {}
_tasks: set[asyncio.Task] = set()  # create_task 결과를 붙잡아 두지 않으면 GC 로 중간에 사라질 수 있다
_llm = None


def _get_llm():
    global _llm  # lazy — load_dotenv() 이후
    if _llm is None:
        _llm = chat_model(MODEL, temperature=0)
    return _llm


def template(user: dict) -> str:
    profile = [f"- 이름: {user['name']}"] + ([f"- 부서: {user['dept']}"] if user.get("dept") else [])
    body = "\n\n".join(f"## {s}\n" + ("\n".join(profile) if s == "프로필" else "") for s in SECTIONS)
    return f"# 사용자 메모리 — {user['name']}\n\n{body}\n"


def load(user_id: str) -> Optional[str]:
    m = user_store.get_memory(user_id)
    return m["content"] if m else None


def for_prompt(md: Optional[str]) -> str:
    if not md:
        return ""
    return (
        "\n\n[사용자 메모리 — 이전 대화에서 정리한 이 사용자의 정보]\n"
        "질문이 모호할 때(예: '그거', '우리 팀') 참고하고, 담당 영역에 맞춰 답하세요.\n"
        "'선호 · 작업 방식' 에 적힌 답변 형식(예: 표로 정리)은 사용자가 따로 말하지 않아도 지키세요.\n"
        "이 메모리는 조회 결과가 아닙니다 — 수치나 현황은 반드시 tool 로 다시 확인하세요.\n"
        "--- 메모리 시작 ---\n"
        f"{md.strip()}\n"
        "--- 메모리 끝 ---"
    )


def _valid(md: str) -> bool:
    return md.startswith("# ") and "## " in md and len(md) <= MAX_CHARS * 1.2


def _clean(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):  # 지시를 어기고 감싸서 온 경우
        text = re.sub(r"^```\w*\n?|\n?```$", "", text).strip()
    return text


async def update_after_turn(user: dict, user_text: str, answer: str, tools: list[dict], date: str) -> None:
    """응답이 끝난 뒤 백그라운드로 호출. 실패해도 대화에는 영향 없음."""
    if not ENABLED or not answer.strip():
        return
    uid = user["user_id"]
    lock = _locks.setdefault(uid, asyncio.Lock())
    async with lock:  # 같은 사용자의 연속 턴이 서로 덮어쓰지 않게
        current = load(uid) or template(user)
        used = ", ".join(
            f"{t['name']}({', '.join(f'{k}={v}' for k, v in (t.get('args') or {}).items())})" for t in tools
        ) or "없음"
        turn = (
            f"날짜: {date}\n사용자 질문: {user_text}\n"
            f"사용한 tool: {used}\n"
            f"답변(요약용, 일부): {_TAG_RE.sub('', answer)[:ANSWER_CHARS]}"
        )
        try:
            res = await _get_llm().ainvoke([
                SystemMessage(content=UPDATE_PROMPT),
                HumanMessage(content=f"[현재 메모리]\n{current}\n\n[이번 대화]\n{turn}"),
            ])
        except Exception:  # noqa: BLE001
            log.exception("memory update failed (%s)", uid)
            return
        new = _clean(res.content if isinstance(res.content, str) else str(res.content))
        if not _valid(new):
            log.warning("memory update rejected (%s): 형식/길이 검사 실패 (%d자)", uid, len(new))
            return
        if new != current.strip():
            user_store.save_memory(uid, new, "chat")
            log.info("memory updated (%s, %d자)", uid, len(new))


def schedule_update(user: dict, user_text: str, answer: str, tools: list[dict], date: str) -> None:
    """응답 흐름을 막지 않고 백그라운드에서 메모리를 고친다."""
    if not ENABLED:
        return
    task = asyncio.create_task(update_after_turn(user, user_text, answer, tools, date))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
