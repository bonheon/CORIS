// 최근 사용한 스킬 — 이 브라우저에만 저장 (스킬 선택 팝오버의 '최근 사용')
const KEY = "coris-recent-skills";
const MAX = 8;

export function recentSkillIds(): string[] {
  try {
    const v = JSON.parse(localStorage.getItem(KEY) ?? "[]");
    return Array.isArray(v) ? v.filter((x) => typeof x === "string") : [];
  } catch {
    return [];
  }
}

export function pushRecentSkills(ids: string[]) {
  if (!ids.length) return;
  try {
    const next = [...ids, ...recentSkillIds().filter((x) => !ids.includes(x))].slice(0, MAX);
    localStorage.setItem(KEY, JSON.stringify(next));
  } catch {
    // 저장소를 못 쓰는 환경(사생활 보호 모드 등) — 최근 목록만 비어 보인다
  }
}
