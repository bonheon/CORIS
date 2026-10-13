import React, { useState } from "react";
import { Pencil, Play, Plus, X } from "lucide-react";
import { api, EventInput, HubEvent } from "../api";
import { useHub } from "../hub";
import { fmtShort, WEEKDAYS } from "../lib/hooks";

const EMPTY: EventInput = {
  name: "", schedule: { kind: "daily", time: "07:30", weekday: null },
  prompt: "", skill_id: null, agent_id: "auto", target: "", enabled: true,
};

const scheduleLabel = (e: Pick<HubEvent, "schedule">) =>
  e.schedule.kind === "daily" ? "매일" : `매주 ${WEEKDAYS[e.schedule.weekday ?? 0]}`;

export default function EventsPage({ navigate }: { navigate: (p: string) => void }) {
  const { events, skills, conversations, refreshEvents, refreshConversations, agentName, toast } = useHub();
  const [running, setRunning] = useState<Set<string>>(new Set());
  const [editing, setEditing] = useState<{ id: string | null; form: EventInput } | null>(null);

  const history = conversations.filter((c) => c.source === "event").slice(0, 12);
  const failed = events.filter((e) => e.last_run?.status === "error");

  const toggle = async (e: HubEvent) => {
    await api.toggleEvent(e.id, !e.enabled);
    await refreshEvents();
  };

  const run = async (e: HubEvent) => {
    setRunning((s) => new Set(s).add(e.id));
    try {
      const res = await api.runEvent(e.id);
      toast(res.last_run?.status === "ok" ? `'${e.name}' 실행 완료` : `'${e.name}' 실행 실패`);
    } catch {
      toast("실행 요청에 실패했습니다");
    } finally {
      setRunning((s) => { const n = new Set(s); n.delete(e.id); return n; });
      await Promise.all([refreshEvents(), refreshConversations()]);
    }
  };

  const openEdit = (e?: HubEvent) =>
    setEditing(e
      ? { id: e.id, form: { name: e.name, schedule: e.schedule, prompt: e.prompt, skill_id: e.skill_id, agent_id: e.agent_id, target: e.target, enabled: e.enabled } }
      : { id: null, form: EMPTY });

  return (
    <section className="center">
      <header className="c-head"><b>이벤터</b></header>
      <div className="scroll">
        <div className="inner wide">
          <div className="page-head">
            <div>
              <h1>이벤터</h1>
              <p>질문이나 스킬을 정해진 시간에 실행합니다. 결과는 대화 목록에 "자동"으로 남습니다.</p>
            </div>
            <button className="btn primary" onClick={() => openEdit()}><Plus size={15} />스케줄 추가</button>
          </div>

          {failed.length > 0 && (
            <div className="note err" style={{ marginBottom: 14 }}>
              최근 실행이 실패한 이벤트가 {failed.length}건 있습니다: {failed.map((e) => e.name).join(", ")}
            </div>
          )}

          <div className="dash">
            <div className="panel" style={{ overflowX: "auto" }}>
              <table className="tbl">
                <thead>
                  <tr><th style={{ width: 90 }}>일정</th><th>작업</th><th style={{ width: 130 }}>최근 실행</th><th style={{ width: 150 }} /></tr>
                </thead>
                <tbody>
                  {events.map((e) => {
                    const skill = skills.find((s) => s.id === e.skill_id);
                    const busy = running.has(e.id);
                    return (
                      <tr key={e.id} className={e.enabled ? "" : "off"}>
                        <td className="when-cell num">{e.schedule.time}<small>{scheduleLabel(e)}</small></td>
                        <td>
                          <div className="q-title">
                            {e.name}
                            {skill && <span className="pill gr">스킬 · {skill.name}</span>}
                          </div>
                          <div className="q-sub">
                            {e.prompt ? `"${e.prompt}"` : "스킬 지침대로 실행"} · {agentName(e.agent_id)}
                            {e.target && ` → ${e.target}`}
                          </div>
                        </td>
                        <td>
                          {busy ? <span className="pill mute"><span className="spin" />실행 중</span>
                            : e.last_run ? (
                              <button
                                className={`pill ${e.last_run.status === "ok" ? "ok" : "err"}`}
                                style={{ border: 0, cursor: e.last_run.conversation_id ? "pointer" : "default" }}
                                title={e.last_run.summary}
                                onClick={() => e.last_run?.conversation_id && navigate(`/c/${e.last_run.conversation_id}`)}
                              >
                                {e.last_run.status === "ok" ? "완료" : "실패"} {fmtShort(e.last_run.at)}
                              </button>
                            ) : <span className="pill mute">{e.next_run ? `다음 ${fmtShort(e.next_run)}` : "중지됨"}</span>}
                        </td>
                        <td>
                          <div style={{ display: "flex", gap: 6, alignItems: "center", justifyContent: "flex-end" }}>
                            <button className="ib" title="수정" onClick={() => openEdit(e)}><Pencil size={14} /></button>
                            <button className="btn sm" onClick={() => run(e)} disabled={busy}><Play size={13} />실행</button>
                            <button className={`toggle ${e.enabled ? "on" : ""}`} onClick={() => toggle(e)} aria-label={e.enabled ? "끄기" : "켜기"} />
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                  {!events.length && <tr><td colSpan={4} className="muted" style={{ textAlign: "center", padding: 28 }}>등록된 스케줄이 없습니다</td></tr>}
                </tbody>
              </table>
            </div>

            <div>
              <div className="panel">
                <div className="panel-h"><b>실행 기록</b></div>
                <div className="timeline">
                  {!history.length && <div className="muted" style={{ fontSize: 12.5, padding: "8px 0" }}>아직 실행 기록이 없습니다. "실행"을 눌러 바로 돌려볼 수 있습니다.</div>}
                  {history.map((c) => (
                    <div key={c.id} className="tl">
                      <time className="num">{fmtShort(c.updated_at)}</time>
                      <div className="rd"><i /></div>
                      <div>
                        <button onClick={() => navigate(`/c/${c.id}`)}><b>{c.title}</b></button>
                        <small>{c.summary}</small>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
              <div className="note" style={{ fontSize: 12 }}>
                <div>자동 실행은 백엔드를 <code className="mono">HUB_SCHEDULER=1</code> 로 띄웠을 때만 동작합니다. 꺼져 있어도 "실행" 버튼으로 바로 돌릴 수 있습니다.</div>
              </div>
            </div>
          </div>
        </div>
      </div>

      {editing && (
        <EventForm
          initial={editing.form}
          isNew={!editing.id}
          onClose={() => setEditing(null)}
          onDelete={editing.id ? async () => {
            if (!window.confirm("이 스케줄을 삭제할까요?")) return;
            await api.deleteEvent(editing.id!);
            await refreshEvents();
            setEditing(null);
            toast("스케줄을 삭제했습니다");
          } : undefined}
          onSave={async (form) => {
            if (editing.id) await api.updateEvent(editing.id, form);
            else await api.createEvent(form);
            await refreshEvents();
            setEditing(null);
            toast("스케줄을 저장했습니다");
          }}
        />
      )}
    </section>
  );
}

function EventForm({ initial, isNew, onClose, onSave, onDelete }: {
  initial: EventInput; isNew: boolean; onClose: () => void;
  onSave: (f: EventInput) => Promise<void>; onDelete?: () => Promise<void>;
}) {
  const { meta, skills } = useHub();
  const [f, setF] = useState<EventInput>(initial);
  const [err, setErr] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const set = (patch: Partial<EventInput>) => setF((x) => ({ ...x, ...patch }));

  const submit = async () => {
    if (!f.name.trim()) return setErr("이름을 입력하세요");
    if (!f.prompt.trim() && !f.skill_id) return setErr("질문을 입력하거나 스킬을 선택하세요");
    setSaving(true);
    try { await onSave(f); } catch (e: any) { setErr(e.message); setSaving(false); }
  };

  return (
    <div className="modal-bg" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal">
        <div className="modal-h">
          <b>{isNew ? "스케줄 추가" : "스케줄 수정"}</b>
          <button className="ib" style={{ marginLeft: "auto" }} onClick={onClose} aria-label="닫기"><X size={15} /></button>
        </div>
        <div className="form">
          <div className="field">
            <label>이름</label>
            <input className="input" value={f.name} maxLength={60} onChange={(e) => set({ name: e.target.value })} placeholder="예) 전일 이슈 리포트" />
          </div>
          <div className="field grid3">
            <div>
              <label className="label">반복</label>
              <select className="select" value={f.schedule.kind}
                onChange={(e) => set({ schedule: { ...f.schedule, kind: e.target.value as "daily" | "weekly", weekday: e.target.value === "weekly" ? f.schedule.weekday ?? 0 : null } })}>
                <option value="daily">매일</option>
                <option value="weekly">매주</option>
              </select>
            </div>
            <div>
              <label className="label">요일</label>
              <select className="select" disabled={f.schedule.kind === "daily"} value={f.schedule.weekday ?? 0}
                onChange={(e) => set({ schedule: { ...f.schedule, weekday: Number(e.target.value) } })}>
                {WEEKDAYS.map((d, i) => <option key={d} value={i}>{d}요일</option>)}
              </select>
            </div>
            <div>
              <label className="label">시각</label>
              <input className="input" type="time" value={f.schedule.time} onChange={(e) => set({ schedule: { ...f.schedule, time: e.target.value } })} />
            </div>
          </div>
          <div className="field grid2">
            <div>
              <label className="label">에이전트</label>
              <select className="select" value={f.agent_id} onChange={(e) => set({ agent_id: e.target.value })}>
                {meta?.agents.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
              </select>
            </div>
            <div>
              <label className="label">스킬<span>선택</span></label>
              <select className="select" value={f.skill_id ?? ""} onChange={(e) => set({ skill_id: e.target.value || null })}>
                <option value="">사용 안 함</option>
                {skills.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
              </select>
            </div>
          </div>
          <div className="field">
            <label>질문<span>스킬만 쓰면 비워도 됩니다</span></label>
            <textarea className="textarea" style={{ minHeight: 72 }} value={f.prompt} onChange={(e) => set({ prompt: e.target.value })} placeholder="예) 이번 주 공지 정리해줘" />
          </div>
          <div className="field">
            <label>공유 대상<span>표시용 — 채널 연동은 추후</span></label>
            <input className="input" value={f.target} onChange={(e) => set({ target: e.target.value })} placeholder="예) 팀 메일" />
          </div>
          {err && <div className="note err">{err}</div>}
        </div>
        <div className="form-foot">
          {onDelete && <button className="btn danger" onClick={onDelete}>삭제</button>}
          <span className="sp" />
          <button className="btn" onClick={onClose}>취소</button>
          <button className="btn primary" onClick={submit} disabled={saving}>{saving ? "저장 중…" : "저장"}</button>
        </div>
      </div>
    </div>
  );
}
