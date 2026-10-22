import React, { useEffect, useMemo, useRef, useState } from "react";
import { Blocks, Check, ChevronDown, ChevronRight, Lock, Plus, RotateCcw, Search, SlidersHorizontal, X } from "lucide-react";
import { useHub } from "../hub";
import type { Skill } from "../api";
import { recentSkillIds } from "../lib/recent";
import "../styles/controlbar.css";

// 대화 위 한 줄 선택 바 — 펼치지 않고 질문하면서 바로 켜고 끈다.
//   ① 영역 탭: 전체 · 공정 · 장비 · 품질 → 그 영역 태그(+ 공통)의 tool 이 한 번에 켜진다. 전체 = 자동
//   ② 스킬 칩: 켜 둔 스킬. × 로 끄고, [+ 스킬] 에서 검색해 여러 개 켠다
//        1개 켜짐 → 그 절차로 실행 / 2개 이상 → 질문마다 그중 맞는 것만 (맞는 게 없으면 일반 답변)
//   ③ ⚙ 세부: tool 하나씩 켜고 끄기 · 에이전트 지정 — 필요한 사람만
// 상태(agentId · skillIds · selectedTools)는 ChatPage 가 들고 있고 요청에 그대로 실린다.

interface Props {
  agentId: string;
  skillIds: string[];
  selectedTools: string[];
  area: string;                       // "" = 전체
  onAgentChange: (id: string) => void;
  onSkillIdsChange: (ids: string[]) => void;
  onToolsChange: (tools: string[]) => void;
  onAreaChange: (area: string) => void;
}

const COMMON = "공통";
const CHIP_MAX = 3;

function Switch({ on, disabled, onClick }: { on: boolean; disabled?: boolean; onClick?: () => void }) {
  return (
    <button type="button" role="switch" aria-checked={on} className={`sw ${on ? "on" : ""}`} disabled={disabled} onClick={onClick}>
      <i />
    </button>
  );
}

/** 바깥을 누르거나 Esc 면 닫히는 팝오버 */
function usePopover() {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) setOpen(false); };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("mousedown", onDown); document.removeEventListener("keydown", onKey); };
  }, [open]);
  return { open, setOpen, ref };
}

function SkillRow({ s, on, onToggle, mine, admin }: { s: Skill; on: boolean; onToggle: () => void; mine: boolean; admin: boolean }) {
  return (
    <button className={`qb-sk ${on ? "on" : ""}`} onClick={onToggle}>
      <span className="qb-check">{on && <Check size={12} strokeWidth={3} />}</span>
      <span className="qb-sk-main">
        <b>{s.name}</b>
        <small>
          {s.tags.map((t) => <i key={t}>{t}</i>)}
          {s.visibility === "private" && (mine ? <em>내 스킬</em> : admin && <em>{s.owner_name}의 스킬</em>)}
        </small>
      </span>
    </button>
  );
}

export default function QuickBar({ agentId, skillIds, selectedTools, area, onAgentChange, onSkillIdsChange, onToolsChange, onAreaChange }: Props) {
  const { meta, skills, me } = useHub();
  const skillPop = usePopover();
  const setPop = usePopover();
  const [q, setQ] = useState("");
  const [openGroups, setOpenGroups] = useState<Set<string>>(new Set());   // ⚙ 에서 펼친 tool 그룹
  const admin = !!me?.is_admin;
  const myId = me?.user.user_id;

  const byId = useMemo(() => new Map(skills.map((s) => [s.id, s])), [skills]);
  const on = useMemo(() => skillIds.map((id) => byId.get(id)).filter(Boolean) as Skill[], [skillIds, byId]);
  const locked = useMemo(() => new Set(on.length === 1 ? on[0].tools : []), [on]);

  const agents = useMemo(() => meta?.agents ?? [], [meta]);
  const agent = agents.find((a) => a.id === agentId);
  const auto = !agent || agentId === "auto";
  const defaults = useMemo(() => {
    if (!meta) return new Set<string>();
    const gids = auto ? agents.flatMap((a) => a.default_groups) : agent!.default_groups;
    return new Set(meta.groups.filter((g) => gids.includes(g.id)).flatMap((g) => g.tools));
  }, [meta, agents, agent, auto]);

  if (!meta) return null;
  const info = new Map(meta.tools.map((t) => [t.name, t]));
  const usable = (n: string) => !!info.get(n)?.available;
  const manual = selectedTools.length > 0;
  const isOn = (n: string) => locked.has(n) || (manual ? selectedTools.includes(n) : defaults.has(n));
  const order = (names: Set<string>) => meta.tools.map((t) => t.name).filter((n) => names.has(n));

  // ① 영역 탭
  const pickArea = (a: string) => {
    onAreaChange(a);
    if (!a) return onToolsChange([]);
    const names = meta.groups.filter((g) => g.tags?.includes(a) || g.tags?.includes(COMMON)).flatMap((g) => g.tools);
    onToolsChange(order(new Set(names.filter(usable))));
  };

  // ② 스킬
  const toggleSkill = (id: string) =>
    onSkillIdsChange(skillIds.includes(id) ? skillIds.filter((x) => x !== id) : [...skillIds, id]);
  const query = q.trim().toLowerCase();
  const match = (s: Skill) => !query || [s.name, s.description, ...s.tags].some((t) => t.toLowerCase().includes(query));
  const inArea = (s: Skill) => !area || s.tags.includes(area) || s.tags.includes(COMMON);
  const listed = skills.filter(match).sort((a, b) => Number(inArea(b)) - Number(inArea(a)));
  const recent = query ? [] : recentSkillIds().map((id) => byId.get(id)).filter(Boolean).slice(0, 4) as Skill[];
  const mine = listed.filter((s) => s.visibility === "private" && s.owner === myId);
  const others = admin ? listed.filter((s) => s.visibility === "private" && s.owner !== myId) : [];
  const official = listed.filter((s) => s.visibility === "official");

  // ③ tool 세부
  const setTools = (names: string[], turnOn: boolean) => {
    const next = new Set(manual ? selectedTools : Array.from(defaults));
    names.filter((n) => usable(n) && !locked.has(n)).forEach((n) => (turnOn ? next.add(n) : next.delete(n)));
    const ordered = order(next);
    const same = ordered.length === defaults.size && ordered.every((n) => defaults.has(n));
    onToolsChange(same ? [] : ordered);
  };
  const onCount = meta.tools.filter((t) => isOn(t.name)).length;
  const dirty = manual || skillIds.length > 0 || !auto || !!area;
  const reset = () => { onToolsChange([]); onSkillIdsChange([]); onAgentChange("auto"); onAreaChange(""); };

  const section = (title: string, list: Skill[]) => list.length > 0 && (
    <div className="qb-sec">
      <h5>{title}</h5>
      {list.map((s) => <SkillRow key={s.id} s={s} on={skillIds.includes(s.id)} onToggle={() => toggleSkill(s.id)}
        mine={s.owner === myId} admin={admin} />)}
    </div>
  );

  return (
    <div className="qb">
      <div className="seg qb-area">
        {["", ...meta.areas].map((a) => (
          <button key={a || "all"} className={a === area ? "on" : ""} onClick={() => pickArea(a)}
            title={a ? `켜지는 tool 그룹: ${meta.groups.filter((g) => g.tags?.includes(a) || g.tags?.includes(COMMON)).map((g) => g.name).join(", ")}` : "질문에 맞게 자동"}>
            {a || "전체"}
          </button>
        ))}
      </div>

      {/* 팝오버를 스킬 영역 시작점에 붙인다 — 칩이 늘어 [+ 스킬] 버튼이 움직여도 목록 위치는 그대로 */}
      <div className="qb-skills" ref={skillPop.ref}>
        <Blocks size={13} className="qb-ico" />
        {on.slice(0, CHIP_MAX).map((s) => (
          <span key={s.id} className="qb-chip" title={s.description}>
            {s.name}
            <button onClick={() => toggleSkill(s.id)} aria-label={`${s.name} 끄기`}><X size={11} /></button>
          </span>
        ))}
        {on.length > CHIP_MAX && <span className="qb-more" onClick={() => skillPop.setOpen(true)}>+{on.length - CHIP_MAX}</span>}
        {on.length > 0 && <span className="qb-mode">{on.length === 1 ? "항상 적용" : "질문마다 자동"}</span>}

        <button className="qb-add" onClick={() => { skillPop.setOpen(!skillPop.open); setQ(""); }}>
          <Plus size={12} />스킬
        </button>
        {skillPop.open && (
            <div className="qb-pop qb-skill-pop">
              <label className="qb-search">
                <Search size={13} />
                <input autoFocus value={q} onChange={(e) => setQ(e.target.value)} placeholder="스킬 · 태그 검색" />
              </label>
              <div className="qb-list">
                {section("최근 사용", recent)}
                {section("내 스킬", mine)}
                {section("공식 업무", official)}
                {section("다른 사용자의 스킬 (관리자)", others)}
                {listed.length === 0 && <div className="qb-empty">'{q}' 에 맞는 스킬이 없습니다</div>}
              </div>
              <div className="qb-foot">
                1개 켜면 그 절차로 · 2개 이상이면 질문마다 맞는 것만 적용
                {skillIds.length > 0 && <button className="link" onClick={() => onSkillIdsChange([])}>모두 끄기</button>}
              </div>
            </div>
          )}
      </div>

      <div className="qb-end">
        {dirty && <button className="ghost" onClick={reset} title="영역 · 스킬 · tool 을 처음 상태로"><RotateCcw size={12} />초기화</button>}
        <div className="qb-anchor" ref={setPop.ref}>
          <button className={`qb-add ${manual ? "on" : ""}`} onClick={() => setPop.setOpen(!setPop.open)} title="tool 하나씩 켜고 끄기 · 에이전트 지정">
            <SlidersHorizontal size={12} />Tool {onCount}{!manual && <em>자동</em>}
          </button>
          {setPop.open && (
            <div className="qb-pop qb-set-pop">
              {agents.length > 2 && (
                <div className="qb-sec">
                  <h5>에이전트</h5>
                  <div className="seg">
                    {agents.map((a) => (
                      <button key={a.id} className={a.id === agentId ? "on" : ""} onClick={() => onAgentChange(a.id)} title={a.description}>{a.name}</button>
                    ))}
                  </div>
                </div>
              )}
              <div className="qb-sec">
                <h5>Tool <small>{manual ? "직접 선택" : "자동 — 질문에 맞게"}</small></h5>
                {meta.groups.filter((g) => g.tools.length > 0).map((g) => {
                  const names = g.tools.filter((n) => usable(n) && !locked.has(n));
                  const all = g.tools.every(isOn);
                  const onN = g.tools.filter(isOn).length;
                  const expanded = openGroups.has(g.id);
                  const toggleOpen = () => setOpenGroups((o) => {
                    const next = new Set(o);
                    next.has(g.id) ? next.delete(g.id) : next.add(g.id);
                    return next;
                  });
                  return (
                    <div key={g.id} className={`cb-group ${expanded ? "open" : ""}`}>
                      <div className="cb-gh">
                        {/* 이름을 누르면 이 그룹에 어떤 기능이 있는지 펼쳐 보여준다 — 켜고 끄기는 오른쪽 스위치 */}
                        <button className="qb-gbtn" onClick={toggleOpen} aria-expanded={expanded}>
                          {expanded ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
                          <span>
                            <b>{g.name}</b>
                            <small className="qb-gtag">
                              {onN}/{g.tools.length}{!!g.tags?.length && ` · ${g.tags.join(" · ")}`}
                            </small>
                            {g.description && <em className="qb-gdesc">{g.description}</em>}
                          </span>
                        </button>
                        <Switch on={all} disabled={names.length === 0} onClick={() => setTools(names, !all)} />
                      </div>
                      {expanded && g.tools.map((n) => {
                        const t = info.get(n);
                        return (
                          <div key={n} className="qb-tool">
                            <div>
                              <b>{t?.label ?? n}{!t?.available && <span className="tag err">사용 불가</span>}</b>
                              <p title={t?.description}>{t?.description || "설명 없음"}</p>
                              <code>{n}</code>
                            </div>
                            {locked.has(n) ? <span className="tag lock"><Lock size={10} />스킬 필수</span>
                              : <Switch on={isOn(n)} disabled={!usable(n)} onClick={() => setTools([n], !isOn(n))} />}
                          </div>
                        );
                      })}
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
