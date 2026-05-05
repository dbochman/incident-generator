from __future__ import annotations

from datetime import datetime, timezone
from threading import Lock
from typing import Any

from fastapi import FastAPI, Request
from pydantic import BaseModel, Field


class PagerDutyEvent(BaseModel):
    routing_key: str | None = None
    event_action: str | None = None
    dedup_key: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    links: list[dict[str, Any]] = Field(default_factory=list)
    images: list[dict[str, Any]] = Field(default_factory=list)
    client: str | None = None
    client_url: str | None = None


app = FastAPI(title="fake-pagerduty")
_captured: list[dict[str, Any]] = []
_lock = Lock()


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/v2/enqueue")
async def enqueue(event: PagerDutyEvent, request: Request) -> dict[str, str]:
    record = event.model_dump()
    record["received_at"] = datetime.now(timezone.utc).isoformat()
    record["source_ip"] = request.client.host if request.client else None
    with _lock:
        _captured.append(record)
    return {
        "status": "success",
        "message": "Event processed",
        "dedup_key": event.dedup_key or f"fake-{len(_captured)}",
    }


@app.get("/captured")
def captured() -> dict[str, Any]:
    with _lock:
        events = list(_captured)
    return {"count": len(events), "events": events}


@app.delete("/captured")
def clear() -> dict[str, int]:
    with _lock:
        count = len(_captured)
        _captured.clear()
    return {"deleted": count}
