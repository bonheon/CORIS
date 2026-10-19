// INSP Wafer Map 카드 — [WAFER_MAP:<lot_id>] 태그. 데이터: 화면 전용 MCP tool ui_insp_map.
//   왼쪽: Lot 전체 웨이퍼 작은 맵 (빨강 테두리 = 기준 초과, 주황 = 자동 분류 패턴) → 클릭하면 오른쪽에 크게
//   오른쪽: 선택 웨이퍼 (마우스를 올리면 유형 · 좌표 · 크기, Ctrl+휠 확대 · 드래그 이동, 우측 상단 초기화)
//   위쪽 유형 칩: defect 유형별 켜고 끄기 (작은 맵 · 큰 맵 같이)
// 좌표는 웨이퍼 중심 원점 mm. 다른 맵(설비 · 계측) 스킬도 같은 형식이면 이 카드를 그대로 쓴다.
import React, { useMemo, useState } from "react";
import type { EChartsOption } from "echarts";
import { useUiData } from "../../lib/hooks";
import { cssVar, EChart, paletteColors, useThemeKey } from "./ChartCard";

type Defect = [number, number, number, number]; // x(mm), y(mm), class index, size(um)
interface Wafer { slot: number; pattern: string; total: number; defects: Defect[] }
interface InspMap {
  lot_id: string; step: string; wafer_diameter_mm: number; limit_per_wafer: number;
  classes: string[]; wafers: Wafer[];
}

/** 처음 크게 보여줄 웨이퍼 — 기준 초과 > 패턴 > defect 많은 순 */
function worst(wafers: Wafer[], limit: number): number {
  const score = (w: Wafer) => (w.total > limit ? 1e6 : 0) + (w.pattern !== "Random" ? 1e5 : 0) + w.total;
  return [...wafers].sort((a, b) => score(b) - score(a))[0]?.slot ?? 1;
}

function Thumb({ w, r, colors, hidden, limit, on, onClick }: {
  w: Wafer; r: number; colors: string[]; hidden: Set<number>; limit: number; on: boolean; onClick: () => void;
}) {
  const state = w.total > limit ? "over" : w.pattern !== "Random" ? "pattern" : "";
  return (
    <button className={`wm-thumb ${state} ${on ? "on" : ""}`} onClick={onClick}
      title={`Slot ${w.slot} · ${w.total}개 · ${w.pattern}`}>
      <svg viewBox={`${-r - 4} ${-r - 4} ${2 * r + 8} ${2 * r + 8}`}>
        <circle r={r} className="wm-wafer" />
        <path d={`M -8 ${r - 1} L 0 ${r - 9} L 8 ${r - 1} Z`} className="wm-notch" />
        {w.defects.map((d, i) => hidden.has(d[2]) ? null : (
          // SVG 는 y 가 아래로 커지므로 뒤집는다
          <circle key={i} cx={d[0]} cy={-d[1]} r={3.2} fill={colors[d[2] % colors.length]} />
        ))}
      </svg>
      <span><b>{w.slot}</b>{w.total}</span>
    </button>
  );
}

function bigOption(w: Wafer, data: InspMap, colors: string[], hidden: Set<number>): EChartsOption {
  const r = data.wafer_diameter_mm / 2;
  const line = cssVar("--line-strong"), sub = cssVar("--sub"), sunken = cssVar("--sunken");
  const outline = Array.from({ length: 181 }, (_, i) => {
    const t = (i / 180) * 2 * Math.PI;
    return [r * Math.cos(t), r * Math.sin(t)];
  });
  const axis = { type: "value" as const, min: -r - 5, max: r + 5, show: false };
  return {
    animation: false,
    grid: { left: 8, right: 8, top: 8, bottom: 8 },
    xAxis: axis,
    yAxis: axis,
    tooltip: {
      trigger: "item",
      formatter: (p: any) => p.seriesName === "_wafer" ? "" :
        `<b>${p.seriesName}</b><br/>x ${p.value[0]} · y ${p.value[1]} mm<br/>크기 ${p.value[3]} µm`,
    },
    toolbox: { right: 4, top: 4, iconStyle: { borderColor: sub }, feature: { restore: { title: "초기화" } } },
    dataZoom: [
      { type: "inside", xAxisIndex: 0, filterMode: "none", zoomOnMouseWheel: "ctrl", moveOnMouseWheel: false },
      { type: "inside", yAxisIndex: 0, filterMode: "none", zoomOnMouseWheel: "ctrl", moveOnMouseWheel: false },
    ],
    series: [
      {
        name: "_wafer", type: "line", data: outline, showSymbol: false, silent: true,
        lineStyle: { color: line, width: 1.5 }, areaStyle: { color: sunken }, z: 1,
      },
      ...data.classes.map((name, ci) => ({
        name, type: "scatter" as const, z: 3,
        data: hidden.has(ci) ? [] : w.defects.filter((d) => d[2] === ci),
        symbolSize: (v: number[]) => Math.min(12, 4 + v[3] * 3),
        itemStyle: { color: colors[ci % colors.length], opacity: 0.85 },
      })),
    ],
  };
}

export default function WaferMapCard({ lotId }: { lotId: string }) {
  const args = useMemo(() => ({ lot_id: lotId }), [lotId]);
  const { data, error } = useUiData<InspMap>("ui_insp_map", args);
  const [picked, setPicked] = useState<number | null>(null);
  const [hidden, setHidden] = useState<Set<number>>(new Set());
  const themeKey = useThemeKey();
  const colors = useMemo(() => paletteColors(), [themeKey]);  // eslint-disable-line react-hooks/exhaustive-deps

  const slot = picked ?? (data ? worst(data.wafers, data.limit_per_wafer) : 1);
  const wafer = data?.wafers.find((w) => w.slot === slot);
  const option = useMemo(
    () => (data && wafer ? bigOption(wafer, data, colors, hidden) : null),
    [data, wafer, colors, hidden, themeKey],  // eslint-disable-line react-hooks/exhaustive-deps
  );
  const counts = useMemo(() => {
    const c = data?.classes.map(() => 0) ?? [];
    data?.wafers.forEach((w) => w.defects.forEach((d) => { c[d[2]] += 1; }));
    return c;
  }, [data]);

  if (error) return <div className="err-msg">Wafer Map 로드 실패 — {error}</div>;
  if (!data || !wafer || !option) return <div className="chart-loading"><span className="spin" />Wafer Map 불러오는 중</div>;

  const r = data.wafer_diameter_mm / 2;
  const toggle = (ci: number) => setHidden((h) => {
    const next = new Set(h);
    next.has(ci) ? next.delete(ci) : next.add(ci);
    return next;
  });
  const shown = wafer.defects.filter((d) => !hidden.has(d[2])).length;

  return (
    <div className="panel" style={{ margin: 0 }}>
      <div className="panel-h">
        <b>INSP Wafer Map</b>
        <small>{data.lot_id} · {data.step} · {data.wafers.length}장 · 기준 {data.limit_per_wafer}/장</small>
      </div>
      <div className="panel-b">
        <div className="wm-classes">
          {data.classes.map((name, ci) => (
            <button key={name} className={`wm-class ${hidden.has(ci) ? "off" : ""}`} onClick={() => toggle(ci)}>
              <i style={{ background: colors[ci % colors.length] }} />{name}<small>{counts[ci]}</small>
            </button>
          ))}
          <span className="wm-legend"><i className="over" />기준 초과 <i className="pattern" />패턴</span>
        </div>
        <div className="wm-body">
          <div className="wm-grid">
            {data.wafers.map((w) => (
              <Thumb key={w.slot} w={w} r={r} colors={colors} hidden={hidden} limit={data.limit_per_wafer}
                on={w.slot === slot} onClick={() => setPicked(w.slot)} />
            ))}
          </div>
          <div className="wm-big">
            <div className="wm-big-h">
              <b>Slot {wafer.slot}</b>
              <span>{shown === wafer.total ? `${wafer.total}개` : `${shown} / ${wafer.total}개`}</span>
              {wafer.total > data.limit_per_wafer && <span className="pill err">기준 초과</span>}
              {wafer.pattern !== "Random" && <span className="pill warn">{wafer.pattern}</span>}
            </div>
            <EChart option={option} style={{ height: "auto", aspectRatio: "1 / 1" }} />
            <small className="muted">Ctrl+휠 확대 · 드래그 이동 · 점에 마우스를 올리면 상세</small>
          </div>
        </div>
      </div>
    </div>
  );
}
