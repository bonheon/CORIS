import React, { ClipboardEvent, DragEvent, KeyboardEvent, useEffect, useLayoutEffect, useRef, useState } from "react";
import { ArrowUp, Blocks, ChevronDown, ImagePlus, Square, Wrench, X } from "lucide-react";
import { api, Attachment } from "../api";
import { useHub } from "../hub";
import ToolPicker from "./ToolPicker";

interface Props {
  onSend: (text: string, attachments?: Attachment[]) => void;
  onStop?: () => void;
  busy: boolean;
  agentId: string;
  skillId: string | null;
  onAgentChange: (id: string) => void;
  onSkillChange: (id: string | null) => void;
  /** 사용자가 고른 tool — 비어 있으면 자동(agent 기본 tool) */
  selectedTools: string[];
  onToolsChange: (tools: string[]) => void;
  placeholder?: string;
  autoFocus?: boolean;
}

// 첨부 중인 이미지 — 고르는 즉시 업로드하고, 끝나면 att 가 채워진다
interface PendingImage { key: string; name: string; preview: string; att?: Attachment; error?: string }

const IMAGE_ONLY_PROMPT = "첨부한 이미지를 해석해줘";

function readDataUrl(f: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(String(r.result));
    r.onerror = () => reject(r.error);
    r.readAsDataURL(f);
  });
}

/** 클립보드 캡처는 이름이 image.png 로 와서 구분이 안 된다 — 시각으로 이름을 붙인다 */
function imageName(f: File) {
  if (f.name && f.name !== "image.png") return f.name;
  const t = new Date();
  const p = (n: number) => String(n).padStart(2, "0");
  return `캡처-${p(t.getHours())}${p(t.getMinutes())}${p(t.getSeconds())}.${f.type.split("/")[1] || "png"}`;
}

// 입력 상태를 여기 가둬서 타이핑이 메시지 목록을 다시 그리지 않게 한다
function Composer({ onSend, onStop, busy, agentId, skillId, onAgentChange, onSkillChange, selectedTools, onToolsChange, placeholder, autoFocus }: Props) {
  const { meta, skills } = useHub();
  const [text, setText] = useState("");
  const [menu, setMenu] = useState<"agent" | "skill" | "tools" | null>(null);
  const [hl, setHl] = useState(0);
  const [images, setImages] = useState<PendingImage[]>([]);
  const [dragging, setDragging] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const ta = useRef<HTMLTextAreaElement>(null);
  const root = useRef<HTMLDivElement>(null);

  const agent = meta?.agents.find((a) => a.id === agentId);
  const skill = skills.find((s) => s.id === skillId);
  const toolSummary = selectedTools.length
    ? `${selectedTools.length + (skill?.tools.filter((t) => !selectedTools.includes(t)).length ?? 0)}개`
    : skill ? `스킬 ${skill.tools.length}개` : "자동";

  // "/" 로 시작하면 스킬 메뉴 — 입력한 글자로 필터
  const slash = text.startsWith("/") ? text.slice(1).toLowerCase() : null;
  const slashSkills = slash === null ? [] : skills.filter((s) => s.name.toLowerCase().includes(slash));
  const showSlash = slash !== null && slashSkills.length > 0;

  useLayoutEffect(() => {
    const el = ta.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  }, [text]);

  useEffect(() => {
    if (!menu) return;
    const close = (e: MouseEvent) => { if (!root.current?.contains(e.target as Node)) setMenu(null); };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [menu]);

  useEffect(() => { setHl(0); }, [slash]);

  const pickSkill = (id: string | null) => {
    onSkillChange(id);
    setMenu(null);
    if (slash !== null) setText("");
    ta.current?.focus();
  };

  // ── 이미지 첨부: 붙여넣기(Ctrl+V) · 끌어다 놓기 · 파일 선택 ──
  const addFiles = (files: File[]) => {
    files.filter((f) => f.type.startsWith("image/")).forEach(async (f) => {
      const key = `${Date.now()}-${Math.random()}`;
      const name = imageName(f);
      setImages((list) => [...list, { key, name, preview: URL.createObjectURL(f) }]);
      try {
        const att = await api.uploadImage({ name, mime: f.type, data: await readDataUrl(f) });
        setImages((list) => list.map((x) => (x.key === key ? { ...x, att } : x)));
      } catch (e: any) {
        setImages((list) => list.map((x) => (x.key === key ? { ...x, error: e.message ?? "업로드 실패" } : x)));
      }
    });
  };
  const removeImage = (key: string) =>
    setImages((list) => {
      list.filter((x) => x.key === key).forEach((x) => URL.revokeObjectURL(x.preview));
      return list.filter((x) => x.key !== key);
    });
  const onPaste = (e: ClipboardEvent<HTMLTextAreaElement>) => {
    const files = Array.from(e.clipboardData.files).filter((f) => f.type.startsWith("image/"));
    if (!files.length) return;  // 글자 붙여넣기는 그대로
    e.preventDefault();
    addFiles(files);
  };
  const onDrop = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setDragging(false);
    addFiles(Array.from(e.dataTransfer.files));
  };

  const uploading = images.some((x) => !x.att && !x.error);
  const ready = images.filter((x) => x.att).map((x) => x.att!);
  const canSend = !busy && !uploading && (!!text.trim() || ready.length > 0) && !text.trim().startsWith("/");

  const send = () => {
    if (!canSend) return;
    onSend(text.trim() || IMAGE_ONLY_PROMPT, ready);
    setText("");
    images.forEach((x) => URL.revokeObjectURL(x.preview));
    setImages([]);
  };

  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (showSlash) {
      if (e.key === "ArrowDown") { e.preventDefault(); setHl((h) => (h + 1) % slashSkills.length); return; }
      if (e.key === "ArrowUp") { e.preventDefault(); setHl((h) => (h - 1 + slashSkills.length) % slashSkills.length); return; }
      if (e.key === "Enter" || e.key === "Tab") { e.preventDefault(); pickSkill(slashSkills[hl].id); return; }
      if (e.key === "Escape") { setText(""); return; }
    }
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      send();
    }
  };

  return (
    <div className="composer" ref={root}>
      <div className={`box ${dragging ? "drop" : ""}`}
        onDragOver={(e) => { if (e.dataTransfer.types.includes("Files")) { e.preventDefault(); setDragging(true); } }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}>
        {showSlash && (
          <div className="menu">
            {slashSkills.map((s, i) => (
              <button key={s.id} className={i === hl ? "hl" : ""} onMouseDown={(e) => { e.preventDefault(); pickSkill(s.id); }}>
                <b>/{s.name}</b>
                <small>{s.description || `tool ${s.tools.length}개`}</small>
              </button>
            ))}
          </div>
        )}
        {images.length > 0 && (
          <div className="att-row">
            {images.map((x) => (
              <div key={x.key} className={`att ${x.error ? "err" : ""}`} title={x.error ?? x.name}>
                <img src={x.preview} alt={x.name} />
                {!x.att && !x.error && <span className="att-busy"><span className="spin" /></span>}
                {x.error && <span className="att-busy">!</span>}
                <button onClick={() => removeImage(x.key)} aria-label="첨부 삭제"><X size={11} /></button>
              </div>
            ))}
          </div>
        )}
        <textarea
          ref={ta}
          onPaste={onPaste}
          rows={1}
          value={text}
          autoFocus={autoFocus}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={onKey}
          placeholder={placeholder ?? "질문을 입력하세요.  / 로 스킬 · Ctrl+V 로 캡처 이미지 첨부"}
        />
        <div className="bar">
          <div style={{ position: "relative" }}>
            <button className="opt" onClick={() => setMenu(menu === "agent" ? null : "agent")}>
              에이전트 <b>{agent?.name ?? "자동 선택"}</b>
              <ChevronDown size={13} />
            </button>
            {menu === "agent" && (
              <div className="menu">
                {meta?.agents.map((a) => (
                  <button key={a.id} className={a.id === agentId ? "sel" : ""} onClick={() => { onAgentChange(a.id); setMenu(null); }}>
                    <b>{a.name}</b>
                    <small>{a.description}{a.id !== "auto" && ` · tool ${a.tools.length}`}</small>
                  </button>
                ))}
              </div>
            )}
          </div>
          <div style={{ position: "relative" }}>
            {skill ? (
              <span className="opt skill-on" role="button" onClick={() => onSkillChange(null)} title="스킬 해제">
                <Blocks size={14} />{skill.name}<X size={12} />
              </span>
            ) : (
              <button className="opt" onClick={() => setMenu(menu === "skill" ? null : "skill")}>
                <Blocks size={14} />스킬
              </button>
            )}
            {menu === "skill" && (
              <div className="menu">
                {skills.length === 0 && <button disabled><small>저장된 스킬이 없습니다</small></button>}
                {skills.map((s) => (
                  <button key={s.id} onClick={() => pickSkill(s.id)}>
                    <b>{s.name}</b>
                    <small>{s.description || `tool ${s.tools.length}개`}</small>
                  </button>
                ))}
              </div>
            )}
          </div>
          <div style={{ position: "relative" }}>
            <button className={`opt ${selectedTools.length ? "skill-on" : ""}`} onClick={() => setMenu(menu === "tools" ? null : "tools")}>
              <Wrench size={13} />Tool <b>{toolSummary}</b>
              <ChevronDown size={13} />
            </button>
            {menu === "tools" && (
              <div className="menu wide">
                <ToolPicker agentId={agentId} skillTools={skill?.tools ?? []} selected={selectedTools} onChange={onToolsChange} />
              </div>
            )}
          </div>
          <input ref={fileInput} type="file" accept="image/*" multiple hidden
            onChange={(e) => { addFiles(Array.from(e.target.files ?? [])); e.target.value = ""; }} />
          <button className="opt" onClick={() => fileInput.current?.click()} title="이미지 첨부 (Ctrl+V 로 캡처 붙여넣기 가능)">
            <ImagePlus size={14} />
          </button>
          {busy && onStop ? (
            <button className="send stop" onClick={onStop} aria-label="중지"><Square size={12} fill="currentColor" /></button>
          ) : (
            <button className="send" onClick={send} disabled={!canSend} aria-label="전송"><ArrowUp size={17} strokeWidth={2.2} /></button>
          )}
        </div>
      </div>
    </div>
  );
}

export default React.memo(Composer);
