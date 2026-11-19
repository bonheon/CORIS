// 스킬 단계 편집기 — 단계를 정의하면 LLM 대신 단계 실행 엔진(backend hub/steps.py)이 순서대로 실행한다.
//   입력값: 대화에서 뽑을 값 (Lot ID 등)
//   단계:   조회(data) · 계산(compute) · 조건(condition) · 판단(judge, LLM) · 보고(report)
//   참조:   {{input.x}} · {{item.열}} · {{s1.count}} · {{s3[i].열|first}} · {{table:s6}} · {{s7.text}} — '참조 넣기' 로 고른다
import React, { useMemo } from "react";
import { ArrowDown, ArrowUp, Plus, Trash2 } from "lucide-react";
import type { StepDef, StepInputDef, StepType, ToolInfo } from "../api";

const TYPE_LABEL: Record<StepType, string> = { data: "조회", compute: "계산", condition: "조건", judge: "판단 (LLM)", report: "보고" };
const TYPE_HINT: Record<StepType, string> = {
  data: "tool 을 정해진 인자로 호출합니다. '반복' 을 채우면 그 목록의 항목마다 동시에 호출합니다.",
  compute: "코드로 표를 만들거나 목록을 정리합니다 — LLM 을 쓰지 않습니다.",
  condition: "조건이 참이면 지정한 단계로 건너뜁니다. empty(s1.rows) 처럼 쓰면 코드가, 문장으로 쓰면 LLM 이 판단합니다.",
  judge: "앞 단계 결과를 보고 LLM 이 판단합니다. 기준을 적으면 위에서부터 처음 맞는 판정을 고릅니다.",
  report: "{{…}} 를 쓰면 코드가 채워 항상 같은 양식이 됩니다. 양식 설명만 쓰면 LLM 이 본문 '## 보고 양식' 대로 씁니다.",
};

const nextId = (steps: StepDef[]) => {
  const used = new Set(steps.map((s) => s.id));
  let n = steps.length + 1;
  while (used.has(`s${n}`)) n += 1;
  return `s${n}`;
};

function blank(type: StepType, id: string): StepDef {
  switch (type) {
    case "data": return { id, type, title: "", tool: "", args: {} };
    case "compute": return { id, type, title: "", op: "table", for_each: "", columns: {} };
    case "condition": return { id, type, title: "", if: "", then: "end" };
    case "judge": return { id, type, title: "", from: [], prompt: "" };
    default: return { id, type, title: "보고서", template: "" };
  }
}

/** 키 · 값 목록 (tool 인자 · 표 열) */
function KV({ value, onChange, keyPh, valPh, refs, disabled }: {
  value: Record<string, unknown>; onChange: (v: Record<string, unknown>) => void;
  keyPh: string; valPh: string; refs: string[]; disabled?: boolean;
}) {
  const rows = Object.entries(value);
  const set = (i: number, k: string, v: unknown) => {
    const next = rows.map((r, j) => (j === i ? [k, v] : r)) as [string, unknown][];
    onChange(Object.fromEntries(next));
  };
  return (
    <div className="step-kv">
      {rows.map(([k, v], i) => (
        <div key={i} className="step-kv-row">
          <input className="input" value={k} placeholder={keyPh} disabled={disabled} onChange={(e) => set(i, e.target.value, v)} />
          <input className="input mono" value={typeof v === "string" ? v : JSON.stringify(v)} placeholder={valPh} disabled={disabled}
            onChange={(e) => set(i, k, /^-?\d+(\.\d+)?$/.test(e.target.value) ? Number(e.target.value) : e.target.value)} />
          {!disabled && <RefPick refs={refs} onPick={(r) => set(i, k, `${typeof v === "string" ? v : ""}${r}`)} />}
          {!disabled && <button className="ib" title="삭제" onClick={() => onChange(Object.fromEntries(rows.filter((_, j) => j !== i)))}><Trash2 size={13} /></button>}
        </div>
      ))}
      {!disabled && <button className="ghost" onClick={() => onChange({ ...value, [`key${rows.length + 1}`]: "" })}><Plus size={12} />추가</button>}
    </div>
  );
}

/** 참조 넣기 — 지금 단계에서 쓸 수 있는 입력값 · 앞 단계 결과 */
function RefPick({ refs, onPick }: { refs: string[]; onPick: (r: string) => void }) {
  if (!refs.length) return null;
  return (
    <select className="select ref-pick" value="" onChange={(e) => e.target.value && onPick(e.target.value)} title="참조 넣기">
      <option value="">참조 넣기</option>
      {refs.map((r) => <option key={r} value={r}>{r}</option>)}
    </select>
  );
}

export default function StepEditor({ steps, inputs, onChange, tools, disabled }: {
  steps: StepDef[]; inputs: StepInputDef[];
  onChange: (p: { steps?: StepDef[]; inputs?: StepInputDef[] }) => void;
  tools: ToolInfo[]; disabled?: boolean;
}) {
  const setStep = (i: number, patch: Partial<StepDef>) => onChange({ steps: steps.map((s, j) => (j === i ? { ...s, ...patch } : s)) });
  const move = (i: number, d: number) => {
    const next = [...steps];
    const [x] = next.splice(i, 1);
    next.splice(i + d, 0, x);
    onChange({ steps: next });
  };
  const add = (type: StepType) => onChange({ steps: [...steps, blank(type, nextId(steps))] });
  const toolNames = useMemo(() => tools.map((t) => t.name), [tools]);

  /** i 번째 단계에서 쓸 수 있는 참조 */
  const refsFor = (i: number, inLoop: boolean, forText = false): string[] => {
    const out = inputs.filter((x) => x.name).map((x) => `{{input.${x.name}}}`);
    if (inLoop) out.push("{{item}}", "{{item.열이름}}", "{{item.날짜열|date}}");
    steps.slice(0, i).forEach((s) => {
      if (s.type === "data") {
        out.push(`{{${s.id}.count}}`, `{{${s.id}.summary}}`, `{{${s.id}.열이름}}`);
        if (s.for_each && inLoop) out.push(`{{${s.id}[i].열이름|first}}`);
        if (forText) out.push(`{{table:${s.id}}}`);
      } else if (s.type === "compute") {
        out.push(`{{${s.id}.count}}`);
        if (forText) out.push(`{{table:${s.id}}}`);
      } else if (s.type === "judge") {
        out.push(`{{${s.id}.text}}`, ...(s.criteria?.length ? [`{{${s.id}.verdict}}`] : []), ...(s.outputs ?? []).map((o) => `{{${s.id}.${o}}}`));
      } else if (s.type === "condition" && s.verdict) {
        out.push("{{verdict}}");
      }
    });
    return Array.from(new Set(out));
  };
  /** 반복 · 조건에 쓰는 목록 참조 (중괄호 없이) */
  const listRefs = (i: number) => steps.slice(0, i).flatMap((s) =>
    s.type === "data" ? [`${s.id}.rows`, `${s.id}.열이름`] : s.type === "compute" ? [`${s.id}.rows`, `${s.id}.values`] :
      s.type === "judge" ? (s.outputs ?? []).map((o) => `${s.id}.${o}`) : []);

  return (
    <div className="steps-ed">
      <div className="steps-sub">
        <b>입력값</b><span>대화에서 뽑아 단계에 넣는 값 — 필수 값이 없으면 사용자에게 되묻습니다</span>
      </div>
      {inputs.map((x, i) => (
        <div key={i} className="in-row">
          <input className="input mono" placeholder="이름 (lot_id)" value={x.name} disabled={disabled}
            onChange={(e) => onChange({ inputs: inputs.map((y, j) => (j === i ? { ...y, name: e.target.value } : y)) })} />
          <input className="input" placeholder="표시명 (Lot ID)" value={x.label ?? ""} disabled={disabled}
            onChange={(e) => onChange({ inputs: inputs.map((y, j) => (j === i ? { ...y, label: e.target.value } : y)) })} />
          <input className="input" placeholder="예시 (TE2FE35)" value={x.example ?? ""} disabled={disabled}
            onChange={(e) => onChange({ inputs: inputs.map((y, j) => (j === i ? { ...y, example: e.target.value } : y)) })} />
          <label className="mcp-chk" style={{ margin: 0 }}>
            <input type="checkbox" checked={!!x.required} disabled={disabled}
              onChange={(e) => onChange({ inputs: inputs.map((y, j) => (j === i ? { ...y, required: e.target.checked } : y)) })} />필수
          </label>
          {!disabled && <button className="ib" title="삭제" onClick={() => onChange({ inputs: inputs.filter((_, j) => j !== i) })}><Trash2 size={13} /></button>}
        </div>
      ))}
      {!disabled && <button className="ghost" onClick={() => onChange({ inputs: [...inputs, { name: "", label: "", required: true }] })}><Plus size={12} />입력값 추가</button>}

      <div className="steps-sub" style={{ marginTop: 16 }}>
        <b>단계</b><span>위에서부터 순서대로 실행 · 조회 · 계산 · 조건은 코드, 판단 · 자유 양식 보고만 LLM</span>
      </div>
      {steps.map((s, i) => {
        const loop = !!s.for_each;
        return (
          <div key={i} className={`step-card t-${s.type}`}>
            <div className="step-h">
              <span className="step-no">{i + 1}</span>
              <input className="input mono step-id" value={s.id} disabled={disabled} onChange={(e) => setStep(i, { id: e.target.value })} title="단계 id — 참조할 때 씁니다" />
              <select className="select step-type" value={s.type} disabled={disabled} onChange={(e) => setStep(i, blank(e.target.value as StepType, s.id))}>
                {(Object.keys(TYPE_LABEL) as StepType[]).map((t) => <option key={t} value={t}>{TYPE_LABEL[t]}</option>)}
              </select>
              <input className="input" value={s.title ?? ""} placeholder="단계 이름 (처리 과정에 보입니다)" disabled={disabled} onChange={(e) => setStep(i, { title: e.target.value })} />
              {!disabled && (
                <span className="step-acts">
                  <button className="ib" title="위로" disabled={i === 0} onClick={() => move(i, -1)}><ArrowUp size={13} /></button>
                  <button className="ib" title="아래로" disabled={i === steps.length - 1} onClick={() => move(i, 1)}><ArrowDown size={13} /></button>
                  <button className="ib" title="삭제" onClick={() => onChange({ steps: steps.filter((_, j) => j !== i) })}><Trash2 size={13} /></button>
                </span>
              )}
            </div>
            <p className="step-hint">{TYPE_HINT[s.type]}</p>

            {s.type === "data" && (
              <div className="step-grid">
                <label>tool</label>
                <select className="select" value={s.tool ?? ""} disabled={disabled} onChange={(e) => setStep(i, { tool: e.target.value })}>
                  <option value="">선택</option>
                  {tools.map((t) => <option key={t.name} value={t.name}>{t.label} ({t.name})</option>)}
                  {s.tool && !toolNames.includes(s.tool) && <option value={s.tool}>{s.tool} (사용 불가)</option>}
                </select>
                <label>반복<span>선택</span></label>
                <div className="step-inline">
                  <input className="input mono" list={`lr-${i}`} value={s.for_each ?? ""} placeholder="예) s1.rows — 비우면 한 번만" disabled={disabled}
                    onChange={(e) => setStep(i, { for_each: e.target.value || undefined })} />
                  <datalist id={`lr-${i}`}>{listRefs(i).map((r) => <option key={r} value={r} />)}</datalist>
                </div>
                <label>인자</label>
                <KV value={s.args ?? {}} onChange={(args) => setStep(i, { args })} keyPh="인자 이름" valPh="값 또는 {{참조}}" refs={refsFor(i, loop)} disabled={disabled} />
              </div>
            )}

            {s.type === "compute" && (
              <div className="step-grid">
                <label>계산</label>
                <select className="select" value={s.op ?? "table"} disabled={disabled} onChange={(e) => setStep(i, { op: e.target.value as StepDef["op"] })}>
                  <option value="table">표 만들기 — 항목마다 한 행</option>
                  <option value="unique">목록 중복 제거</option>
                  <option value="filter">행 거르기</option>
                </select>
                {(s.op ?? "table") === "table" ? (
                  <>
                    <label>행 기준</label>
                    <input className="input mono" list={`lr-${i}`} value={s.for_each ?? ""} placeholder="예) s1.rows — 이 목록의 항목마다 한 행" disabled={disabled}
                      onChange={(e) => setStep(i, { for_each: e.target.value || undefined })} />
                    <datalist id={`lr-${i}`}>{listRefs(i).map((r) => <option key={r} value={r} />)}</datalist>
                    <label>열</label>
                    <KV value={s.columns ?? {}} onChange={(columns) => setStep(i, { columns: columns as Record<string, string> })}
                      keyPh="열 이름 (표에 보임)" valPh="{{item.lot_id}}" refs={refsFor(i, true)} disabled={disabled} />
                  </>
                ) : (
                  <>
                    <label>대상</label>
                    <input className="input mono" list={`lr-${i}`} value={s.of ?? ""} placeholder="예) s1.eqp_id" disabled={disabled} onChange={(e) => setStep(i, { of: e.target.value })} />
                    <datalist id={`lr-${i}`}>{listRefs(i).map((r) => <option key={r} value={r} />)}</datalist>
                    {s.op === "filter" && (
                      <>
                        <label>조건</label>
                        <div className="step-inline">
                          <input className="input mono" value={s.column ?? ""} placeholder="열 (status)" disabled={disabled} onChange={(e) => setStep(i, { column: e.target.value })} />
                          <span className="muted">=</span>
                          <input className="input mono" value={s.equals ?? ""} placeholder="값 (HOLD)" disabled={disabled} onChange={(e) => setStep(i, { equals: e.target.value })} />
                        </div>
                      </>
                    )}
                  </>
                )}
              </div>
            )}

            {s.type === "condition" && (
              <div className="step-grid">
                <label>조건</label>
                <input className="input mono" list={`cd-${i}`} value={s.if ?? ""} placeholder="예) empty(s1.rows) · count(s2.eq_ids) > 3 · 문장도 가능" disabled={disabled}
                  onChange={(e) => setStep(i, { if: e.target.value })} />
                <datalist id={`cd-${i}`}>{listRefs(i).flatMap((r) => [`empty(${r})`, `not empty(${r})`, `count(${r}) > 0`]).map((r) => <option key={r} value={r} />)}</datalist>
                <label>참이면</label>
                <select className="select" value={s.then ?? "end"} disabled={disabled} onChange={(e) => setStep(i, { then: e.target.value })}>
                  <option value="end">보고 단계로 바로</option>
                  {steps.slice(i + 1).map((x) => <option key={x.id} value={x.id}>{x.id} · {x.title || TYPE_LABEL[x.type]} 로 건너뛰기</option>)}
                </select>
                <label>판정<span>선택</span></label>
                <input className="input" value={s.verdict ?? ""} placeholder="예) 정상 — 보고에서 {{verdict}} 로 씁니다" disabled={disabled} onChange={(e) => setStep(i, { verdict: e.target.value || undefined })} />
              </div>
            )}

            {s.type === "judge" && (
              <div className="step-grid">
                <label>근거 단계</label>
                <div className="step-chips">
                  {steps.slice(0, i).map((x) => {
                    const on = (s.from ?? []).includes(x.id);
                    return (
                      <button key={x.id} className={`chip-btn ${on ? "on" : ""}`} disabled={disabled}
                        onClick={() => setStep(i, { from: on ? (s.from ?? []).filter((f) => f !== x.id) : [...(s.from ?? []), x.id] })}>
                        {x.id} · {x.title || TYPE_LABEL[x.type]}
                      </button>
                    );
                  })}
                  {i === 0 && <span className="muted">앞 단계가 없습니다</span>}
                </div>
                <label>지시</label>
                <textarea className="textarea" rows={3} value={s.prompt ?? ""} disabled={disabled} placeholder="예) Lot 마다 해제 검토 가능 / 보류 / 엔지니어 확인 필요 중 하나와 근거 한 줄"
                  onChange={(e) => setStep(i, { prompt: e.target.value })} />
                <label>판정 기준<span>선택 · 한 줄에 '판정: 조건'</span></label>
                <textarea className="textarea mono" rows={3} disabled={disabled}
                  value={(s.criteria ?? []).map((c) => `${c.verdict}: ${c.when}`).join("\n")}
                  placeholder={"엔지니어 확인 요청: 기준 초과 웨이퍼 1장 이상\n관찰: 패턴 웨이퍼만 있음\n정상: 이상 웨이퍼 없음"}
                  onChange={(e) => setStep(i, {
                    criteria: e.target.value.split("\n").map((l) => l.split(/:(.*)/s)).filter((p) => p[0]?.trim())
                      .map(([v, w]) => ({ verdict: v.trim(), when: (w ?? "").trim() })),
                  })} />
                <label>출력 값<span>선택 · 다음 단계에서 쓸 값 이름, 쉼표로</span></label>
                <input className="input mono" value={(s.outputs ?? []).join(", ")} placeholder="예) abnormal_slots, eq_ids" disabled={disabled}
                  onChange={(e) => setStep(i, { outputs: e.target.value.split(",").map((x) => x.trim()).filter(Boolean) })} />
              </div>
            )}

            {s.type === "report" && (
              <div className="step-grid">
                <label>양식</label>
                <div>
                  <textarea className="textarea mono" rows={8} value={s.template ?? ""} disabled={disabled}
                    placeholder={"## Hold Lot 현황 · {{s1.count}}건\n{{table:s6}}\n\n### 판단\n{{s7.text}}"}
                    onChange={(e) => setStep(i, { template: e.target.value })} />
                  {!disabled && <div style={{ marginTop: 6 }}><RefPick refs={refsFor(i, false, true)} onPick={(r) => setStep(i, { template: `${s.template ?? ""}${r}` })} /></div>}
                </div>
              </div>
            )}
          </div>
        );
      })}
      {!disabled && (
        <div className="step-add">
          {(Object.keys(TYPE_LABEL) as StepType[]).map((t) => (
            <button key={t} className="ghost" onClick={() => add(t)}><Plus size={12} />{TYPE_LABEL[t]}</button>
          ))}
        </div>
      )}
    </div>
  );
}
