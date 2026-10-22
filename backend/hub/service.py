"""
Hub 도메인 로직 — 대화 기록, 이벤터 실행/스케줄.
"""
import asyncio
import logging
import re
from datetime import datetime, timedelta
from typing import Optional

from hub import skills, store

log = logging.getLogger("hub")

_TAG_RE = re.compile(r"\[[A-Z_]+:[^\]]+\]")
_MD_RE = re.compile(r"[#*`>|_~-]+")


def summarize(text: str, limit: int = 90) -> str:
    """대화 목록에 보일 한 줄 요약 — 차트 태그와 마크다운 기호를 걷어낸 첫 문장."""
    plain = _MD_RE.sub(" ", _TAG_RE.sub("", text))
    plain = " ".join(plain.split())
    return plain[:limit] + ("…" if len(plain) > limit else "")


# ── 대화 ──────────────────────────────────────────────────────

def conversation_head(conv: dict) -> dict:
    """목록용 — messages 제외."""
    return {k: v for k, v in conv.items() if k != "messages"} | {"turns": len(conv["messages"]) // 2}


def save_turn(
    conv_id: Optional[str], user_text: str, assistant_text: str, tools: list[dict],
    agent_id: str, skill_id: Optional[str], source: str = "chat", event_id: Optional[str] = None,
    routed_agent: Optional[str] = None, route: Optional[dict] = None, user_id: Optional[str] = None,
    trace: Optional[list[dict]] = None, routed_skill: Optional[str] = None,
    attachments: Optional[list[dict]] = None, suggestions: Optional[list[str]] = None,
    skill_ids: Optional[list[str]] = None,
) -> dict:
    """agent_id · skill_id 는 사용자가 고른 값(auto · 없음 포함), routed_agent · routed_skill 은 실제로 적용된 값
    — 다음 턴 sticky routing 기준. routed_skill 은 workflow 가 끝나 skill 이 빠진 턴이면 지운다."""
    ts = store.now_iso()
    conv = store.get_item("conversations", conv_id) if conv_id else None
    if conv is None:
        conv = {
            "id": conv_id or store.new_id("cv"),
            "title": summarize(user_text, 40),
            "source": source, "event_id": event_id,
            "created_at": ts, "messages": [],
        }
    conv["messages"] += [
        {"role": "user", "content": user_text, "at": ts} | ({"attachments": attachments} if attachments else {}),
        {"role": "assistant", "content": assistant_text, "tools": tools, "agent": routed_agent, "route": route,
         "trace": trace or [], "at": ts} | ({"suggestions": suggestions} if suggestions else {}),
    ]
    conv.update(agent_id=agent_id, skill_id=skill_id, updated_at=ts, summary=summarize(assistant_text))
    if skill_ids is not None:
        conv["skill_ids"] = skill_ids  # 화면의 스킬 칩 상태 — 대화를 다시 열 때 복원
    if routed_agent:
        conv["routed_agent"] = routed_agent
        conv["routed_skill"] = routed_skill
    if user_id:
        conv.setdefault("user_id", user_id)
    store.upsert_item("conversations", conv)

    used = routed_skill or skill_id
    if used and skills.get_item(used):
        skills.count_use(used)
    return conv


# ── 이벤터 ────────────────────────────────────────────────────

def next_run(event: dict, now: Optional[datetime] = None) -> Optional[str]:
    if not event["enabled"]:
        return None
    now = now or datetime.now()
    hh, mm = map(int, event["schedule"]["time"].split(":"))
    cand = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    weekday = event["schedule"].get("weekday") if event["schedule"]["kind"] == "weekly" else None
    for _ in range(8):
        if cand > now and (weekday is None or cand.weekday() == weekday):
            return cand.isoformat(timespec="minutes")
        cand = (cand + timedelta(days=1)).replace(hour=hh, minute=mm)
    return None


def event_view(event: dict) -> dict:
    return event | {"next_run": next_run(event)}


async def run_event(event_id: str) -> dict:
    """이벤트를 지금 실행하고 결과 대화를 저장한다."""
    import agent  # 순환 import 방지 — agent 가 hub 모듈들을 쓴다

    event = store.get_item("events", event_id)
    if event is None:
        raise KeyError(event_id)

    skill = skills.get_item(event.get("skill_id"))
    prompt = event.get("prompt") or (f"'{skill['name']}' 스킬을 실행해줘" if skill else event["name"])
    started = datetime.now()
    try:
        text, tools, plan = await agent.run([{"role": "user", "content": prompt}], event.get("agent_id"), event.get("skill_id"))
        conv = save_turn(None, prompt, text, tools, event.get("agent_id") or "auto", event.get("skill_id"),
                         source="event", event_id=event_id, routed_agent=plan.agent_id, route=plan.summary(),
                         routed_skill=plan.skill_id)
        conv["title"] = event["name"]
        store.upsert_item("conversations", conv)
        event["last_run"] = {
            "at": started.isoformat(timespec="seconds"), "status": "ok",
            "conversation_id": conv["id"], "summary": conv["summary"],
            "tool_count": len(tools), "elapsed_s": round((datetime.now() - started).total_seconds(), 1),
        }
    except Exception as e:  # noqa: BLE001 — 실패도 기록으로 남긴다
        log.exception("event %s failed", event_id)
        event["last_run"] = {
            "at": started.isoformat(timespec="seconds"), "status": "error",
            "conversation_id": None, "summary": str(e)[:200], "tool_count": 0,
            "elapsed_s": round((datetime.now() - started).total_seconds(), 1),
        }
    store.upsert_item("events", event)
    return event_view(event)


async def scheduler_loop(interval_s: int = 30) -> None:
    """HUB_SCHEDULER=1 일 때만 main.py 가 띄운다. 분 단위로 도래한 이벤트를 실행."""
    fired: set[str] = set()
    while True:
        now = datetime.now()
        stamp = now.strftime("%Y-%m-%dT%H:%M")
        for ev in store.list_items("events"):
            sch = ev["schedule"]
            due = ev["enabled"] and sch["time"] == now.strftime("%H:%M") and (
                sch["kind"] == "daily" or sch.get("weekday") == now.weekday()
            )
            key = f"{ev['id']}@{stamp}"
            if due and key not in fired:
                fired.add(key)
                asyncio.create_task(run_event(ev["id"]))
        await asyncio.sleep(interval_s)
