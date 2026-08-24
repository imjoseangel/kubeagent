import asyncio
import contextlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from app.core.config import settings
from app.health_server import Heartbeat, start_health_server
from app.persistence.store import store
from app.routers import diagnose


async def _beat_forever(heartbeat: Heartbeat) -> None:
    while True:
        heartbeat.beat()
        await asyncio.sleep(settings.heartbeat_interval_seconds)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    heartbeat = Heartbeat()
    heartbeat.beat()
    health_server = start_health_server(
        settings.health_port, heartbeat, store, settings.health_stale_seconds
    )
    beat_task = asyncio.create_task(_beat_forever(heartbeat))
    try:
        yield
    finally:
        beat_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await beat_task
        health_server.shutdown()


app = FastAPI(title="kubeagent", lifespan=lifespan)
app.include_router(diagnose.router)


@app.get("/")
async def root() -> dict:
    return {"message": "kubeagent - Kubernetes troubleshooting agent"}


if __name__ == "__main__":
    uvicorn.run(app=app, host="0.0.0.0", port=8000)
