// MCP 서버의 tool 을 그룹으로 묶어 가져오기 — tool 이 많은 서버용.
//   왼쪽: 서버의 tool 목록 (검색 · 미지정만 보기 · 여러 개 선택)
//   아래: 선택한 tool 을 [기존 그룹에 넣기] / [새 그룹 만들기] / [가져오지 않기]
//   오른쪽: 그룹 — 이름 · 영역 태그 · 설명 편집, × 로 tool 빼기
// 그룹(기본 그룹 포함)에 들어간 tool 만 Coris 로 가져온다. 기본 그룹 = 서버 이름으로 보이는 묶음.
import React, { useMemo, useState } from "react";
import { FolderPlus, Search, Trash2, X } from "lucide-react";
import type { McpToolSpec } from "../api";

export interface GroupDraft { id: string; name: string; description: string; tags: string }

interface Props {
  specs: McpToolSpec[];
  tools: string[];                       // 가져올 tool (그룹에 들어간 것)
  toolGroup: Record<string, string>;     // tool → 그룹 id ("" 또는 없음 = 기본 그룹)
  groups: GroupDraft[];
  serverName: string;
  labels: Record<string, string>;
  onChange: (p: { tools?: string[]; toolGroup?: Record<string, string>; groups?: GroupDraft[] }) => void;
}

const DEFAULT = "";
const firstLine = (s: string) => s.split("\n").find((l) => l.trim())?.trim() ?? "";
const newId = () => `g${Date.now().toString(36).slice(-6)}`;

export default function McpToolGrouper({ specs, tools, toolGroup, groups, serverName, labels, onChange }: Props) {
  const [sel, setSel] = useState<Set<string>>(new Set());
  const [q, setQ] = useState("");
  const [onlyFree, setOnlyFree] = useState(false);
  const [target, setTarget] = useState<string>(groups[0]?.id ?? DEFAULT);
  const [newName, setNewName] = useState("");

  const imported = useMemo(() => new Set(tools), [tools]);
  const groupOf = (n: string) => (imported.has(n) ? toolGroup[n] ?? DEFAULT : null);
  const groupName = (gid: string) => (gid === DEFAULT ? `기본 (${serverName || "서버 이름"})` : groups.find((g) => g.id === gid)?.name || "이름 없는 그룹");

  const query = q.trim().toLowerCase();
  const visible = specs.filter((t) =>
    (!query || t.name.toLowerCase().includes(query) || t.description.toLowerCase().includes(query))
    && (!onlyFree || !imported.has(t.name)));
  const pickable = visible.filter((t) => !t.ui);
  const allOn = pickable.length > 0 && pickable.every((t) => sel.has(t.name));
  const free = specs.filter((t) => !t.ui && !imported.has(t.name)).length;

  const toggle = (n: string) => setSel((s) => { const x = new Set(s); x.has(n) ? x.delete(n) : x.add(n); return x; });
  const toggleAll = () => setSel((s) => {
    const x = new Set(s);
    pickable.forEach((t) => (allOn ? x.delete(t.name) : x.add(t.name)));
    return x;
  });

  // 선택한 tool 을 그룹에 넣는다 (가져오기 대상에도 추가)
  const assign = (names: string[], gid: string, extraGroups?: GroupDraft[]) => {
    const order = specs.map((t) => t.name);
    const nextTools = order.filter((n) => imported.has(n) || names.includes(n));
    const nextMap = { ...toolGroup };
    names.forEach((n) => { if (gid === DEFAULT) delete nextMap[n]; else nextMap[n] = gid; });
    onChange({ tools: nextTools, toolGroup: nextMap, ...(extraGroups ? { groups: extraGroups } : {}) });
    setSel(new Set());
  };
  const exclude = (names: string[]) => {
    const nextMap = { ...toolGroup };
    names.forEach((n) => delete nextMap[n]);
    onChange({ tools: tools.filter((n) => !names.includes(n)), toolGroup: nextMap });
    setSel(new Set());
  };
  const createGroup = () => {
    const name = newName.trim();
    if (!name) return;
    const g = { id: newId(), name, description: "", tags: "" };
    assign(Array.from(sel), g.id, [...groups, g]);
    setTarget(g.id);
    setNewName("");
  };
  const patchGroup = (gid: string, p: Partial<GroupDraft>) =>
    onChange({ groups: groups.map((g) => (g.id === gid ? { ...g, ...p } : g)) });
  const removeGroup = (gid: string) => onChange({   // 들어 있던 tool 은 기본 그룹으로
    groups: groups.filter((g) => g.id !== gid),
    toolGroup: Object.fromEntries(Object.entries(toolGroup).filter(([, v]) => v !== gid)),
  });

  const members = (gid: string) => tools.filter((n) => (toolGroup[n] ?? DEFAULT) === gid);
  const picked = Array.from(sel);

  return (
    <div className="tg">
      <div className="tg-bar">
        <label className="tg-search"><Search size={13} />
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="tool 이름 · 설명 검색" />
        </label>
        <label className="mcp-chk tg-free">
          <input type="checkbox" checked={onlyFree} onChange={(e) => setOnlyFree(e.target.checked)} />미지정만<span>{free}개</span>
        </label>
      </div>

      <div className="tg-body">
        {/* 서버의 tool 목록 */}
        <div className="tg-list">
          <label className="tg-row tg-head">
            <input type="checkbox" checked={allOn} onChange={toggleAll} disabled={!pickable.length} />
            <span>보이는 tool 전체 선택 ({pickable.length})</span>
          </label>
          {visible.map((t) => {
            const gid = groupOf(t.name);
            return (
              <label key={t.name} className={`tg-row ${sel.has(t.name) ? "sel" : ""} ${t.ui ? "off" : ""}`} title={t.description}>
                <input type="checkbox" checked={sel.has(t.name)} disabled={t.ui} onChange={() => toggle(t.name)} />
                <span className="tg-main">
                  <b>{labels[t.name] || t.name}</b>
                  <small>{firstLine(t.description) || "설명 없음"}</small>
                </span>
                {t.ui ? <span className="tag">화면 전용</span>
                  : gid === null ? <span className="tag">미지정</span>
                  : <span className="tag ok">{groupName(gid)}</span>}
              </label>
            );
          })}
          {!visible.length && <div className="tg-empty">조건에 맞는 tool 이 없습니다</div>}
        </div>

        {/* 그룹 */}
        <div className="tg-groups">
          {[...groups.map((g) => g.id), DEFAULT].map((gid) => {
            const g = groups.find((x) => x.id === gid);
            const list = members(gid);
            if (gid === DEFAULT && !list.length && groups.length) return null;
            return (
              <div key={gid || "default"} className="tg-group">
                {g ? (
                  <div className="tg-gh">
                    <input className="input" value={g.name} maxLength={40} placeholder="그룹 이름" onChange={(e) => patchGroup(g.id, { name: e.target.value })} />
                    <span className="tg-n">{list.length}개</span>
                    <button className="ghost" title="그룹 삭제 — tool 은 기본 그룹으로" onClick={() => removeGroup(g.id)}><Trash2 size={12} /></button>
                  </div>
                ) : (
                  <div className="tg-gh"><b>기본 ({serverName || "서버 이름"})</b><span className="tg-n">{list.length}개</span></div>
                )}
                {g && (
                  <div className="tg-gmeta">
                    <input className="input" value={g.tags} placeholder="영역 태그 (예: 품질, 생산)" onChange={(e) => patchGroup(g.id, { tags: e.target.value })} />
                    <input className="input" value={g.description} placeholder="설명" onChange={(e) => patchGroup(g.id, { description: e.target.value })} />
                  </div>
                )}
                <div className="tg-chips">
                  {list.map((n) => (
                    <span key={n} className="tg-chip">{labels[n] || n}
                      <button onClick={() => exclude([n])} aria-label={`${n} 빼기`} title="가져오지 않기"><X size={10} /></button>
                    </span>
                  ))}
                  {!list.length && <small className="muted">비어 있음 — 왼쪽에서 tool 을 골라 넣으세요</small>}
                </div>
              </div>
            );
          })}
          {!groups.length && !tools.length && <div className="tg-empty">왼쪽에서 tool 을 고른 뒤 아래에서 새 그룹을 만드세요</div>}
        </div>
      </div>

      {/* 선택한 tool 일괄 처리 */}
      <div className={`tg-act ${picked.length ? "on" : ""}`}>
        <b>선택 {picked.length}개</b>
        <span className="tg-sep">→</span>
        <select className="select" value={target} onChange={(e) => setTarget(e.target.value)} disabled={!picked.length}>
          {groups.map((g) => <option key={g.id} value={g.id}>{g.name || "이름 없는 그룹"}</option>)}
          <option value={DEFAULT}>기본 ({serverName || "서버 이름"})</option>
        </select>
        <button className="btn sm" disabled={!picked.length} onClick={() => assign(picked, target)}>넣기</button>
        <span className="tg-sep">또는</span>
        <input className="input" value={newName} onChange={(e) => setNewName(e.target.value)} placeholder="새 그룹 이름" maxLength={40}
          onKeyDown={(e) => { if (e.key === "Enter" && !e.nativeEvent.isComposing) { e.preventDefault(); createGroup(); } }} />
        <button className="btn sm primary" disabled={!picked.length || !newName.trim()} onClick={createGroup}><FolderPlus size={12} />새 그룹 만들기</button>
        <button className="ghost" disabled={!picked.some((n) => imported.has(n))} onClick={() => exclude(picked)}>가져오지 않기</button>
      </div>
    </div>
  );
}
