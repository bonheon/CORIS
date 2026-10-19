// 공통 차트 카드 — [CHART:<ui tool>?<args>] 태그. 화면 전용 MCP tool 이 아래 형식(ChartSpec)을 돌려주면
// 차트 종류마다 카드를 새로 만들 필요 없이 이 카드 하나로 그린다.
//   Ctrl+휠: 확대 · 축소 (그냥 휠은 페이지 스크롤) / 드래그: 이동 / 하단 슬라이더: 구간 / 우측 상단: 영역 확대 · 초기화 · 이미지 저장
import React, { useEffect, useMemo, useRef } from "react";
import * as echarts from "echarts";
import { useUiData } from "../../lib/hooks";

export interface ChartSpec {
  title?: string;
  subtitle?: string;
  x: { type: "time" | "category" | "value"; label?: string };
  y: { label?: string; unit?: string };
  series: { name: string; type?: "line" | "bar" | "scatter"; data: [string | number, number][] }[];
  limits?: { name: string; value: number }[];
}

const PALETTE = ["--c-blue", "--c-green", "--c-amber", "--c-purple", "--c-sky", "--c-red"];
const FALLBACK = ["#3b82f6", "#22a06b", "#f59e0b", "#8b5cf6", "#0ea5e9", "#ef4444"];

/** 테마 팔레트 색 (카드들이 같은 색 순서를 쓰도록) */
export function paletteColors(): string[] {
  return PALETTE.map(cssVar).map((c, i) => c || FALLBACK[i]);
}

export function cssVar(name: string) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

/** 테마(라이트 · 다크)가 바뀌면 다시 그리기 위한 값 */
export function useThemeKey() {
  const [key, setKey] = React.useState(() => document.documentElement.dataset.theme ?? "");
  useEffect(() => {
    const ob = new MutationObserver(() => setKey(document.documentElement.dataset.theme ?? ""));
    ob.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    return () => ob.disconnect();
  }, []);
  return key;
}

function toOption(spec: ChartSpec): echarts.EChartsOption {
  const ink = cssVar("--ink"), sub = cssVar("--sub"), line = cssVar("--line"), err = cssVar("--err") || "#d33";
  const colors = paletteColors();
  const unit = spec.y.unit ? ` ${spec.y.unit}` : "";
  const category = spec.x.type === "category"
    ? Array.from(new Set(spec.series.flatMap((s) => s.data.map((p) => String(p[0])))))
    : undefined;

  return {
    color: colors,
    animation: false,
    textStyle: { color: ink },
    grid: { left: 56, right: 24, top: 70, bottom: 62 },
    legend: { top: 4, left: 0, textStyle: { color: sub }, type: "scroll", right: 110 },
    tooltip: {
      trigger: spec.series.every((s) => s.type === "scatter") ? "item" : "axis",
      valueFormatter: (v) => (typeof v === "number" ? `${v.toLocaleString()}${unit}` : String(v)),
    },
    toolbox: {
      right: 0, top: 4, iconStyle: { borderColor: sub },
      feature: { dataZoom: { title: { zoom: "영역 확대", back: "되돌리기" } }, restore: { title: "초기화" }, saveAsImage: { title: "이미지 저장" } },
    },
    dataZoom: [
      // 그냥 휠은 페이지 스크롤로 넘긴다 — 대화 중간의 차트에서 스크롤이 막히지 않게
      { type: "inside", xAxisIndex: 0, filterMode: "none", zoomOnMouseWheel: "ctrl", moveOnMouseWheel: false },
      { type: "slider", xAxisIndex: 0, filterMode: "none", height: 20, bottom: 8, textStyle: { color: sub } },
    ],
    xAxis: {
      // 시간축은 이름 없이 (자명하고 슬라이더와 겹친다)
      type: spec.x.type, data: category, name: spec.x.type === "time" ? undefined : spec.x.label, nameLocation: "end",
      axisLine: { lineStyle: { color: line } }, axisLabel: { color: sub }, splitLine: { show: false },
      scale: spec.x.type === "value",
    } as any,  // ECharts 는 축 type 별로 타입이 갈려 있어 런타임 값으로는 좁힐 수 없다
    yAxis: {
      type: "value", scale: true, name: spec.y.label ? `${spec.y.label}${unit}` : undefined,
      nameTextStyle: { color: sub, align: "left", padding: [0, 0, 4, -40] }, nameGap: 14,
      axisLabel: { color: sub }, splitLine: { lineStyle: { color: line } },
    },
    series: spec.series.map((s, i) => ({
      name: s.name,
      type: s.type ?? "line",
      data: s.data,
      showSymbol: false,
      symbolSize: s.type === "scatter" ? 6 : 4,
      sampling: s.type === "line" || !s.type ? "lttb" : undefined,
      large: s.data.length > 2000,
      lineStyle: { width: 1.6 },
      // 관리선은 첫 계열에만 — 계열마다 그리면 겹친다
      markLine: i === 0 && spec.limits?.length ? {
        silent: true, symbol: "none",
        lineStyle: { color: err, type: "dashed", width: 1.2 },
        label: { formatter: "{b} {c}", color: err, position: "insideEndTop" },
        data: spec.limits.map((l) => ({ name: l.name, yAxis: l.value })),
      } : undefined,
    })),
  };
}

/** ECharts 한 개 — 크기 변화 추적 · 휠 처리(그냥 휠은 페이지 스크롤, Ctrl+휠만 차트) 공통 */
export function EChart({ option, style }: { option: echarts.EChartsOption; style?: React.CSSProperties }) {
  const el = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!el.current) return;
    const chart = echarts.init(el.current, undefined, { renderer: "canvas" });
    chart.setOption(option);
    const ro = new ResizeObserver(() => chart.resize());
    ro.observe(el.current);
    // 그냥 휠은 ECharts 에 닿기 전에 막아 페이지 스크롤로 보낸다 (zoomOnMouseWheel: "ctrl" 만으로는
    // ECharts 가 휠 이벤트를 삼켜 대화 중간의 차트에서 스크롤이 멈춘다). Ctrl+휠만 차트 확대로.
    const root = el.current;
    const onWheel = (e: WheelEvent) => { if (!e.ctrlKey) e.stopPropagation(); };
    root.addEventListener("wheel", onWheel, { capture: true });
    return () => { root.removeEventListener("wheel", onWheel, { capture: true }); ro.disconnect(); chart.dispose(); };
  }, [option]);

  return <div ref={el} style={{ width: "100%", height: 380, ...style }} />;
}

function Chart({ spec }: { spec: ChartSpec }) {
  const themeKey = useThemeKey();
  const option = useMemo(() => toOption(spec), [spec, themeKey]);  // eslint-disable-line react-hooks/exhaustive-deps
  return <EChart option={option} />;
}

export default function ChartCard({ value }: { value: string }) {
  const [tool, query = ""] = value.split("?");
  const args = useMemo(() => Object.fromEntries(new URLSearchParams(query)), [query]);
  const { data, error } = useUiData<ChartSpec>(tool, args);

  if (error) return <div className="err-msg">차트 로드 실패 — {error}</div>;
  if (!data) return <div className="chart-loading"><span className="spin" />차트 불러오는 중</div>;
  return (
    <div className="panel" style={{ margin: 0 }}>
      <div className="panel-h">
        <b>{data.title ?? "차트"}</b>
        {data.subtitle && <small>{data.subtitle}</small>}
        <small style={{ marginLeft: "auto" }}>Ctrl+휠 확대 · 드래그 이동</small>
      </div>
      <div className="panel-b" style={{ paddingTop: 4 }}><Chart spec={data} /></div>
    </div>
  );
}
