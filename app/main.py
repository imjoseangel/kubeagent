import uvicorn
from fastapi import FastAPI

from app.routers import diagnose, k8s_health

app = FastAPI(title="kubeagent")
app.include_router(k8s_health.router)
app.include_router(diagnose.router)


@app.get("/")
async def root() -> dict:
    return {"message": "kubeagent - Kubernetes troubleshooting agent"}


if __name__ == "__main__":
    uvicorn.run(app=app, host="0.0.0.0", port=8000)
