import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { CalendarClock, Share2, Sparkles } from "lucide-react";
import { api, Attachment, RouteInfo, streamChat, ToolRun, UserCtx } from "../api";
import { Message } from "../types";
import { useHub } from "../hub";
import MessageBubble from "../components/MessageBubble";
import Composer from "../shell/Composer";
import QuickBar from "../shell/QuickBar";
import { pushRecentSkills } from "../lib/recent";
import { getFollowUpSuggestions, STARTERS } from "../lib/suggestions";

let seq = 0;
const localId = () => `m${Date.now().toString(36)}${++seq}`;

interface Props {
  convId: string | null;
  navigate: (p: string, replace?: boolean) => void;
}

export default function ChatPage({ convId, navigate }: Props) {
  const { meta, refreshConversations, refreshEvents, takePending, pendingTick, agentName, toast, conversations } = useHub();
  const [messages, setMessages] = useState<Message[]>([]);
  const [agentId, setAgentId] = useState("auto");
  const [skillIds, setSkillIds] = useState<string[]>([]);   // 켜 둔 스킬 (QuickBar 칩)
  const [area, setArea] = useState("");                       // 영역 탭 — "" = 전체
  const [toolSel, setToolSel] = useState<string[]>([]);   // 비어 있으면 자동
  const [busy, setBusy] = useState(false);
  const [loadErr, setLoadErr] = useState<string | null>(null);

  const idRef = useRef<string | null>(convId);     // 현재 대화 id (새 대화면 meta 이벤트로 채워짐)
  const ownId = useRef<string | null>(null);       // 이 화면이 방금 만든 대화 — 라우트 변경 시 다시 불러오지 않음
  const abort = useRef<AbortController | null>(null);
  const bottom = useRef<HTMLDivElement>(null);
  const messagesRef = useRef(messages);
  messagesRef.current = messages;

  // ── 라우트 변경: 대화 불러오기 / 초기화 ──
  useEffect(() => {
    if (convId && convId === ownId.current) return;
    abort.current?.abort();
    idRef.current = convId;
    ownId.current = null;
    setLoadErr(null);
    // 같은 커밋에서 바로 send() 가 불릴 수 있으므로 ref 도 즉시 비운다
    messagesRef.current = [];
    setMessages([]);
    if (!convId) return;
    let alive = true;
    api.conversation(convId).then(
      (c) => {
        if (!alive) return;
        setAgentId(c.agent_id || "auto");
        setSkillIds(c.skill_ids ?? (c.skill_id ? [c.skill_id] : []));
        setMessages(c.messages.map((m, i) => ({ id: `${c.id}-${i}`, role: m.role, content: m.content, at: m.at, tools: m.tools, route: m.route, attachments: m.attachments, suggestions: m.suggestions })));
      },
      () => alive && setLoadErr("대화를 불러오지 못했습니다"),
    );
    return () => { alive = false; };
  }, [convId]);

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, busy]);  // busy — 응답이 끝나고 추천 칩이 나타날 때도 내려간다

  const patchLast = (fn: (m: Message) => Message) =>
    setMessages((prev) => prev.map((m, i) => (i === prev.length - 1 ? fn(m) : m)));

  const send = useCallback(async (text: string, agent = agentId, skills = skillIds, tools = toolSel, attachments: Attachment[] = []) => {
    const now = new Date().toISOString();
    const startedAt = Date.now();
    const history: Message[] = [...messagesRef.current, { id: localId(), role: "user", content: text, at: now, attachments }];
    setMessages([...history, { id: localId(), role: "assistant", content: "", at: now, streaming: true, tools: [], startedAt }]);
    setBusy(true);
    const ctrl = new AbortController();
    abort.current = ctrl;
    let created = false;

    pushRecentSkills(skills);
    try {
      await streamChat(
        {
          messages: history.map((m) => ({ role: m.role, content: m.content, attachments: m.attachments?.map((a) => a.id) })),
          conversation_id: idRef.current,
          agent_id: agent,
          skill_ids: skills,
          tool_selection: tools.length ? { tools } : null,
        },
        {
          onMeta: (id) => {
            if (!idRef.current) {
              idRef.current = id;
              ownId.current = id;
              created = true;
              navigate(`/c/${id}`, true);
            }
          },
          onUser: (userCtx: UserCtx) => patchLast((m) => ({ ...m, userCtx })),
          onRoute: (route: RouteInfo) => patchLast((m) => ({ ...m, route })),
          onDelta: (t) => patchLast((m) => ({ ...m, content: m.content + t })),
          onToolStart: (run: ToolRun) => patchLast((m) => ({ ...m, tools: [...(m.tools ?? []), run] })),
          onToolEnd: (id, ms, ok) =>
            patchLast((m) => ({ ...m, toolMark: m.content.length, tools: m.tools?.map((r) => (r.id === id ? { ...r, ms, ok } : r)) })),
          onError: (msg) => patchLast((m) => ({ ...m, error: `에이전트 오류: ${msg}` })),
          onSuggestions: (items) => patchLast((m) => ({ ...m, suggestions: items })),
        },
        ctrl.signal,
      );
    } catch (e: any) {
      if (e?.name !== "AbortError") {
        patchLast((m) => ({ ...m, error: "응답을 받지 못했습니다. 백엔드 서버를 확인해주세요." }));
      }
    } finally {
      patchLast((m) => ({ ...m, streaming: false, elapsed: Date.now() - startedAt }));
      setBusy(false);
      if (abort.current === ctrl) abort.current = null;
      refreshConversations().catch(() => {});
      if (created) ownId.current = idRef.current;
    }
  }, [agentId, skillIds, toolSel, navigate, refreshConversations]);

  // 홈 / 스킬 화면에서 넘어온 질문 바로 실행
  useEffect(() => {
    if (convId) return;
    const p = takePending();
    if (!p) return;
    setAgentId(p.agentId);
    const pendingSkills = p.skillId ? [p.skillId] : [];
    setSkillIds(pendingSkills);
    setToolSel(p.tools ?? []);
    send(p.text, p.agentId, pendingSkills, p.tools ?? [], p.attachments ?? []);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pendingTick, convId]);

  const stop = useCallback(() => abort.current?.abort(), []);

  // agent 를 바꾸면 그 agent 범위 밖 tool 은 선택에서 뺀다 (자동이면 그대로)
  const changeAgent = useCallback((id: string) => {
    setAgentId(id);
    const pool = id === "auto" ? null : meta?.agents.find((a) => a.id === id)?.tools;
    if (pool) setToolSel((sel) => sel.filter((t) => pool.includes(t)));
  }, [meta]);

  const lastRoute = useMemo(
    () => [...messages].reverse().find((m) => m.role === "assistant" && m.route)?.route ?? null,
    [messages],
  );
  const onSend = useCallback((t: string, a?: Attachment[]) => send(t, undefined, undefined, undefined, a), [send]);

  const title = useMemo(() => {
    if (!convId) return "새 대화";
    return conversations.find((c) => c.id === convId)?.title
      ?? messages.find((m) => m.role === "user")?.content.slice(0, 40)
      ?? "대화";
  }, [convId, conversations, messages]);

  const lastAI = [...messages].reverse().find((m) => m.role === "assistant" && !m.streaming);
  // LLM 추천이 있으면 그것을, 없으면(꺼짐 · 실패 · 옛 대화) 카드 태그 기반 고정 추천
  const followUps = !busy && lastAI && !lastAI.error
    ? (lastAI.suggestions?.length ? lastAI.suggestions : getFollowUpSuggestions(lastAI.content)).slice(0, 3)
    : [];

  // 마지막 질문을 매일 아침 실행하는 이벤터로 등록 (비활성 상태로 만들고 이벤터 화면에서 확인)
  const scheduleDaily = useCallback(async () => {
    const q = [...messagesRef.current].reverse().find((m) => m.role === "user");
    if (!q) return;
    await api.createEvent({
      name: q.content.slice(0, 30),
      schedule: { kind: "daily", time: "07:30", weekday: null },
      prompt: q.content, skill_id: skillIds.length === 1 ? skillIds[0] : null, agent_id: agentId, target: "", enabled: false,
    });
    await refreshEvents();
    toast(`이벤터에 등록했습니다 · 매일 07:30 (꺼짐 상태)`);
    navigate("/events");
  }, [agentId, skillIds, navigate, refreshEvents, toast]);

  const copyLink = () => {
    navigator.clipboard?.writeText(window.location.href).then(() => toast("대화 링크를 복사했습니다"), () => {});
  };

  return (
      <section className="center">
        <header className="c-head">
          <b>{title}</b>
          {convId && (
            <span className="agent-badge" title={lastRoute?.route_reason}>
              <i />{agentId === "auto" && lastRoute ? `자동 → ${lastRoute.agent_name}` : agentName(agentId)}
            </span>
          )}
          {convId && (
            <div className="right">
              <button className="ib" title="링크 복사" onClick={copyLink}><Share2 size={15} /></button>
              <button className="ib" title="이벤터로 등록" onClick={scheduleDaily} disabled={busy}>
                <CalendarClock size={15} />
              </button>
            </div>
          )}
        </header>

        <QuickBar
          agentId={agentId}
          skillIds={skillIds}
          selectedTools={toolSel}
          area={area}
          onAgentChange={changeAgent}
          onSkillIdsChange={setSkillIds}
          onToolsChange={setToolSel}
          onAreaChange={setArea}
        />

        <div className="scroll">
          <div className="inner">
            {loadErr && <div className="err-msg">{loadErr}</div>}
            {!convId && messages.length === 0 && (
              <div className="empty">
                <h1>무엇을 확인할까요?</h1>
                <p>그냥 질문하면 필요한 tool 을 알아서 골라 조회합니다. 위에서 영역을 고르거나 스킬을 켜 두면 그 업무 방식대로 답합니다.</p>
                <div className="starters">
                  {STARTERS.map((s) => (
                    <button key={s.q} className="starter" onClick={() => { setAgentId(s.agent); send(s.q, s.agent, skillIds); }}>
                      <div className="k">{s.k}</div>
                      <b>{s.q}</b>
                      <small>{s.d}</small>
                    </button>
                  ))}
                </div>
              </div>
            )}
            {messages.map((m) => <MessageBubble key={m.id} message={m} />)}
            {followUps.length > 0 && (
              <div className="follow">
                <span className="follow-k"><Sparkles size={12} />추천</span>
                {followUps.map((q) => <button key={q} className="chip" onClick={() => send(q)} title="누르면 바로 질문합니다">{q}</button>)}
              </div>
            )}
            <div ref={bottom} />
          </div>
        </div>

        <Composer
          onSend={onSend}
          onStop={stop}
          busy={busy}
          agentId={agentId}
          skillId={null}
          onAgentChange={changeAgent}
          onSkillChange={(id) => id && setSkillIds((ids) => (ids.includes(id) ? ids : [...ids, id]))}
          selectedTools={toolSel}
          onToolsChange={setToolSel}
          showOptions={false}
          placeholder={messages.length ? "이어서 질문하세요…" : undefined}
          autoFocus
        />
      </section>

  );
}
