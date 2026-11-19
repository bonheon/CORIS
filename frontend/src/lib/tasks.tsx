// 작업 큐(task table) 공용 — 스케줄링 화면(일정별 진행 상태)과 작업 목록 화면이 같이 쓴다.
import React, { useCallback, useEffect, useRef, useState } from "react";
import { api, HubTask } from "../api";

export const TRIGGER: Record<HubTask["trigger"], string> = { schedule: "예약", manual: "지금 실행", retry: "다시 실행" };
export const isActive = (t: HubTask) => t.status === "queued" || t.status === "running";

export function TaskStatusPill({ t }: { t: HubTask }) {
  switch (t.status) {
    case "queued": return <span className="pill mute">대기{t.position ? ` ${t.position}번째` : ""}</span>;
    case "running": return <span className="pill warn"><span className="spin" />실행 중</span>;
    case "done": return <span className="pill ok">완료</span>;
    case "error": return <span className="pill err">실패</span>;
    default: return <span className="pill mute">취소</span>;
  }
}

/** 처리 중 · 대기 작업이 있으면 2.5초마다, 없으면 15초마다 다시 받는다. 새로 끝난 작업이 있으면 onFinish */
export function useTasks(onFinish?: () => void, limit = 100) {
  const [tasks, setTasks] = useState<HubTask[]>([]);
  const finished = useRef<Set<string> | null>(null);
  const load = useCallback(async () => {
    const list = await api.tasks({ limit });
    const ids = new Set(list.filter((t) => !isActive(t)).map((t) => t.id));
    if (finished.current && Array.from(ids).some((id) => !finished.current!.has(id))) onFinish?.();
    finished.current = ids;
    setTasks(list);
    return list;
  }, [onFinish, limit]);
  useEffect(() => {
    let timer: number | undefined;
    let alive = true;
    const tick = async () => {
      let busy = false;
      try { busy = (await load()).some(isActive); } catch { /* 다음 회차에 다시 */ }
      if (alive) timer = window.setTimeout(tick, busy ? 2500 : 15000);
    };
    tick();
    return () => { alive = false; window.clearTimeout(timer); };
  }, [load]);
  return [tasks, load] as const;
}

/** 대기 순서대로 — 실행 중이 맨 앞 */
export const queueOf = (tasks: HubTask[]) =>
  tasks.filter(isActive).sort((a, b) => (a.status === "running" ? -1 : b.status === "running" ? 1 : (a.position ?? 0) - (b.position ?? 0)));
