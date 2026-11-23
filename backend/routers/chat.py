"""
POST /api/chat — SSE 스트리밍.

이벤트 (data: <json>):
  {"type": "meta", "conversation_id"}          첫 이벤트
  {"type": "user", "user_id", "name", "memory_chars", "memory_version"}   불러온 사용자 메모리
  {"type": "route", "agent_id", "agent_name", "route_mode", "route_reason",
   "tools", "locked", "dropped", "warnings",
   "skill_id", "skill_name", "skill_mode"}       분기 결과 · 이번 턴에 켜진 tool · 적용된 skill
  {"type": "tool_start", "id", "name", "args"}  (첨부 이미지 해석도 name=image_analysis 로 온다)
  {"type": "tool_end", "id", "name", "ms", "ok"}
  {"type": "delta", "delta"}                   텍스트 토큰
  {"type": "suggestions", "items"}             답변 후 추천 후속 질문 (없으면 보내지 않음)
  {"type": "error", "message"}
  [DONE]
  {"type": "stopped"}                          사용자가 중지함 (그때까지의 답변은 저장)
응답이 끝나면 대화가 hub 저장소에 기록되고, 사용자 메모리(md)가 백그라운드로 갱신된다.
답변은 백그라운드 작업(hub/runs.py)이라 화면 연결이 끊겨도 계속된다 — GET /api/chat/{id}/stream 으로 다시 연결,
POST /api/chat/{id}/cancel 로 중지.

프론트는 텍스트만 보내므로, 저장된 대화에서 같은 답변을 찾아 그 턴의 tool 호출 · 결과(trace)를
붙여 agent 에 넘긴다 — 후속 질문에서 앞서 조회한 데이터를 그대로 쓰게 하기 위함.
"""
import asyncio
import json
import logging
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

import agent
from db import user_store
from hub import memory, runs, service, skills, store, suggest, timing, uploads, vision
from hub.users import current_user
from hub.routing import ToolSelection, resolve

router = APIRouter(prefix="/api", tags=["chat"])
log = logging.getLogger("chat")


class Message(BaseModel):
    role: str
    content: str
    attachments: list[str] = []   # 업로드 id (POST /api/hub/uploads) — 사용자 메시지의 첨부 이미지


class ChatRequest(BaseModel):
    messages: list[Message]
    conversation_id: Optional[str] = None
    agent_id: str = "auto"
    skill_id: Optional[str] = None      # 예전 형식 — skill_ids 가 없을 때만
    skill_ids: list[str] = []           # 켜 둔 스킬: 1개면 그 절차로, 2개 이상이면 질문마다 그중 맞는 것
    tool_selection: Optional[ToolSelection] = None


def _attach_traces(messages: list[dict], conv: Optional[dict]) -> list[dict]:
    if not conv:
        return messages
    traces = {m["content"]: m["trace"] for m in conv["messages"] if m["role"] == "assistant" and m.get("trace")}
    return [m | {"trace": traces[m["content"]]} if m["role"] == "assistant" and m["content"] in traces else m
            for m in messages]


def _sse(payload) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


_sse_text = _sse


@router.post("/chat")
async def chat(req: ChatRequest, request: Request, user: dict = Depends(current_user)):
    conv_id = req.conversation_id or store.new_id("cv")
    # 응답 시간 측정 (hub/timing.py · docs/TIMING.md) — 요청 도착부터. pre.request = 본문 읽기 + 사용자 확인(current_user)
    t = timing.Timing("chat", t0=getattr(request.state, "t0", None), conv=conv_id, user=user["user_id"])
    t.add("pre.request", timing.now() - t.t0)
    messages = [m.model_dump() for m in req.messages]
    user_text = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
    with t.span("db.load_conversation"):
        conv = store.get_item("conversations", req.conversation_id) if req.conversation_id else None
    prev_agent = conv.get("routed_agent") if conv else None
    prev_skill = conv.get("routed_skill") if conv else None
    messages = _attach_traces(messages, conv)
    # 사용자에게 보이는 스킬만 — 남의 '내 스킬' id 를 넣어도 쓰이지 않는다
    with t.span("db.skills"):
        visible = {s["id"]: s for s in skills.list_items(user["user_id"], user["is_admin"])}
    picked = [visible[i] for i in dict.fromkeys(req.skill_ids or ([req.skill_id] if req.skill_id else [])) if i in visible]
    skill = picked[0] if len(picked) == 1 else None
    skill_pool = picked if len(picked) > 1 else list(visible.values())
    with t.span("db.user_memory"):
        mem = user_store.get_memory(user["user_id"])

    async def generate():
        timing.activate(t)  # 이 안의 LangChain LLM · tool 호출이 자동으로 기록된다

        def _sse(payload) -> str:  # 화면으로 보내는 이벤트 — 보낸 시각을 기록
            t.event(payload.get("type", "?") if isinstance(payload, dict) else "?")
            return _sse_text(payload)

        yield _sse({"type": "meta", "conversation_id": conv_id})
        yield _sse({"type": "user", "user_id": user["user_id"], "name": user["name"],
                    "memory_chars": len(mem["content"]) if mem else 0,
                    "memory_version": mem["version"] if mem else 0})
        text: list[str] = []
        runs: dict[str, dict] = {}
        trace: list[dict] = []
        plan = None
        attachments: list[dict] = []
        suggestions: list[str] = []
        stopped = False
        failed = False
        try:
            prepared = messages
            vision_t0 = timing.now()
            async for ev in vision.prepare(messages):  # 첨부 이미지 → VLM 해석 (진행은 tool 처럼 보인다)
                if ev["type"] == "prepared":
                    prepared, attachments = ev["messages"], ev["attachments"]
                    continue
                if ev["type"] == "tool_start":
                    runs[ev["id"]] = {"name": ev["name"], "args": ev["args"], "ms": None, "ok": None}
                elif ev["type"] == "tool_end" and ev["id"] in runs:
                    runs[ev["id"]].update(ms=ev["ms"], ok=ev["ok"])
                yield _sse(ev)
            t.add("vision", timing.now() - vision_t0)
            async with t.span("router"):
                plan = await resolve(prepared, req.agent_id, skill, req.tool_selection, prev_agent, prev_skill,
                                     skill_pool=skill_pool, pool_explicit=len(picked) > 1)
            yield _sse(plan.event())
            applied = skill or skills.get_item(plan.skill_id)  # Router 가 고른 skill 포함
            agent_t0 = timing.now()
            async for ev in agent.stream(prepared, plan, applied, memory.for_prompt(mem["content"] if mem else None),
                                         session_id=conv_id):
                if ev["type"] == "delta":
                    text.append(ev["text"])
                    yield _sse({"type": "delta", "delta": ev["text"]})
                    continue
                if ev["type"] == "trace":  # 저장용 — 화면에는 보내지 않는다
                    trace = ev["trace"]
                    continue
                if ev["type"] == "tool_start":
                    runs[ev["id"]] = {"name": ev["name"], "args": ev["args"], "ms": None, "ok": None}
                elif ev["type"] == "tool_end" and ev["id"] in runs:
                    runs[ev["id"]].update(ms=ev["ms"], ok=ev["ok"])
                yield _sse(ev)
            t.add("agent", timing.now() - agent_t0)
            t.mark("answer_done")  # 답변 글은 여기까지 — 아래 추천 질문 · 저장은 '답변 중' 표시가 꺼지는 시점에 영향
            # 답변이 다 나간 뒤 — 화면은 이미 답을 보여주고 있고, 추천 칩만 뒤따라 붙는다
            async with t.span("suggest"):
                suggestions = await suggest.generate(user_text, "".join(text), plan.tools)
            if suggestions:
                yield _sse({"type": "suggestions", "items": suggestions})
        except asyncio.CancelledError:   # 사용자가 중지 (POST /api/chat/{id}/cancel) — 그때까지의 답변은 저장
            stopped = True
            raise
        except Exception as e:  # noqa: BLE001
            log.exception("chat failed")
            failed = True
            yield _sse({"type": "error", "message": str(e)[:300]})
        finally:
            if text or runs:
                body = "".join(text) + ("\n\n_(중지됨)_" if stopped and text else "(중지됨)" if stopped else "")
                with t.span("db.save_turn"):
                    service.save_turn(conv_id, user_text, body, list(runs.values()),
                                      req.agent_id, skill["id"] if skill else None,
                                      routed_agent=plan.agent_id if plan else None,
                                      routed_skill=plan.skill_id if plan else None,
                                      route=plan.summary() if plan else None, user_id=user["user_id"], trace=trace,
                                      attachments=attachments, suggestions=suggestions,
                                      skill_ids=[s["id"] for s in picked])
                memory.schedule_update(user, user_text, "".join(text), list(runs.values()), date.today().isoformat())
            t.finish("stopped" if stopped else "error" if failed else "ok")
        yield "data: [DONE]\n\n"

    # 답변은 백그라운드 작업으로 — 화면이 연결을 끊어도(다른 대화로 이동) 끝까지 만들어 저장한다 (hub/runs.py)
    if runs.active(conv_id):
        raise HTTPException(409, "이 대화는 아직 답변 중입니다")
    last = next((m for m in reversed(messages) if m["role"] == "user"), {})
    att = [uploads.public(u) for u in (uploads.get(i) for i in last.get("attachments") or []) if u]
    run = runs.start(runs.Run(conv_id, user["user_id"], user_text, att, is_new=conv is None), generate())
    return _stream(run.subscribe())


# 프록시가 SSE 를 모아서 보내지 않게 — CRA 개발 서버의 gzip 은 no-transform 을, nginx 는 X-Accel-Buffering 을 본다
def _stream(body) -> StreamingResponse:
    return StreamingResponse(body, media_type="text/event-stream", headers={
        "Cache-Control": "no-cache, no-transform",
        "X-Accel-Buffering": "no",
    })


@router.get("/chat/{conv_id}/stream")
async def resume(conv_id: str, user: dict = Depends(current_user)):
    """진행 중(또는 방금 끝난) 답변에 다시 연결 — 처음부터 다시 받는다. 첫 이벤트 resume 에 이번 턴의 질문이 온다."""
    run = runs.get(conv_id)
    if run is None or run.user_id != user["user_id"]:
        raise HTTPException(404, "진행 중인 답변이 없습니다")

    async def body():
        yield _sse({"type": "resume", "user_text": run.user_text, "attachments": run.attachments,
                    "started_at": run.started_at, "done": run.done})
        async for chunk in run.subscribe():
            yield chunk

    return _stream(body())


@router.post("/chat/{conv_id}/cancel")
async def cancel(conv_id: str, user: dict = Depends(current_user)):
    """중지 — 그때까지 만든 답변은 저장된다."""
    run = runs.active(conv_id)
    if run is None or run.user_id != user["user_id"]:
        raise HTTPException(404, "진행 중인 답변이 없습니다")
    runs.cancel(conv_id)
    return {"ok": True}
