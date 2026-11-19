// 작업 목록 — 작업 큐(task table). 스케줄링에서 넣은 작업이 한 번에 한 건씩, 넣은 순서대로 처리된다.
//   위: 지금 큐 (실행 중 + 대기, 대기는 취소 가능)
//   아래: 작업 기록 (상태 필터 · 결과 대화 열기 · 실패/취소 다시 실행)
import React, { useCallback, useMemo, useState } from "react";
import { ExternalLink, RotateCcw, X } from "lucide-react";
import { api, HubTask, TaskStatus } from "../api";
import { useHub } from "../hub";
import { fmtShort } from "../lib/hooks";
import { queueOf, TaskStatusPill, TRIGGER, useTasks } from "../lib/tasks";

type TaskFilter = "all" | "active" | "done" | "error";
const FILTER_STATUS: Record<TaskFilter, TaskStatus[] | null> = {
  all: null, active: ["queued", "running"], done: ["done"], error: ["error", "canceled"],
};
const FILTER_LABEL: Record<TaskFilter, string> = { all: "전체", active: "대기 · 실행", done: "완료", error: "실패 · 취소" };

export default function TasksPage({ navigate }: { navigate: (p: string) => void }) {
  const { refreshEvents, refreshConversations, agentName, toast } = useHub();
  const [filter, setFilter] = useState<TaskFilter>("all");
  const onFinish = useCallback(() => { refreshEvents(); refreshConversations(); }, [refreshEvents, refreshConversations]);
  const [tasks, reload] = useTasks(onFinish, 300);

  const queue = useMemo(() => queueOf(tasks), [tasks]);
  const count = (f: TaskFilter) => tasks.filter((t) => !FILTER_STATUS[f] || FILTER_STATUS[f]!.includes(t.status)).length;
  const shown = tasks.filter((t) => !FILTER_STATUS[filter] || FILTER_STATUS[filter]!.includes(t.status));

  const cancel = async (t: HubTask) => {
    try { await api.cancelTask(t.id); toast("대기 작업을 취소했습니다"); } catch (err: any) { toast(err.message); }
    await reload();
  };
  const retry = async (t: HubTask) => {
    try { await api.retryTask(t.id); toast(`'${t.event_name}' 다시 실행 — 작업 큐에 넣었습니다`); } catch (err: any) { toast(err.message); }
    await reload();
  };

  return (
    <section className="center">
      <header className="c-head"><b>작업 목록</b></header>
      <div className="scroll">
        <div className="inner wide">
          <div className="page-head">
            <div>
              <h1>작업 목록</h1>
              <p>스케줄링에서 넣은 작업입니다. 작업 큐에서 <b>한 번에 한 건씩, 넣은 순서대로</b> agent 에 넘겨 처리하고 결과를 대화로 남깁니다.</p>
            </div>
            <button className="btn" onClick={() => navigate("/events")}>스케줄링으로</button>
          </div>

          <div className="panel">
            <div className="panel-h"><b>작업 큐</b><small>{queue.length ? `${queue.length}건` : "비어 있음"}</small></div>
            {!queue.length && <div className="muted" style={{ fontSize: 12.5, padding: "12px 16px" }}>대기 중인 작업이 없습니다. 스케줄링에서 "실행"을 누르거나 예약 시각이 되면 큐에 들어옵니다.</div>}
            {queue.map((t) => (
              <div key={t.id} className="tk-row">
                <span className="tk-pos">{t.status === "running" ? <span className="spin" /> : t.position}</span>
                <span className="ell" title={t.prompt}>
                  <b>{t.event_name}</b> <span className="muted">· {TRIGGER[t.trigger]} · {fmtShort(t.created_at)} 넣음{t.started_at ? ` · ${fmtShort(t.started_at)} 시작` : ""}</span>
                </span>
                {t.status === "queued"
                  ? <button className="ib" title="대기 취소" onClick={() => cancel(t)}><X size={14} /></button>
                  : <span className="pill warn">실행 중</span>}
              </div>
            ))}
          </div>

          <div className="panel" style={{ overflowX: "auto" }}>
            <div className="panel-h">
              <b>작업 기록</b><small>최근 {tasks.length}건</small>
              <div className="seg" style={{ marginLeft: "auto" }}>
                {(Object.keys(FILTER_LABEL) as TaskFilter[]).map((f) => (
                  <button key={f} className={filter === f ? "on" : ""} onClick={() => setFilter(f)}>{FILTER_LABEL[f]} {count(f)}</button>
                ))}
              </div>
            </div>
            <table className="tbl">
              <thead>
                <tr><th style={{ width: 96 }}>상태</th><th>작업</th><th style={{ width: 96 }}>넣은 시각</th><th style={{ width: 120 }}>처리</th><th>결과</th><th style={{ width: 80 }} /></tr>
              </thead>
              <tbody>
                {shown.map((t) => (
                  <tr key={t.id}>
                    <td><TaskStatusPill t={t} /></td>
                    <td>
                      <div className="q-title">{t.event_name}</div>
                      <div className="q-sub">{TRIGGER[t.trigger]}{t.attempt > 1 ? ` · ${t.attempt}회차` : ""} · {agentName(t.routed_agent ?? t.agent_id)}</div>
                    </td>
                    <td className="num">{fmtShort(t.created_at)}</td>
                    <td className="num">
                      {t.started_at ? fmtShort(t.started_at) : "—"}
                      {t.elapsed_s != null && <small className="muted" style={{ display: "block" }}>{t.elapsed_s}초 · tool {t.tool_count}</small>}
                    </td>
                    <td className="tk-sum" title={t.error ?? t.summary}>{t.error ?? (t.summary || "—")}</td>
                    <td>
                      <div style={{ display: "flex", gap: 4, justifyContent: "flex-end" }}>
                        {t.conversation_id && <button className="ib" title="결과 대화 열기" onClick={() => navigate(`/c/${t.conversation_id}`)}><ExternalLink size={14} /></button>}
                        {(t.status === "error" || t.status === "canceled") && <button className="ib" title="다시 실행" onClick={() => retry(t)}><RotateCcw size={14} /></button>}
                        {t.status === "queued" && <button className="ib" title="대기 취소" onClick={() => cancel(t)}><X size={14} /></button>}
                      </div>
                    </td>
                  </tr>
                ))}
                {!shown.length && <tr><td colSpan={6} className="muted" style={{ textAlign: "center", padding: 24 }}>작업 기록이 없습니다</td></tr>}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </section>
  );
}
