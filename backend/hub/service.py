"""
Hub 도메인 로직 — 대화 기록, 이벤터 스케줄 · 작업 큐(task table).
"""
import asyncio
import logging
import os
import re
import time
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


# ── 작업 큐 (task table) ──────────────────────────────────────
# 이벤터는 agent 를 직접 부르지 않고 task 를 쌓는다. worker 하나가 오래된 순으로 한 건씩 처리한다
# (agent 에 넘겨 처리하고 결과를 받아오는 동안 다음 task 는 대기). 상태: queued → running → done | error,
# 대기 중인 task 는 canceled 로 취소할 수 있고, 실패 · 취소된 task 는 같은 내용으로 다시 넣을 수 있다(retry).

TASKS = "tasks"
QUEUED, RUNNING, DONE, ERROR, CANCELED = "queued", "running", "done", "error", "canceled"
FINISHED = (DONE, ERROR, CANCELED)
MAX_TASKS = int(os.getenv("HUB_MAX_TASKS", "500"))   # 끝난 task 는 이 개수를 넘으면 오래된 것부터 지운다

_wake = asyncio.Event()
_seq = 0


def _next_seq() -> int:
    """같은 초에 쌓인 task 도 넣은 순서대로 처리하도록 단조 증가 번호를 붙인다."""
    global _seq
    _seq = max(_seq + 1, time.time_ns())
    return _seq


def _prune() -> None:
    done = sorted((t for t in store.list_items(TASKS) if t["status"] in FINISHED), key=lambda t: t["seq"])
    for t in done[: max(0, len(store.list_items(TASKS)) - MAX_TASKS)]:
        store.delete_item(TASKS, t["id"])


def enqueue(event_id: str, trigger: str = "manual", retry_of: Optional[dict] = None) -> dict:
    """이벤트 → task 1건 (대기). 실행 시점의 설정을 task 에 그대로 담는다 — 이후 이벤트를 고쳐도 대기 중 task 는 그대로.
    trigger: schedule(정해진 시각) | manual(지금 실행) | retry(다시 실행)."""
    if retry_of:
        spec = {k: retry_of[k] for k in ("event_id", "event_name", "prompt", "skill_id", "agent_id")}
    else:
        event = store.get_item("events", event_id)
        if event is None:
            raise KeyError(event_id)
        skill = skills.get_item(event.get("skill_id"))
        spec = {
            "event_id": event_id, "event_name": event["name"],
            "prompt": event.get("prompt") or (f"'{skill['name']}' 스킬을 실행해줘" if skill else event["name"]),
            "skill_id": event.get("skill_id"), "agent_id": event.get("agent_id") or "auto",
        }
    task = spec | {
        "id": store.new_id("tk"), "seq": _next_seq(), "trigger": trigger, "status": QUEUED,
        "attempt": (retry_of.get("attempt", 1) + 1) if retry_of else 1, "retry_of": retry_of["id"] if retry_of else None,
        "created_at": store.now_iso(), "started_at": None, "finished_at": None, "elapsed_s": None,
        "routed_agent": None, "conversation_id": None, "tool_count": 0, "summary": "", "error": None,
    }
    store.upsert_item(TASKS, task)
    _prune()
    _wake.set()
    return task_view(task)


def _queue() -> list[dict]:
    return sorted((t for t in store.list_items(TASKS) if t["status"] == QUEUED), key=lambda t: t["seq"])


def task_view(task: dict) -> dict:
    """화면용 — 대기 중이면 몇 번째 차례인지 붙인다 (1 = 다음 차례)."""
    if task["status"] != QUEUED:
        return task | {"position": None}
    ids = [t["id"] for t in _queue()]
    return task | {"position": ids.index(task["id"]) + 1 if task["id"] in ids else None}


def list_tasks(event_id: Optional[str] = None, status: Optional[str] = None, limit: int = 50) -> list[dict]:
    items = store.list_items(TASKS)
    if event_id:
        items = [t for t in items if t["event_id"] == event_id]
    if status:
        items = [t for t in items if t["status"] in status.split(",")]
    items.sort(key=lambda t: t["seq"], reverse=True)
    pos = {t["id"]: i + 1 for i, t in enumerate(_queue())}
    return [t | {"position": pos.get(t["id"])} for t in items[:limit]]


def cancel_task(task_id: str) -> dict:
    """대기 중인 task 만 취소된다 — 이미 agent 에 넘어간(running) task 는 끝날 때까지 기다린다."""
    task = store.get_item(TASKS, task_id)
    if task is None:
        raise KeyError(task_id)
    if task["status"] != QUEUED:
        raise ValueError("대기 중인 작업만 취소할 수 있습니다")
    task.update(status=CANCELED, finished_at=store.now_iso())
    return task_view(store.upsert_item(TASKS, task))


def retry_task(task_id: str) -> dict:
    task = store.get_item(TASKS, task_id)
    if task is None:
        raise KeyError(task_id)
    if task["status"] not in (ERROR, CANCELED):
        raise ValueError("실패하거나 취소된 작업만 다시 실행할 수 있습니다")
    return enqueue(task["event_id"], "retry", retry_of=task)


def cancel_event_tasks(event_id: str) -> int:
    n = 0
    for t in _queue():
        if t["event_id"] == event_id:
            cancel_task(t["id"])
            n += 1
    return n


def has_pending(event_id: str) -> bool:
    return any(t["event_id"] == event_id and t["status"] in (QUEUED, RUNNING) for t in store.list_items(TASKS))


async def _execute(task: dict) -> dict:
    """task 1건을 agent 에 넘겨 처리하고 결과(대화)를 받아 task · 이벤트에 기록한다."""
    import agent  # 순환 import 방지 — agent 가 hub 모듈들을 쓴다

    started = datetime.now()
    task.update(status=RUNNING, started_at=started.isoformat(timespec="seconds"))
    store.upsert_item(TASKS, task)
    try:
        text, tools, plan = await agent.run([{"role": "user", "content": task["prompt"]}], task["agent_id"], task["skill_id"])
        conv = save_turn(None, task["prompt"], text, tools, task["agent_id"], task["skill_id"],
                         source="event", event_id=task["event_id"], routed_agent=plan.agent_id, route=plan.summary(),
                         routed_skill=plan.skill_id)
        conv.update(title=task["event_name"], task_id=task["id"])
        store.upsert_item("conversations", conv)
        task.update(status=DONE, conversation_id=conv["id"], summary=conv["summary"], tool_count=len(tools),
                    routed_agent=plan.agent_id)
    except Exception as e:  # noqa: BLE001 — 실패도 기록으로 남긴다
        log.exception("task %s (event %s) failed", task["id"], task["event_id"])
        task.update(status=ERROR, error=str(e)[:300], summary=str(e)[:200])
    task.update(finished_at=store.now_iso(), elapsed_s=round((datetime.now() - started).total_seconds(), 1))
    store.upsert_item(TASKS, task)

    event = store.get_item("events", task["event_id"])
    if event is not None:  # 실행 중에 이벤트가 지워졌으면 task 기록만 남긴다
        event["last_run"] = {
            "at": task["started_at"], "status": "ok" if task["status"] == DONE else "error",
            "conversation_id": task["conversation_id"], "summary": task["summary"],
            "tool_count": task["tool_count"], "elapsed_s": task["elapsed_s"], "task_id": task["id"],
        }
        store.upsert_item("events", event)
    return task


def _recover() -> None:
    """서버가 처리 도중 내려갔다면 running 으로 남은 task 를 실패로 정리한다 (다시 실행은 사용자가)."""
    for t in store.list_items(TASKS):
        if t["status"] == RUNNING:
            t.update(status=ERROR, error="서버 재시작으로 중단됨", summary="서버 재시작으로 중단됨",
                     finished_at=store.now_iso())
            store.upsert_item(TASKS, t)


async def task_worker(idle_s: int = 30) -> None:
    """작업 큐 처리기 — main.py 가 항상 띄운다. 한 번에 한 건씩, 넣은 순서대로."""
    _recover()
    while True:
        _wake.clear()
        queue = _queue()
        if not queue:
            try:
                await asyncio.wait_for(_wake.wait(), idle_s)
            except asyncio.TimeoutError:
                pass
            continue
        try:
            await _execute(queue[0])
        except Exception:  # noqa: BLE001 — 기록 실패 등으로 worker 가 죽으면 큐 전체가 멈춘다
            log.exception("task worker error")
            await asyncio.sleep(1)


async def scheduler_loop(interval_s: int = 30) -> None:
    """HUB_SCHEDULER=1 일 때만 main.py 가 띄운다. 분 단위로 도래한 이벤트를 작업 큐에 넣는다.
    같은 이벤트가 아직 대기 · 실행 중이면 이번 회차는 건너뛴다 (밀린 작업이 쌓이지 않게)."""
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
                if has_pending(ev["id"]):
                    log.warning("event %s: 이전 작업이 아직 대기 · 실행 중 — %s 회차 건너뜀", ev["id"], stamp)
                else:
                    enqueue(ev["id"], "schedule")
        await asyncio.sleep(interval_s)
