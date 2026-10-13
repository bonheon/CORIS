import React, { useEffect, useMemo, useRef, useState } from "react";
import { Info, Play, Plus } from "lucide-react";
import { api, SkillInput } from "../api";
import { useHub } from "../hub";
import { skillDraft } from "../lib/draft";

const EMPTY: SkillInput = { name: "", description: "", tools: [], instructions: "" };

export default function SkillsPage({ selected, navigate }: { selected?: string; navigate: (p: string, replace?: boolean) => void }) {
  const { meta, skills, refreshSkills, startChat, toast } = useHub();
  const isNew = selected === "new";
  const current = skills.find((s) => s.id === selected);
  const [form, setForm] = useState<SkillInput>(EMPTY);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  // 다른 화면에서 넘긴 tool 초안 — ref 에 옮겨 두어야 StrictMode 의 effect 2회 실행에도 유지된다
  const draft = useRef<string[]>([]);

  // 선택이 없으면 첫 스킬로
  useEffect(() => {
    if (!selected && skills.length) navigate(`/skills/${skills[0].id}`, true);
  }, [selected, skills, navigate]);

  useEffect(() => {
    setErr(null);
    if (isNew) {
      if (skillDraft.tools.length) {
        draft.current = skillDraft.tools;
        skillDraft.tools = [];
      }
      setForm({ ...EMPTY, tools: draft.current });
    } else if (current) {
      setForm({ name: current.name, description: current.description, tools: current.tools, instructions: current.instructions });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected, current?.updated_at]);

  const groups = useMemo(() => {
    const out = new Map<string, NonNullable<typeof meta>["tools"]>();
    meta?.tools.forEach((t) => out.set(t.category, [...(out.get(t.category) ?? []), t]));
    return Array.from(out.entries());
  }, [meta]);

  const dirty = isNew || !current || JSON.stringify(form) !== JSON.stringify({
    name: current.name, description: current.description, tools: current.tools, instructions: current.instructions,
  });

  const toggleTool = (name: string) =>
    setForm((f) => ({ ...f, tools: f.tools.includes(name) ? f.tools.filter((t) => t !== name) : [...f.tools, name] }));

  const save = async () => {
    if (!form.name.trim()) return setErr("이름을 입력하세요");
    if (!form.tools.length) return setErr("tool을 1개 이상 선택하세요");
    setSaving(true);
    setErr(null);
    try {
      const saved = isNew ? await api.createSkill(form) : await api.updateSkill(selected!, form);
      await refreshSkills();
      toast("스킬을 저장했습니다");
      if (isNew) navigate(`/skills/${saved.id}`, true);
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setSaving(false);
    }
  };

  const remove = async () => {
    if (!current || !window.confirm(`'${current.name}' 스킬을 삭제할까요?`)) return;
    await api.deleteSkill(current.id);
    await refreshSkills();
    toast("스킬을 삭제했습니다");
    navigate("/skills", true);
  };

  const test = () => {
    if (!current) return;
    startChat({ text: `'${current.name}' 스킬을 실행해줘`, agentId: "auto", skillId: current.id });
  };

  return (
    <section className="center">
      <header className="c-head"><b>스킬</b></header>
      <div className="scroll">
        <div className="inner wide">
          <div className="page-head">
            <div>
              <h1>스킬</h1>
              <p>tool 몇 개와 작업 지침을 묶어 저장합니다. 대화에서 <code className="mono">/</code> 로 불러오거나 이벤터에 연결할 수 있습니다.</p>
            </div>
            <button className="btn primary" onClick={() => navigate("/skills/new")}><Plus size={15} />새 스킬</button>
          </div>

          <div className="split">
            <div className="panel" style={{ marginBottom: 0 }}>
              {isNew && <button className="sk-item on"><b>새 스킬</b><small>작성 중</small></button>}
              {skills.map((s) => (
                <button key={s.id} className={`sk-item ${s.id === selected ? "on" : ""}`} onClick={() => navigate(`/skills/${s.id}`)}>
                  <b>{s.name}</b>
                  <small>tool {s.tools.length} · {s.uses ? `${s.uses}회 사용` : "사용 기록 없음"}</small>
                </button>
              ))}
              {!skills.length && !isNew && <div className="list-empty">저장된 스킬이 없습니다</div>}
            </div>

            {(isNew || current) && (
              <div className="panel" style={{ marginBottom: 0 }}>
                <div className="form">
                  <div className="field">
                    <label>이름</label>
                    <input className="input" value={form.name} maxLength={60} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="예) 주간 공지 브리핑" />
                  </div>
                  <div className="field">
                    <label>설명<span>목록과 / 메뉴에 표시됩니다</span></label>
                    <input className="input" value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
                  </div>

                  <div className="field">
                    <div className="label">사용할 tool<span>{form.tools.length}개 선택</span></div>
                    {groups.map(([cat, tools]) => (
                      <div key={cat} className="tool-group">
                        <h4>{cat}</h4>
                        <div className="tools">
                          {tools.map((t) => {
                            const on = form.tools.includes(t.name);
                            return (
                              <label key={t.name} className={`tool ${on ? "sel" : ""}`}>
                                <input type="checkbox" checked={on} onChange={() => toggleTool(t.name)} />
                                <div><b>{t.label}</b><code>{t.name}</code><p>{t.description}</p></div>
                              </label>
                            );
                          })}
                        </div>
                      </div>
                    ))}
                  </div>

                  <div className="field">
                    <label>작업 지침<span>LLM에게 전달되는 절차</span></label>
                    <textarea
                      className="textarea"
                      value={form.instructions}
                      onChange={(e) => setForm({ ...form, instructions: e.target.value })}
                      placeholder={"1. 먼저 ~를 조회한다.\n2. 결과가 ~이면 ~를 추가로 확인한다.\n3. 마지막에 ~를 표로 정리한다."}
                    />
                  </div>

                  <div className="note">
                    <Info size={15} style={{ flexShrink: 0, marginTop: 2 }} />
                    <div>이 스킬을 쓰는 동안 에이전트는 선택한 <b>tool {form.tools.length}개</b>만 볼 수 있습니다. 후보가 적을수록 tool을 잘못 고르는 일이 줄어듭니다.</div>
                  </div>
                  {err && <div className="note err" style={{ marginTop: 10 }}>{err}</div>}
                </div>
                <div className="form-foot">
                  {current && <button className="btn danger" onClick={remove}>삭제</button>}
                  <span className="sp" />
                  {current && <button className="btn" onClick={test} disabled={dirty}><Play size={14} />대화에서 실행</button>}
                  <button className="btn primary" onClick={save} disabled={saving || !dirty}>{saving ? "저장 중…" : "저장"}</button>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </section>
  );
}
