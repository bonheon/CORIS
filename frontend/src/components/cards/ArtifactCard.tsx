// code interpreter 결과물 — [ARTIFACT:a_xxxxxxxxxxxx] 태그.
// HTML 은 LLM 이 만든 코드의 산출물이므로 sandbox iframe 에 격리한다:
//   allow-scripts 만 허용 (allow-same-origin 없음) → Coris 화면 · 쿠키 · 저장소에 접근할 수 없다.
//   plotly.js 는 /vendor 에서 받는다 (srcdoc 의 상대 경로는 Coris 주소 기준).
// 화면과 iframe 은 postMessage 로만 주고받는다 (BRIDGE 스크립트를 srcdoc 에 넣는다):
//   iframe → 화면 : 내용 높이 (카드 높이를 맞춰 안쪽 스크롤을 없앤다)
//   화면 → iframe : 테마 (다크 모드면 차트 배경 · 글자 · 격자 색을 바꾼다)
import React, { useEffect, useMemo, useRef, useState } from "react";
import { Download, Maximize2, X } from "lucide-react";
import { useUiData } from "../../lib/hooks";

interface Artifact { kind: "html" | "image" | "missing"; title: string; html?: string; mime?: string; data?: string }

const BRIDGE = `<script>(function(){
  // documentElement.scrollHeight 는 iframe 높이보다 작아지지 않는다 — body 내용 높이로 잰다 (줄어들 때도 맞춤)
  // plotly 가 만든 html 은 doctype 이 없어(호환 모드) 차트 div 의 height:100% 가 iframe 높이를 따라간다 —
  // 차트가 있으면 각 차트의 레이아웃 높이 끝으로, 없으면 body 내용 높이로 잰다
  function post(){
    var b = document.body; if (!b) return;
    var gs = document.querySelectorAll(".plotly-graph-div"), h = 0;
    gs.forEach(function(gd){ if (gd._fullLayout) h = Math.max(h, gd.getBoundingClientRect().top + window.scrollY + gd._fullLayout.height); });
    if (!h) { h = 0; for (var i = 0; i < b.children.length; i++) h = Math.max(h, b.children[i].getBoundingClientRect().bottom + window.scrollY); }
    parent.postMessage({coris:"size", h: Math.ceil(h + 4)}, "*");
  }
  // 폰트가 늦게 준비되면 범례 글자 폭을 잘못 재서 겹친다 — 폰트 준비 후 범례만 다시 그린다
  // 같은 값을 relayout 하면 plotly 가 아무것도 하지 않으므로, datarevision 을 바꿔 react 로 전체를 다시 그린다
  function relegend(){ if (!window.Plotly) return; document.querySelectorAll(".plotly-graph-div").forEach(function(gd){
    if (gd._fullLayout && gd._fullLayout.showlegend)
      Plotly.react(gd, gd.data, Object.assign({}, gd.layout, {datarevision: Date.now()})); }); }
  window.addEventListener("load", function(){
    post(); setTimeout(post, 300);
    var fr = document.fonts && document.fonts.ready ? document.fonts.ready : Promise.resolve();
    fr.then(function(){ setTimeout(relegend, 80); });
  });
  window.addEventListener("load", function(){
    document.querySelectorAll(".plotly-graph-div").forEach(function(gd){ if (gd.on) gd.on("plotly_afterplot", post); });
  });
  window.addEventListener("message", function(e){
    var d = e.data || {};
    if (d.coris === "fit" && window.Plotly) {   // 크게 보기 — 차트가 하나면 창 높이를 채운다
      var gs = document.querySelectorAll(".plotly-graph-div");
      if (gs.length === 1) { Plotly.relayout(gs[0], {height: Math.max(window.innerHeight - 6, 300)}); }
      return;
    }
    if (d.coris !== "theme") return;
    var c = d.dark ? {bg:"#151917", ink:"#e4e2db", sub:"#9aa19b", grid:"#262c28", line:"#3a413c"}
                   : {bg:"#ffffff", ink:"#2b302c", sub:"#6b716c", grid:"#eeece6", line:"#d9d5ca"};
    document.documentElement.style.background = c.bg; document.body.style.background = c.bg;
    if (!window.Plotly) return;
    document.querySelectorAll(".plotly-graph-div").forEach(function(gd){
      if (!gd._fullLayout) return;
      var u = {paper_bgcolor:c.bg, plot_bgcolor:c.bg, "font.color":c.ink, "title.font.color":c.ink,
               "legend.font.color":c.sub, "hoverlabel.bgcolor":c.bg, "hoverlabel.bordercolor":c.line, "hoverlabel.font.color":c.ink};
      Object.keys(gd._fullLayout).forEach(function(k){
        if (/^[xy]axis\\d*$/.test(k)) { u[k+".gridcolor"]=c.grid; u[k+".linecolor"]=c.line; u[k+".tickcolor"]=c.line;
          u[k+".tickfont.color"]=c.sub; u[k+".title.font.color"]=c.sub; }
      });
      (gd.layout.annotations||[]).forEach(function(_, i){ u["annotations["+i+"].font.color"]=c.sub; });
      Plotly.relayout(gd, u);
    });
  });
  parent.postMessage({coris:"ready"}, "*");
})();</script>`;

const withBridge = (html: string) => (html.includes("</body>") ? html.replace("</body>", BRIDGE + "</body>") : html + BRIDGE);
const isDark = () => document.documentElement.dataset.theme === "dark";

function download(name: string, blob: Blob) {
  const url = URL.createObjectURL(blob);
  const a = Object.assign(document.createElement("a"), { href: url, download: name });
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/** sandbox iframe — 높이를 내용에 맞추고(fill 이면 부모를 채움) 테마를 따라간다 */
function Frame({ title, html, fill }: { title: string; html: string; fill?: boolean }) {
  const ref = useRef<HTMLIFrameElement>(null);
  const [h, setH] = useState(480);
  const doc = useMemo(() => withBridge(html), [html]);

  useEffect(() => {
    const sendTheme = () => ref.current?.contentWindow?.postMessage({ coris: "theme", dark: isDark() }, "*");
    const onMsg = (e: MessageEvent) => {
      if (e.source !== ref.current?.contentWindow) return;
      if (e.data?.coris === "size" && typeof e.data.h === "number") setH(Math.min(Math.max(e.data.h, 200), 2400));
      if (e.data?.coris === "ready") {
        sendTheme();
        if (fill) ref.current?.contentWindow?.postMessage({ coris: "fit" }, "*");
      }
    };
    window.addEventListener("message", onMsg);
    const mo = new MutationObserver(sendTheme);   // 화면 테마 전환
    mo.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    return () => { window.removeEventListener("message", onMsg); mo.disconnect(); };
  }, [fill]);

  return (
    <iframe ref={ref} title={title} sandbox="allow-scripts" srcDoc={doc} className="art-frame"
      style={fill ? { height: "100%" } : { height: h }} />
  );
}

export default function ArtifactCard({ id }: { id: string }) {
  const args = useMemo(() => ({ artifact_id: id }), [id]);
  const { data, error } = useUiData<Artifact>("ui_artifact", args);
  const [big, setBig] = useState(false);

  useEffect(() => {
    if (!big) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setBig(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [big]);

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

  const body = (fill?: boolean) => data.kind === "html"
    ? <Frame title={data.title} html={data.html!} fill={fill} />
    : <img alt={data.title} src={`data:${data.mime};base64,${data.data}`} className="art-img" />;

  return (
    <>
      <div className="panel art-card">
        <div className="panel-h">
          <b>{data.title}</b>
          <small>Python 실행 결과{data.kind === "html" ? " · 드래그 확대 · 더블클릭 초기화" : ""}</small>
          <span className="art-acts">
            <button className="ghost" onClick={() => setBig(true)} title="크게 보기"><Maximize2 size={12} />크게</button>
            <button className="ghost" onClick={save}><Download size={12} />저장</button>
          </span>
        </div>
        <div className="art-body">{body()}</div>
      </div>

      {big && (
        <div className="art-full" onMouseDown={(e) => e.target === e.currentTarget && setBig(false)}>
          <div className="art-full-box">
            <div className="panel-h">
              <b>{data.title}</b>
              <small>Esc 로 닫기</small>
              <span className="art-acts">
                <button className="ghost" onClick={save}><Download size={12} />저장</button>
                <button className="ib" onClick={() => setBig(false)} aria-label="닫기"><X size={15} /></button>
              </span>
            </div>
            <div className="art-full-body">{body(true)}</div>
          </div>
        </div>
      )}
    </>
  );
}
