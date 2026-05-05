"""FastAPI entrypoint for the misbehaving app."""

from __future__ import annotations

import asyncio
import json
import sys
import time

from fastapi import FastAPI, Response
from fastapi.responses import JSONResponse, PlainTextResponse

from .config import load_settings
from .handlers import checkout_outcome, readiness_status
from .metrics import MetricsStore


SETTINGS = load_settings()
STARTED_AT = time.monotonic()
METRICS = MetricsStore(version=SETTINGS.version, deploy_time=SETTINGS.deploy_time)

app = FastAPI(title="misbehaving-app")


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/readyz")
def readyz() -> Response:
    status = readiness_status(SETTINGS, started_at=STARTED_AT, now=time.monotonic())
    if status == 200:
        return JSONResponse({"status": "ready"}, status_code=200)
    return JSONResponse({"status": "warming"}, status_code=503)


@app.get("/api/v1/{resource}/{order_id}")
async def checkout(resource: str, order_id: str) -> Response:
    del resource
    outcome = checkout_outcome(SETTINGS, order_id)
    await asyncio.sleep(outcome.duration_ms / 1000.0)
    METRICS.observe_request(route=SETTINGS.route_label, status=outcome.status_code, duration_ms=outcome.duration_ms)
    for record in outcome.logs:
        print(json.dumps(record, sort_keys=True), file=sys.stdout, flush=True)
    return JSONResponse(outcome.body, status_code=outcome.status_code)


@app.get("/metrics")
def metrics() -> Response:
    return PlainTextResponse(METRICS.render(), media_type="text/plain; version=0.0.4")
