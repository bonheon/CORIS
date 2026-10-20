import React, { useMemo, useState } from "react";
import { Blocks, Bot, ChevronDown, ChevronUp, Lock, RotateCcw, Wrench } from "lucide-react";
import { useHub } from "../hub";
import "../styles/controlbar.css";

// 대화 위 실행 설정 — agent · skill · tool 을 화면에서 바로 켜고 끈다.
// 상태는 Composer 와 같은 값(agentId · skillId · selectedTools)을 쓴다.
//   selectedTools 가 비어 있으면 "자동": agent 기본 group 의 tool (자동 선택이면 모든 agent 기본 tool)
//   스킬 필수 tool 은 항상 켜져 있고 끌 수 없다.

export type BarVariant = "chips" | "panel";

interface Props {
  variant: BarVariant;
  onVariantChange: (v: BarVariant) => void;
  agentId: string;
  skillId: string | null;
  selectedTools: string[];
  onAgentChange: (id: string) => void;
  onSkillChange: (id: string | null) => void;
  onToolsChange: (tools: string[]) => void;
}

function Switch({ on, disabled, onClick }: { on: boolean; disabled?: boolean; onClick?: () => void }) {
  return (
    <button type="button" role="switch" aria-checked={on} className={`sw ${on ? "on" : ""}`} disabled={disabled} onClick={onClick}>
      <i />
    </button>
  );
}

export default function ControlBar({ variant, onVariantChange, agentId, skillId, selectedTools, onAgentChange, onSkillChange, onToolsChange }: Props) {
  const { meta, skills } = useHub();
  const [open, setOpen] = useState(false);

  const agents = useMemo(() => meta?.agents ?? [], [meta]);
  const agent = agents.find((a) => a.id === agentId);
  const auto = !agent || agentId === "auto";
  const skill = skills.find((s) => s.id === skillId);
  const locked = useMemo(() => new Set(skill?.tools ?? []), [skill]);

  const defaults = useMemo(() => {
    if (!meta) return new Set<string>();
    const groups = auto ? agents.flatMap((a) => a.default_groups) : agent!.default_groups;
    return new Set(meta.groups.filter((g) => groups.includes(g.id)).flatMap((g) => g.tools));
  }, [meta, agents, agent, auto]);
  const pool = useMemo(
    () => new Set(auto ? meta?.tools.map((t) => t.name) : agent!.tools),
    [meta, agent, auto],
  );

  if (!meta) return null;
  const info = new Map(meta.tools.map((t) => [t.name, t]));
  const usable = (n: string) => !locked.has(n) && !!info.get(n)?.available && pool.has(n);
  const manual = selectedTools.length > 0;
  const isOn = (n: string) => locked.has(n) || (manual ? selectedTools.includes(n) : defaults.has(n));

  // 자동 상태에서 끄면 기본 tool 목록에서 시작해 수동으로 바뀐다. 다시 기본과 같아지면 자동으로 돌린다.
  const setTools = (names: string[], on: boolean) => {
    const next = new Set(manual ? selectedTools : Array.from(defaults));
    names.filter(usable).forEach((n) => (on ? next.add(n) : next.delete(n)));
    const ordered = meta.tools.map((t) => t.name).filter((n) => next.has(n));
    const same = ordered.length === defaults.size && ordered.every((n) => defaults.has(n));
    onToolsChange(same ? [] : ordered);
  };

  const groups = meta.groups.filter((g) => g.tools.length > 0);
  const onCount = meta.tools.filter((t) => isOn(t.name)).length;
  const reset = () => { onToolsChange([]); onSkillChange(null); onAgentChange("auto"); };
  const dirty = manual || !!skill || !auto;

  const switcher = (
    <div className="cb-variant" title="화면 시안 비교용">
      <button className={variant === "chips" ? "sel" : ""} onClick={() => onVariantChange("chips")}>시안 A</button>
      <button className={variant === "panel" ? "sel" : ""} onClick={() => onVariantChange("panel")}>시안 B</button>
    </div>
  );

  // ── 시안 A: 한 줄 칩 — 누를 때마다 켜고 끈다 ──
  if (variant === "chips") {
    return (
      <div className="cb cb-chips">
        <div className="cb-row">
          <span className="cb-k"><Bot size={13} />에이전트</span>
          <div className="seg">
            {agents.map((a) => (
              <button key={a.id} className={a.id === agentId ? "sel" : ""} onClick={() => onAgentChange(a.id)}>{a.name}</button>
            ))}
          </div>
          <span className="cb-sep" />
          <span className="cb-k"><Blocks size={13} />스킬</span>
          {skills.length === 0 && <small className="cb-none">없음</small>}
          {skills.map((s) => (
            <button key={s.id} className={`tg ${s.id === skillId ? "on" : ""}`} onClick={() => onSkillChange(s.id === skillId ? null : s.id)}>
              <i />{s.name}
            </button>
          ))}
          <span className="cb-sep" />
          <span className="cb-k"><Wrench size={13} />Tool <b>{manual ? "수동" : "자동"}</b></span>
          {groups.flatMap((g) => g.tools).map((n) => {
            const t = info.get(n);
            const lock = locked.has(n);
            return (
              <button key={n} className={`tg ${isOn(n) ? "on" : ""} ${lock ? "lock" : ""}`} disabled={!lock && !usable(n)}
                title={lock ? "스킬 필수 tool" : t?.description} onClick={() => setTools([n], !isOn(n))}>
                {lock ? <Lock size={10} /> : <i />}{t?.label ?? n}
              </button>
            );
          })}
          <div className="cb-end">
            {dirty && <button className="ghost" onClick={reset}><RotateCcw size={12} />초기화</button>}
            {switcher}
          </div>
        </div>
      </div>
    );
  }

  // ── 시안 B: 요약 한 줄 + 펼치면 3열 스위치 패널 ──
  return (
    <div className={`cb cb-panel ${open ? "open" : ""}`}>
      <div className="cb-sum" role="button" onClick={() => setOpen(!open)}>
        <span><Bot size={13} />에이전트 <b>{agent?.name ?? "자동 선택"}</b></span>
        <span><Blocks size={13} />스킬 <b>{skill?.name ?? "없음"}</b></span>
        <span><Wrench size={13} />Tool <b>{onCount}/{meta.tools.length} 켜짐</b>{!manual && <em>자동</em>}</span>
        <div className="cb-end" onClick={(e) => e.stopPropagation()}>
          {dirty && <button className="ghost" onClick={reset}><RotateCcw size={12} />초기화</button>}
          {switcher}
          <button className="ib sm" onClick={() => setOpen(!open)} aria-label="펼치기">
            {open ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
          </button>
        </div>
      </div>
      {open && (
        <div className="cb-cols">
          <div className="cb-col">
            <h4>에이전트 <small>하나 선택</small></h4>
            {agents.map((a) => (
              <label key={a.id} className={`cb-item ${a.id === agentId ? "on" : ""}`}>
                <input type="radio" name="cb-agent" checked={a.id === agentId} onChange={() => onAgentChange(a.id)} />
                <div><b>{a.name}</b><small>{a.description}</small></div>
              </label>
            ))}
          </div>
          <div className="cb-col">
            <h4>스킬 <small>켜면 절차대로 실행</small></h4>
            {skills.length === 0 && <small className="cb-none">저장된 스킬이 없습니다</small>}
            {skills.map((s) => (
              <div key={s.id} className={`cb-item ${s.id === skillId ? "on" : ""}`}>
                <div><b>{s.name}</b><small>tool {s.tools.length}개 · {s.description.split("\n")[0]}</small></div>
                <Switch on={s.id === skillId} onClick={() => onSkillChange(s.id === skillId ? null : s.id)} />
              </div>
            ))}
          </div>
          <div className="cb-col">
            <h4>Tool <small>{manual ? "수동 선택" : "자동 — 에이전트 기본값"}</small></h4>
            {groups.map((g) => {
              const names = g.tools.filter(usable);
              const all = g.tools.every(isOn);
              return (
                <div key={g.id} className="cb-group">
                  <div className="cb-gh">
                    <b>{g.name}</b>
                    <Switch on={all} disabled={names.length === 0} onClick={() => setTools(names, !all)} />
                  </div>
                  {g.tools.length > 1 && g.tools.map((n) => (
                    <div key={n} className="cb-t">
                      <span>{info.get(n)?.label ?? n}</span>
                      {locked.has(n) ? <span className="tag lock"><Lock size={10} />스킬 필수</span>
                        : <Switch on={isOn(n)} disabled={!usable(n)} onClick={() => setTools([n], !isOn(n))} />}
                    </div>
                  ))}
                  {g.tools.length === 1 && locked.has(g.tools[0]) && <span className="tag lock"><Lock size={10} />스킬 필수</span>}
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
