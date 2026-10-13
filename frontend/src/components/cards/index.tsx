// 카드 태그 레지스트리 — AI 응답 본문의 [TAG:value] 를 찾아 카드 컴포넌트로 그린다.
//
// 카드 추가 순서
//   1) MCP 서버에 화면 전용 tool(ui_xxx) 추가 → backend/hub/catalog.yaml 의 ui_tools 에 등록
//   2) 이 폴더에 카드 컴포넌트 작성 — 데이터는 useUiData("ui_xxx", {...}) 로 받는다
//   3) 아래 CARDS 에 태그 등록
//   4) backend/hub/tool_guides.yaml 에 LLM 용 tool 의 태그 형식 안내 추가
//
// 차트는 대부분 카드를 새로 만들 필요가 없다:
//   - 정형 차트(스킬 · 반복 조회) → ui tool 이 ChartSpec 형식을 돌려주면 [CHART:ui_xxx?인자] 로 끝 (ChartCard)
//   - 그때그때 다른 차트       → code interpreter 가 만든 HTML 을 [ARTIFACT:id] 로 (ArtifactCard)
import React from "react";
import NoticeListCard from "./NoticeListCard";
import ChartCard from "./ChartCard";
import ArtifactCard from "./ArtifactCard";

export const CARDS: Record<string, (value: string) => React.ReactNode> = {
  NOTICE_LIST: (value) => <NoticeListCard keyword={value} />,
  CHART: (value) => <ChartCard value={value} />,
  ARTIFACT: (value) => <ArtifactCard id={value} />,
};

const TAG_RE = new RegExp(`\\[(${Object.keys(CARDS).join("|") || "(?!)"}):([^\\]]*)\\]`, "g");

export type Part = { type: "text"; value: string } | { type: "card"; tag: string; value: string };

/** 본문을 텍스트 / 카드 조각으로 나눈다. 등록되지 않은 태그는 텍스트로 남는다. */
export function splitCards(content: string): Part[] {
  const parts: Part[] = [];
  let last = 0;
  for (const m of Array.from(content.matchAll(TAG_RE))) {
    if (m.index! > last) parts.push({ type: "text", value: content.slice(last, m.index) });
    parts.push({ type: "card", tag: m[1], value: m[2] });
    last = m.index! + m[0].length;
  }
  if (last < content.length) parts.push({ type: "text", value: content.slice(last) });
  return parts;
}
