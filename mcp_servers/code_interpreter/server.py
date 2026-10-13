"""
Code interpreter MCP 서버 — 대화마다 Jupyter 커널 하나를 띄워 Python 을 실행한다.

tool
  - run_python(code, session_id)   LLM 용. session_id 는 Coris 가 대화 id 로 채운다 (LLM 에는 보이지 않음)
  - ui_artifact(artifact_id)       화면 전용. save_html · matplotlib 이 만든 결과물(HTML / 이미지)

결과물은 workspace/artifacts 에 파일로 남고, LLM 은 [ARTIFACT:id] 태그만 답변에 넣는다.
화면은 HTML 결과물을 sandbox iframe(스크립트만 허용, Coris 화면 · 로그인 정보 접근 불가)으로 띄운다.

※ 로컬 개발용 격리 수준 — 커널은 이 서버와 같은 권한의 프로세스다.
  회사 배포 시에는 이 서버를 컨테이너(네트워크는 Coris API 만 허용, CPU · 메모리 제한) 안에서 띄운다.

실행:
    cd mcp_servers/code_interpreter && .venv/bin/python server.py      # http://localhost:8120/mcp
"""
import atexit
import base64
import json
import logging
import os
import queue
import re
import shutil
import threading
import time
from functools import partial
from pathlib import Path
from typing import Optional

import anyio
from jupyter_client.manager import KernelManager
from mcp.server.fastmcp import FastMCP

log = logging.getLogger("code_interpreter")

HOST = os.getenv("MCP_HOST", "127.0.0.1")
PORT = int(os.getenv("MCP_PORT", "8120"))
WORKDIR = Path(os.getenv("CI_WORKDIR") or Path(__file__).resolve().parent / "workspace")
ARTIFACT_DIR = WORKDIR / "artifacts"
SESSION_DIR = WORKDIR / "sessions"
EXEC_TIMEOUT = float(os.getenv("CI_EXEC_TIMEOUT_SEC", "60"))
IDLE_SEC = float(os.getenv("CI_IDLE_SEC", "1800"))     # 이 시간 동안 안 쓴 커널은 정리
MAX_SESSIONS = int(os.getenv("CI_MAX_SESSIONS", "8"))
OUTPUT_CHARS = int(os.getenv("CI_OUTPUT_CHARS", "6000"))  # LLM 에 돌려줄 출력 길이
ERROR_TAIL_CHARS = 1500
INIT_CODE = (Path(__file__).resolve().parent / "kernel_init.py").read_text(encoding="utf-8")

_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_SID = re.compile(r"[^A-Za-z0-9_-]")
_AID = re.compile(r"^a_[0-9a-f]{12}$")
_TAG = re.compile(r"\[ARTIFACT:(a_[0-9a-f]{12})\]")

mcp = FastMCP("coris-code-interpreter", instructions="대화별 Python 실행 (pandas · numpy · plotly · matplotlib)",
              host=HOST, port=PORT, stateless_http=True)


# ── 커널 세션 ─────────────────────────────────────────────────

class Session:
    def __init__(self, sid: str):
        self.sid = sid
        self.dir = SESSION_DIR / sid
        self.dir.mkdir(parents=True, exist_ok=True)
        env = {**os.environ, "CI_ARTIFACT_DIR": str(ARTIFACT_DIR)}
        self.km = KernelManager(kernel_name="python3")
        self.km.start_kernel(cwd=str(self.dir), env=env)
        self.kc = self.km.blocking_client()
        self.kc.start_channels()
        self.kc.wait_for_ready(timeout=60)
        self.lock = threading.Lock()
        self.last_used = time.time()
        out = self.execute(INIT_CODE, timeout=60)
        if out["error"]:
            raise RuntimeError(f"커널 초기화 실패: {out['error']}")

    def execute(self, code: str, timeout: float) -> dict:
        """실행이 끝날 때까지 iopub 을 읽는다. 시간 초과면 interrupt."""
        out = {"stdout": [], "result": [], "error": None, "images": [], "timed_out": False}
        msg_id = self.kc.execute(code, store_history=True, allow_stdin=False)
        deadline = time.time() + timeout
        while True:
            remaining = deadline - time.time()
            if remaining <= 0 and not out["timed_out"]:
                out["timed_out"] = True
                self.km.interrupt_kernel()
                deadline = time.time() + 10  # interrupt 후 idle 까지 기다림
                continue
            if remaining <= 0:
                break
            try:
                msg = self.kc.get_iopub_msg(timeout=min(remaining, 1))
            except queue.Empty:
                continue
            if msg["parent_header"].get("msg_id") != msg_id:
                continue
            kind, content = msg["msg_type"], msg["content"]
            if kind == "stream":
                out["stdout"].append(content["text"])
            elif kind in ("execute_result", "display_data"):
                data = content.get("data", {})
                if "image/png" in data:
                    out["images"].append(data["image/png"])
                elif "text/plain" in data:
                    out["result"].append(data["text/plain"])
            elif kind == "error":
                out["error"] = _format_error(content)
            elif kind == "status" and content.get("execution_state") == "idle":
                break
        self.last_used = time.time()
        return out

    def close(self) -> None:
        try:
            self.kc.stop_channels()
            self.km.shutdown_kernel(now=True)
        except Exception:  # noqa: BLE001
            log.exception("kernel shutdown failed: %s", self.sid)


_sessions: dict[str, Session] = {}
_pool_lock = threading.Lock()


def _get_session(raw_sid: str) -> Session:
    sid = _SID.sub("_", raw_sid or "default")[:64] or "default"
    with _pool_lock:
        now = time.time()
        for k in [k for k, s in _sessions.items() if now - s.last_used > IDLE_SEC]:
            log.info("idle 세션 정리: %s", k)
            _sessions.pop(k).close()
        if sid not in _sessions:
            while len(_sessions) >= MAX_SESSIONS:
                oldest = min(_sessions.values(), key=lambda s: s.last_used)
                log.info("세션 수 초과 — 가장 오래된 세션 정리: %s", oldest.sid)
                _sessions.pop(oldest.sid).close()
            log.info("새 커널: %s", sid)
            _sessions[sid] = Session(sid)
        return _sessions[sid]


@atexit.register
def _shutdown_all() -> None:
    for s in list(_sessions.values()):
        s.close()


# ── 결과물 ───────────────────────────────────────────────────

def _save_image(b64png: str, title: str) -> str:
    aid = "a_" + os.urandom(6).hex()
    (ARTIFACT_DIR / f"{aid}.png").write_bytes(base64.b64decode(b64png))
    (ARTIFACT_DIR / f"{aid}.json").write_text(json.dumps({"kind": "image", "title": title}, ensure_ascii=False), encoding="utf-8")
    return aid


def _format_error(content: dict) -> str:
    """LLM 이 고칠 수 있게 — 예외 메시지를 맨 앞에, traceback 은 끝부분(실패한 줄 · 원인)만.
    앞에서 자르면 정작 중요한 마지막 예외 메시지가 잘려 같은 코드를 반복한다."""
    head = f"{content.get('ename')}: {content.get('evalue')}"
    tb = _ANSI.sub("", "\n".join(content.get("traceback") or []))
    tail = tb[-ERROR_TAIL_CHARS:]
    return f"{head}\n\n(traceback 끝부분)\n{'…' if len(tb) > ERROR_TAIL_CHARS else ''}{tail}"


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + f"\n…(이하 {len(text) - limit}자 생략 — 필요한 부분만 출력하세요)"


def _run(code: str, session_id: str) -> str:
    try:
        session = _get_session(session_id)
    except Exception as e:  # noqa: BLE001
        log.exception("session start failed")
        return f"[error]\n커널을 시작하지 못했습니다: {e}"
    with session.lock:  # 같은 대화의 실행은 순서대로
        out = session.execute(code, EXEC_TIMEOUT)

    stdout = "".join(out["stdout"])
    artifacts = _TAG.findall(stdout)
    stdout = _TAG.sub("", stdout).strip()
    artifacts += [_save_image(img, "그림") for img in out["images"]]

    parts = []
    if stdout:
        parts.append("[stdout]\n" + _clip(stdout, OUTPUT_CHARS))
    if out["result"]:
        parts.append("[result]\n" + _clip("\n".join(out["result"]), OUTPUT_CHARS))
    if out["timed_out"]:
        parts.append(f"[error]\n실행 시간 {EXEC_TIMEOUT:.0f}초를 넘어 중단했습니다. 데이터를 줄이거나 나눠서 실행하세요.")
    elif out["error"]:
        parts.append("[error]\n" + out["error"])
    if artifacts:
        parts.append("[결과물] 아래 태그를 답변에 그대로 넣으면 화면에 보입니다\n" + "\n".join(f"[ARTIFACT:{a}]" for a in artifacts))
    return "\n\n".join(parts) or "(출력 없음 — 확인할 값은 print 하세요)"


# ── tool ─────────────────────────────────────────────────────

@mcp.tool(structured_output=False)
async def run_python(code: str, session_id: str = "") -> str:
    """Python 코드를 실행하고 출력 · 마지막 식의 값 · 오류를 돌려준다. 같은 대화에서는 변수와 import 가 유지된다.

    언제 사용: 계산 · 통계 · 데이터 가공, 기본 차트 카드에 없는 형태의 차트(이동평균, 설비 간 차이, 분포 등).
    사용 가능: pandas, numpy, plotly, matplotlib
    도우미 함수:
      - load_ref(data_ref) → 다른 tool 결과의 data_ref 데이터를 DataFrame(x, series, value)으로
      - save_html(fig, "제목") → plotly Figure 를 대화형 차트 결과물로 저장 ([ARTIFACT:id] 생성)
    자주 쓰는 패턴 (load_ref 결과는 long 형식: x, series, value):
      df = load_ref(ref).sort_values("x")
      df["ma"] = (df.set_index("x").groupby("series")["value"]
                  .transform(lambda s: s.rolling("7D").mean()).values)   # "7일" 은 시간 창 — rolling(7) 은 7개 점
      fig = px.line(df, x="x", y="ma", color="series")      # groupby().apply() 대신 transform 을 쓴다
      wide = df.pivot(index="x", columns="series", values="value")   # 설비별 열이 필요할 때

    Args:
        code: 실행할 Python 코드
    """
    return await anyio.to_thread.run_sync(partial(_run, code, session_id))


@mcp.tool(structured_output=False)
def ui_artifact(artifact_id: str) -> str:
    """[화면 전용] run_python 이 만든 결과물 — HTML 또는 이미지(base64)."""
    if not _AID.match(artifact_id):
        return json.dumps({"kind": "missing", "title": "잘못된 결과물 id"}, ensure_ascii=False)
    meta_path = ARTIFACT_DIR / f"{artifact_id}.json"
    if not meta_path.exists():
        return json.dumps({"kind": "missing", "title": "결과물이 없습니다 (정리되었거나 다른 서버)"}, ensure_ascii=False)
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    if meta["kind"] == "html":
        meta["html"] = (ARTIFACT_DIR / f"{artifact_id}.html").read_text(encoding="utf-8")
    else:
        meta["mime"] = "image/png"
        meta["data"] = base64.b64encode((ARTIFACT_DIR / f"{artifact_id}.png").read_bytes()).decode()
    return json.dumps(meta, ensure_ascii=False)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    shutil.rmtree(SESSION_DIR, ignore_errors=True)  # 지난 실행의 세션 폴더 — 커널은 이미 없다
    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    log.info("code interpreter MCP: http://%s:%d/mcp (workspace=%s)", HOST, PORT, WORKDIR)
    mcp.run(transport="streamable-http")
