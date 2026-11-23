import { Probe, startProbe } from "./timingProbe";

// Hub 백엔드 API — 타입과 호출 함수

export interface Agent {
  id: string; name: string; description: string;
  tools: string[];               // 허용 범위 (allowed_groups 의 tool 전체)
  allowed_groups: string[]; default_groups: string[];
}
export interface ToolGroup {
  id: string; name: string; description: string; tools: string[]; tags?: string[];
  imported?: boolean;   // 화면에서 만든 그룹 (MCP 서버 · 그룹 메뉴)
  custom?: boolean;     // 그룹 메뉴에서 만든 그룹 — 서버 상관없이 tool 을 묶음
  server?: string; default_on?: boolean;
}
/** 그룹 메뉴에서 만든 tool 그룹 — GET /api/hub/tool-groups */
export interface ToolGroupRec {
  id: string; name: string; description: string; tags: string[]; tools: string[];
  default_on: boolean; enabled: boolean; owner: string | null; created_at: string; updated_at: string;
}
export type ToolGroupInput = Pick<ToolGroupRec, "name" | "description" | "tags" | "tools" | "default_on" | "enabled">;
export interface ToolInfo {
  name: string; label: string; category: string; description: string;
  group: string | null; available: boolean; server: string | null;
}
export interface McpServer {
  name: string; url: string; status: "ok" | "down"; source: "yaml" | "hub";
  tools: string[];      // Coris 에 들어온 tool
  offered: number;      // 서버가 제공하는 tool 수
  error: string | null; checked_at: string;
}
/** MCP 서버 설정 — yaml(배포 설정, 읽기 전용) 또는 hub(화면에서 등록) */
export interface McpServerConf {
  id: string; name: string; description: string; url: string; transport: string;
  headers: Record<string, string>;   // 값은 가려져서 온다 (그대로 보내면 기존 값 유지)
  enabled: boolean; tools: string[]; labels: Record<string, string>; default_on: boolean; tags?: string[];
  groups?: McpGroup[];   // 서버 안의 tool 묶음 (비우면 서버 = 그룹 하나)
  source: "yaml" | "hub"; status?: McpServer | null;
}
export interface McpGroup { id: string; name: string; description: string; tags: string[]; tools: string[] }
export type McpServerInput = Omit<McpServerConf, "source" | "status">;
export interface McpToolSpec {
  name: string; description: string; ui: boolean;
  params: { name: string; type: string; required: boolean; description: string }[];
}
export interface Portal { id: string; name: string; description: string; status: "ok" | "warn" | "err"; note: string; url: string }
export interface Meta {
  agents: Agent[]; groups: ToolGroup[]; tools: ToolInfo[]; portals: Portal[];
  areas: string[];   // 업무 영역 (공정 · 장비 · 품질) — 대화 위 영역 탭
  mcp_servers: McpServer[];
}

/** 첨부 이미지 — POST /api/hub/uploads 결과 */
export interface Attachment { id: string; name: string; mime: string }
export const uploadUrl = (id: string) => `/api/hub/uploads/${id}`;

export interface ToolRun { id?: string; name: string; args: Record<string, unknown>; ms: number | null; ok: boolean | null }

/** 백엔드 분기 결과 — 어떤 agent 가 어떤 tool 로 처리하는지 */
export type RouteMode = "manual" | "single" | "sticky" | "router" | "fallback";
export interface RouteInfo {
  agent_id: string; agent_name: string;
  route_mode: RouteMode; route_reason: string;
  tools: string[]; locked: string[];
  dropped: { name: string; reason: "excluded" | "not_allowed" | "unavailable" }[];
  warnings: string[];
  // 적용된 skill — manual: 사용자가 고름, router: 질문 보고 자동 선택, sticky: 직전 턴 workflow 유지
  skill_id?: string | null; skill_name?: string | null; skill_mode?: SkillMode;
}
export type SkillMode = "none" | "manual" | "router" | "sticky";
export interface User {
  user_id: string; name: string; dept: string; email: string;
  profile: Record<string, unknown>; created_at: string; last_seen: string;
}
export interface UserMemory { user_id: string; content: string; version: number; updated_at: string; source: string }
export interface MemoryVersion { version: number; source: string; created_at: string; chars?: number; content?: string }
export interface Me { user: User; is_admin: boolean; memory: UserMemory | null; memory_enabled: boolean; template: string }
/** 채팅 시작 시 백엔드가 불러온 사용자 · 메모리 */
export interface UserCtx { user_id: string; name: string; memory_chars: number; memory_version: number }

export interface ToolSelection { groups?: string[]; tools?: string[]; exclude?: string[] }

export interface StoredMessage {
  role: "user" | "assistant"; content: string; tools?: ToolRun[]; at: string;
  agent?: string | null; route?: RouteInfo | null; attachments?: Attachment[]; suggestions?: string[];
}
export interface ConvHead {
  id: string; title: string; source: "chat" | "event"; event_id: string | null;
  agent_id: string; skill_id: string | null; skill_ids?: string[]; summary: string;
  created_at: string; updated_at: string; turns: number;
  favorite?: boolean;   // 즐겨찾기 — 전체 삭제에서 빠진다
  status?: "running" | "done";   // running = 지금 답변을 만드는 중 (화면을 떠나도 계속된다)
}
export interface Conversation extends Omit<ConvHead, "turns"> { messages: StoredMessage[] }

export interface Skill {
  id: string; name: string; description: string; tools: string[]; instructions: string;
  tags: string[];                       // 자유 입력 — 영역 탭 · 검색
  visibility: "official" | "private";   // 공식(모두) | 내 스킬(만든 사람 · 관리자)
  owner: string | null; owner_name: string;
  uses: number; created_at: string; updated_at: string;
  inputs?: StepInputDef[];   // 단계 실행 입력값
  steps?: StepDef[];         // 단계 정의 — 있으면 단계 실행 엔진이 순서대로 실행 (LLM 은 판단 · 보고만)
}
export type SkillVisibility = "official" | "private";
export type SkillInput = Pick<Skill, "name" | "description" | "tools" | "instructions" | "tags"> & {
  visibility?: SkillVisibility; inputs?: StepInputDef[]; steps?: StepDef[];
};

/** 단계 실행 (hub/steps.py) — SKILL.md 의 inputs · steps 와 같은 모양 */
export interface StepInputDef { name: string; label?: string; required?: boolean; example?: string }
export type StepType = "data" | "compute" | "condition" | "judge" | "report";
export interface StepDef {
  id: string; type: StepType; title?: string;
  tool?: string; args?: Record<string, unknown>; for_each?: string;                 // data (for_each 는 compute table 도)
  op?: "table" | "unique" | "filter"; columns?: Record<string, string>; of?: string; column?: string; equals?: string;   // compute
  if?: string; then?: string; verdict?: string;                                     // condition
  from?: string[]; prompt?: string; outputs?: string[]; criteria?: { verdict: string; when: string }[];   // judge
  template?: string;                                                                // report
  [k: string]: unknown;
}

export interface Schedule { kind: "daily" | "weekly"; time: string; weekday: number | null }
export interface LastRun {
  at: string; status: "ok" | "error"; conversation_id: string | null;
  summary: string; tool_count: number; elapsed_s: number; task_id?: string;
}
export interface HubEvent {
  id: string; name: string; schedule: Schedule; prompt: string; skill_id: string | null;
  agent_id: string; target: string; enabled: boolean; last_run: LastRun | null; next_run: string | null;
}
export type EventInput = Omit<HubEvent, "id" | "last_run" | "next_run">;

/** 작업 큐(task table) — 스케줄 실행 1건. 한 번에 한 건씩, 넣은 순서대로 처리된다 */
export type TaskStatus = "queued" | "running" | "done" | "error" | "canceled";
export interface HubTask {
  id: string; event_id: string; event_name: string; prompt: string; skill_id: string | null; agent_id: string;
  trigger: "schedule" | "manual" | "retry"; status: TaskStatus; attempt: number; retry_of: string | null;
  created_at: string; started_at: string | null; finished_at: string | null; elapsed_s: number | null;
  routed_agent: string | null; conversation_id: string | null; tool_count: number; summary: string; error: string | null;
  position: number | null;   // 대기 중일 때 차례 (1 = 다음)
}

async function req<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, {
    ...init,
    headers: init?.body ? { "Content-Type": "application/json" } : undefined,
  });
  if (!res.ok) {
    const detail = await res.json().then((j) => j.detail, () => res.statusText);
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return res.json();
}
const json = (method: string, body: unknown): RequestInit => ({ method, body: JSON.stringify(body) });

export const api = {
  meta: () => req<Meta>("/api/hub/meta"),
  me: () => req<Me>("/api/hub/me"),
  saveMemory: (content: string) => req<UserMemory>("/api/hub/me/memory", json("PUT", { content })),
  resetMemory: () => req("/api/hub/me/memory", { method: "DELETE" }),
  memoryHistory: () => req<MemoryVersion[]>("/api/hub/me/memory/history"),
  memoryVersion: (v: number) => req<MemoryVersion>(`/api/hub/me/memory/history/${v}`),
  restoreMemory: (v: number) => req<UserMemory>(`/api/hub/me/memory/history/${v}/restore`, { method: "POST" }),
  refreshCatalog: () => req<{ tools: number; servers: McpServer[] }>("/api/hub/catalog/refresh", { method: "POST" }),

  mcpServers: () => req<McpServerConf[]>("/api/hub/mcp/servers"),
  mcpProbe: (conn: { url: string; transport: string; headers: Record<string, string>; server_id?: string }) =>
    req<McpToolSpec[]>("/api/hub/mcp/probe", json("POST", conn)),
  mcpServerTools: (id: string) => req<McpToolSpec[]>(`/api/hub/mcp/servers/${id}/tools`),
  createMcpServer: (s: McpServerInput) => req<McpServerConf>("/api/hub/mcp/servers", json("POST", s)),
  updateMcpServer: (id: string, s: Omit<McpServerInput, "id">) => req<McpServerConf>(`/api/hub/mcp/servers/${id}`, json("PUT", s)),
  deleteMcpServer: (id: string) => req(`/api/hub/mcp/servers/${id}`, { method: "DELETE" }),

  uploadImage: (f: { name: string; mime: string; data: string }) => req<Attachment>("/api/hub/uploads", json("POST", f)),

  conversations: () => req<ConvHead[]>("/api/hub/conversations"),
  conversation: (id: string) => req<Conversation>(`/api/hub/conversations/${id}`),
  deleteConversation: (id: string) => req(`/api/hub/conversations/${id}`, { method: "DELETE" }),
  patchConversation: (id: string, p: { title?: string; favorite?: boolean }) => req<ConvHead>(`/api/hub/conversations/${id}`, json("PATCH", p)),
  deleteAllConversations: (source?: string) =>
    req<{ ok: boolean; deleted: number }>(`/api/hub/conversations${source ? `?source=${source}` : ""}`, { method: "DELETE" }),

  skills: () => req<Skill[]>("/api/hub/skills"),
  createSkill: (s: SkillInput) => req<Skill>("/api/hub/skills", json("POST", s)),
  updateSkill: (id: string, s: SkillInput) => req<Skill>(`/api/hub/skills/${id}`, json("PUT", s)),
  deleteSkill: (id: string) => req(`/api/hub/skills/${id}`, { method: "DELETE" }),
  copySkill: (id: string) => req<Skill>(`/api/hub/skills/${id}/copy`, { method: "POST" }),

  events: () => req<HubEvent[]>("/api/hub/events"),
  createEvent: (e: EventInput) => req<HubEvent>("/api/hub/events", json("POST", e)),
  updateEvent: (id: string, e: EventInput) => req<HubEvent>(`/api/hub/events/${id}`, json("PUT", e)),
  toggleEvent: (id: string, enabled: boolean) => req<HubEvent>(`/api/hub/events/${id}`, json("PATCH", { enabled })),
  deleteEvent: (id: string) => req(`/api/hub/events/${id}`, { method: "DELETE" }),
  runEvent: (id: string) => req<HubTask>(`/api/hub/events/${id}/run`, { method: "POST" }),

  tasks: (p: { event_id?: string; status?: string; limit?: number } = {}) =>
    req<HubTask[]>(`/api/hub/tasks?${new URLSearchParams(Object.entries(p).filter(([, v]) => v != null).map(([k, v]) => [k, String(v)]))}`),
  cancelTask: (id: string) => req<HubTask>(`/api/hub/tasks/${id}/cancel`, { method: "POST" }),
  retryTask: (id: string) => req<HubTask>(`/api/hub/tasks/${id}/retry`, { method: "POST" }),

  toolGroups: () => req<ToolGroupRec[]>("/api/hub/tool-groups"),
  createToolGroup: (g: ToolGroupInput) => req<ToolGroupRec>("/api/hub/tool-groups", json("POST", g)),
  updateToolGroup: (id: string, g: ToolGroupInput) => req<ToolGroupRec>(`/api/hub/tool-groups/${id}`, json("PUT", g)),
  deleteToolGroup: (id: string) => req(`/api/hub/tool-groups/${id}`, { method: "DELETE" }),
};

// ── 채팅 스트리밍 (SSE over fetch) ─────────────────────────────

export interface ChatRequest {
  messages: { role: "user" | "assistant"; content: string; attachments?: string[] }[];
  conversation_id: string | null;
  agent_id: string;
  skill_ids: string[];           // 켜 둔 스킬 — 1개면 그 절차, 2개 이상이면 질문마다 맞는 것
  tool_selection?: ToolSelection | null;
}
export interface ChatHandlers {
  onMeta: (conversationId: string) => void;
  onUser: (ctx: UserCtx) => void;
  onRoute: (route: RouteInfo) => void;
  onDelta: (text: string) => void;
  onToolStart: (run: ToolRun & { id: string }) => void;
  onToolEnd: (id: string, ms: number, ok: boolean) => void;
  onError: (message: string) => void;
  onSuggestions?: (items: string[]) => void;
  onResume?: (info: { user_text: string; attachments: Attachment[]; started_at: string; done: boolean }) => void;
  onStopped?: () => void;
}

export async function streamChat(body: ChatRequest, h: ChatHandlers, signal?: AbortSignal) {
  const probe = startProbe();  // 응답 시간 측정 — localStorage coris.timing=1 일 때만 (docs/TIMING.md)
  const res = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  if (res.status === 409) throw new Error("이 대화는 아직 답변 중입니다");
  if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`);
  probe.headers();
  try {
    await readSSE(res, h, probe);
  } finally {
    probe.finish();
  }
}

/** 진행 중(또는 방금 끝난) 답변에 다시 연결 — 처음부터 다시 받는다. 진행 중인 답변이 없으면 false */
export async function resumeChat(convId: string, h: ChatHandlers, signal?: AbortSignal): Promise<boolean> {
  const res = await fetch(`/api/chat/${convId}/stream`, { signal });
  if (res.status === 404) return false;
  if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`);
  await readSSE(res, h);
  return true;
}

export const cancelChat = (convId: string) => fetch(`/api/chat/${convId}/cancel`, { method: "POST" });

async function readSSE(res: Response, h: ChatHandlers, probe?: Probe) {
  const reader = res.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";
    probe?.read(lines.filter((l) => l.startsWith("data: ")).length);
    for (const line of lines) {
      if (!line.startsWith("data: ")) continue;
      const payload = line.slice(6);
      if (payload === "[DONE]") return;
      let ev: any;
      try { ev = JSON.parse(payload); } catch { continue; }
      probe?.event(ev.type, ev.type === "meta" ? ev.conversation_id : undefined);
      switch (ev.type) {
        case "meta": h.onMeta(ev.conversation_id); break;
        case "user": { const { type, ...ctx } = ev; h.onUser(ctx as UserCtx); break; }
        case "route": { const { type, ...route } = ev; h.onRoute(route as RouteInfo); break; }
        case "delta": h.onDelta(ev.delta); break;
        case "tool_start": h.onToolStart({ id: ev.id, name: ev.name, args: ev.args, ms: null, ok: null }); break;
        case "tool_end": h.onToolEnd(ev.id, ev.ms, ev.ok); break;
        case "error": h.onError(ev.message); break;
        case "suggestions": h.onSuggestions?.(ev.items ?? []); break;
        case "resume": h.onResume?.(ev); break;
        case "stopped": h.onStopped?.(); break;
      }
    }
  }
}
