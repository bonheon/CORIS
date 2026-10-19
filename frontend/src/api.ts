// Hub 백엔드 API — 타입과 호출 함수

export interface Agent {
  id: string; name: string; description: string;
  tools: string[];               // 허용 범위 (allowed_groups 의 tool 전체)
  allowed_groups: string[]; default_groups: string[];
}
export interface ToolGroup { id: string; name: string; description: string; tools: string[] }
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
  enabled: boolean; tools: string[]; labels: Record<string, string>; default_on: boolean;
  source: "yaml" | "hub"; status?: McpServer | null;
}
export type McpServerInput = Omit<McpServerConf, "source" | "status">;
export interface McpToolSpec {
  name: string; description: string; ui: boolean;
  params: { name: string; type: string; required: boolean; description: string }[];
}
export interface Portal { id: string; name: string; description: string; status: "ok" | "warn" | "err"; note: string; url: string }
export interface Meta {
  agents: Agent[]; groups: ToolGroup[]; tools: ToolInfo[]; portals: Portal[];
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
export interface Me { user: User; memory: UserMemory | null; memory_enabled: boolean; template: string }
/** 채팅 시작 시 백엔드가 불러온 사용자 · 메모리 */
export interface UserCtx { user_id: string; name: string; memory_chars: number; memory_version: number }

export interface ToolSelection { groups?: string[]; tools?: string[]; exclude?: string[] }

export interface StoredMessage {
  role: "user" | "assistant"; content: string; tools?: ToolRun[]; at: string;
  agent?: string | null; route?: RouteInfo | null; attachments?: Attachment[]; suggestions?: string[];
}
export interface ConvHead {
  id: string; title: string; source: "chat" | "event"; event_id: string | null;
  agent_id: string; skill_id: string | null; summary: string;
  created_at: string; updated_at: string; turns: number;
}
export interface Conversation extends Omit<ConvHead, "turns"> { messages: StoredMessage[] }

export interface Skill {
  id: string; name: string; description: string; tools: string[]; instructions: string;
  uses: number; created_at: string; updated_at: string;
}
export type SkillInput = Pick<Skill, "name" | "description" | "tools" | "instructions">;

export interface Schedule { kind: "daily" | "weekly"; time: string; weekday: number | null }
export interface LastRun {
  at: string; status: "ok" | "error"; conversation_id: string | null;
  summary: string; tool_count: number; elapsed_s: number;
}
export interface HubEvent {
  id: string; name: string; schedule: Schedule; prompt: string; skill_id: string | null;
  agent_id: string; target: string; enabled: boolean; last_run: LastRun | null; next_run: string | null;
}
export type EventInput = Omit<HubEvent, "id" | "last_run" | "next_run">;

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

  skills: () => req<Skill[]>("/api/hub/skills"),
  createSkill: (s: SkillInput) => req<Skill>("/api/hub/skills", json("POST", s)),
  updateSkill: (id: string, s: SkillInput) => req<Skill>(`/api/hub/skills/${id}`, json("PUT", s)),
  deleteSkill: (id: string) => req(`/api/hub/skills/${id}`, { method: "DELETE" }),

  events: () => req<HubEvent[]>("/api/hub/events"),
  createEvent: (e: EventInput) => req<HubEvent>("/api/hub/events", json("POST", e)),
  updateEvent: (id: string, e: EventInput) => req<HubEvent>(`/api/hub/events/${id}`, json("PUT", e)),
  toggleEvent: (id: string, enabled: boolean) => req<HubEvent>(`/api/hub/events/${id}`, json("PATCH", { enabled })),
  deleteEvent: (id: string) => req(`/api/hub/events/${id}`, { method: "DELETE" }),
  runEvent: (id: string) => req<HubEvent>(`/api/hub/events/${id}/run`, { method: "POST" }),
};

// ── 채팅 스트리밍 (SSE over fetch) ─────────────────────────────

export interface ChatRequest {
  messages: { role: "user" | "assistant"; content: string; attachments?: string[] }[];
  conversation_id: string | null;
  agent_id: string;
  skill_id: string | null;
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
}

export async function streamChat(body: ChatRequest, h: ChatHandlers, signal?: AbortSignal) {
  const res = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`);

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";
    for (const line of lines) {
      if (!line.startsWith("data: ")) continue;
      const payload = line.slice(6);
      if (payload === "[DONE]") return;
      let ev: any;
      try { ev = JSON.parse(payload); } catch { continue; }
      switch (ev.type) {
        case "meta": h.onMeta(ev.conversation_id); break;
        case "user": { const { type, ...ctx } = ev; h.onUser(ctx as UserCtx); break; }
        case "route": { const { type, ...route } = ev; h.onRoute(route as RouteInfo); break; }
        case "delta": h.onDelta(ev.delta); break;
        case "tool_start": h.onToolStart({ id: ev.id, name: ev.name, args: ev.args, ms: null, ok: null }); break;
        case "tool_end": h.onToolEnd(ev.id, ev.ms, ev.ok); break;
        case "error": h.onError(ev.message); break;
        case "suggestions": h.onSuggestions?.(ev.items ?? []); break;
      }
    }
  }
}
