import React, { useEffect, useState } from "react";
import { BookUser, Check, ChevronRight, CircleAlert, GitBranch, ListChecks, PenLine, TriangleAlert } from "lucide-react";
import type { RouteMode, SkillMode } from "../api";
import { Message } from "../types";
import { useHub } from "../hub";

// 응답이 만들어지는 과정 — agent 분기 → tool 호출 → 결과 분석/답변 작성
// 스트리밍 중에는 펼쳐서 단계별로 보여주고, 끝나면 한 줄 요약으로 접는다.

const MODE_LABEL: Record<RouteMode, string> = {
  manual: "직접 지정",
  single: "선택한 tool 기준",
  sticky: "직전 agent 유지",
  router: "자동 분기",
  fallback: "기본 agent",
};

const SKILL_MODE_LABEL: Record<Exclude<SkillMode, "none">, string> = {
  manual: "직접 선택",
  router: "자동 선택",
  sticky: "진행 중 유지",
};

const DROP_LABEL = { excluded: "끔", not_allowed: "agent 범위 밖", unavailable: "서버 응답 없음" } as const;

export const fmtMs = (ms: number) => (ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(1)}s`);

function fmtArgs(args: Record<string, unknown>) {
  const s = Object.entries(args)
    .filter(([, v]) => v !== null && v !== undefined && v !== "")
    .map(([k, v]) => `${k}=${Array.isArray(v) ? v.join(",") : String(v)}`)
    .join(" · ");
  return s.length > 80 ? s.slice(0, 80) + "…" : s;
}

function Elapsed({ from }: { from: number }) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const t = window.setInterval(() => setNow(Date.now()), 100);
    return () => window.clearInterval(t);
  }, []);
  return <span className="num">{((now - from) / 1000).toFixed(1)}s</span>;
}

type StepState = "run" | "ok" | "fail";

function Step({ state, icon, children, right }: { state: StepState; icon?: React.ReactNode; children: React.ReactNode; right?: React.ReactNode }) {
  return (
    <li className={`st ${state}`}>
      <span className="st-ic">
        {state === "run" ? <span className="spin" /> : state === "fail" ? <CircleAlert size={13} /> : icon ?? <Check size={13} strokeWidth={2.6} />}
      </span>
      <div className="st-body">{children}</div>
      {right && <span className="st-r">{right}</span>}
    </li>
  );
}

export default function RunTrace({ message }: { message: Message }) {
  const { toolLabel } = useHub();
  const live = !!message.streaming;
  const [open, setOpen] = useState(false);
  const { route, tools = [] } = message;

  // 저장된 옛 대화(분기 정보 없음)에 tool 도 없으면 보여줄 게 없다
  if (!live && !route && tools.length === 0) return null;

  const pending = tools.some((t) => t.ok === null);
  const failed = tools.filter((t) => t.ok === false).length;
  const writing = message.content.length > (message.toolMark ?? 0);
  const expanded = live || open;

  let phase: React.ReactNode = null;
  if (live && route && !pending) {
    phase = writing
      ? <Step state="run">답변 작성 중</Step>
      : <Step state="run">{tools.length ? "조회 결과 분석 중" : "답변 준비 중"}</Step>;
  }

  return (
    <div className={`trace ${live ? "live" : ""}`}>
      <button className="tr-head" onClick={() => !live && setOpen((o) => !o)} disabled={live}>
        {!live && <ChevronRight size={13} className={`chev ${open ? "on" : ""}`} />}
        <b>{live ? "처리 중" : "처리 과정"}</b>
        {route && <span className="tr-agent"><GitBranch size={12} />{route.agent_name}</span>}
        {route?.skill_name && <span className="tr-agent"><ListChecks size={12} />{route.skill_name}</span>}
        {tools.length > 0 && <span>tool {tools.length}개{failed ? ` · 실패 ${failed}` : ""}</span>}
        {route && route.warnings.length > 0 && <span className="tr-warn"><TriangleAlert size={12} />{route.warnings.length}</span>}
        <span className="tr-time">
          {live && message.startedAt ? <Elapsed from={message.startedAt} /> : message.elapsed ? fmtMs(message.elapsed) : null}
        </span>
      </button>

      {expanded && (
        <ol className="tr-steps">
          {message.userCtx && (
            <Step state="ok" icon={<BookUser size={13} />}>
              {message.userCtx.memory_chars
                ? <>사용자 메모리 불러옴 <small>{message.userCtx.name} · v{message.userCtx.memory_version} · {message.userCtx.memory_chars.toLocaleString()}자</small></>
                : <>사용자 메모리 없음 <small>{message.userCtx.name} · 이번 대화부터 쌓입니다</small></>}
            </Step>
          )}
          {!route ? (
            live && <Step state="run">질문 분석 · agent 선택 중</Step>
          ) : (
            <Step state="ok" icon={<GitBranch size={13} />} right={<span className="tag">{MODE_LABEL[route.route_mode]}</span>}>
              <b>{route.agent_name}</b> 가 처리
              {route.route_reason && <small>{route.route_reason}</small>}
              <small>
                켜진 tool {route.tools.length}개
                {route.locked.length > 0 && ` · 스킬 필수 ${route.locked.length}개`}
                {route.dropped.length > 0 && " · 제외 " + route.dropped.map((d) => `${toolLabel(d.name)}(${DROP_LABEL[d.reason]})`).join(", ")}
              </small>
              {route.warnings.map((w) => <small key={w} className="warn"><TriangleAlert size={11} />{w}</small>)}
            </Step>
          )}
          {route?.skill_name && route.skill_mode && route.skill_mode !== "none" && (
            <Step state="ok" icon={<ListChecks size={13} />} right={<span className="tag">{SKILL_MODE_LABEL[route.skill_mode]}</span>}>
              스킬 <b>{route.skill_name}</b> 절차 적용
            </Step>
          )}

          {tools.map((t, i) => (
            <Step key={t.id ?? i} state={t.ok === null ? "run" : t.ok ? "ok" : "fail"}
                  right={t.ms !== null ? <span className="num">{fmtMs(t.ms)}</span> : null}>
              {toolLabel(t.name)}{t.ok === null && " 조회 중"}
              <small className="mono">{t.name}{fmtArgs(t.args) && ` (${fmtArgs(t.args)})`}</small>
            </Step>
          ))}

          {phase}
          {!live && <Step state="ok" icon={<PenLine size={13} />}>답변 완료</Step>}
        </ol>
      )}
    </div>
  );
}
