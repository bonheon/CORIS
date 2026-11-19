import React, { KeyboardEvent, useMemo, useState } from "react";
import { PanelRightClose, Pencil, Plus, Search, Star, Trash2, X } from "lucide-react";
import { api, ConvHead } from "../api";
import { useHub } from "../hub";
import { dayLabel, fmtTime } from "../lib/hooks";

type Filter = "all" | "chat" | "event";

interface Props {
  activeId: string | null;
  navigate: (p: string) => void;
  onFold?: () => void;   // 목록 접기
}

export default function ConversationList({ activeId, navigate, onFold }: Props) {
  const { conversations, refreshConversations, toast, isUnread } = useHub();
  const [q, setQ] = useState("");
  const [filter, setFilter] = useState<Filter>("all");

  const groups = useMemo(() => {
    const needle = q.trim().toLowerCase();
    const items = conversations.filter(
      (c) =>
        (filter === "all" || c.source === filter) &&
        (!needle || c.title.toLowerCase().includes(needle) || c.summary.toLowerCase().includes(needle)),
    );
    const out: { day: string; items: typeof items }[] = [];
    const favs = items.filter((c) => c.favorite);
    if (favs.length) out.push({ day: "즐겨찾기", items: favs });
    for (const c of items.filter((x) => !x.favorite)) {
      const day = dayLabel(c.updated_at);
      if (out.length && out[out.length - 1].day === day && day !== "즐겨찾기") out[out.length - 1].items.push(c);
      else out.push({ day, items: [c] });
    }
    return out;
  }, [conversations, q, filter]);

  const [editing, setEditing] = useState<{ id: string; title: string } | null>(null);
  const inFilter = conversations.filter((c) => filter === "all" || c.source === filter);
  const deletable = inFilter.filter((c) => !c.favorite).length;

  const toggleFav = async (e: React.MouseEvent, c: ConvHead) => {
    e.stopPropagation();
    await api.patchConversation(c.id, { favorite: !c.favorite });
    await refreshConversations();
    toast(c.favorite ? "즐겨찾기를 해제했습니다" : "즐겨찾기에 추가했습니다 — 전체 삭제에서 빠집니다");
  };

  const startRename = (e: React.MouseEvent, c: ConvHead) => {
    e.stopPropagation();
    setEditing({ id: c.id, title: c.title });
  };
  const saveRename = async () => {
    if (!editing) return;
    const { id, title } = editing;
    setEditing(null);
    const old = conversations.find((c) => c.id === id);
    if (!title.trim() || title.trim() === old?.title) return;
    await api.patchConversation(id, { title: title.trim() });
    await refreshConversations();
    toast("대화 이름을 바꿨습니다");
  };
  const onRenameKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.nativeEvent.isComposing) return;
    if (e.key === "Enter") saveRename();
    if (e.key === "Escape") setEditing(null);
  };

  const removeAll = async () => {
    const what = filter === "all" ? "" : `'${{ chat: "내 질문", event: "스케줄링" }[filter]}' `;
    const kept = inFilter.length - deletable;
    if (!window.confirm(`${what}대화 ${deletable}개를 모두 삭제할까요?${kept ? ` (즐겨찾기 ${kept}개는 남습니다)` : ""}\n삭제한 대화는 되돌릴 수 없습니다.`)) return;
    const res = await api.deleteAllConversations(filter === "all" ? undefined : filter);
    await refreshConversations();
    toast(`대화 ${res.deleted}개를 삭제했습니다`);
    if (activeId && !conversations.find((c) => c.id === activeId)?.favorite) navigate("/new");
  };

  const remove = async (e: React.MouseEvent, id: string) => {
    e.stopPropagation();
    if (!window.confirm("이 대화를 삭제할까요?")) return;
    await api.deleteConversation(id);
    await refreshConversations();
    toast("대화를 삭제했습니다");
    if (id === activeId) navigate("/new");
  };

  return (
    <div className="list">
      <div className="list-head">
        {onFold && <button className="ib cl-fold" onClick={onFold} title="목록 접기 — 넓게 보기" aria-label="목록 접기"><PanelRightClose size={14} /></button>}
        <b>대화</b>
        <button className="ib cl-clear" onClick={removeAll} disabled={!deletable} title="전체 삭제 (즐겨찾기 제외)" aria-label="전체 삭제">
          <Trash2 size={14} />
        </button>
        <button className="btn-new" onClick={() => navigate("/new")}>
          <Plus size={13} strokeWidth={2.2} />새 대화
        </button>
      </div>
      <label className="search">
        <Search size={14} />
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="대화 검색" />
      </label>
      <div className="filters">
        {(["all", "chat", "event"] as Filter[]).map((f) => (
          <button key={f} className={filter === f ? "on" : ""} onClick={() => setFilter(f)}>
            {{ all: "전체", chat: "내 질문", event: "스케줄링" }[f]}
          </button>
        ))}
      </div>
      <div className="convs">
        {groups.length === 0 && (
          <div className="list-empty">{conversations.length ? "검색 결과가 없습니다" : "아직 대화가 없습니다"}</div>
        )}
        {groups.map((g) => (
          <React.Fragment key={g.day}>
            <div className="day">{g.day}</div>
            {g.items.map((c) => {
              const renaming = editing?.id === c.id;
              return (
                <div
                  key={c.id}
                  role="button"
                  tabIndex={0}
                  className={`cv ${c.id === activeId ? "on" : ""} ${c.favorite ? "fav" : ""}`}
                  onClick={() => !renaming && navigate(`/c/${c.id}`)}
                  onKeyDown={(e) => !renaming && e.key === "Enter" && navigate(`/c/${c.id}`)}
                >
                  <div className="t">
                    {renaming ? (
                      <input className="cv-rename" autoFocus value={editing!.title} maxLength={80}
                        onClick={(e) => e.stopPropagation()} onChange={(e) => setEditing({ id: c.id, title: e.target.value })}
                        onKeyDown={onRenameKey} onBlur={saveRename} />
                    ) : <b title={c.title}>{c.title}</b>}
                    {c.source === "event" && <span className="auto">자동</span>}
                    {c.status === "running"
                      ? <span className="cv-st run"><span className="spin" />답변 중</span>
                      : isUnread(c) && c.id !== activeId && <span className="cv-st done">답변 완료</span>}
                    {c.favorite && !renaming && <Star className="cv-star" size={12} />}
                    <time className="num">{fmtTime(c.updated_at)}</time>
                  </div>
                  <small>{c.summary || "…"}</small>
                  {!renaming && (
                    <div className="cv-acts">
                      <button className={c.favorite ? "on" : ""} onClick={(e) => toggleFav(e, c)} aria-label={c.favorite ? "즐겨찾기 해제" : "즐겨찾기"} title={c.favorite ? "즐겨찾기 해제" : "즐겨찾기"}>
                        <Star size={13} />
                      </button>
                      <button onClick={(e) => startRename(e, c)} aria-label="이름 변경" title="이름 변경"><Pencil size={12} /></button>
                      <button className="del" onClick={(e) => remove(e, c.id)} aria-label="대화 삭제" title="삭제"><X size={13} /></button>
                    </div>
                  )}
                </div>
              );
            })}
          </React.Fragment>
        ))}
      </div>
    </div>
  );
}
