"""
응답 시간 측정 — 질문 하나가 어디서 시간을 쓰는지 나눠 기록한다 (docs/TIMING.md).

Coris 다른 모듈에 기대지 않는다 — 회사판에 파일째 복사해서 쓴다.

질문마다 한 줄 요약(로그) + JSON 한 줄(TIMING_LOG 파일)을 남긴다.
  구간(span)   직접 감싼 구간 — db.* · router · agent · suggest 등. 이름이 db. 로 시작하면 DB 합계에 들어간다
  LLM          LangChain 으로 부른 모든 LLM 호출 — 모델 · 걸린 시간 · 첫 토큰까지 · 입력 길이 · tool 호출 수
  tool         tool 실행 시간
  화면 이벤트  첫 글자(delta)까지 · delta 개수 · delta 사이 최대 간격
  loop 멈춤    서버 event loop 가 막힌 시간 — async 함수 안의 동기 DB 호출 · 무거운 계산이 있으면 커진다.
               이 값이 크면 그동안 **모든 사용자**의 스트리밍이 멈춘다

쓰는 법
    t = timing.Timing("chat", conv=conv_id)          # 질문 시작
    timing.activate(t)                               # 이 안에서 부르는 LangChain LLM · tool 이 자동으로 기록된다
    async with t.span("db.load_history"): ...        # 구간 (with 도 된다)
    t.event("delta")                                 # 화면으로 이벤트를 보낼 때
    t.finish()                                       # 끝 — 로그 · 파일에 남긴다
    timing.start_loop_monitor()                      # 서버 기동 시 한 번 (lifespan)
"""
import asyncio
import contextvars
import json
import logging
import os
import time
import uuid
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

ENABLED = os.getenv("TIMING", "1") != "0"
LOG_PATH = os.getenv("TIMING_LOG", "")                # 비우면 로그만. 경로면 JSON 한 줄씩 추가 (예: data/timing.jsonl)
LAG_MS = int(os.getenv("TIMING_LAG_MS", "50"))        # 이보다 긴 event loop 멈춤만 기록

log = logging.getLogger("timing")
_current: contextvars.ContextVar = contextvars.ContextVar("coris_timing", default=None)


def now() -> float:
    return time.perf_counter()


def _ms(sec: float) -> int:
    return round(sec * 1000)


# ── event loop 멈춤 감시 ─────────────────────────────────────────
# 50ms 마다 깨어나도록 잠들고, 실제로 늦게 깬 만큼이 '멈춤' — 그 사이 loop 를 누가 붙잡고 있었다는 뜻

_lags: deque = deque(maxlen=5000)   # (시각, ms)
_monitor: Optional[asyncio.Task] = None


async def _loop_monitor(interval: float = 0.05) -> None:
    while True:
        t = now()
        await asyncio.sleep(interval)
        lag = _ms(now() - t - interval)
        if lag >= LAG_MS:
            _lags.append((now(), lag))


def start_loop_monitor() -> Optional[asyncio.Task]:
    global _monitor
    if ENABLED and _monitor is None:
        _monitor = asyncio.get_running_loop().create_task(_loop_monitor())
    return _monitor


def _lags_between(t0: float, t1: float) -> list:
    return [ms for t, ms in _lags if t0 <= t <= t1]


# ── 질문 하나의 기록 ────────────────────────────────────────────

class _Span:
    def __init__(self, t: "Timing", name: str):
        self.t, self.name = t, name

    def __enter__(self):
        self.t0 = now()
        return self

    def __exit__(self, *exc):
        self.t.add(self.name, now() - self.t0)
        return False

    async def __aenter__(self):
        return self.__enter__()

    async def __aexit__(self, *exc):
        return self.__exit__(*exc)


class Timing:
    def __init__(self, kind: str, t0: Optional[float] = None, **meta: Any):
        self.id = uuid.uuid4().hex[:8]
        self.kind, self.meta = kind, meta
        self.t0 = t0 or now()
        self.started_at = datetime.now().isoformat(timespec="seconds")
        self.spans: dict = {}
        self.marks: dict = {}
        self.llm: list = []
        self.tools: list = []
        self.deltas = 0
        self._last_delta: Optional[float] = None
        self.max_delta_gap = 0
        self.done = False

    def span(self, name: str) -> _Span:
        return _Span(self, name)

    def add(self, name: str, sec: float) -> None:
        self.spans.setdefault(name, []).append(_ms(sec))

    def mark(self, name: str) -> None:
        """처음 한 번만 — 시작부터 몇 ms 인지."""
        self.marks.setdefault(name, _ms(now() - self.t0))

    def event(self, kind: str) -> None:
        """화면으로 이벤트를 보낼 때 (서버가 만든 시각 — 화면에 닿은 시각은 scripts/measure_stream.py 로)."""
        self.mark(f"first_{kind}")
        if kind == "delta":
            t = now()
            if self._last_delta is not None:
                self.max_delta_gap = max(self.max_delta_gap, _ms(t - self._last_delta))
            self._last_delta = t
            self.deltas += 1

    def summary(self) -> dict:
        end = now()
        lags = _lags_between(self.t0, end)
        db = {k: sum(v) for k, v in self.spans.items() if k.startswith("db.")}
        return {
            "id": self.id, "kind": self.kind, "at": self.started_at, **self.meta,
            "total_ms": _ms(end - self.t0),
            "first_delta_ms": self.marks.get("first_delta"),
            "marks": self.marks,
            "spans": {k: (v[0] if len(v) == 1 else {"n": len(v), "ms": sum(v)}) for k, v in self.spans.items()},
            "db_ms": sum(db.values()),
            "llm_n": len(self.llm), "llm_ms": sum(x["ms"] for x in self.llm), "llm": self.llm,
            "tool_n": len(self.tools), "tool_ms": sum(x["ms"] for x in self.tools), "tools": self.tools,
            "deltas": self.deltas, "max_delta_gap_ms": self.max_delta_gap,
            "loop_stall_n": len(lags), "loop_stall_max_ms": max(lags, default=0), "loop_stall_sum_ms": sum(lags),
        }

    def finish(self, status: str = "ok") -> Optional[dict]:
        if self.done or not ENABLED:
            return None
        self.done = True
        s = self.summary() | {"status": status}
        log.info(_line(s))
        if LOG_PATH:
            try:
                p = Path(LOG_PATH)
                p.parent.mkdir(parents=True, exist_ok=True)
                with p.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(s, ensure_ascii=False) + "\n")
            except OSError:
                log.exception("timing 파일 기록 실패: %s", LOG_PATH)
        return s


def _sec(ms: Optional[int]) -> str:
    return "-" if ms is None else f"{ms / 1000:.1f}s"


def _line(s: dict) -> str:
    """사람이 읽는 한 줄 — 상세는 JSON(TIMING_LOG)."""
    by_model: dict = {}
    for x in s["llm"]:
        by_model.setdefault(x["model"], []).append(x["ms"])
    llm = ", ".join(f"{m} {len(v)}회 {_sec(sum(v))}" for m, v in by_model.items()) or "없음"
    spans = " ".join(f"{k}={_sec(v if isinstance(v, int) else v['ms'])}" for k, v in s["spans"].items())
    return (f"[timing {s['id']}] {s['kind']} {s.get('conv', '')} 총 {_sec(s['total_ms'])} | 첫 글자 {_sec(s['first_delta_ms'])}"
            f" | LLM {s['llm_n']}회 {_sec(s['llm_ms'])} ({llm}) | tool {s['tool_n']}회 {_sec(s['tool_ms'])}"
            f" | DB {_sec(s['db_ms'])} | loop 멈춤 {s['loop_stall_n']}회 최대 {_sec(s['loop_stall_max_ms'])}"
            f" | delta {s['deltas']}개 최대 간격 {_sec(s['max_delta_gap_ms'])} | {spans}")


# ── LangChain 호출 자동 기록 ─────────────────────────────────────
# activate() 한 동안 그 안에서 부르는 모든 LangChain LLM · tool 에 콜백이 붙는다
# (agent 그래프 · Router · 추천 질문 등 config 를 따로 넘기지 않는 호출까지)

try:
    from langchain_core.callbacks import BaseCallbackHandler
except ImportError:  # LangChain 이 없는 곳에서도 import 는 되게
    BaseCallbackHandler = object  # type: ignore

_handler_var: contextvars.ContextVar = contextvars.ContextVar("coris_timing_handler", default=None)
try:
    from langchain_core.tracers.context import register_configure_hook
    register_configure_hook(_handler_var, True)
    HOOKED = True
except Exception:  # noqa: BLE001 — 버전이 달라 없으면 callbacks() 를 config 에 직접 넣는다
    HOOKED = False


def _model_name(serialized: Optional[dict], kw: dict) -> str:
    meta = kw.get("metadata") or {}
    sk = (serialized or {}).get("kwargs") or {}
    return meta.get("ls_model_name") or sk.get("model_name") or sk.get("model") or "llm"


class Callback(BaseCallbackHandler):
    run_inline = True   # 스레드로 넘기지 않고 바로 — 측정이 측정 대상을 늦추지 않게

    def __init__(self, t: Timing):
        self.t = t
        self.runs: dict = {}

    # LLM
    def on_chat_model_start(self, serialized, messages, *, run_id, **kw):
        chars = sum(len(str(m.content)) + len(json.dumps(getattr(m, "tool_calls", None) or [], default=str))
                    for batch in messages for m in batch)
        self.runs[run_id] = {"model": _model_name(serialized, kw), "t0": now(), "first": None, "chunks": 0,
                             "msgs": sum(len(b) for b in messages), "in_chars": chars}

    def on_llm_start(self, serialized, prompts, *, run_id, **kw):
        self.runs[run_id] = {"model": _model_name(serialized, kw), "t0": now(), "first": None, "chunks": 0,
                             "msgs": len(prompts), "in_chars": sum(len(p) for p in prompts)}

    def on_llm_new_token(self, token, *, run_id, **kw):
        r = self.runs.get(run_id)
        if r is not None:
            r["chunks"] += 1
            if r["first"] is None:
                r["first"] = now()

    def _end_llm(self, run_id, response=None, error=None):
        r = self.runs.pop(run_id, None)
        if r is None or self.t.done:
            return
        rec = {"model": r["model"], "ms": _ms(now() - r["t0"]),
               "first_token_ms": _ms(r["first"] - r["t0"]) if r["first"] else None,
               "msgs": r["msgs"], "in_chars": r["in_chars"], "chunks": r["chunks"]}
        try:
            msg = response.generations[0][0].message
            rec["tool_calls"] = len(getattr(msg, "tool_calls", None) or [])
            usage = getattr(msg, "usage_metadata", None) or (response.llm_output or {}).get("token_usage") or {}
            if usage:
                rec["in_tok"] = usage.get("input_tokens") or usage.get("prompt_tokens")
                rec["out_tok"] = usage.get("output_tokens") or usage.get("completion_tokens")
        except Exception:  # noqa: BLE001 — 응답 형식이 달라도 시간 기록은 남긴다
            pass
        if error is not None:
            rec["error"] = str(error)[:200]
        self.t.llm.append(rec)

    def on_llm_end(self, response, *, run_id, **kw):
        self._end_llm(run_id, response=response)

    def on_llm_error(self, error, *, run_id, **kw):
        self._end_llm(run_id, error=error)

    # tool
    def on_tool_start(self, serialized, input_str, *, run_id, **kw):
        self.runs[run_id] = {"name": (serialized or {}).get("name") or kw.get("name") or "tool", "t0": now()}

    def _end_tool(self, run_id, ok: bool):
        r = self.runs.pop(run_id, None)
        if r is not None and not self.t.done:
            self.t.tools.append({"name": r["name"], "ms": _ms(now() - r["t0"]), "ok": ok})

    def on_tool_end(self, output, *, run_id, **kw):
        self._end_tool(run_id, True)

    def on_tool_error(self, error, *, run_id, **kw):
        self._end_tool(run_id, False)


def activate(t: Timing) -> Timing:
    """이후 이 흐름(같은 asyncio task 와 그 안에서 만든 task)에서 부르는 LangChain 호출을 t 에 기록."""
    _current.set(t)
    if ENABLED and BaseCallbackHandler is not object:
        _handler_var.set(Callback(t))
    return t


def current() -> Optional[Timing]:
    return _current.get()


def callbacks() -> list:
    """register_configure_hook 이 없는 LangChain 버전용 — config={"callbacks": timing.callbacks()} 로 넘긴다."""
    h = _handler_var.get()
    return [h] if (h is not None and not HOOKED) else []


# ── 요청 시작 시각 (인증 · 사용자 조회 등 endpoint 이전 시간까지 재기 위해) ──

class RequestStartMiddleware:
    """순수 ASGI 미들웨어 — 스트리밍 응답을 감싸지 않는다 (BaseHTTPMiddleware 는 SSE 를 모아 보낼 수 있어 쓰지 않는다).
    endpoint 에서 request.state.t0 로 읽는다."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            scope.setdefault("state", {})["t0"] = now()
        await self.app(scope, receive, send)
