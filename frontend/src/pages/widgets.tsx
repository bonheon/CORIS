// 홈 대시보드와 정보 패널이 함께 쓰는 작은 목록들
import React from "react";
import { HubEvent } from "../api";
import { useHub } from "../hub";
import { fmtTime } from "../lib/hooks";

export function StatusRows() {
  const { meta } = useHub();
  return (
    <>
      {meta?.portals.map((p) => (
        <div key={p.id} className="row">
          <span className={`dot ${p.status}`} />
          <span className="nm">{p.name}</span>
          <span className={`rt ${p.status === "warn" ? "w" : p.status === "err" ? "e" : ""}`}>{p.note}</span>
        </div>
      ))}
    </>
  );
}

const isToday = (iso: string | null | undefined) => !!iso && new Date(iso).toDateString() === new Date().toDateString();

const within24h = (iso: string | null | undefined) =>
  !!iso && new Date(iso).getTime() - Date.now() < 24 * 3600 * 1000;

/** 오늘 실행됐거나 24시간 안에 실행될 이벤트 — 시각순 */
export function todayEvents(events: HubEvent[]) {
  return events
    .filter((e) => isToday(e.last_run?.at) || within24h(e.next_run))
    .sort((a, b) => a.schedule.time.localeCompare(b.schedule.time));
}

export function EventStatus({ e }: { e: HubEvent }) {
  if (isToday(e.last_run?.at)) {
    return e.last_run!.status === "ok"
      ? <span className="pill ok">완료 {fmtTime(e.last_run!.at)}</span>
      : <span className="pill err">실패</span>;
  }
  if (e.last_run?.status === "error") return <span className="pill err">최근 실패</span>;
  if (e.next_run && !isToday(e.next_run)) return <span className="pill mute">내일</span>;
  return <span className="pill mute">대기</span>;
}

export function TodayEvents({ onOpen }: { onOpen?: (e: HubEvent) => void }) {
  const { events } = useHub();
  const list = todayEvents(events);
  if (!list.length) return <div className="muted" style={{ fontSize: 12.5, padding: "4px 0" }}>24시간 안에 예정된 이벤터가 없습니다</div>;
  return (
    <>
      {list.map((e) => (
        <div key={e.id} className="row" style={onOpen ? { cursor: "pointer" } : undefined} onClick={() => onOpen?.(e)}>
          <span className="when num">{e.schedule.time}</span>
          <span className="ell">{e.name}</span>
          <span className="rt"><EventStatus e={e} /></span>
        </div>
      ))}
    </>
  );
}

export function SkillRows({ onOpen }: { onOpen?: (id: string) => void }) {
  const { skills } = useHub();
  if (!skills.length) return <div className="muted" style={{ fontSize: 12.5, padding: "4px 0" }}>저장된 스킬이 없습니다</div>;
  return (
    <>
      {skills.slice(0, 5).map((s) => (
        <div key={s.id} className="row" style={onOpen ? { cursor: "pointer" } : undefined} onClick={() => onOpen?.(s.id)}>
          <span className="nm ell">{s.name}</span>
          <span className="rt">tool {s.tools.length}{s.uses ? ` · ${s.uses}회` : ""}</span>
        </div>
      ))}
    </>
  );
}
