import React, { useState } from "react";
import { HubProvider } from "./hub";
import { useRoute, useTheme } from "./lib/hooks";
import Rail from "./shell/Rail";
import ConversationList from "./shell/ConversationList";
import HomePage from "./pages/HomePage";
import ChatPage from "./pages/ChatPage";
import SkillsPage from "./pages/SkillsPage";
import EventsPage from "./pages/EventsPage";
import TasksPage from "./pages/TasksPage";
import PortalsPage from "./pages/PortalsPage";
import McpPage from "./pages/McpPage";
import ToolGroupsPage from "./pages/ToolGroupsPage";
import MePage from "./pages/MePage";

// 레이아웃: rail | 본문 | 대화 목록(홈 · 대화 화면)
export default function App() {
  const [route, navigate] = useRoute();
  const [theme, toggleTheme] = useTheme();

  const isChat = route.page === "chat" || route.page === "new";
  const withList = isChat || route.page === "home";
  // 대화 목록 접기 — 차트 · 표를 넓게 보려고. 브라우저에 기억한다
  const [listHidden, setListHidden] = useState(() => { try { return localStorage.getItem("coris.listHidden") === "1"; } catch { return false; } });
  const toggleList = () => setListHidden((v) => {
    try { localStorage.setItem("coris.listHidden", v ? "0" : "1"); } catch {}
    return !v;
  });
  const showList = withList && !listHidden;
  const layout = showList ? "" : withList ? "nolist" : "full";

  return (
    <HubProvider navigate={navigate}>
      <div className={`ws ${layout}`}>
        <Rail route={route} navigate={navigate} theme={theme} onToggleTheme={toggleTheme}
          listToggle={withList ? { hidden: listHidden, onToggle: toggleList } : undefined} />
        {route.page === "home" && <HomePage navigate={navigate} />}
        {isChat && <ChatPage convId={route.page === "chat" ? route.id : null} navigate={navigate} />}
        {route.page === "skills" && <SkillsPage selected={route.id} navigate={navigate} />}
        {route.page === "events" && <EventsPage navigate={navigate} />}
        {route.page === "tasks" && <TasksPage navigate={navigate} />}
        {route.page === "portals" && <PortalsPage />}
        {route.page === "mcp" && <McpPage selected={route.id} navigate={navigate} />}
        {route.page === "groups" && <ToolGroupsPage selected={route.id} navigate={navigate} />}
        {route.page === "me" && <MePage />}
        {showList && <ConversationList activeId={route.page === "chat" ? route.id : null} navigate={navigate} onFold={toggleList} />}
      </div>
    </HubProvider>
  );
}
