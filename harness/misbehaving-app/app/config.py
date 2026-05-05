"""Runtime settings for the misbehaving app."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Mapping


DEFAULT_VERSION = "v0.0.0"


@dataclass(frozen=True)
class Settings:
    service_name: str = "checkout-api"
    route_label: str = "/api/v1/checkout"
    fivexx_ratio: float = 0.0
    latency_base_ms: int = 25
    latency_p99_ms: int = 50
    deploy_time: str = ""
    version: str = DEFAULT_VERSION
    ready_delay_seconds: int = 0
    dependency_5xx_ratio: float = 0.0
    dependency_name: str = "checkout-db"
    dependency_latency_ms: int = 0
    error_message: str = "upstream_unavailable"


def load_settings(environ: Mapping[str, str] | None = None) -> Settings:
    env = environ or os.environ
    settings = Settings(
        service_name=str(env.get("MISBEHAVE_SERVICE_NAME") or "checkout-api"),
        route_label=_route_label(env.get("MISBEHAVE_ROUTE_LABEL") or "/api/v1/checkout"),
        fivexx_ratio=_ratio(env.get("MISBEHAVE_5XX_RATIO"), "MISBEHAVE_5XX_RATIO"),
        latency_base_ms=_non_negative_int(env.get("MISBEHAVE_LATENCY_BASE_MS"), "MISBEHAVE_LATENCY_BASE_MS", 25),
        latency_p99_ms=_non_negative_int(env.get("MISBEHAVE_LATENCY_P99_MS"), "MISBEHAVE_LATENCY_P99_MS", 50),
        deploy_time=str(env.get("MISBEHAVE_DEPLOY_TIME") or _utc_now_iso()),
        version=str(env.get("MISBEHAVE_VERSION") or DEFAULT_VERSION),
        ready_delay_seconds=_non_negative_int(
            env.get("MISBEHAVE_READY_DELAY_S"),
            "MISBEHAVE_READY_DELAY_S",
            0,
        ),
        dependency_5xx_ratio=_ratio(
            env.get("MISBEHAVE_DEPENDENCY_5XX_RATIO"),
            "MISBEHAVE_DEPENDENCY_5XX_RATIO",
        ),
        dependency_name=str(env.get("MISBEHAVE_DEPENDENCY_NAME") or "checkout-db"),
        dependency_latency_ms=_non_negative_int(
            env.get("MISBEHAVE_DEPENDENCY_LATENCY_MS"),
            "MISBEHAVE_DEPENDENCY_LATENCY_MS",
            0,
        ),
        error_message=str(env.get("MISBEHAVE_ERROR_MESSAGE") or "upstream_unavailable"),
    )
    if settings.latency_p99_ms < settings.latency_base_ms:
        raise ValueError("MISBEHAVE_LATENCY_P99_MS must be >= MISBEHAVE_LATENCY_BASE_MS")
    return settings


def _ratio(value: str | None, name: str) -> float:
    if value in (None, ""):
        return 0.0
    parsed = float(value)
    if parsed < 0.0 or parsed > 1.0:
        raise ValueError(f"{name} must be between 0 and 1")
    return parsed


def _non_negative_int(value: str | None, name: str, default: int) -> int:
    if value in (None, ""):
        return default
    parsed = int(value)
    if parsed < 0:
        raise ValueError(f"{name} must be non-negative")
    return parsed


def _route_label(value: str) -> str:
    normalized = value.strip()
    if not normalized.startswith("/"):
        normalized = f"/{normalized}"
    return normalized.rstrip("/") or "/api/v1/checkout"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
