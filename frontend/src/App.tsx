import React from "react";
import { HubProvider } from "./hub";
import { useRoute, useTheme } from "./lib/hooks";
import Rail from "./shell/Rail";
import ConversationList from "./shell/ConversationList";
import HomePage from "./pages/HomePage";
import ChatPage from "./pages/ChatPage";
import SkillsPage from "./pages/SkillsPage";
import EventsPage from "./pages/EventsPage";
import PortalsPage from "./pages/PortalsPage";
import McpPage from "./pages/McpPage";
import MePage from "./pages/MePage";

// 레이아웃: rail | 대화 목록 | 본문 | 정보 패널(대화 화면만)
export default function App() {
  const [route, navigate] = useRoute();
  const [theme, toggleTheme] = useTheme();

  const isChat = route.page === "chat" || route.page === "new";
  const withList = isChat || route.page === "home";
  const layout = isChat ? "" : withList ? "no-ctx" : "full";

  return (
    <HubProvider navigate={navigate}>
      <div className={`ws ${layout}`}>
        <Rail route={route} navigate={navigate} theme={theme} onToggleTheme={toggleTheme} />
        {withList && <ConversationList activeId={route.page === "chat" ? route.id : null} navigate={navigate} />}
        {route.page === "home" && <HomePage navigate={navigate} />}
        {isChat && <ChatPage convId={route.page === "chat" ? route.id : null} navigate={navigate} />}
        {route.page === "skills" && <SkillsPage selected={route.id} navigate={navigate} />}
        {route.page === "events" && <EventsPage navigate={navigate} />}
        {route.page === "portals" && <PortalsPage />}
        {route.page === "mcp" && <McpPage selected={route.id} navigate={navigate} />}
        {route.page === "me" && <MePage />}
      </div>
    </HubProvider>
  );
}
