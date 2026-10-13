// 예시 카드 — 공지 목록. 새 카드를 만들 때 이 파일을 복사해서 시작한다.
import React from "react";
import { useUiData } from "../../lib/hooks";

interface Notice { id: string; date: string; dept: string; title: string; body: string }
interface Payload { keyword: string; items: Notice[] }

export default function NoticeListCard({ keyword }: { keyword: string }) {
  const { data, error } = useUiData<Payload>("ui_notices", { keyword });

  if (error) return <div className="err-msg">공지 로드 실패 — {error}</div>;
  if (!data) return <div className="chart-loading"><span className="spin" />공지 불러오는 중</div>;
  return (
    <div className="panel" style={{ margin: 0 }}>
      <div className="panel-h"><b>공지</b><small>{data.keyword ? `'${data.keyword}' · ` : ""}{data.items.length}건</small></div>
      <div className="panel-b">
        {data.items.length === 0 && <div className="muted" style={{ padding: "8px 0" }}>검색 결과가 없습니다</div>}
        {data.items.map((n) => (
          <div key={n.id} className="row" title={n.body}>
            <span className="when num">{n.date.slice(5)}</span>
            <span className="ell">{n.title}</span>
            <span className="rt">{n.dept}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
