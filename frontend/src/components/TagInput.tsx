import React, { KeyboardEvent, useId, useState } from "react";
import { X } from "lucide-react";

/** 태그 자유 입력 — Enter · 쉼표로 추가, × 로 삭제. suggestions 는 추천 목록 (스킬 · tool 그룹 태그) */
export default function TagInput({ value, onChange, suggestions, disabled, placeholder }: {
  value: string[]; onChange: (v: string[]) => void; suggestions: string[]; disabled?: boolean; placeholder?: string;
}) {
  const [text, setText] = useState("");
  const listId = useId();
  const add = (raw: string) => {
    const t = raw.trim().replace(/,$/, "").trim();
    if (t && !value.includes(t)) onChange([...value, t]);
    setText("");
  };
  const onKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if ((e.key === "Enter" || e.key === ",") && !e.nativeEvent.isComposing) { e.preventDefault(); add(text); }
    if (e.key === "Backspace" && !text && value.length) onChange(value.slice(0, -1));
  };
  return (
    <div className={`tag-input ${disabled ? "off" : ""}`}>
      {value.map((t) => (
        <span key={t} className="tag ok">{t}{!disabled && <button onClick={() => onChange(value.filter((x) => x !== t))} aria-label={`${t} 삭제`}><X size={10} /></button>}</span>
      ))}
      {!disabled && (
        <>
          <input value={text} list={listId} onChange={(e) => setText(e.target.value)} onKeyDown={onKey}
            onBlur={() => text.trim() && add(text)} placeholder={value.length ? "" : placeholder ?? "예) 공정, Lot 기준 — Enter 로 추가"} />
          <datalist id={listId}>{suggestions.filter((s) => !value.includes(s)).map((s) => <option key={s} value={s} />)}</datalist>
        </>
      )}
    </div>
  );
}
