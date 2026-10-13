import React, { useMemo, useState } from "react";
import { Plus, Search, X } from "lucide-react";
import { api } from "../api";
import { useHub } from "../hub";
import { dayLabel, fmtTime } from "../lib/hooks";

type Filter = "all" | "chat" | "event";

interface Props {
  activeId: string | null;
  navigate: (p: string) => void;
}

export default function ConversationList({ activeId, navigate }: Props) {
  const { conversations, refreshConversations, toast } = useHub();
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
    for (const c of items) {
      const day = dayLabel(c.updated_at);
      if (out.length && out[out.length - 1].day === day) out[out.length - 1].items.push(c);
      else out.push({ day, items: [c] });
    }
    return out;
  }, [conversations, q, filter]);

  const remove = async (e: React.MouseEvent, id: string) => {
    e.stopPropagation();
    await api.deleteConversation(id);
    await refreshConversations();
    toast("대화를 삭제했습니다");
    if (id === activeId) navigate("/new");
  };

  return (
    <div className="list">
      <div className="list-head">
        <b>대화</b>
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
            {{ all: "전체", chat: "내 질문", event: "이벤터" }[f]}
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
            {g.items.map((c) => (
              <div
                key={c.id}
                role="button"
                tabIndex={0}
                className={`cv ${c.id === activeId ? "on" : ""}`}
                onClick={() => navigate(`/c/${c.id}`)}
                onKeyDown={(e) => e.key === "Enter" && navigate(`/c/${c.id}`)}
              >
                <div className="t">
                  <b>{c.title}</b>
                  {c.source === "event" && <span className="auto">자동</span>}
                  <time className="num">{fmtTime(c.updated_at)}</time>
                </div>
                <small>{c.summary || "…"}</small>
                <button className="del" onClick={(e) => remove(e, c.id)} aria-label="대화 삭제">
                  <X size={13} />
                </button>
              </div>
            ))}
          </React.Fragment>
        ))}
      </div>
    </div>
  );
}
