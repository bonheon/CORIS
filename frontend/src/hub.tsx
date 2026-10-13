import React, { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { api, Attachment, ConvHead, HubEvent, Me, Meta, Skill } from "./api";

// 새 대화를 시작할 때 채팅 화면으로 넘기는 요청
export interface PendingChat { text: string; agentId: string; skillId: string | null; tools?: string[]; attachments?: Attachment[] }

interface HubState {
  meta: Meta | null;
  me: Me | null;
  refreshMe: () => Promise<void>;
  conversations: ConvHead[];
  skills: Skill[];
  events: HubEvent[];
  refreshMeta: () => Promise<void>;
  refreshConversations: () => Promise<void>;
  refreshSkills: () => Promise<void>;
  refreshEvents: () => Promise<void>;
  toolLabel: (name: string) => string;
  agentName: (id: string | null | undefined) => string;
  /** 새 대화로 이동하며 질문을 바로 보낸다 */
  startChat: (p: PendingChat) => void;
  takePending: () => PendingChat | null;
  /** startChat 호출마다 증가 — 이미 /new 에 있어도 채팅 화면이 반응하도록 */
  pendingTick: number;
  toast: (msg: string) => void;
}

const Ctx = createContext<HubState | null>(null);

export function useHub(): HubState {
  const v = useContext(Ctx);
  if (!v) throw new Error("HubProvider missing");
  return v;
}

export function HubProvider({ children, navigate }: { children: React.ReactNode; navigate: (p: string) => void }) {
  const [meta, setMeta] = useState<Meta | null>(null);
  const [me, setMe] = useState<Me | null>(null);
  const [conversations, setConversations] = useState<ConvHead[]>([]);
  const [skills, setSkills] = useState<Skill[]>([]);
  const [events, setEvents] = useState<HubEvent[]>([]);
  const [toastMsg, setToastMsg] = useState<string | null>(null);
  const pending = useRef<PendingChat | null>(null);
  const [pendingTick, setPendingTick] = useState(0);

  const refreshMeta = useCallback(async () => { setMeta(await api.meta()); }, []);
  const refreshMe = useCallback(async () => { setMe(await api.me()); }, []);
  const refreshConversations = useCallback(async () => { setConversations(await api.conversations()); }, []);
  const refreshSkills = useCallback(async () => { setSkills(await api.skills()); }, []);
  const refreshEvents = useCallback(async () => { setEvents(await api.events()); }, []);

  useEffect(() => {
    api.meta().then(setMeta).catch(() => setMeta(null));
    refreshMe().catch(() => {});
    refreshConversations().catch(() => {});
    refreshSkills().catch(() => {});
    refreshEvents().catch(() => {});
  }, [refreshMe, refreshConversations, refreshSkills, refreshEvents]);

  const toast = useCallback((msg: string) => {
    setToastMsg(msg);
    window.setTimeout(() => setToastMsg((m) => (m === msg ? null : m)), 2400);
  }, []);

  const value = useMemo<HubState>(() => {
    const labels = new Map(meta?.tools.map((t) => [t.name, t.label]));
    const agents = new Map(meta?.agents.map((a) => [a.id, a.name]));
    return {
      meta, me, refreshMe, conversations, skills, events,
      refreshMeta, refreshConversations, refreshSkills, refreshEvents,
      toolLabel: (n) => labels.get(n) ?? n,
      agentName: (id) => agents.get(id ?? "auto") ?? "자동 선택",
      startChat: (p) => { pending.current = p; setPendingTick((n) => n + 1); navigate("/new"); },
      takePending: () => { const p = pending.current; pending.current = null; return p; },
      pendingTick,
      toast,
    };
  }, [meta, me, refreshMe, conversations, skills, events, refreshMeta, refreshConversations, refreshSkills, refreshEvents, navigate, toast, pendingTick]);

  return (
    <Ctx.Provider value={value}>
      {children}
      {toastMsg && <div className="toast">{toastMsg}</div>}
    </Ctx.Provider>
  );
}
