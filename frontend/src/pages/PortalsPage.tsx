import React from "react";
import { ExternalLink } from "lucide-react";
import { useHub } from "../hub";

const STATUS = { ok: ["ok", "정상"], warn: ["warn", "주의"], err: ["err", "점검"] } as const;

export default function PortalsPage() {
  const { meta } = useHub();
  return (
    <section className="center">
      <header className="c-head"><b>포탈</b></header>
      <div className="scroll">
        <div className="inner wide">
          <div className="page-head">
            <div>
              <h1>포탈</h1>
              <p>사내 포탈 연결 상태입니다. 상태 값은 health check 연동 전까지 예시 데이터입니다.</p>
            </div>
          </div>
          <div className="portal-grid">
            {meta?.portals.map((p) => {
              const [cls, label] = STATUS[p.status];
              return (
                <div key={p.id} className="portal">
                  <div className="top">
                    <div className="glyph">{p.name[0]}</div>
                    <div><b>{p.name}</b></div>
                    <span className={`pill ${cls}`} style={{ marginLeft: "auto" }}>{label}</span>
                  </div>
                  <p>{p.description}</p>
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                    <span className="muted" style={{ fontSize: 12 }}>{p.note}</span>
                    <a className="ghost" href={p.url} target="_blank" rel="noreferrer"><ExternalLink size={12} />열기</a>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </section>
  );
}
