/**
 * 화면 쪽 응답 시간 측정 (docs/TIMING.md) — 기본은 꺼져 있다.
 *   켜기: 브라우저 콘솔에서 localStorage.setItem("coris.timing", "1") 후 새로고침
 *   끄기: localStorage.removeItem("coris.timing")
 *
 * 질문 하나가 끝나면 콘솔에 표로 찍고 window.__corisTiming 에 쌓는다.
 *   headers_ms        요청 → 응답 헤더 (서버가 스트림을 열기까지)
 *   first_delta_ms    요청 → 첫 글자가 브라우저에 닿기까지
 *   reads / max_events_per_read
 *                     네트워크에서 몇 번에 나눠 받았나 · 한 번에 가장 많이 몰려 온 이벤트 수.
 *                     delta 가 수백 개인데 reads 가 몇 번뿐이면 → 중간(프록시 · gzip)이 모아서 보내는 것
 *   max_gap_ms        delta 가 브라우저에 닿은 간격 중 가장 긴 것
 *   longtask_n / longtask_ms
 *                     답변을 받는 동안 화면(메인 스레드)이 50ms 넘게 멈춘 횟수 · 합계 — 그리기(마크다운)가 무거우면 커진다
 */
type Row = Record<string, number | string | null>;

export interface Probe {
  headers(): void;
  read(events: number): void;
  event(type: string, convId?: string): void;
  finish(): void;
}

const NOOP: Probe = { headers() {}, read() {}, event() {}, finish() {} };

export function startProbe(): Probe {
  if (typeof window === "undefined" || window.localStorage?.getItem("coris.timing") !== "1") return NOOP;
  const t0 = performance.now();
  const ms = () => Math.round(performance.now() - t0);
  const row: Row = {
    conv: null, headers_ms: null, first_event_ms: null, first_tool_ms: null, first_delta_ms: null,
    last_delta_ms: null, done_ms: null, deltas: 0, reads: 0, max_events_per_read: 0, max_gap_ms: 0,
    longtask_n: 0, longtask_ms: 0, longtask_max_ms: 0,
  };
  let lastDelta: number | null = null;
  let finished = false;
  let observer: PerformanceObserver | null = null;
  try {
    observer = new PerformanceObserver((list) => {
      for (const e of list.getEntries()) {
        row.longtask_n = (row.longtask_n as number) + 1;
        row.longtask_ms = (row.longtask_ms as number) + Math.round(e.duration);
        row.longtask_max_ms = Math.max(row.longtask_max_ms as number, Math.round(e.duration));
      }
    });
    observer.observe({ type: "longtask", buffered: false });
  } catch { observer = null; }  // longtask 를 지원하지 않는 브라우저

  return {
    headers() { row.headers_ms = ms(); },
    read(events) {
      row.reads = (row.reads as number) + 1;
      row.max_events_per_read = Math.max(row.max_events_per_read as number, events);
    },
    event(type, convId) {
      if (row.first_event_ms === null) row.first_event_ms = ms();
      if (convId) row.conv = convId;
      if (type === "tool_start" && row.first_tool_ms === null) row.first_tool_ms = ms();
      if (type === "delta") {
        const now = performance.now();
        if (row.first_delta_ms === null) row.first_delta_ms = ms();
        if (lastDelta !== null) row.max_gap_ms = Math.max(row.max_gap_ms as number, Math.round(now - lastDelta));
        lastDelta = now;
        row.last_delta_ms = ms();
        row.deltas = (row.deltas as number) + 1;
      }
    },
    finish() {
      if (finished) return;
      finished = true;
      row.done_ms = ms();
      // 마지막 그리기가 끝난 뒤 longtask 까지 받도록 한 박자 늦게 닫는다
      setTimeout(() => {
        observer?.disconnect();
        const w = window as any;
        (w.__corisTiming = w.__corisTiming || []).push(row);
        console.info("[coris timing]", row.conv);
        console.table(row);
      }, 300);
    },
  };
}
