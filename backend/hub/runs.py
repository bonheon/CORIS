"""
진행 중인 답변(run) — 답변 생성을 화면 연결과 분리한다.

POST /api/chat 은 답변을 백그라운드 작업으로 시작하고, 화면은 그 작업의 이벤트를 구독만 한다.
  - 화면이 다른 대화로 옮겨 연결이 끊겨도 답변은 끝까지 만들어지고 저장된다
  - 다시 열면 GET /api/chat/{id}/stream 으로 처음부터 다시 받아 이어서 보여준다 (이벤트를 모아 둔다)
  - 대화 목록은 active() 로 '답변 중' 을 표시한다
  - 중지는 cancel() — 작업을 취소하면 그때까지의 답변이 저장된다

프로세스 메모리에만 있다 (uvicorn 단일 worker 기준). 서버가 재시작되면 진행 중이던 답변은 사라진다.
"""
import asyncio
import json
import logging
from typing import AsyncIterator, Optional

from hub import store

log = logging.getLogger("runs")

KEEP_SEC = 120   # 끝난 run 을 이 시간 동안 남겨 둔다 — 끝날 무렵 다시 연결한 화면이 마지막 이벤트를 받도록


class Run:
    def __init__(self, conv_id: str, user_id: str, user_text: str, attachments: list[dict], is_new: bool):
        self.conv_id, self.user_id, self.user_text = conv_id, user_id, user_text
        self.attachments, self.is_new = attachments, is_new
        self.started_at = store.now_iso()
        self.events: list[str] = []          # SSE 문자열 그대로
        self.done = False
        self.cond = asyncio.Condition()
        self.task: Optional[asyncio.Task] = None

    async def push(self, chunk: str) -> None:
        async with self.cond:
            self.events.append(chunk)
            self.cond.notify_all()

    async def finish(self) -> None:
        async with self.cond:
            self.done = True
            self.cond.notify_all()

    async def subscribe(self) -> AsyncIterator[str]:
        """처음부터 지금까지의 이벤트를 보내고, 끝날 때까지 새 이벤트를 이어서 보낸다."""
        i = 0
        while True:
            async with self.cond:
                while i >= len(self.events) and not self.done:
                    await self.cond.wait()
                batch, i, done = self.events[i:], len(self.events), self.done
            for chunk in batch:
                yield chunk
            if done and i >= len(self.events):
                return

    def head(self) -> dict:
        """대화 목록용 — 아직 저장 전인 새 대화도 목록에 보이게."""
        title = " ".join(self.user_text.split())[:40] or "새 대화"
        return {"id": self.conv_id, "title": title, "source": "chat", "event_id": None, "agent_id": "auto",
                "skill_id": None, "summary": "답변 중…", "created_at": self.started_at,
                "updated_at": self.started_at, "turns": 0, "status": "running"}


_runs: dict[str, Run] = {}


def _sse(payload) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


async def _drive(run: Run, source: AsyncIterator[str]) -> None:
    try:
        async for chunk in source:
            await run.push(chunk)
    except asyncio.CancelledError:
        log.info("run %s 중지됨", run.conv_id)
        await run.push(_sse({"type": "stopped"}))
        await run.push("data: [DONE]\n\n")
    except Exception as e:  # noqa: BLE001
        log.exception("run %s failed", run.conv_id)
        await run.push(_sse({"type": "error", "message": str(e)[:300]}))
        await run.push("data: [DONE]\n\n")
    finally:
        await run.finish()
        await asyncio.sleep(KEEP_SEC)
        if _runs.get(run.conv_id) is run:
            _runs.pop(run.conv_id, None)


def start(run: Run, source: AsyncIterator[str]) -> Run:
    _runs[run.conv_id] = run
    run.task = asyncio.create_task(_drive(run, source))
    return run


def get(conv_id: str) -> Optional[Run]:
    return _runs.get(conv_id)


def active(conv_id: str) -> Optional[Run]:
    r = _runs.get(conv_id)
    return r if r and not r.done else None


def active_runs() -> list[Run]:
    return [r for r in _runs.values() if not r.done]


def cancel(conv_id: str) -> bool:
    r = active(conv_id)
    if not r or not r.task:
        return False
    r.task.cancel()
    return True
