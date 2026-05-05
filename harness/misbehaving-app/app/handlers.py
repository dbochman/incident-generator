"""Deterministic symptom injection for the misbehaving app."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .config import Settings


ROUTE_LABEL = "/api/v1/checkout"


@dataclass(frozen=True)
class CheckoutOutcome:
    status_code: int
    body: dict[str, Any]
    duration_ms: int
    logs: tuple[dict[str, Any], ...]
    trace_id: str


def readiness_status(settings: Settings, *, started_at: float, now: float) -> int:
    if settings.ready_delay_seconds and now - started_at < settings.ready_delay_seconds:
        return 503
    return 200


def checkout_outcome(settings: Settings, order_id: str, *, now: datetime | None = None) -> CheckoutOutcome:
    request_time = now or datetime.now(timezone.utc)
    trace_id = _trace_id(order_id)
    status_code = 503 if _selected(order_id, settings.fivexx_ratio, salt="5xx") else 200
    duration_ms = _duration_ms(settings, order_id)
    route = settings.route_label

    logs: list[dict[str, Any]] = []
    if _selected(order_id, settings.dependency_5xx_ratio, salt="dependency"):
        logs.append(
            _log_record(
                request_time,
                service=settings.service_name,
                route=route,
                level="error",
                status=status_code,
                duration_ms=duration_ms,
                order_id=order_id,
                trace_id=trace_id,
                downstream=settings.dependency_name,
                reason="connection_refused",
            )
        )
    if settings.dependency_latency_ms:
        logs.append(
            _log_record(
                request_time,
                service=settings.service_name,
                route=route,
                level="warn",
                status=status_code,
                duration_ms=duration_ms,
                order_id=order_id,
                trace_id=trace_id,
                downstream=settings.dependency_name,
                reason="slow_query",
                query_ms=settings.dependency_latency_ms,
            )
        )

    if status_code >= 500:
        body = {"error": settings.error_message}
        logs.append(
            _log_record(
                request_time,
                service=settings.service_name,
                route=route,
                level="error",
                status=status_code,
                duration_ms=duration_ms,
                order_id=order_id,
                trace_id=trace_id,
                reason="upstream_unavailable",
                message=settings.error_message,
                version=settings.version,
            )
        )
    else:
        body = {"ok": True, "order_id": order_id, "version": settings.version}
        logs.append(
            _log_record(
                request_time,
                service=settings.service_name,
                route=route,
                level="info",
                status=status_code,
                duration_ms=duration_ms,
                order_id=order_id,
                trace_id=trace_id,
                version=settings.version,
            )
        )

    return CheckoutOutcome(
        status_code=status_code,
        body=body,
        duration_ms=duration_ms,
        logs=tuple(logs),
        trace_id=trace_id,
    )


def route_label(path: str) -> str:
    if path.startswith("/api/v1/"):
        parts = path.strip("/").split("/")
        if len(parts) >= 3:
            return f"/{parts[0]}/{parts[1]}/{parts[2]}"
    return path


def _duration_ms(settings: Settings, order_id: str) -> int:
    if settings.latency_p99_ms > settings.latency_base_ms and _stable_fraction(order_id, "latency") >= 0.99:
        return settings.latency_p99_ms
    return settings.latency_base_ms


def _selected(order_id: str, ratio: float, *, salt: str) -> bool:
    if ratio <= 0.0:
        return False
    if ratio >= 1.0:
        return True
    return _stable_fraction(order_id, salt) < ratio


def _stable_fraction(value: str, salt: str) -> float:
    digest = hashlib.sha256(f"{salt}:{value}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") / 2**64


def _trace_id(order_id: str) -> str:
    return hashlib.sha256(f"trace:{order_id}".encode("utf-8")).hexdigest()[:16]


def _log_record(
    ts: datetime,
    *,
    service: str,
    route: str,
    level: str,
    status: int,
    duration_ms: int,
    order_id: str,
    trace_id: str,
    **extra: Any,
) -> dict[str, Any]:
    record = {
        "ts": ts.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "level": level,
        "service": service,
        "route": route,
        "status": status,
        "duration_ms": duration_ms,
        "order_id": order_id,
        "trace_id": trace_id,
    }
    record.update({key: value for key, value in extra.items() if value not in (None, "")})
    return record
