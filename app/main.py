from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from app.core.config import settings
from app.health_server import start_health_server
from app.routers import diagnose


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    health_server = start_health_server(settings.health_port)
    try:
        yield
    finally:
        health_server.shutdown()


app = FastAPI(title="kubeagent", lifespan=lifespan)
app.include_router(diagnose.router)


@app.get("/")
async def root() -> dict:
    return {"message": "kubeagent - Kubernetes troubleshooting agent"}


if __name__ == "__main__":
    uvicorn.run(app=app, host="0.0.0.0", port=8000)
