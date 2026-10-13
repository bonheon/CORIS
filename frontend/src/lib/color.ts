// 테마 변수(var(--x))에도 동작하는 투명도 적용 — "#rrggbb" + "33" 문자열 결합 대체
export const alpha = (color: string, hex: string) =>
  `color-mix(in srgb, ${color} ${Math.round((parseInt(hex, 16) / 255) * 100)}%, transparent)`;
