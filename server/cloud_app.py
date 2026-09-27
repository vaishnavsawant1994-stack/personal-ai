from __future__ import annotations
from contextlib import asynccontextmanager
from app.main import build_runtime
from core.config import settings
from server.api import create_app

runtime=build_runtime()

@asynccontextmanager
async def lifespan(app):
    runtime['automations'].start()
    try:
        yield
    finally:
        runtime['voice'].stop()
        runtime['automations'].stop()
        runtime['telemetry'].persist()
        runtime['apns'].close()

app=create_app(
    runtime['executor'],
    settings,
    device_registry=runtime['device_registry'],
    device_gateway=runtime['device_gateway'],
    second_brain=runtime['second_brain'],
    automations=runtime['automations'],
    runtime=runtime,
)
app.router.lifespan_context=lifespan
