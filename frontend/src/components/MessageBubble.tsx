import React from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { uploadUrl } from "../api";
import { Message } from "../types";
import { CARDS, Part, splitCards } from "./cards";
import RunTrace from "./RunTrace";

interface Props {
  message: Message;
}

// 마크다운 — 스타일은 theme.css 의 .md 에서
const MD: Record<string, React.FC<any>> = {
  table: ({ children }) => (
    <div className="tbl-wrap"><table>{children}</table></div>
  ),
};

function renderPart(p: Part, i: number) {
  if (p.type === "text") {
    return p.value.trim() ? (
      <ReactMarkdown key={i} remarkPlugins={[remarkGfm]} components={MD}>{p.value}</ReactMarkdown>
    ) : null;
  }
  return <div key={i} className="chart-slot">{CARDS[p.tag](p.value)}</div>;
}

function MessageBubbleInner({ message }: Props) {
  if (message.role === "user") {
    return (
      <div className="u">
        <div>
          {!!message.attachments?.length && (
            <div className="u-atts">
              {message.attachments.map((a) => (
                <a key={a.id} href={uploadUrl(a.id)} target="_blank" rel="noreferrer" title={a.name}>
                  <img src={uploadUrl(a.id)} alt={a.name} />
                </a>
              ))}
            </div>
          )}
          {message.content}
        </div>
      </div>
    );
  }

  return (
    <div className="bot">
      <div className="av">C</div>
      <div className="body">
        <RunTrace message={message} />
        {message.streaming ? (
          // 스트리밍 중 — 마크다운 파싱 생략 (매 토큰 재파싱 방지)
          <div className="md" style={{ whiteSpace: "pre-wrap" }}>{message.content.replace(/\[[A-Z_]+:[^\]]*\]?/g, "")}</div>
        ) : (
          <div className="md">{splitCards(message.content).map(renderPart)}</div>
        )}
        {message.error && <div className="err-msg" style={{ marginTop: 8 }}>{message.error}</div>}
      </div>
    </div>
  );
}

const MessageBubble = React.memo(MessageBubbleInner);
export default MessageBubble;
