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
응답이 끝나면 대화가 hub 저장소에 기록되고, 사용자 메모리(md)가 백그라운드로 갱신된다.

프론트는 텍스트만 보내므로, 저장된 대화에서 같은 답변을 찾아 그 턴의 tool 호출 · 결과(trace)를
붙여 agent 에 넘긴다 — 후속 질문에서 앞서 조회한 데이터를 그대로 쓰게 하기 위함.
"""
import json
import logging
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

import agent
from db import user_store
from hub import memory, service, skills, store, suggest, vision
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


@router.post("/chat")
async def chat(req: ChatRequest, user: dict = Depends(current_user)):
    conv_id = req.conversation_id or store.new_id("cv")
    messages = [m.model_dump() for m in req.messages]
    user_text = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
    conv = store.get_item("conversations", req.conversation_id) if req.conversation_id else None
    prev_agent = conv.get("routed_agent") if conv else None
    prev_skill = conv.get("routed_skill") if conv else None
    messages = _attach_traces(messages, conv)
    # 사용자에게 보이는 스킬만 — 남의 '내 스킬' id 를 넣어도 쓰이지 않는다
    visible = {s["id"]: s for s in skills.list_items(user["user_id"], user["is_admin"])}
    picked = [visible[i] for i in dict.fromkeys(req.skill_ids or ([req.skill_id] if req.skill_id else [])) if i in visible]
    skill = picked[0] if len(picked) == 1 else None
    skill_pool = picked if len(picked) > 1 else list(visible.values())
    mem = user_store.get_memory(user["user_id"])

    async def generate():
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
        try:
            prepared = messages
            async for ev in vision.prepare(messages):  # 첨부 이미지 → VLM 해석 (진행은 tool 처럼 보인다)
                if ev["type"] == "prepared":
                    prepared, attachments = ev["messages"], ev["attachments"]
                    continue
                if ev["type"] == "tool_start":
                    runs[ev["id"]] = {"name": ev["name"], "args": ev["args"], "ms": None, "ok": None}
                elif ev["type"] == "tool_end" and ev["id"] in runs:
                    runs[ev["id"]].update(ms=ev["ms"], ok=ev["ok"])
                yield _sse(ev)
            plan = await resolve(prepared, req.agent_id, skill, req.tool_selection, prev_agent, prev_skill,
                                 skill_pool=skill_pool, pool_explicit=len(picked) > 1)
            yield _sse(plan.event())
            applied = skill or skills.get_item(plan.skill_id)  # Router 가 고른 skill 포함
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
            # 답변이 다 나간 뒤 — 화면은 이미 답을 보여주고 있고, 추천 칩만 뒤따라 붙는다
            suggestions = await suggest.generate(user_text, "".join(text), plan.tools)
            if suggestions:
                yield _sse({"type": "suggestions", "items": suggestions})
        except Exception as e:  # noqa: BLE001
            log.exception("chat failed")
            yield _sse({"type": "error", "message": str(e)[:300]})
        finally:
            if text or runs:
                service.save_turn(conv_id, user_text, "".join(text), list(runs.values()),
                                  req.agent_id, skill["id"] if skill else None, routed_agent=plan.agent_id if plan else None,
                                  routed_skill=plan.skill_id if plan else None,
                                  route=plan.summary() if plan else None, user_id=user["user_id"], trace=trace,
                                  attachments=attachments, suggestions=suggestions, skill_ids=[s["id"] for s in picked])
                memory.schedule_update(user, user_text, "".join(text), list(runs.values()), date.today().isoformat())
        yield "data: [DONE]\n\n"

    # 프록시가 SSE 를 모아서 보내지 않게 — CRA 개발 서버의 gzip 은 no-transform 을, nginx 는 X-Accel-Buffering 을 본다
    return StreamingResponse(generate(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache, no-transform",
        "X-Accel-Buffering": "no",
    })
