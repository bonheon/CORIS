import React, { useCallback, useEffect, useMemo, useState } from "react";
import { Blocks, Info, Plus, RotateCw, Trash2 } from "lucide-react";
import { api, McpServerConf, McpToolSpec } from "../api";
import { useHub } from "../hub";
import { skillDraft } from "../lib/draft";

// MCP 서버 — 회사 MCP 주소 등록 → tool 목록 불러오기 → 가져올 tool 선택 → 저장 → 스킬 만들기.
// 저장하면 서버 하나가 tool group 하나가 되어 대화 · 스킬 화면에 바로 나타난다.

interface Form {
  id: string; name: string; description: string; url: string; transport: string;
  headers: { k: string; v: string }[];
  enabled: boolean; tools: string[]; labels: Record<string, string>; default_on: boolean;
}

const EMPTY: Form = {
  id: "", name: "", description: "", url: "", transport: "streamable_http",
  headers: [{ k: "Authorization", v: "" }], enabled: true, tools: [], labels: {}, default_on: true,
};

const toForm = (s: McpServerConf): Form => ({
  id: s.id, name: s.name, description: s.description, url: s.url, transport: s.transport || "streamable_http",
  headers: Object.entries(s.headers).map(([k, v]) => ({ k, v })),
  enabled: s.enabled, tools: s.tools, labels: s.labels, default_on: s.default_on,
});

const headerMap = (rows: Form["headers"]) =>
  Object.fromEntries(rows.filter((r) => r.k.trim()).map((r) => [r.k.trim(), r.v]));

const firstLine = (s: string) => s.split("\n").find((l) => l.trim())?.trim() ?? "";

export default function McpPage({ selected, navigate }: { selected?: string; navigate: (p: string, replace?: boolean) => void }) {
  const { refreshMeta, toast } = useHub();
  const [servers, setServers] = useState<McpServerConf[]>([]);
  const [form, setForm] = useState<Form>(EMPTY);
  const [specs, setSpecs] = useState<McpToolSpec[] | null>(null);
  const [probing, setProbing] = useState(false);
  const [probeErr, setProbeErr] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const isNew = selected === "new";
  const current = servers.find((s) => s.id === selected);
  const readOnly = current?.source === "yaml";

  const load = useCallback(async () => setServers(await api.mcpServers()), []);
  useEffect(() => { load().catch(() => {}); }, [load]);

  useEffect(() => {
    if (!selected && servers.length) navigate(`/mcp/${(servers.find((s) => s.source === "hub") ?? servers[0]).id}`, true);
  }, [selected, servers, navigate]);

  const probe = useCallback(async (f: Form, serverId?: string, yaml = false) => {
    if (!f.url.trim()) return setProbeErr("URL 을 입력하세요");
    setProbing(true);
    setProbeErr(null);
    try {
      setSpecs(yaml
        ? await api.mcpServerTools(serverId!)
        : await api.mcpProbe({ url: f.url.trim(), transport: f.transport, headers: headerMap(f.headers), server_id: serverId }));
    } catch (e: any) {
      setSpecs(null);
      setProbeErr(e.message);
    } finally {
      setProbing(false);
    }
  }, []);

  // 선택이 바뀌면 폼을 채우고, 등록된 서버면 현재 tool 목록을 바로 불러온다
  useEffect(() => {
    setErr(null);
    setProbeErr(null);
    setSpecs(null);
    if (isNew) {
      setForm(EMPTY);
    } else if (current) {
      const f = toForm(current);
      setForm(f);
      probe(f, current.id, current.source === "yaml");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected, current?.id]);

  const set = (p: Partial<Form>) => setForm((f) => ({ ...f, ...p }));
  const pickable = useMemo(() => (specs ?? []).filter((t) => !t.ui), [specs]);
  const offered = useMemo(() => new Set((specs ?? []).map((t) => t.name)), [specs]);
  const missing = specs ? form.tools.filter((t) => !offered.has(t)) : [];

  const toggle = (name: string) =>
    set({ tools: form.tools.includes(name) ? form.tools.filter((t) => t !== name) : [...form.tools, name] });
  const all = (on: boolean) => set({ tools: on ? pickable.map((t) => t.name) : [] });

  const dirty = isNew || !current || JSON.stringify(form) !== JSON.stringify(toForm(current));

  const save = async () => {
    if (isNew && !form.id.trim()) return setErr("ID 를 입력하세요");
    if (!form.name.trim()) return setErr("이름을 입력하세요");
    if (form.enabled && !form.tools.length) return setErr("가져올 tool 을 1개 이상 선택하세요");
    setSaving(true);
    setErr(null);
    const body = {
      name: form.name.trim(), description: form.description, url: form.url.trim(), transport: form.transport,
      headers: headerMap(form.headers), enabled: form.enabled, tools: form.tools,
      labels: Object.fromEntries(Object.entries(form.labels).filter(([k, v]) => form.tools.includes(k) && v.trim())),
      default_on: form.default_on,
    };
    try {
      const saved = isNew ? await api.createMcpServer({ id: form.id.trim(), ...body }) : await api.updateMcpServer(form.id, body);
      await Promise.all([load(), refreshMeta()]);
      toast(`'${saved.name}' 저장 · tool ${saved.tools.length}개 반영`);
      if (isNew) navigate(`/mcp/${saved.id}`, true);
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setSaving(false);
    }
  };

  const remove = async () => {
    if (!current || !window.confirm(`'${current.name}' 서버를 삭제할까요? 이 서버의 tool 을 쓰는 스킬은 해당 tool 이 '사용 불가' 가 됩니다.`)) return;
    await api.deleteMcpServer(current.id);
    await Promise.all([load(), refreshMeta()]);
    toast("MCP 서버를 삭제했습니다");
    navigate("/mcp", true);
  };

  const makeSkill = () => {
    skillDraft.tools = [...form.tools];
    navigate("/skills/new");
  };

  return (
    <section className="center">
      <header className="c-head"><b>MCP 서버</b></header>
      <div className="scroll">
        <div className="inner wide">
          <div className="page-head">
            <div>
              <h1>MCP 서버</h1>
              <p>운영 중인 MCP 서버 주소를 등록하고, 서버의 tool 중 Coris 에서 쓸 것만 골라 가져옵니다. 가져온 tool 로 스킬을 만들 수 있습니다.</p>
            </div>
            <button className="btn primary" onClick={() => navigate("/mcp/new")}><Plus size={15} />서버 등록</button>
          </div>

          <div className="split">
            <div className="panel" style={{ marginBottom: 0 }}>
              {isNew && <button className="sk-item on"><b>새 서버</b><small>작성 중</small></button>}
              {servers.map((s) => {
                const st = s.status;
                return (
                  <button key={s.id} className={`sk-item ${s.id === selected ? "on" : ""}`} onClick={() => navigate(`/mcp/${s.id}`)}>
                    <b style={{ display: "flex", alignItems: "center", gap: 7 }}>
                      <span className={`dot ${!s.enabled ? "mute" : st?.status === "ok" ? "ok" : "err"}`} />
                      {s.name}
                      {s.source === "yaml" && <span className="pill mute" style={{ marginLeft: "auto" }}>yaml</span>}
                    </b>
                    <small>
                      {!s.enabled ? "꺼짐" : st?.status !== "ok" ? "응답 없음" : s.source === "hub" ? `tool ${s.tools.length}개 사용 · 서버 ${st.offered}개` : `tool ${st.tools.length}개`}
                    </small>
                  </button>
                );
              })}
              {!servers.length && !isNew && <div className="list-empty">등록된 서버가 없습니다</div>}
            </div>

            {(isNew || current) && (
              <div className="panel" style={{ marginBottom: 0 }}>
                <div className="form">
                  {readOnly && (
                    <div className="note" style={{ marginBottom: 18 }}>
                      <Info size={15} style={{ flexShrink: 0, marginTop: 2 }} />
                      <div>배포 설정(<code className="mono">backend/mcp_servers.yaml</code>)에 있는 서버입니다. 화면에서는 조회만 할 수 있습니다.</div>
                    </div>
                  )}

                  <div className="mcp-grid">
                    <div className="field">
                      <label>ID<span>{isNew ? "영문 소문자 · 숫자 · _ (변경 불가)" : ""}</span></label>
                      <input className="input mono" value={form.id} disabled={!isNew} placeholder="예) quality_mcp"
                        onChange={(e) => set({ id: e.target.value.toLowerCase() })} />
                    </div>
                    <div className="field">
                      <label>이름<span>tool 그룹 이름으로 보입니다</span></label>
                      <input className="input" value={form.name} disabled={readOnly} maxLength={40} placeholder="예) 품질 데이터"
                        onChange={(e) => set({ name: e.target.value })} />
                    </div>
                  </div>

                  <div className="field">
                    <label>URL</label>
                    <div style={{ display: "flex", gap: 8 }}>
                      <select className="select" style={{ width: 160 }} value={form.transport} disabled={readOnly}
                        onChange={(e) => set({ transport: e.target.value })}>
                        <option value="streamable_http">streamable_http</option>
                        <option value="sse">sse</option>
                      </select>
                      <input className="input mono" value={form.url} disabled={readOnly} placeholder="https://mcp.company.com/xxx/mcp"
                        onChange={(e) => set({ url: e.target.value })} />
                    </div>
                  </div>

                  <div className="field">
                    <div className="label">헤더<span>인증 토큰 등 — 저장 후에는 가려집니다. ${"{ENV_VAR}"} 로 쓰면 .env 값을 씁니다</span></div>
                    {form.headers.map((h, i) => (
                      <div key={i} className="mcp-hdr">
                        <input className="input mono" value={h.k} disabled={readOnly} placeholder="Header"
                          onChange={(e) => set({ headers: form.headers.map((r, j) => (j === i ? { ...r, k: e.target.value } : r)) })} />
                        <input className="input mono" value={h.v} disabled={readOnly} placeholder="Bearer …"
                          onChange={(e) => set({ headers: form.headers.map((r, j) => (j === i ? { ...r, v: e.target.value } : r)) })} />
                        {!readOnly && (
                          <button className="ghost" title="삭제" onClick={() => set({ headers: form.headers.filter((_, j) => j !== i) })}><Trash2 size={12} /></button>
                        )}
                      </div>
                    ))}
                    {!readOnly && (
                      <button className="ghost" onClick={() => set({ headers: [...form.headers, { k: "", v: "" }] })}><Plus size={12} />헤더 추가</button>
                    )}
                  </div>

                  <div className="field">
                    <div className="label" style={{ display: "flex", alignItems: "center", gap: 8 }}>
                      tool
                      <span>{specs ? `${form.tools.length} / ${pickable.length} 선택` : "목록을 불러오세요"}</span>
                      <span style={{ marginLeft: "auto", display: "flex", gap: 6 }}>
                        {specs && !readOnly && <>
                          <button className="ghost" onClick={() => all(true)}>전체 선택</button>
                          <button className="ghost" onClick={() => all(false)}>전체 해제</button>
                        </>}
                        <button className="btn sm" disabled={probing}
                          onClick={() => probe(form, isNew ? undefined : form.id, readOnly)}>
                          <RotateCw size={12} className={probing ? "spinning" : ""} />{specs ? "다시 불러오기" : "tool 목록 불러오기"}
                        </button>
                      </span>
                    </div>
                    {probeErr && <div className="note err">{probeErr}</div>}
                    {missing.length > 0 && (
                      <div className="note err" style={{ marginBottom: 8 }}>서버에 없는 tool 이 선택되어 있습니다 (사용 불가): {missing.join(", ")}</div>
                    )}
                    {specs && specs.length === 0 && <div className="muted" style={{ fontSize: 12.5 }}>서버가 제공하는 tool 이 없습니다</div>}
                    <div className="tools mcp-tools">
                      {(specs ?? []).map((t) => {
                        const on = form.tools.includes(t.name) || (readOnly && (!form.tools.length || form.tools.includes(t.name)));
                        return (
                          <label key={t.name} className={`tool ${on && !t.ui ? "sel" : ""} ${t.ui ? "off" : ""}`}>
                            <input type="checkbox" checked={on && !t.ui} disabled={readOnly || t.ui} onChange={() => toggle(t.name)} />
                            <div style={{ minWidth: 0, flex: 1 }}>
                              <b>{form.labels[t.name] || t.name}{t.ui && <span className="pill mute" style={{ marginLeft: 6 }}>화면 전용</span>}</b>
                              <code>{t.name}</code>
                              <p title={t.description}>{firstLine(t.description) || "설명 없음"}</p>
                              {t.params.length > 0 && (
                                <div className="tools-mini">
                                  {t.params.map((p) => <span key={p.name} title={p.description}>{p.name}{p.required ? "*" : ""}: {p.type}</span>)}
                                </div>
                              )}
                              {on && !t.ui && !readOnly && (
                                <input className="input mcp-label" value={form.labels[t.name] ?? ""} placeholder="화면 표시명 (선택)"
                                  onClick={(e) => e.preventDefault()}
                                  onChange={(e) => set({ labels: { ...form.labels, [t.name]: e.target.value } })} />
                              )}
                            </div>
                          </label>
                        );
                      })}
                    </div>
                  </div>

                  {!readOnly && (
                    <div className="field">
                      <label className="mcp-chk">
                        <input type="checkbox" checked={form.default_on} onChange={(e) => set({ default_on: e.target.checked })} />
                        기본으로 켜기<span>끄면 스킬이나 tool 직접 선택으로만 쓰입니다 (tool 이 많을 때 권장)</span>
                      </label>
                      <label className="mcp-chk">
                        <input type="checkbox" checked={form.enabled} onChange={(e) => set({ enabled: e.target.checked })} />
                        사용<span>끄면 이 서버의 tool 을 가져오지 않습니다</span>
                      </label>
                    </div>
                  )}
                  {err && <div className="note err">{err}</div>}
                </div>

                {!readOnly && (
                  <div className="form-foot">
                    {current && <button className="btn danger" onClick={remove}>삭제</button>}
                    <span className="sp" />
                    {current && (
                      <button className="btn" onClick={makeSkill} disabled={dirty || !form.tools.length}>
                        <Blocks size={14} />선택한 tool 로 스킬 만들기
                      </button>
                    )}
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
