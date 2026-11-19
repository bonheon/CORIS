import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { CalendarClock, Share2, Sparkles } from "lucide-react";
import { api, Attachment, cancelChat, ChatHandlers, resumeChat, RouteInfo, streamChat, ToolRun, UserCtx } from "../api";
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
  const { meta, refreshConversations, refreshEvents, takePending, pendingTick, agentName, toast, conversations, markSeen } = useHub();
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
  // 지금 화면에 붙어 있는 답변 스트림 — 다른 대화로 옮기면 null. 옮긴 뒤 도착하는 이전 답변의 이벤트가
  // 새 대화 화면을 고치지 않게 막는다 (답변 자체는 서버에서 계속된다 — hub/runs.py)
  const runTok = useRef<object | null>(null);
  const bottom = useRef<HTMLDivElement>(null);
  const messagesRef = useRef(messages);
  messagesRef.current = messages;
  const convsRef = useRef(conversations);
  convsRef.current = conversations;

  const patchLast = (fn: (m: Message) => Message) =>
    setMessages((prev) => prev.map((m, i) => (i === prev.length - 1 ? fn(m) : m)));

  /** 스트림 이벤트 → 화면. tok 이 지금 붙어 있는 스트림일 때만 반영 */
  const handlersFor = (tok: object, onMeta?: (id: string) => void): ChatHandlers => {
    const patch = (fn: (m: Message) => Message) => { if (runTok.current === tok) patchLast(fn); };
    return {
      onMeta: (id) => { if (runTok.current === tok) onMeta?.(id); },
      onUser: (userCtx: UserCtx) => patch((m) => ({ ...m, userCtx })),
      onRoute: (route: RouteInfo) => patch((m) => ({ ...m, route })),
      onDelta: (t) => patch((m) => ({ ...m, content: m.content + t })),
      onToolStart: (run: ToolRun) => patch((m) => ({ ...m, tools: [...(m.tools ?? []), run] })),
      onToolEnd: (id, ms, ok) =>
        patch((m) => ({ ...m, toolMark: m.content.length, tools: m.tools?.map((r) => (r.id === id ? { ...r, ms, ok } : r)) })),
      onError: (msg) => patch((m) => ({ ...m, error: `에이전트 오류: ${msg}` })),
      onSuggestions: (items) => patch((m) => ({ ...m, suggestions: items })),
      onStopped: () => patch((m) => ({ ...m, content: m.content || "(중지됨)" })),
    };
  };

  /** 스트림이 끝났을 때 — 아직 이 화면에 붙어 있으면 마무리하고 '본 것' 으로 기록 */
  const finishRun = (tok: object, startedAt: number) => {
    if (runTok.current !== tok) return;
    runTok.current = null;
    patchLast((m) => ({ ...m, streaming: false, elapsed: Date.now() - startedAt }));
    setBusy(false);
    if (idRef.current) markSeen(idRef.current);
  };

  /** 진행 중인 답변에 다시 연결 (다른 대화에 갔다가 돌아왔을 때) — 진행 중인 답변이 없으면 false */
  const attach = useCallback(async (id: string): Promise<boolean> => {
    const tok = {};
    runTok.current = tok;
    const ctrl = new AbortController();
    abort.current = ctrl;
    let startedAt = Date.now();
    let ok = false;
    try {
      ok = await resumeChat(id, {
        ...handlersFor(tok),
        onResume: (info) => {
          if (runTok.current !== tok) return;
          const last = [...messagesRef.current].reverse().find((m) => m.role === "user");
          if (info.done && last?.content === info.user_text) {   // 그새 끝나 이미 불러온 대화에 들어 있다
            runTok.current = null;
            ctrl.abort();
            return;
          }
          startedAt = new Date(info.started_at).getTime() || Date.now();
          setBusy(true);
          setMessages((prev) => [...prev,
            { id: localId(), role: "user", content: info.user_text, at: info.started_at, attachments: info.attachments },
            { id: localId(), role: "assistant", content: "", at: info.started_at, streaming: true, tools: [], startedAt }]);
        },
      }, ctrl.signal);
    } catch (e: any) {
      if (e?.name !== "AbortError") handlersFor(tok).onError("다시 연결하지 못했습니다");
    } finally {
      if (abort.current === ctrl) abort.current = null;
      finishRun(tok, startedAt);
      refreshConversations().catch(() => {});
    }
    return ok;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshConversations, markSeen]);

  // ── 라우트 변경: 대화 불러오기 / 초기화 ──
  useEffect(() => {
    if (convId && convId === ownId.current) return;
    runTok.current = null;          // 이전 대화의 스트림은 화면에서만 떼어 낸다 (서버 답변은 계속)
    abort.current?.abort();
    setBusy(false);
    idRef.current = convId;
    ownId.current = null;
    setLoadErr(null);
    // 같은 커밋에서 바로 send() 가 불릴 수 있으므로 ref 도 즉시 비운다
    messagesRef.current = [];
    setMessages([]);
    if (!convId) return;
    let alive = true;
    const running = convsRef.current.find((c) => c.id === convId)?.status === "running";
    api.conversation(convId).then(
      (c) => {
        if (!alive) return;
        setAgentId(c.agent_id || "auto");
        setSkillIds(c.skill_ids ?? (c.skill_id ? [c.skill_id] : []));
        const loaded: Message[] = c.messages.map((m, i) => ({ id: `${c.id}-${i}`, role: m.role, content: m.content, at: m.at, tools: m.tools, route: m.route, attachments: m.attachments, suggestions: m.suggestions }));
        messagesRef.current = loaded;
        setMessages(loaded);
        if (running) attach(convId);
        else markSeen(convId);
      },
      // 저장 전인 새 대화(첫 답변 중)는 아직 없다 — 진행 중인 답변에 붙어 본다
      () => { if (alive) attach(convId).then((ok) => { if (alive && !ok) setLoadErr("대화를 불러오지 못했습니다"); }); },
    );
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [convId]);

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, busy]);  // busy — 응답이 끝나고 추천 칩이 나타날 때도 내려간다

  const send = useCallback(async (text: string, agent = agentId, skills = skillIds, tools = toolSel, attachments: Attachment[] = []) => {
    const now = new Date().toISOString();
    const startedAt = Date.now();
    const history: Message[] = [...messagesRef.current, { id: localId(), role: "user", content: text, at: now, attachments }];
    setMessages([...history, { id: localId(), role: "assistant", content: "", at: now, streaming: true, tools: [], startedAt }]);
    setBusy(true);
    const tok = {};
    runTok.current = tok;
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
        handlersFor(tok, (id) => {
          if (!idRef.current) {
            idRef.current = id;
            ownId.current = id;
            created = true;
            navigate(`/c/${id}`, true);
          }
          refreshConversations().catch(() => {});   // 목록에 '답변 중' 으로 바로 보이게
        }),
        ctrl.signal,
      );
    } catch (e: any) {
      if (e?.name !== "AbortError" && runTok.current === tok) {
        patchLast((m) => ({ ...m, error: e?.message?.includes("답변 중") ? e.message : "응답을 받지 못했습니다. 백엔드 서버를 확인해주세요." }));
      }
    } finally {
      if (abort.current === ctrl) abort.current = null;
      finishRun(tok, startedAt);
      refreshConversations().catch(() => {});
      if (created) ownId.current = idRef.current;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [agentId, skillIds, toolSel, navigate, refreshConversations, markSeen]);

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

  // 중지 — 서버의 답변 작업을 취소한다 (그때까지의 답변은 저장되고 'stopped' 이벤트로 스트림이 끝난다).
  // 대화 id 가 아직 없으면(첫 이벤트 전) 연결만 끊는다
  const stop = useCallback(() => {
    if (idRef.current) cancelChat(idRef.current).catch(() => abort.current?.abort());
    else abort.current?.abort();
  }, []);

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

  // 마지막 질문을 매일 아침 실행하는 스케줄로 등록 (비활성 상태로 만들고 스케줄링 화면에서 확인)
  const scheduleDaily = useCallback(async () => {
    const q = [...messagesRef.current].reverse().find((m) => m.role === "user");
    if (!q) return;
    await api.createEvent({
      name: q.content.slice(0, 30),
      schedule: { kind: "daily", time: "07:30", weekday: null },
      prompt: q.content, skill_id: skillIds.length === 1 ? skillIds[0] : null, agent_id: agentId, target: "", enabled: false,
    });
    await refreshEvents();
    toast(`스케줄링에 등록했습니다 · 매일 07:30 (꺼짐 상태)`);
    navigate("/events");
  }, [agentId, skillIds, navigate, refreshEvents, toast]);

  const copyLink = () => {
    navigator.clipboard?.writeText(window.location.href).then(() => toast("대화 링크를 복사했습니다"), () => {});
  };

  return (
      <section className="center chat-page">
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
              <button className="ib" title="스케줄로 등록" onClick={scheduleDaily} disabled={busy}>
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
          <div className="inner chat">
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
