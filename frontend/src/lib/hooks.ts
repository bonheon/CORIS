import { useCallback, useEffect, useState } from "react";

// ── 해시 라우팅 — 라우터 의존성 없이 #/c/:id 형태 ──────────────
export type Route =
  | { page: "home" }
  | { page: "new" }
  | { page: "chat"; id: string }
  | { page: "skills"; id?: string }
  | { page: "events" }
  | { page: "portals" }
  | { page: "mcp"; id?: string }
  | { page: "me" };

function parse(hash: string): Route {
  const [, a, b] = hash.replace(/^#/, "").split("/");
  if (a === "new") return { page: "new" };
  if (a === "c" && b) return { page: "chat", id: b };
  if (a === "skills") return { page: "skills", id: b };
  if (a === "events") return { page: "events" };
  if (a === "portals") return { page: "portals" };
  if (a === "mcp") return { page: "mcp", id: b };
  if (a === "me") return { page: "me" };
  return { page: "home" };
}

export function useRoute(): [Route, (path: string, replace?: boolean) => void] {
  const [route, setRoute] = useState<Route>(() => parse(window.location.hash));
  useEffect(() => {
    const on = () => setRoute(parse(window.location.hash));
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  const navigate = useCallback((path: string, replace = false) => {
    const hash = `#${path}`;
    if (replace) {
      window.history.replaceState(null, "", hash);
      setRoute(parse(hash));
    } else {
      window.location.hash = path;
    }
  }, []);
  return [route, navigate];
}

// ── 테마 ────────────────────────────────────────────────────────
type Theme = "light" | "dark";
const KEY = "hub-theme";

function initialTheme(): Theme {
  try {
    const saved = localStorage.getItem(KEY);
    if (saved === "light" || saved === "dark") return saved;
  } catch {}
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export function useTheme(): [Theme, () => void] {
  const [theme, setTheme] = useState<Theme>(initialTheme);
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
  }, [theme]);
  const toggle = useCallback(() => {
    setTheme((t) => {
      const next = t === "dark" ? "light" : "dark";
      try { localStorage.setItem(KEY, next); } catch {}
      return next;
    });
  }, []);
  return [theme, toggle];
}

// ── 카드 데이터 — 화면 전용 MCP tool 을 GET /api/ui/{tool} 로 ──────────
export function useUiData<T>(tool: string, args: Record<string, string | number>) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const qs = new URLSearchParams(Object.entries(args).map(([k, v]) => [k, String(v)])).toString();
  useEffect(() => {
    let alive = true;
    setData(null);
    setError(null);
    fetch(`/api/ui/${tool}?${qs}`)
      .then(async (r) => {
        const body = await r.json();
        if (!r.ok) throw new Error(body.detail ?? r.statusText);
        return body as T;
      })
      .then((d) => alive && setData(d), (e) => alive && setError(String(e.message ?? e)));
    return () => { alive = false; };
  }, [tool, qs]);
  return { data, error };
}

// ── 시간 표시 ───────────────────────────────────────────────────
export function fmtTime(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit", hour12: false });
}

export function dayLabel(iso: string): string {
  const d = new Date(iso);
  const today = new Date();
  const diff = Math.round((new Date(today.toDateString()).getTime() - new Date(d.toDateString()).getTime()) / 86400000);
  if (diff === 0) return "오늘";
  if (diff === 1) return "어제";
  if (diff === -1) return "내일";
  if (diff > 1 && diff < 7) return `${diff}일 전`;
  return d.toLocaleDateString("ko-KR", { month: "long", day: "numeric" });
}

export function fmtShort(iso: string): string {
  const label = dayLabel(iso);
  return label === "오늘" ? fmtTime(iso) : `${label} ${fmtTime(iso)}`;
}

export const WEEKDAYS = ["월", "화", "수", "목", "금", "토", "일"];
