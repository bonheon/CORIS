import React, { useEffect, useMemo, useRef } from "react";
import { Lock, RotateCcw } from "lucide-react";
import { useHub } from "../hub";
import type { ToolInfo } from "../api";

// Tool 선택 — group(데이터 영역) 단위로 묶어 켜고 끈다.
// 아무것도 고르지 않으면 "자동": agent 기본 group(또는 스킬 tool)을 백엔드가 쓴다.
// 스킬 필수 tool 은 항상 켜져 있고 끌 수 없다 (백엔드도 같은 규칙으로 잠근다).

interface Props {
  agentId: string;
  skillTools: string[];
  selected: string[];
  onChange: (tools: string[]) => void;
}

type Why = "locked" | "unavailable" | "outside" | null;

function Check({ state, disabled, onClick }: { state: boolean | "some"; disabled?: boolean; onClick?: () => void }) {
  const ref = useRef<HTMLInputElement>(null);
  useEffect(() => { if (ref.current) ref.current.indeterminate = state === "some"; }, [state]);
  return <input ref={ref} type="checkbox" checked={state === true} disabled={disabled} onChange={onClick} />;
}

export default function ToolPicker({ agentId, skillTools, selected, onChange }: Props) {
  const { meta, agentName } = useHub();
  const agent = meta?.agents.find((a) => a.id === agentId);
  const auto = !agent || agentId === "auto";
  const pool = useMemo(() => new Set(auto ? meta?.tools.map((t) => t.name) : agent!.tools), [auto, agent, meta]);
  const defaults = useMemo(() => {
    if (auto || !meta) return new Set<string>();
    return new Set(meta.groups.filter((g) => agent!.default_groups.includes(g.id)).flatMap((g) => g.tools));
  }, [auto, agent, meta]);
  const locked = useMemo(() => new Set(skillTools), [skillTools]);
  const sel = useMemo(() => new Set(selected), [selected]);

  if (!meta) return null;
  const info = new Map(meta.tools.map((t) => [t.name, t]));

  const why = (name: string): Why => {
    if (locked.has(name)) return "locked";
    const t = info.get(name);
    if (!t || !t.available) return "unavailable";
    if (!t.group || !pool.has(name)) return "outside";
    return null;
  };
  const isOn = (name: string) => locked.has(name) || sel.has(name);

  const toggle = (names: string[], on: boolean) => {
    const next = new Set(sel);
    names.filter((n) => why(n) === null).forEach((n) => (on ? next.add(n) : next.delete(n)));
    onChange(meta.tools.map((t) => t.name).filter((n) => next.has(n)));  // 화면 순서 유지
  };

  const sections: { id: string; name: string; description: string; tools: string[] }[] = [
    ...meta.groups,
    { id: "_none", name: "기타", description: "그룹 미지정 — catalog.yaml 에 추가해야 사용 가능", tools: meta.tools.filter((t) => !t.group).map((t) => t.name) },
  ].filter((g) => g.tools.length > 0);

  // 자동 선택일 때: 고른 tool 을 모두 처리할 수 있는 agent (백엔드 candidates 와 같은 규칙)
  const need = [...selected, ...skillTools];
  const capable = auto && need.length
    ? meta.agents.filter((a) => a.id !== "auto" && need.every((n) => a.tools.includes(n))).map((a) => a.name)
    : [];

  return (
    <div className="picker">
      <div className="pk-head">
        <b>Tool 선택</b>
        <small>
          {selected.length === 0
            ? auto ? "자동 — 질문에 맞는 agent 의 기본 tool 을 씁니다" : `자동 — ${agentName(agentId)} 기본 tool 사용`
            : `${selected.length}개 선택${skillTools.length ? ` + 스킬 필수 ${skillTools.length}개` : ""}`}
        </small>
        {selected.length > 0 && (
          <button className="ghost" onClick={() => onChange([])}><RotateCcw size={12} />자동으로</button>
        )}
      </div>

      <div className="pk-body">
        {sections.map((g) => {
          const usable = g.tools.filter((n) => why(n) === null);
          const onCount = usable.filter((n) => sel.has(n)).length;
          const state = onCount === 0 ? false : onCount === usable.length ? true : "some";
          return (
            <div key={g.id} className="pk-group">
              <label className={`pk-g ${usable.length === 0 ? "off" : ""}`}>
                <Check state={state} disabled={usable.length === 0} onClick={() => toggle(usable, state !== true)} />
                <b>{g.name}</b>
                <small>{g.description}</small>
              </label>
              {g.tools.map((n) => {
                const t = info.get(n) as ToolInfo | undefined;
                const w = why(n);
                return (
                  <label key={n} className={`pk-t ${w && w !== "locked" ? "off" : ""}`} title={t?.description}>
                    <Check state={isOn(n)} disabled={w !== null} onClick={() => toggle([n], !sel.has(n))} />
                    <span>{t?.label ?? n}</span>
                    <small className="mono">{n}</small>
                    {w === "locked" && <span className="tag lock"><Lock size={10} />스킬 필수</span>}
                    {w === "unavailable" && <span className="tag err">서버 응답 없음</span>}
                    {w === "outside" && <span className="tag">{t?.group ? "agent 범위 밖" : "그룹 없음"}</span>}
                    {!w && selected.length === 0 && defaults.has(n) && <span className="tag ok">기본</span>}
                  </label>
                );
              })}
            </div>
          );
        })}
      </div>

      {auto && need.length > 0 && (
        <div className="pk-foot">
          처리 가능한 agent: <b>{capable.length ? capable.join(", ") : "없음 — 기본 agent 로 처리"}</b>
        </div>
      )}
    </div>
  );
}
