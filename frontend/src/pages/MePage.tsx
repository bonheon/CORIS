import React, { useCallback, useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { History, PenLine, RotateCcw, Trash2 } from "lucide-react";
import { api, MemoryVersion } from "../api";
import { useHub } from "../hub";

// 내 정보 · 사용자 메모리 — 대화가 끝날 때마다 백엔드가 고쳐 쓰는 markdown 문서.
// 다음 대화의 시스템 프롬프트에 들어가므로, 틀린 내용은 여기서 바로 고치거나 지울 수 있게 한다.

const fmtTime = (iso: string) =>
  new Date(iso).toLocaleString("ko-KR", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit", hour12: false });

const SOURCE = { chat: "대화로 갱신", edit: "직접 수정", restore: "복원" } as Record<string, string>;

export default function MePage() {
  const { me, refreshMe, toast } = useHub();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [history, setHistory] = useState<MemoryVersion[]>([]);
  const [preview, setPreview] = useState<MemoryVersion | null>(null);
  const [busy, setBusy] = useState(false);

  const loadHistory = useCallback(() => api.memoryHistory().then(setHistory, () => setHistory([])), []);
  // 대화 직후 백그라운드 갱신분을 보도록 들어올 때마다 다시 읽는다
  useEffect(() => { refreshMe().catch(() => {}); loadHistory(); }, [refreshMe, loadHistory]);

  if (!me) return <section className="center"><header className="c-head"><b>내 정보</b></header></section>;
  const { user, memory } = me;

  const run = async (fn: () => Promise<unknown>, msg: string) => {
    setBusy(true);
    try {
      await fn();
      await Promise.all([refreshMe(), loadHistory()]);
      toast(msg);
    } catch (e: any) {
      toast(`실패: ${e?.message ?? e}`);
    } finally {
      setBusy(false);
    }
  };

  const startEdit = () => { setDraft(memory?.content ?? me.template); setEditing(true); setPreview(null); };
  const save = () => run(() => api.saveMemory(draft), "메모리를 저장했습니다").then(() => setEditing(false));
  const reset = () => {
    if (window.confirm("메모리를 비울까요? 이전 버전 기록은 남습니다.")) run(api.resetMemory, "메모리를 비웠습니다");
  };
  const open = (v: number) => api.memoryVersion(v).then(setPreview, () => toast("버전을 불러오지 못했습니다"));
  const restore = (v: number) => run(() => api.restoreMemory(v), `v${v} 로 복원했습니다`).then(() => setPreview(null));

  const shown = preview?.content ?? memory?.content;

  return (
    <section className="center">
      <header className="c-head"><b>내 정보</b></header>
      <div className="scroll">
        <div className="inner wide">
          <div className="page-head">
            <div>
              <h1>{user.name}</h1>
              <p>
                <span className="mono">{user.user_id}</span>
                {user.dept && ` · ${user.dept}`}
                {user.email && ` · ${user.email}`}
              </p>
            </div>
          </div>

          <div className="me-grid">
            <div className="me-card">
              <div className="me-card-head">
                <div>
                  <b>{preview ? `메모리 v${preview.version} (이전 버전)` : "사용자 메모리"}</b>
                  <small>
                    {preview
                      ? `${fmtTime(preview.created_at)} · ${SOURCE[preview.source] ?? preview.source}`
                      : memory
                        ? `v${memory.version} · ${fmtTime(memory.updated_at)} · ${SOURCE[memory.source] ?? memory.source} · ${memory.content.length.toLocaleString()}자`
                        : "아직 없음 — 대화를 하면 자동으로 쌓입니다"}
                    {!me.memory_enabled && " · 자동 갱신 꺼짐 (MEMORY_ENABLED=0)"}
                  </small>
                </div>
                <div className="me-actions">
                  {preview ? (
                    <>
                      <button className="ghost" onClick={() => setPreview(null)}>현재 버전 보기</button>
                      <button className="btn" onClick={() => restore(preview.version)} disabled={busy}><RotateCcw size={13} />이 버전으로 복원</button>
                    </>
                  ) : editing ? (
                    <>
                      <button className="ghost" onClick={() => setEditing(false)}>취소</button>
                      <button className="btn" onClick={save} disabled={busy || !draft.trim()}>저장</button>
                    </>
                  ) : (
                    <>
                      <button className="ghost" onClick={startEdit}><PenLine size={12} />직접 수정</button>
                      {memory && <button className="ghost danger" onClick={reset} disabled={busy}><Trash2 size={12} />비우기</button>}
                    </>
                  )}
                </div>
              </div>
              {editing ? (
                <textarea className="textarea mono me-editor" value={draft} onChange={(e) => setDraft(e.target.value)} spellCheck={false} />
              ) : shown ? (
                <div className="md me-md"><ReactMarkdown remarkPlugins={[remarkGfm]}>{shown}</ReactMarkdown></div>
              ) : (
                <div className="muted me-empty">
                  대화를 나누면 담당 업무, 자주 다루는 시스템 · 문서, 선호하는 답변 방식 등이 여기에 정리됩니다.
                  다음 대화부터 이 내용을 참고해 답합니다.
                </div>
              )}
            </div>

            <aside className="me-card">
              <div className="me-card-head"><div><b><History size={13} /> 변경 기록</b><small>최근 {history.length}개</small></div></div>
              {history.length === 0 && <div className="muted" style={{ fontSize: 12.5 }}>기록이 없습니다</div>}
              {history.map((h) => (
                <button key={h.version} className={`me-ver ${preview?.version === h.version ? "on" : ""}`} onClick={() => open(h.version)}>
                  <b className="num">v{h.version}</b>
                  <span>{SOURCE[h.source] ?? h.source}</span>
                  <small>{fmtTime(h.created_at)}{h.chars ? ` · ${h.chars.toLocaleString()}자` : ""}</small>
                </button>
              ))}
            </aside>
          </div>
        </div>
      </div>
    </section>
  );
}
