// 새 대화 화면의 시작 질문과, 마지막 AI 응답의 카드 태그를 보고 고르는 후속 질문

export const STARTERS = [
  { k: "INSP", agent: "auto", q: "TE2FE35 INSP 웨이퍼 맵 정리해줘", d: "스킬 · INSP Wafer Map 정리" },
  { k: "스킬", agent: "auto", q: "이번 주 챙겨야 할 공지 정리해줘", d: "예시 스킬 · 공지 브리핑" },
  { k: "차트", agent: "auto", q: "최근 30일 막 두께 추이 보여줘", d: "공통 차트 카드 · 확대/축소" },
  { k: "Python", agent: "auto", q: "막 두께를 설비별 7일 이동평균으로 그려서 비교해줘", d: "code interpreter · 자유 형식 차트" },
];

// 카드 태그 → 후속 질문. 카드를 추가할 때 같이 등록한다 (없으면 후속 질문을 보이지 않는다)
const FOLLOW_UPS: Record<string, string[]> = {
  NOTICE_LIST: ["이번 주 일정만 추려줘", "부서별로 묶어서 표로 정리해줘", "내가 해야 할 일만 알려줘"],
  CHART: ["설비별 7일 이동평균으로 다시 그려줘", "설비별 값 분포를 박스플롯으로 비교해줘", "관리한계 이탈 시점만 표로 정리해줘"],
  WAFER_MAP: ["기준 초과 웨이퍼만 자세히 보여줘", "패턴 웨이퍼들 위치를 겹쳐서 비교해줘", "유형별 defect 크기 분포 그려줘"],
  ARTIFACT: ["이 결과를 표로도 정리해줘", "다른 지표(온도)로도 같은 차트 그려줘"],
};

export function getFollowUpSuggestions(content: string): string[] {
  const tag = Object.keys(FOLLOW_UPS).find((t) => content.includes(`[${t}:`));
  return tag ? FOLLOW_UPS[tag] : [];
}
