import React, { useCallback, useState } from "react";
import { RefreshCw } from "lucide-react";
import { Attachment } from "../api";
import { useHub } from "../hub";
import Composer from "../shell/Composer";
import { fmtShort } from "../lib/hooks";
import { STARTERS } from "../lib/suggestions";
import { StatusRows, TodayEvents, SkillRows } from "./widgets";

function greeting() {
  const h = new Date().getHours();
  return h < 11 ? "좋은 아침입니다" : h < 18 ? "좋은 오후입니다" : "오늘도 수고하셨습니다";
}

// 홈 — 허브 현황(대화 · 스킬 · 이벤터 · MCP) + 빠른 시작. 업무 대시보드 카드는 필요해지면 여기에 추가한다.
export default function HomePage({ navigate }: { navigate: (p: string) => void }) {
  const { meta, me, conversations, skills, events, startChat, refreshMeta } = useHub();
  const [agentId, setAgentId] = useState("auto");
  const [skillId, setSkillId] = useState<string | null>(null);
  const [tools, setTools] = useState<string[]>([]);

  const onSend = useCallback((text: string, attachments?: Attachment[]) => startChat({ text, agentId, skillId, tools, attachments }),
    [startChat, agentId, skillId, tools]);

  const today = new Date().toLocaleDateString("ko-KR", { month: "long", day: "numeric", weekday: "short" });
  const servers = meta?.mcp_servers ?? [];
  const downServers = servers.filter((s) => s.status !== "ok");
  const toolsOk = meta?.tools.filter((t) => t.available).length ?? 0;
  const activeEvents = events.filter((e) => e.enabled).length;
  const totalUses = skills.reduce((n, s) => n + (s.uses ?? 0), 0);

  return (
    <section className="center">
      <header className="c-head"><b>홈</b></header>
      <div className="scroll">
        <div className="inner wide">
          <div className="dash-head">
            <div>
              <h1>{greeting()}{me ? `, ${me.user.name}님` : ""}</h1>
              <p>{today}</p>
            </div>
            <button className="ib" onClick={refreshMeta} title="새로고침"><RefreshCw size={14} /></button>
          </div>

          <div className="kpis">
            {meta ? (
              <>
                <div className="kpi">
                  <small>대화</small>
                  <b className="num">{conversations.length}</b>
                  <div className="d">{conversations[0] ? `최근 ${fmtShort(conversations[0].updated_at)}` : "아직 없음"}</div>
                </div>
                <div className="kpi">
                  <small>스킬</small>
                  <b className="num">{skills.length}</b>
                  <div className="d">누적 실행 {totalUses}회</div>
                </div>
                <div className="kpi">
                  <small>이벤터</small>
                  <b className="num">{activeEvents}<em>/ {events.length}</em></b>
                  <div className="d">켜진 이벤터 / 전체</div>
                </div>
                <div className="kpi">
                  <small>MCP tool</small>
                  <b className="num">{toolsOk}<em>/ {meta.tools.length}</em></b>
                  <div className={`d ${downServers.length ? "bad" : "good"}`}>
                    {downServers.length ? `응답 없음: ${downServers.map((s) => s.name).join(", ")}` : `서버 ${servers.length}개 정상`}
                  </div>
                </div>
              </>
            ) : (
              [0, 1, 2, 3].map((i) => <div key={i} className="kpi skeleton" style={{ height: 86 }} />)
            )}
          </div>

          <div className="dash">
            <div>
              <div className="panel">
                <div className="panel-h"><b>빠른 시작</b><small>예시 질문</small></div>
                <div className="panel-b">
                  <div className="starters" style={{ marginTop: 8 }}>
                    {STARTERS.map((s) => (
                      <button key={s.q} className="starter" onClick={() => startChat({ text: s.q, agentId: s.agent, skillId: null })}>
                        <div className="k">{s.k}</div>
                        <b>{s.q}</b>
                        <small>{s.d}</small>
                      </button>
                    ))}
                  </div>
                </div>
              </div>

              <div className="panel">
                <div className="panel-h"><b>최근 대화</b><button className="link" onClick={() => navigate("/new")}>새 대화</button></div>
                <div className="panel-b">
                  {conversations.length === 0 && <div className="muted" style={{ padding: "12px 0" }}>아직 대화가 없습니다</div>}
                  {conversations.slice(0, 6).map((c) => (
                    <div key={c.id} className="row" style={{ cursor: "pointer" }} onClick={() => navigate(`/c/${c.id}`)}>
                      <span className="nm ell" style={{ maxWidth: "40%" }}>{c.title}</span>
                      <span className="ell muted">{c.summary}</span>
                      <span className="rt">{fmtShort(c.updated_at)}</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>

            <div>
              <div className="panel">
                <div className="panel-h"><b>예정 이벤터</b><button className="link" onClick={() => navigate("/events")}>관리</button></div>
                <div className="panel-b"><TodayEvents onOpen={() => navigate("/events")} /></div>
              </div>
              <div className="panel">
                <div className="panel-h"><b>포탈</b><button className="link" onClick={() => navigate("/portals")}>전체</button></div>
                <div className="panel-b"><StatusRows /></div>
              </div>
              <div className="panel">
                <div className="panel-h"><b>내 스킬</b><button className="link" onClick={() => navigate("/skills/new")}>새로 만들기</button></div>
                <div className="panel-b"><SkillRows onOpen={(id) => navigate(`/skills/${id}`)} /></div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <Composer
        onSend={onSend}
        busy={false}
        agentId={agentId}
        skillId={skillId}
        onAgentChange={setAgentId}
        onSkillChange={setSkillId}
        selectedTools={tools}
        onToolsChange={setTools}
        placeholder="무엇이든 질문하세요.  / 로 스킬 불러오기"
      />
    </section>
  );
}
