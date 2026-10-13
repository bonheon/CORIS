import React from "react";
import { House, MessageSquare, Blocks, CalendarClock, LayoutGrid, Moon, Sun, Plug } from "lucide-react";
import { Route } from "../lib/hooks";
import { useHub } from "../hub";

interface Props {
  route: Route;
  navigate: (p: string) => void;
  theme: "light" | "dark";
  onToggleTheme: () => void;
}

export default function Rail({ route, navigate, theme, onToggleTheme }: Props) {
  const { events, me, meta } = useHub();
  const failed = events.some((e) => e.enabled && e.last_run?.status === "error");
  const mcpDown = meta?.mcp_servers.some((s) => s.status !== "ok") ?? false;

  const items = [
    { key: "home", path: "/", label: "홈", icon: House, on: route.page === "home" },
    { key: "chat", path: "/new", label: "대화", icon: MessageSquare, on: route.page === "chat" || route.page === "new" },
    { key: "mcp", path: "/mcp", label: "MCP 서버", icon: Plug, on: route.page === "mcp", badge: mcpDown },
    { key: "skills", path: "/skills", label: "스킬", icon: Blocks, on: route.page === "skills" },
    { key: "events", path: "/events", label: "이벤터", icon: CalendarClock, on: route.page === "events", badge: failed },
    { key: "portals", path: "/portals", label: "포탈", icon: LayoutGrid, on: route.page === "portals" },
  ];

  return (
    <nav className="rail">
      <div className="logo">C</div>
      {items.map(({ key, path, label, icon: Icon, on, badge }) => (
        <button key={key} className={`rb ${on ? "on" : ""}`} onClick={() => navigate(path)} aria-label={label}>
          <Icon size={19} strokeWidth={1.8} />
          {badge && <span className="badge" />}
          <span className="tip">{label}</span>
        </button>
      ))}
      <div className="sp" />
      <button className="rb" onClick={onToggleTheme} aria-label="테마 전환">
        {theme === "dark" ? <Sun size={18} strokeWidth={1.8} /> : <Moon size={18} strokeWidth={1.8} />}
        <span className="tip">{theme === "dark" ? "라이트 모드" : "다크 모드"}</span>
      </button>
      <button className={`rb me-btn ${route.page === "me" ? "on" : ""}`} onClick={() => navigate("/me")} aria-label="내 정보">
        <span className="me">{me?.user.name.slice(0, 1) ?? "나"}</span>
        <span className="tip">{me ? `${me.user.name} · 내 메모리` : "내 정보"}</span>
      </button>
    </nav>
  );
}
