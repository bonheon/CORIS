import React, { useEffect, useMemo, useRef, useState } from "react";
import { Copy, Info, Play, Plus } from "lucide-react";
import TagInput from "../components/TagInput";
import StepEditor from "../components/StepEditor";
import { api, Skill, SkillInput } from "../api";
import { useHub } from "../hub";
import { skillDraft } from "../lib/draft";

const EMPTY: SkillInput = { name: "", description: "", tools: [], instructions: "", tags: [], inputs: [], steps: [] };

// 목록 필터 — 관리자는 다른 사용자의 '내 스킬' 도 본다
type Filter = "all" | "mine" | "official" | "others";

const toInput = (s: Skill): SkillInput =>
  ({ name: s.name, description: s.description, tools: s.tools, instructions: s.instructions, tags: s.tags, visibility: s.visibility,
     inputs: s.inputs ?? [], steps: s.steps ?? [] });

export default function SkillsPage({ selected, navigate }: { selected?: string; navigate: (p: string, replace?: boolean) => void }) {
  const { meta, me, skills, refreshSkills, startChat, toast } = useHub();
  const isNew = selected === "new";
  const current = skills.find((s) => s.id === selected);
  const [form, setForm] = useState<SkillInput>(EMPTY);
  const [filter, setFilter] = useState<Filter>("all");
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  // 다른 화면에서 넘긴 tool 초안 — ref 에 옮겨 두어야 StrictMode 의 effect 2회 실행에도 유지된다
  const draft = useRef<string[]>([]);

  const admin = !!me?.is_admin;
  const myId = me?.user.user_id;
  const mine = (s: Skill) => s.visibility === "private" && s.owner === myId;
  const canEdit = isNew || (!!current && (admin || mine(current)));

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
      setForm(toInput(current));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected, current?.updated_at]);

  const groups = useMemo(() => {
    const out = new Map<string, NonNullable<typeof meta>["tools"]>();
    meta?.tools.forEach((t) => out.set(t.category, [...(out.get(t.category) ?? []), t]));
    return Array.from(out.entries());
  }, [meta]);
  const tagSuggestions = useMemo(
    () => Array.from(new Set([...(meta?.areas ?? []), "공통", ...skills.flatMap((s) => s.tags)])),
    [meta, skills],
  );
  const listed = skills.filter((s) =>
    filter === "all" ? true : filter === "mine" ? mine(s) : filter === "official" ? s.visibility === "official" : s.visibility === "private" && !mine(s));

  const dirty = isNew || !current || JSON.stringify(form) !== JSON.stringify(toInput(current));

  const toggleTool = (name: string) =>
    setForm((f) => ({ ...f, tools: f.tools.includes(name) ? f.tools.filter((t) => t !== name) : [...f.tools, name] }));

  const save = async () => {
    if (!form.name.trim()) return setErr("이름을 입력하세요");
    // 조회 단계에서 쓰는 tool 은 필수 tool 에 자동으로 넣는다 (agent 가 그 tool 을 쓸 수 있어야 실행된다)
    const stepTools = (form.steps ?? []).filter((x) => x.type === "data" && x.tool).map((x) => x.tool as string);
    const body: SkillInput = { ...form, tools: Array.from(new Set([...form.tools, ...stepTools])) };
    if (!body.tools.length) return setErr("tool을 1개 이상 선택하세요");
    setSaving(true);
    setErr(null);
    try {
      const saved = isNew ? await api.createSkill(body) : await api.updateSkill(selected!, body);
      await refreshSkills();
      toast(isNew && saved.visibility === "private" ? "내 스킬로 저장했습니다 — 나만 볼 수 있습니다" : "스킬을 저장했습니다");
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

  const copy = async () => {
    if (!current) return;
    const saved = await api.copySkill(current.id);
    await refreshSkills();
    toast("내 스킬로 복제했습니다 — 내 방식대로 고쳐서 쓰세요");
    navigate(`/skills/${saved.id}`);
  };

  const test = () => {
    if (!current) return;
    startChat({ text: `'${current.name}' 스킬을 실행해줘`, agentId: "auto", skillId: current.id });
  };

  const badge = (s: Skill) => s.visibility === "official"
    ? <span className="tag">공식</span>
    : mine(s) ? <span className="tag ok">내 스킬</span> : <span className="tag">{s.owner_name}</span>;

  return (
    <section className="center">
      <header className="c-head"><b>스킬</b></header>
      <div className="scroll">
        <div className="inner wide">
          <div className="page-head">
            <div>
              <h1>스킬</h1>
              <p>
                tool 과 작업 절차를 묶어 둔 업무입니다. 새로 만든 스킬은 <b>나만 보이는 내 스킬</b>이고, 공식 업무는 복제해서 내 방식대로 고칠 수 있습니다.
                {admin && " 관리자는 모든 사용자의 스킬을 보고 공식 업무로 지정할 수 있습니다."}
              </p>
            </div>
            <button className="btn primary" onClick={() => navigate("/skills/new")}><Plus size={15} />새 스킬</button>
          </div>

          <div className="split">
            <div className="panel" style={{ marginBottom: 0 }}>
              <div className="sk-filter seg">
                <button className={filter === "all" ? "on" : ""} onClick={() => setFilter("all")}>전체</button>
                <button className={filter === "mine" ? "on" : ""} onClick={() => setFilter("mine")}>내 스킬</button>
                <button className={filter === "official" ? "on" : ""} onClick={() => setFilter("official")}>공식</button>
                {admin && <button className={filter === "others" ? "on" : ""} onClick={() => setFilter("others")}>사용자</button>}
              </div>
              {isNew && <button className="sk-item on"><b>새 스킬</b><small>작성 중 · 내 스킬</small></button>}
              {listed.map((s) => (
                <button key={s.id} className={`sk-item ${s.id === selected ? "on" : ""}`} onClick={() => navigate(`/skills/${s.id}`)}>
                  <b>{s.name}</b>
                  <small className="sk-meta">
                    {badge(s)}
                    {!!s.steps?.length && <span className="tag lock">단계 {s.steps.length}</span>}
                    {s.tags.slice(0, 3).map((t) => <span key={t} className="sk-tag">{t}</span>)}
                    <span>· tool {s.tools.length}{s.uses ? ` · ${s.uses}회` : ""}</span>
                  </small>
                </button>
              ))}
              {!listed.length && !isNew && <div className="list-empty">스킬이 없습니다</div>}
            </div>

            {(isNew || current) && (
              <div className="panel" style={{ marginBottom: 0 }}>
                <div className="form">
                  {!canEdit && (
                    <div className="note" style={{ marginBottom: 16 }}>
                      <Info size={15} style={{ flexShrink: 0, marginTop: 2 }} />
                      <div>공식 업무는 관리자만 고칠 수 있습니다. <b>복제해서 내 스킬로</b> 만들면 내 방식대로 바꿔 쓸 수 있습니다.</div>
                    </div>
                  )}
                  <div className="field">
                    <label>이름{current && <span>{current.visibility === "official" ? "공식 업무" : mine(current) ? "내 스킬 · 나만 보임" : `${current.owner_name} 님의 스킬`}</span>}</label>
                    <input className="input" value={form.name} maxLength={60} disabled={!canEdit} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="예) Lot 이상 원인 1차 확인" />
                  </div>
                  <div className="field">
                    <label>설명<span>스킬 검색 · 자동 선택에 쓰입니다 — 언제 쓰는 업무인지</span></label>
                    <input className="input" value={form.description} disabled={!canEdit} onChange={(e) => setForm({ ...form, description: e.target.value })} />
                  </div>
                  <div className="field">
                    <label>태그<span>자유 입력 — 공정 · 장비 · 품질 같은 영역을 넣으면 대화 위 영역 탭에서 먼저 보입니다</span></label>
                    <TagInput value={form.tags} onChange={(tags) => setForm({ ...form, tags })} suggestions={tagSuggestions} disabled={!canEdit} />
                  </div>
                  {admin && (
                    <div className="field">
                      <label className="mcp-chk">
                        <input type="checkbox" checked={form.visibility === "official"}
                          onChange={(e) => setForm({ ...form, visibility: e.target.checked ? "official" : "private" })} />
                        공식 업무로 지정<span>모든 사용자에게 보입니다 (관리자 전용)</span>
                      </label>
                    </div>
                  )}

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
                                <input type="checkbox" checked={on} disabled={!canEdit} onChange={() => toggleTool(t.name)} />
                                <div><b>{t.label}</b><code>{t.name}</code><p title={t.description}>{t.description}</p></div>
                              </label>
                            );
                          })}
                        </div>
                      </div>
                    ))}
                  </div>

                  <div className="field">
                    <div className="label">단계<span>선택 — 정의하면 LLM 대신 단계 실행 엔진이 순서대로 실행합니다 (조회 · 반복 · 표는 코드, 판단만 LLM)</span></div>
                    <StepEditor steps={form.steps ?? []} inputs={form.inputs ?? []} tools={meta?.tools ?? []} disabled={!canEdit}
                      onChange={(p) => setForm((f) => ({ ...f, ...p }))} />
                  </div>

                  <div className="field">
                    <label>작업 지침<span>{(form.steps ?? []).length ? "단계형에서는 자유 양식 보고 단계가 '## 보고 양식' 을 참고합니다" : "LLM에게 전달되는 절차"}</span></label>
                    <textarea
                      className="textarea sk-instr"
                      // 내용 길이에 맞춰 늘어난다 (최소 18줄 · 최대 32줄, 그 이상은 칸 안에서 스크롤 · 아래 모서리로 직접 조절)
                      rows={Math.min(32, Math.max(18, form.instructions.split("\n").length + 2))}
                      value={form.instructions}
                      disabled={!canEdit}
                      onChange={(e) => setForm({ ...form, instructions: e.target.value })}
                      placeholder={"1. 먼저 ~를 조회한다.\n2. 결과가 ~이면 ~를 추가로 확인한다.\n3. 마지막에 ~를 표로 정리한다."}
                    />
                  </div>

                  <div className="note">
                    <Info size={15} style={{ flexShrink: 0, marginTop: 2 }} />
                    {(form.steps ?? []).length
                      ? <div><b>단계 {(form.steps ?? []).length}개</b>를 엔진이 순서대로 실행합니다. LLM 은 입력값 추출 · 판단 단계 · 자유 양식 보고에만 쓰여 빠르고, 표 · 수치는 매번 같습니다.</div>
                      : <div>이 스킬을 쓰는 동안 에이전트는 선택한 <b>tool {form.tools.length}개</b>만 볼 수 있습니다. 후보가 적을수록 tool을 잘못 고르는 일이 줄어듭니다.</div>}
                  </div>
                  {err && <div className="note err" style={{ marginTop: 10 }}>{err}</div>}
                </div>
                <div className="form-foot">
                  {current && canEdit && <button className="btn danger" onClick={remove}>삭제</button>}
                  <span className="sp" />
                  {current && <button className="btn" onClick={copy}><Copy size={14} />복제해서 내 스킬로</button>}
                  {current && <button className="btn" onClick={test} disabled={dirty}><Play size={14} />대화에서 실행</button>}
                  {canEdit && <button className="btn primary" onClick={save} disabled={saving || !dirty}>{saving ? "저장 중…" : "저장"}</button>}
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </section>
  );
}
