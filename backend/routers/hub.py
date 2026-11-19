from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from db import user_store
from hub import catalog, mcp_registry, mcp_store, memory, offload, routing, runs, service, skills, steps, store, tool_groups, uploads
from hub.users import current_user

router = APIRouter(prefix="/api/hub", tags=["hub"])


def _or_404(item: Optional[dict], what: str) -> dict:
    if item is None:
        raise HTTPException(404, f"{what} not found")
    return item


# ── 메타 / 대시보드 ───────────────────────────────────────────

@router.get("/meta")
async def get_meta():
    return await catalog.meta()


@router.post("/catalog/refresh")
async def refresh_catalog():
    """MCP 서버에서 tool 목록을 지금 다시 받아온다."""
    return await catalog.refresh()


class ResolveIn(BaseModel):
    agent_id: str
    skill_id: Optional[str] = None
    tool_selection: routing.ToolSelection = routing.ToolSelection()


@router.post("/tools/resolve")
def resolve_tools(body: ResolveIn):
    """선택 화면 미리보기 — LLM 없이 규칙만 적용. agent=auto 면 후보 agent 목록만 돌려준다."""
    skill = _or_404(skills.get_item(body.skill_id), "skill") if body.skill_id else None
    if body.agent_id not in catalog.AGENTS_BY_ID:
        return {"agent_id": catalog.AUTO, "candidates": routing.candidates(body.tool_selection, skill),
                "locked": routing.skill_tools(skill)}
    plan = routing.plan_tools(body.agent_id, body.tool_selection, skill)
    return {k: v for k, v in plan.event().items() if k not in ("type", "route_mode", "route_reason")}


# ── MCP 서버 ─────────────────────────────────────────────────
# 회사 MCP 서버를 주소로 등록 → tool 목록 확인(probe) → 가져올 tool 선택 → 저장하면 바로 반영.

class McpConn(BaseModel):
    url: str = Field(min_length=1)
    transport: str = Field(default="streamable_http", pattern="^(streamable_http|sse)$")
    headers: dict[str, str] = {}


class McpGroupIn(BaseModel):
    """서버 안의 tool 묶음 — 대화 위 ⚙ · 스킬 편집에서 이 단위로 보인다."""
    id: str = Field(pattern=r"^[a-z0-9_]{1,24}$")
    name: str = Field(min_length=1, max_length=40)
    description: str = ""
    tags: list[str] = []
    tools: list[str] = []


class McpServerIn(McpConn):
    name: str = Field(min_length=1, max_length=40)
    description: str = ""
    enabled: bool = True
    tools: list[str] = []
    labels: dict[str, str] = {}
    default_on: bool = True
    tags: list[str] = []       # 업무 영역 태그 (공정 · 장비 · 품질 · 공통 등) — 대화 위 영역 탭
    groups: list[McpGroupIn] = []   # 서버 안에서 tool 을 나눈 그룹 (비우면 서버 = 그룹 하나)


class McpServerCreate(McpServerIn):
    id: str


def _yaml_view(name: str, conf: dict) -> dict:
    """mcp_servers.yaml 서버 — 화면에서는 읽기 전용. URL 은 치환해서, 헤더는 치환 전 그대로(토큰 노출 방지)."""
    headers = conf.get("headers") or {}
    return {
        "id": name, "name": name, "description": "mcp_servers.yaml", "url": mcp_registry.expand(conf.get("url", "")),
        "transport": conf.get("transport", ""), "headers": {k: mcp_store.mask(v) for k, v in headers.items()},
        "enabled": mcp_registry.is_on(mcp_registry.expand(conf.get("enabled", True))),
        "tools": conf.get("tools") or [], "labels": {}, "default_on": False, "source": "yaml",
    }


@router.get("/mcp/servers")
def list_mcp_servers():
    status = {s["name"]: s for s in mcp_registry.status()}
    items = [_yaml_view(n, c) for n, c in mcp_registry.yaml_servers().items()]
    items += [mcp_store.public(r) | {"source": "hub"} for r in mcp_store.list_items()]
    return [i | {"status": status.get(i["id"])} for i in items]


def _mark_ui(tools: list[dict]) -> list[dict]:
    """화면 전용 tool 표시 — 화면에서 LLM tool 로 고르지 못하게 한다."""
    return [t | {"ui": t["name"] in catalog.UI_TOOLS} for t in tools]


class McpProbeIn(McpConn):
    server_id: Optional[str] = None   # 등록된 서버를 고치는 중이면 — 가려진 헤더 값을 저장된 값으로 채운다


@router.post("/mcp/probe")
async def probe_mcp(body: McpProbeIn):
    """등록 전 미리 보기 — 서버에 붙어 tool 목록만 받아온다."""
    conn = body.model_dump(exclude={"server_id"})
    old = mcp_store.get_item(body.server_id) if body.server_id else None
    conn["headers"] = mcp_store.merge_headers(conn["headers"], (old or {}).get("headers"))
    try:
        return _mark_ui(await mcp_registry.probe(conn))
    except ConnectionError as e:
        raise HTTPException(502, f"MCP 서버 연결 실패: {e}") from e


@router.get("/mcp/servers/{server_id}/tools")
async def probe_saved_mcp(server_id: str):
    """등록된 서버의 현재 tool 목록 (선택 변경용). yaml 서버도 조회만 가능."""
    rec = mcp_store.get_item(server_id)
    if rec:
        conn = mcp_store.connection(rec)
    elif server_id in mcp_registry.yaml_servers():
        conn = {k: v for k, v in mcp_registry.yaml_servers()[server_id].items() if k not in ("enabled", "tools")}
    else:
        raise HTTPException(404, "MCP server not found")
    try:
        return _mark_ui(await mcp_registry.probe(conn))
    except ConnectionError as e:
        raise HTTPException(502, f"MCP 서버 연결 실패: {e}") from e


def _ui_selected(tools: list[str]) -> list[str]:
    bad = [t for t in tools if t in catalog.UI_TOOLS]
    if bad:
        raise HTTPException(422, f"화면 전용 tool 은 LLM tool 로 가져올 수 없음: {', '.join(bad)}")
    return tools


async def _save_mcp(server_id: str, body: McpServerIn, create: bool) -> dict:
    _ui_selected(body.tools)
    if body.enabled and not body.tools:
        raise HTTPException(422, "가져올 tool 을 1개 이상 선택하세요")
    gids = [g.id for g in body.groups]
    if len(gids) != len(set(gids)):
        raise HTTPException(422, "그룹 id 가 겹칩니다")
    for g in body.groups:  # 선택하지 않은 tool 을 그룹에 넣었으면 빼고 저장
        g.tools = [t for t in dict.fromkeys(g.tools) if t in body.tools]
    try:
        if create:
            mcp_store.validate_id(server_id, set(mcp_registry.yaml_servers()))
        rec = mcp_store.save(server_id, body.model_dump(), create=create)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    except KeyError as e:
        raise HTTPException(404, "MCP server not found") from e
    await catalog.refresh()
    return mcp_store.public(rec) | {"source": "hub"}


@router.post("/mcp/servers")
async def create_mcp_server(body: McpServerCreate):
    return await _save_mcp(body.id, McpServerIn(**body.model_dump(exclude={"id"})), create=True)


@router.put("/mcp/servers/{server_id}")
async def update_mcp_server(server_id: str, body: McpServerIn):
    return await _save_mcp(server_id, body, create=False)


@router.delete("/mcp/servers/{server_id}")
async def delete_mcp_server(server_id: str):
    if not mcp_store.delete(server_id):
        raise HTTPException(404, "MCP server not found")
    await catalog.refresh()
    return {"ok": True}


# ── 보관된 tool 결과 (data_ref) ──────────────────────────────
# 큰 tool 결과는 저장소에 보관되고 LLM 에는 요약 + data_ref 만 간다 (hub/offload.py).
# code interpreter 커널의 load_ref("dr_...") 가 부른다 — 그 대화(세션)에서 만든 데이터만 내준다.

@router.get("/data/{ref}")
def get_data_ref(ref: str, x_coris_session: str = Header(default="")):
    rec = _or_404(offload.load(ref), "data_ref")
    if not x_coris_session or offload.session_key(x_coris_session) != rec["session"]:
        raise HTTPException(403, "이 대화에서 만든 데이터가 아닙니다")
    return rec


# ── 첨부 이미지 ──────────────────────────────────────────────
# 입력창에 붙여넣은(Ctrl+V) 이미지. multipart 의존성 없이 base64 JSON 으로 받는다.

class UploadIn(BaseModel):
    name: str = "image"
    mime: str
    data: str   # base64 (data URL 앞부분이 붙어 있어도 된다)


@router.post("/uploads")
def upload_image(body: UploadIn, user: dict = Depends(current_user)):
    try:
        return uploads.public(uploads.save(body.name, body.mime, body.data, user["user_id"]))
    except ValueError as e:
        raise HTTPException(422, str(e)) from e


@router.get("/uploads/{upload_id}")
def get_upload(upload_id: str):
    meta = _or_404(uploads.get(upload_id), "upload")
    return FileResponse(uploads.file_path(meta), media_type=meta["mime"])


# ── 사용자 · 메모리 ────────────────────────────────────────────

class MemoryIn(BaseModel):
    content: str = Field(min_length=1, max_length=memory.MAX_CHARS * 2)


@router.get("/me")
def get_me(user: dict = Depends(current_user)):
    m = user_store.get_memory(user["user_id"])
    return {"user": user, "is_admin": user["is_admin"], "memory": m, "memory_enabled": memory.ENABLED,
            "template": memory.template(user)}


@router.put("/me/memory")
def edit_memory(body: MemoryIn, user: dict = Depends(current_user)):
    """사용자가 화면에서 직접 고친 메모리 — 다음 대화부터 그대로 쓰인다."""
    return user_store.save_memory(user["user_id"], body.content.strip(), "edit")


@router.delete("/me/memory")
def reset_memory(user: dict = Depends(current_user)):
    """최신본만 지운다 (history 는 남김) — 다음 대화부터 새로 쌓인다."""
    user_store.delete_memory(user["user_id"])
    return {"ok": True}


@router.get("/me/memory/history")
def list_memory_history(user: dict = Depends(current_user)):
    return user_store.memory_history(user["user_id"])


@router.get("/me/memory/history/{version}")
def get_memory_version(version: int, user: dict = Depends(current_user)):
    return _or_404(user_store.memory_version(user["user_id"], version), "memory version")


@router.post("/me/memory/history/{version}/restore")
def restore_memory(version: int, user: dict = Depends(current_user)):
    old = _or_404(user_store.memory_version(user["user_id"], version), "memory version")
    return user_store.save_memory(user["user_id"], old["content"], "restore")


# ── 대화 ──────────────────────────────────────────────────────

@router.get("/conversations")
def list_conversations(source: Optional[str] = None, limit: int = 50):
    items = store.list_items("conversations")
    if source:
        items = [c for c in items if c.get("source") == source]
    items.sort(key=lambda c: c["updated_at"], reverse=True)
    heads = [service.conversation_head(c) | {"status": "running" if runs.active(c["id"]) else "done"} for c in items[:limit]]
    # 답변 중인 새 대화 — 아직 저장 전이라 목록에 없으므로 맨 위에 붙인다
    known = {c["id"] for c in items}
    fresh = [r.head() for r in runs.active_runs() if r.conv_id not in known and (not source or source == "chat")]
    return fresh + heads


@router.get("/conversations/{conv_id}")
def get_conversation(conv_id: str):
    conv = _or_404(store.get_item("conversations", conv_id), "conversation")
    # trace(tool 원본 결과)는 다음 턴 agent 입력용 — 화면에는 tools 요약만 내려보낸다
    return conv | {"messages": [{k: v for k, v in m.items() if k != "trace"} for m in conv["messages"]]}


class ConversationPatch(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=80)
    favorite: Optional[bool] = None


@router.patch("/conversations/{conv_id}")
def patch_conversation(conv_id: str, body: ConversationPatch):
    """이름 변경 · 즐겨찾기 켜고 끄기 (보낸 항목만 바꾼다)."""
    conv = _or_404(store.get_item("conversations", conv_id), "conversation")
    if body.title is not None:
        conv["title"] = body.title.strip()
    if body.favorite is not None:
        conv["favorite"] = body.favorite
    return service.conversation_head(store.upsert_item("conversations", conv))


@router.delete("/conversations")
def delete_all_conversations(source: Optional[str] = None):
    """전체 삭제 — 즐겨찾기한 대화는 남긴다. source(chat | event)를 주면 그 종류만."""
    n = store.delete_where("conversations", lambda c: not c.get("favorite") and (not source or c.get("source") == source))
    return {"ok": True, "deleted": n}


@router.delete("/conversations/{conv_id}")
def delete_conversation(conv_id: str):
    if not store.delete_item("conversations", conv_id):
        raise HTTPException(404, "conversation not found")
    return {"ok": True}


# ── 스킬 ──────────────────────────────────────────────────────

class SkillIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    description: str = ""
    tools: list[str] = []
    instructions: str = ""
    tags: list[str] = []
    visibility: Optional[str] = Field(default=None, pattern="^(official|private)$")  # 공식 지정은 관리자만
    # 단계 실행 (선택) — None 이면 기존 정의 유지, [] 면 지움 (프롬프트 skill 로)
    inputs: Optional[list[dict]] = None
    steps: Optional[list[dict]] = None


def _check_tools(names: list[str]) -> list[str]:
    # MCP 서버가 잠시 내려가 있어도 skill 편집은 되도록 catalog.yaml 에 있는 이름도 허용
    known = set(catalog.GROUPED_TOOLS) | set(catalog.TOOLS_BY_NAME)
    unknown = [n for n in names if n not in known]
    if unknown:
        raise HTTPException(422, f"unknown tools: {', '.join(unknown)}")
    return names


def _structure(body: SkillIn) -> Optional[dict]:
    """단계 정의 검사 후 저장할 값 — 보내지 않았으면 None(기존 유지)."""
    if body.inputs is None and body.steps is None:
        return None
    inputs, steps_ = body.inputs or [], body.steps or []
    known = set(catalog.GROUPED_TOOLS) | set(catalog.TOOLS_BY_NAME)
    errs = steps.validate(steps_, inputs, known)
    if errs:
        raise HTTPException(422, "단계 정의 오류 — " + " / ".join(errs[:6]))
    return {"inputs": inputs, "steps": steps_}


def _skill_for(skill_id: str, user: dict, edit: bool = False) -> dict:
    skill = _or_404(skills.get_item(skill_id), "skill")
    if not skills.visible(skill, user["user_id"], user["is_admin"]):
        raise HTTPException(404, "skill not found")  # 남의 내 스킬은 있는지도 알리지 않는다
    if edit and not skills.can_edit(skill, user["user_id"], user["is_admin"]):
        raise HTTPException(403, "공식 스킬은 관리자만 고칠 수 있습니다 — '복제해서 내 스킬로' 를 쓰세요")
    return skill


def _visibility(body: SkillIn, user: dict, default: str) -> str:
    if body.visibility == skills.OFFICIAL and not user["is_admin"]:
        raise HTTPException(403, "공식 스킬 지정은 관리자만 할 수 있습니다")
    return body.visibility or default


@router.get("/skills")
def list_skills(user: dict = Depends(current_user)):
    """내가 볼 수 있는 스킬 — 공식 + 내 스킬 (관리자는 전부)."""
    return skills.list_items(user["user_id"], user["is_admin"])


@router.post("/skills")
def create_skill(body: SkillIn, user: dict = Depends(current_user)):
    """새 스킬은 기본이 '내 스킬'(나만 보임). 관리자는 바로 공식으로 만들 수 있다."""
    _check_tools(body.tools)
    data = body.model_dump(exclude={"visibility", "inputs", "steps"})
    return skills.save(None, **data, visibility=_visibility(body, user, skills.PRIVATE),
                       owner=user["user_id"], owner_name=user["name"], structure=_structure(body))


@router.put("/skills/{skill_id}")
def update_skill(skill_id: str, body: SkillIn, user: dict = Depends(current_user)):
    old = _skill_for(skill_id, user, edit=True)
    _check_tools(body.tools)
    data = body.model_dump(exclude={"visibility", "inputs", "steps"})
    return skills.save(skill_id, **data, visibility=_visibility(body, user, old["visibility"]), structure=_structure(body))


@router.post("/skills/{skill_id}/copy")
def copy_skill(skill_id: str, user: dict = Depends(current_user)):
    """공식 스킬(또는 볼 수 있는 스킬)을 복제해 내 스킬로 — 원본은 그대로."""
    src = _skill_for(skill_id, user)
    return skills.save(None, f"{src['name']} (내 버전)"[:60], src["description"], src["tools"], src["instructions"],
                       tags=src["tags"], visibility=skills.PRIVATE, owner=user["user_id"], owner_name=user["name"],
                       extra=src["extra"])


@router.delete("/skills/{skill_id}")
def delete_skill(skill_id: str, user: dict = Depends(current_user)):
    _skill_for(skill_id, user, edit=True)
    if not skills.delete_item(skill_id):
        raise HTTPException(404, "skill not found")
    return {"ok": True}


# ── 이벤터 ────────────────────────────────────────────────────

class Schedule(BaseModel):
    kind: str = Field(pattern="^(daily|weekly)$")
    time: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    weekday: Optional[int] = Field(default=None, ge=0, le=6)


class EventIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    schedule: Schedule
    prompt: str = ""
    skill_id: Optional[str] = None
    agent_id: str = "auto"
    target: str = ""
    enabled: bool = True


class EventPatch(BaseModel):
    enabled: bool


@router.get("/events")
def list_events():
    return [service.event_view(e) for e in store.list_items("events")]


@router.post("/events")
def create_event(body: EventIn):
    event = body.model_dump() | {"id": store.new_id("ev"), "last_run": None}
    return service.event_view(store.upsert_item("events", event))


@router.put("/events/{event_id}")
def update_event(event_id: str, body: EventIn):
    event = _or_404(store.get_item("events", event_id), "event")
    event.update(body.model_dump())
    return service.event_view(store.upsert_item("events", event))


@router.patch("/events/{event_id}")
def toggle_event(event_id: str, body: EventPatch):
    event = _or_404(store.get_item("events", event_id), "event")
    event["enabled"] = body.enabled
    return service.event_view(store.upsert_item("events", event))


@router.delete("/events/{event_id}")
def delete_event(event_id: str):
    if not store.delete_item("events", event_id):
        raise HTTPException(404, "event not found")
    service.cancel_event_tasks(event_id)   # 대기 중이던 작업은 취소 (실행 중인 것은 끝까지 간다)
    return {"ok": True}


@router.post("/events/{event_id}/run")
def run_event(event_id: str):
    """지금 실행 — 바로 돌리지 않고 작업 큐에 넣는다. 결과는 GET /tasks 로 확인."""
    _or_404(store.get_item("events", event_id), "event")
    return service.enqueue(event_id, "manual")


# ── 작업 큐 (task table) ─────────────────────────────────────

@router.get("/tasks")
def list_tasks(event_id: Optional[str] = None, status: Optional[str] = None, limit: int = 50):
    """최근 task (새것 먼저). status 는 쉼표로 여러 개 — queued,running,done,error,canceled"""
    return service.list_tasks(event_id, status, min(limit, 500))


@router.get("/tasks/{task_id}")
def get_task(task_id: str):
    return service.task_view(_or_404(store.get_item("tasks", task_id), "task"))


@router.post("/tasks/{task_id}/cancel")
def cancel_task(task_id: str):
    try:
        return service.cancel_task(task_id)
    except KeyError as e:
        raise HTTPException(404, "task not found") from e
    except ValueError as e:
        raise HTTPException(409, str(e)) from e


@router.post("/tasks/{task_id}/retry")
def retry_task(task_id: str):
    try:
        return service.retry_task(task_id)
    except KeyError as e:
        raise HTTPException(404, "task not found") from e
    except ValueError as e:
        raise HTTPException(409, str(e)) from e


# ── tool 그룹 (그룹 메뉴) ─────────────────────────────────────
# MCP 서버와 상관없이 tool 을 골라 묶고, 그룹마다 업무 영역 태그를 단다. 저장하면 바로 반영(재시작 불필요).

class ToolGroupIn(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    description: str = Field(default="", max_length=200)
    tags: list[str] = []
    tools: list[str] = []
    default_on: bool = True    # 켜면 질문마다 LLM 이 이 그룹 tool 을 본다
    enabled: bool = True


def _group_body(body: ToolGroupIn) -> dict:
    if not body.tools:
        raise HTTPException(422, "tool 을 1개 이상 넣으세요")
    _ui_selected(body.tools)
    _check_tools(body.tools)
    return body.model_dump()


@router.get("/tool-groups")
def list_tool_groups():
    return tool_groups.list_items()


@router.post("/tool-groups")
def create_tool_group(body: ToolGroupIn, user: dict = Depends(current_user)):
    rec = tool_groups.save(None, _group_body(body), user["user_id"])
    catalog.rebuild()
    return rec


@router.put("/tool-groups/{group_id}")
def update_tool_group(group_id: str, body: ToolGroupIn):
    try:
        rec = tool_groups.save(group_id, _group_body(body))
    except KeyError as e:
        raise HTTPException(404, "tool group not found") from e
    catalog.rebuild()
    return rec


@router.delete("/tool-groups/{group_id}")
def delete_tool_group(group_id: str):
    if not tool_groups.delete(group_id):
        raise HTTPException(404, "tool group not found")
    catalog.rebuild()
    return {"ok": True}
