// tool 그룹 메뉴 — MCP 서버와 상관없이 tool 을 태그(칩)처럼 골라 그룹을 만들고, 그룹마다 업무 영역 태그를 단다.
//   왼쪽: 내가 만든 그룹 + 다른 그룹(설정 파일 · MCP 서버, 읽기 전용)
//   오른쪽: 이름 · 설명 · 태그 · tool 카드(체크, 다른 그룹 소속 표시) · 기본으로 켜기 · 사용
// 저장하면 바로 반영된다 — 대화 위 영역 탭 · ⚙ tool 선택 · 스킬 편집에 그룹 이름으로 보인다.
import React, { useEffect, useMemo, useRef, useState } from "react";
import { Info, Plus } from "lucide-react";
import { api, ToolGroupInput, ToolGroupRec, ToolInfo } from "../api";
import { useHub } from "../hub";
import TagInput from "../components/TagInput";

const EMPTY: ToolGroupInput = { name: "", description: "", tags: [], tools: [], default_on: true, enabled: true };
const toInput = (g: ToolGroupRec): ToolGroupInput =>
  ({ name: g.name, description: g.description, tags: g.tags, tools: g.tools, default_on: g.default_on, enabled: g.enabled });

/** tool 카드 목록 — 서버별로 쭉 나열, 체크로 넣고 뺀다. 다른 그룹(그룹 메뉴)에 이미 들어간 tool 은 그 그룹 이름을 표시 */
function ToolCards({ value, onChange, tools, owners, disabled }: {
  value: string[]; onChange: (v: string[]) => void; tools: ToolInfo[];
  owners: Map<string, string[]>;   // tool → 이 tool 이 들어간 다른 그룹 이름들
  disabled?: boolean;
}) {
  const [q, setQ] = useState("");
  const [onlyFree, setOnlyFree] = useState(false);
  const query = q.trim().toLowerCase();
  const visible = tools.filter((t) =>
    (!query || [t.name, t.label, t.description, t.server ?? ""].some((x) => x.toLowerCase().includes(query)))
    && (!onlyFree || value.includes(t.name) || !owners.get(t.name)?.length));
  const byServer = new Map<string, ToolInfo[]>();
  visible.forEach((t) => { const k = t.server ?? "사용 불가"; byServer.set(k, [...(byServer.get(k) ?? []), t]); });
  const toggle = (n: string) => onChange(value.includes(n) ? value.filter((x) => x !== n) : [...value, n]);

  return (
    <div>
      {!disabled && (
        <div className="tg-bar">
          <input className="input" value={q} onChange={(e) => setQ(e.target.value)} placeholder="tool 이름 · 설명 · 서버로 찾기" />
          <label className="mcp-chk" style={{ margin: 0 }}>
            <input type="checkbox" checked={onlyFree} onChange={(e) => setOnlyFree(e.target.checked)} />다른 그룹에 없는 것만
          </label>
        </div>
      )}
      {Array.from(byServer.entries()).map(([server, list]) => (
        <div key={server} className="tool-group">
          <h4>{server} <span className="muted">· {list.filter((t) => value.includes(t.name)).length}/{list.length}</span></h4>
          <div className="tools">
            {list.map((t) => {
              const on = value.includes(t.name);
              const other = owners.get(t.name) ?? [];
              return (
                <label key={t.name} className={`tool ${on ? "sel" : ""} ${disabled ? "ro" : ""}`}>
                  <input type="checkbox" checked={on} disabled={disabled} onChange={() => toggle(t.name)} />
                  <div>
                    <b>{t.label}</b><code>{t.name}</code>
                    {t.description && <p title={t.description}>{t.description}</p>}
                    {other.length > 0 && <span className="tag lock tg-owner" title={`이미 들어간 그룹: ${other.join(", ")}`}>다른 그룹: {other.join(", ")}</span>}
                  </div>
                </label>
              );
            })}
          </div>
        </div>
      ))}
      {!visible.length && <div className="list-empty">맞는 tool 이 없습니다</div>}
    </div>
  );
}

export default function ToolGroupsPage({ selected, navigate }: { selected?: string; navigate: (p: string, replace?: boolean) => void }) {
  const { meta, refreshMeta, toast } = useHub();
  const [items, setItems] = useState<ToolGroupRec[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [form, setForm] = useState<ToolGroupInput>(EMPTY);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const formFor = useRef<string | undefined>(undefined);

  const load = async () => { setItems(await api.toolGroups()); setLoaded(true); };
  useEffect(() => { load().catch(() => setLoaded(true)); }, []);

  const isNew = selected === "new";
  const current = items.find((g) => g.id === selected);
  const others = (meta?.groups ?? []).filter((g) => !g.custom);
  const readonly = !isNew && !current ? others.find((g) => g.id === selected) : undefined;

  useEffect(() => {
    if (!selected && loaded) navigate(`/groups/${items[0]?.id ?? "new"}`, true);
  }, [selected, loaded, items, navigate]);

  useEffect(() => {
    const key = `${selected}@${current?.updated_at ?? ""}`;
    if (formFor.current === key) return;
    formFor.current = key;
    setErr(null);
    setForm(isNew ? EMPTY : current ? toInput(current) : readonly
      ? { name: readonly.name, description: readonly.description, tags: readonly.tags ?? [], tools: readonly.tools, default_on: !!readonly.default_on, enabled: true }
      : EMPTY);
  }, [selected, isNew, current, readonly]);

  const tools = useMemo(() => (meta?.tools ?? []).filter((t) => t.available || form.tools.includes(t.name)), [meta, form.tools]);
  const tagSuggestions = useMemo(
    () => Array.from(new Set([...(meta?.areas ?? []), "공통", ...(meta?.groups ?? []).flatMap((g) => g.tags ?? [])])),
    [meta],
  );
  // tool → 이 tool 이 들어간 '다른' 그룹 이름 (그룹 메뉴에서 만든 그룹 기준, 지금 보는 그룹은 제외)
  const owners = useMemo(() => {
    const m = new Map<string, string[]>();
    items.filter((g) => g.id !== selected).forEach((g) => g.tools.forEach((n) => m.set(n, [...(m.get(n) ?? []), g.name])));
    return m;
  }, [items, selected]);
  const dirty = isNew || (!!current && JSON.stringify(form) !== JSON.stringify(toInput(current)));
  const editable = isNew || !!current;

  const save = async () => {
    if (!form.name.trim()) return setErr("이름을 입력하세요");
    if (!form.tools.length) return setErr("tool 을 1개 이상 넣으세요");
    setSaving(true);
    setErr(null);
    try {
      const saved = isNew ? await api.createToolGroup(form) : await api.updateToolGroup(selected!, form);
      await Promise.all([load(), refreshMeta()]);
      toast("tool 그룹을 저장했습니다 — 바로 반영됩니다");
      if (isNew) navigate(`/groups/${saved.id}`, true);
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setSaving(false);
    }
  };

  const remove = async () => {
    if (!current || !window.confirm(`'${current.name}' 그룹을 삭제할까요? (tool 은 그대로 남습니다)`)) return;
    await api.deleteToolGroup(current.id);
    await Promise.all([load(), refreshMeta()]);
    toast("tool 그룹을 삭제했습니다");
    navigate("/groups", true);
  };

  const groupTags = (tags: string[] | undefined) => (tags ?? []).slice(0, 4).map((t) => <span key={t} className="sk-tag">{t}</span>);

  return (
    <section className="center">
      <header className="c-head"><b>tool 그룹</b></header>
      <div className="scroll">
        <div className="inner wide">
          <div className="page-head">
            <div>
              <h1>tool 그룹</h1>
              <p>MCP 서버와 상관없이 tool 을 골라 그룹을 만들고, 그룹마다 업무 영역 태그를 답니다. 태그가 맞는 영역 탭에서 그룹이 켜집니다.</p>
            </div>
            <button className="btn primary" onClick={() => navigate("/groups/new")}><Plus size={15} />새 그룹</button>
          </div>

          <div className="split">
            <div className="panel" style={{ marginBottom: 0 }}>
              <div className="tg-sec">내가 만든 그룹 <span>{items.length}</span></div>
              {isNew && <button className="sk-item on"><b>새 그룹</b><small>작성 중</small></button>}
              {items.map((g) => (
                <button key={g.id} className={`sk-item ${g.id === selected ? "on" : ""}`} onClick={() => navigate(`/groups/${g.id}`)}>
                  <b>{g.name}{!g.enabled && <span className="tag" style={{ marginLeft: 6 }}>꺼짐</span>}</b>
                  <small className="sk-meta">{groupTags(g.tags)}<span>· tool {g.tools.length}{g.default_on ? " · 기본 켜짐" : ""}</span></small>
                </button>
              ))}
              {loaded && !items.length && !isNew && <div className="list-empty">아직 만든 그룹이 없습니다</div>}

              <div className="tg-sec">다른 그룹 <span>읽기 전용</span></div>
              {others.map((g) => (
                <button key={g.id} className={`sk-item ${g.id === selected ? "on" : ""}`} onClick={() => navigate(`/groups/${g.id}`)}>
                  <b>{g.name}</b>
                  <small className="sk-meta">
                    <span className="tag">{g.imported ? "MCP 서버" : "설정 파일"}</span>
                    {groupTags(g.tags)}<span>· tool {g.tools.length}</span>
                  </small>
                </button>
              ))}
            </div>

            {(editable || readonly) && (
              <div className="panel" style={{ marginBottom: 0 }}>
                <div className="form">
                  {readonly && (
                    <div className="note" style={{ marginBottom: 16 }}>
                      <Info size={15} style={{ flexShrink: 0, marginTop: 2 }} />
                      <div>{readonly.imported
                        ? <>MCP 서버 화면에서 만든 그룹입니다. <b>MCP 서버</b> 메뉴에서 고칠 수 있습니다.</>
                        : <>설정 파일(<code className="mono">catalog.yaml</code>)의 그룹입니다. 같은 tool 로 새 그룹을 만들어 태그를 다르게 달 수 있습니다.</>}
                      </div>
                    </div>
                  )}
                  <div className="field">
                    <label>이름</label>
                    <input className="input" value={form.name} maxLength={40} disabled={!editable} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="예) 설비 점검" />
                  </div>
                  <div className="field">
                    <label>설명<span>tool 선택 화면에 보입니다</span></label>
                    <input className="input" value={form.description} maxLength={200} disabled={!editable} onChange={(e) => setForm({ ...form, description: e.target.value })} />
                  </div>
                  <div className="field">
                    <label>태그<span>업무 영역({(meta?.areas ?? []).join(" · ")}) 을 넣으면 그 영역 탭에서 켜집니다 · '공통' 은 모든 탭</span></label>
                    <TagInput value={form.tags} onChange={(tags) => setForm({ ...form, tags })} suggestions={tagSuggestions} disabled={!editable}
                      placeholder="예) 장비, 공정 — Enter 로 추가" />
                  </div>
                  <div className="field">
                    <div className="label">tool<span>{form.tools.length}개 선택 · 여러 서버의 tool 을 섞어 넣을 수 있습니다</span></div>
                    <ToolCards value={form.tools} onChange={(t) => setForm({ ...form, tools: t })} tools={tools} owners={owners} disabled={!editable} />
                  </div>
                  {editable && (
                    <div className="field">
                      <label className="mcp-chk">
                        <input type="checkbox" checked={form.default_on} onChange={(e) => setForm({ ...form, default_on: e.target.checked })} />
                        기본으로 켜기<span>켜면 질문마다 LLM 이 이 그룹 tool 을 봅니다. tool 이 많으면 끄고 스킬 · 영역 탭으로 쓰세요</span>
                      </label>
                      <label className="mcp-chk">
                        <input type="checkbox" checked={form.enabled} onChange={(e) => setForm({ ...form, enabled: e.target.checked })} />
                        사용<span>끄면 저장은 남기고 대화 · 스킬 화면에서 숨깁니다</span>
                      </label>
                    </div>
                  )}
                  {err && <div className="note err" style={{ marginTop: 10 }}>{err}</div>}
                </div>
                {editable && (
                  <div className="form-foot">
                    {current && <button className="btn danger" onClick={remove}>삭제</button>}
                    <span className="sp" />
                    <button className="btn primary" onClick={save} disabled={saving || !dirty}>{saving ? "저장 중…" : "저장"}</button>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      </div>
    </section>
  );
}
