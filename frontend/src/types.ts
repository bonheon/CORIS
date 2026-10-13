import type { Attachment, RouteInfo, ToolRun, UserCtx } from "./api";

export interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  attachments?: Attachment[]; // 사용자 메시지의 첨부 이미지
  at: string;              // ISO 시각
  streaming?: boolean;     // true 동안 마크다운 파싱 생략 (plain text)
  tools?: ToolRun[];       // 이 응답을 만들며 실행한 tool
  route?: RouteInfo | null; // 백엔드 분기 결과 (agent · 켜진 tool)
  userCtx?: UserCtx;       // 이 응답에 쓰인 사용자 메모리
  // 진행 표시용 — 스트리밍 중에만 쓴다
  startedAt?: number;      // 요청 시각 (ms)
  toolMark?: number;       // 마지막 tool 이 끝났을 때의 content 길이 → 이후 글자가 없으면 "결과 분석 중"
  elapsed?: number;        // 응답 완료까지 걸린 시간 (ms)
  error?: string;
}
