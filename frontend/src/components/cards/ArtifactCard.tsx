// code interpreter 결과물 — [ARTIFACT:a_xxxxxxxxxxxx] 태그.
// HTML 은 LLM 이 만든 코드의 산출물이므로 sandbox iframe 에 격리한다:
//   allow-scripts 만 허용 (allow-same-origin 없음) → Coris 화면 · 쿠키 · 저장소에 접근할 수 없다.
//   plotly.js 는 /vendor 에서 받는다 (srcdoc 의 상대 경로는 Coris 주소 기준).
import React, { useMemo } from "react";
import { Download } from "lucide-react";
import { useUiData } from "../../lib/hooks";

interface Artifact { kind: "html" | "image" | "missing"; title: string; html?: string; mime?: string; data?: string }

function download(name: string, blob: Blob) {
  const url = URL.createObjectURL(blob);
  const a = Object.assign(document.createElement("a"), { href: url, download: name });
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export default function ArtifactCard({ id }: { id: string }) {
  const args = useMemo(() => ({ artifact_id: id }), [id]);
  const { data, error } = useUiData<Artifact>("ui_artifact", args);

  if (error) return <div className="err-msg">결과물 로드 실패 — {error}</div>;
  if (!data) return <div className="chart-loading"><span className="spin" />결과물 불러오는 중</div>;
  if (data.kind === "missing") return <div className="err-msg">{data.title}</div>;

  const save = () => {
    if (data.kind === "html") {
      // 다운로드한 파일을 열면 plotly.js 를 CDN 에서 받도록 바꾼다 (Coris 밖에서 열리므로)
      const html = data.html!.replace('src="/vendor/plotly.min.js"', 'src="https://cdn.plot.ly/plotly-2.35.2.min.js"');
      download(`${data.title || id}.html`, new Blob([html], { type: "text/html" }));
    } else {
      const bin = Uint8Array.from(atob(data.data!), (c) => c.charCodeAt(0));
      download(`${data.title || id}.png`, new Blob([bin], { type: data.mime }));
    }
  };

  return (
    <div className="panel" style={{ margin: 0 }}>
      <div className="panel-h">
        <b>{data.title}</b>
        <small>Python 실행 결과 · {data.kind === "html" ? "드래그 확대 · 더블클릭 초기화" : "이미지"}</small>
        <button className="ghost" style={{ marginLeft: "auto" }} onClick={save}><Download size={12} />저장</button>
      </div>
      <div className="panel-b" style={{ paddingTop: 4 }}>
        {data.kind === "html" ? (
          <iframe title={data.title} sandbox="allow-scripts" srcDoc={data.html}
            style={{ width: "100%", height: 500, border: 0, background: "#fff", borderRadius: 8 }} />
        ) : (
          <img alt={data.title} src={`data:${data.mime};base64,${data.data}`} style={{ maxWidth: "100%", borderRadius: 8 }} />
        )}
      </div>
    </div>
  );
}
