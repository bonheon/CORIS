import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

from routers.chat import router as chat_router  # noqa: E402
from routers.hub import router as hub_router  # noqa: E402
from routers.ui import router as ui_router  # noqa: E402
from hub import catalog, skills  # noqa: E402
from hub.service import scheduler_loop  # noqa: E402

log = logging.getLogger("main")


async def mcp_refresh_loop(interval_s: int) -> None:
    """MCP 서버가 백엔드보다 늦게 뜨거나 재시작돼도 tool 목록이 따라오도록 주기적으로 다시 받는다."""
    while True:
        await asyncio.sleep(interval_s)
        try:
            await catalog.refresh()
        except Exception:  # noqa: BLE001 — 갱신 실패로 서버가 죽으면 안 된다
            log.exception("MCP refresh failed")


@asynccontextmanager
async def lifespan(_: FastAPI):
    skills.migrate_from_store()  # 예전 hub.json skill → skills/<id>/SKILL.md (남은 게 있을 때만)
    try:
        await catalog.refresh()
    except Exception:  # noqa: BLE001 — MCP 설정 오류여도 기동은 한다 (tool 없이)
        log.exception("MCP initial load failed")
    tasks = [asyncio.create_task(mcp_refresh_loop(int(os.getenv("MCP_REFRESH_SEC", "60"))))]
    # 이벤터 자동 실행은 OpenAI 호출 비용이 드므로 명시적으로 켤 때만 동작
    if os.getenv("HUB_SCHEDULER") == "1":
        tasks.append(asyncio.create_task(scheduler_loop()))
    yield
    for t in tasks:
        t.cancel()


app = FastAPI(title="Coris API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat_router)
app.include_router(hub_router)
app.include_router(ui_router)


@app.get("/health")
def health():
    return {"status": "ok"}
