#!/usr/bin/env python3
from __future__ import annotations

import concurrent.futures
import json
import os
import random
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


def build_targets(templates: dict[str, str], *, release: str, namespace: str) -> dict[str, str]:
    return {
        name: template.format(release=release, namespace=namespace).rstrip("/")
        for name, template in templates.items()
    }


def generate_plan(
    profile: dict[str, Any],
    targets: dict[str, str],
    *,
    duration_seconds: int,
    preview_limit: int | None = None,
) -> dict[str, Any]:
    seed = int(profile["seed"])
    rps = float(profile["rps"])
    total_requests = max(1, int(round(rps * duration_seconds)))
    rng = random.Random(seed)
    traffic_mix = profile["trafficMix"]
    retry_behavior = profile["retryBehavior"]

    requests: list[dict[str, Any]] = []
    counts = {name: 0 for name in traffic_mix}
    limit = total_requests if preview_limit is None else min(total_requests, preview_limit)
    selected_routes: list[str] = []
    for index in range(total_requests):
        route = _choose_route(rng, traffic_mix)
        counts[route] += 1
        if index < limit:
            selected_routes.append(route)

    for index, route in enumerate(selected_routes):
        order_id = f"{seed}-{index:06d}-{route}"
        requests.append(
            {
                "index": index,
                "due_ms": int(index * 1000 / rps),
                "route": route,
                "url": f"{targets[route]}/{order_id}",
                "order_id": order_id,
            }
        )

    return {
        "seed": seed,
        "warmup_seconds": int(profile["warmupSeconds"]),
        "rps": rps,
        "concurrency": int(profile["concurrency"]),
        "duration_seconds": duration_seconds,
        "total_requests": total_requests,
        "preview_limit": limit,
        "traffic_mix": traffic_mix,
        "dependency_fanout": profile["dependencyFanout"],
        "retry_behavior": retry_behavior,
        "counts_by_route": counts,
        "requests": requests,
    }


def run_load(profile: dict[str, Any], targets: dict[str, str], *, duration_seconds: int) -> int:
    plan = generate_plan(profile, targets, duration_seconds=duration_seconds)
    start = time.monotonic()
    warmup_seconds = plan["warmup_seconds"]
    attempts = int(_retry_value(plan["retry_behavior"], "maxAttempts", "max_attempts", default=1))
    base_delay_ms = int(_retry_value(plan["retry_behavior"], "baseDelayMs", "base_delay_ms", default=50))

    _log({"event": "loadgen_started", **_summary(plan)})
    with concurrent.futures.ThreadPoolExecutor(max_workers=plan["concurrency"]) as executor:
        futures: list[concurrent.futures.Future[dict[str, Any]]] = []
        full_plan = generate_plan(profile, targets, duration_seconds=duration_seconds, preview_limit=plan["total_requests"])
        for item in full_plan["requests"]:
            due_at = start + (item["due_ms"] / 1000.0)
            sleep_for = due_at - time.monotonic()
            if sleep_for > 0:
                time.sleep(sleep_for)
            elapsed = time.monotonic() - start
            if elapsed >= warmup_seconds and not os.environ.get("SRE_AGENT_LOADGEN_WARMUP_LOGGED"):
                os.environ["SRE_AGENT_LOADGEN_WARMUP_LOGGED"] = "1"
                _log({"event": "warmup_complete", "elapsed_seconds": round(elapsed, 3)})
            futures.append(executor.submit(_request_with_retries, item, attempts, base_delay_ms))

        failures = 0
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            if not result["ok"]:
                failures += 1
            _log(result)

    _log({"event": "loadgen_finished", "failures": failures, "total_requests": plan["total_requests"]})
    return 0


def main() -> int:
    profile_path = Path(os.environ.get("SRE_AGENT_LOADGEN_PROFILE", "/config/traffic-profile.json"))
    target_path = Path(os.environ.get("SRE_AGENT_LOADGEN_TARGETS", "/config/target-templates.json"))
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    target_templates = json.loads(target_path.read_text(encoding="utf-8"))
    release = os.environ.get("SRE_AGENT_ECOMMERCE_RELEASE", "ecommerce-lite")
    namespace = os.environ.get("SRE_AGENT_ECOMMERCE_NAMESPACE", "ecommerce")
    duration_seconds = int(os.environ.get("SRE_AGENT_LOADGEN_DURATION_SECONDS", "600"))
    preview_limit = int(os.environ.get("SRE_AGENT_LOADGEN_PREVIEW_REQUESTS", "30"))
    targets = build_targets(target_templates, release=release, namespace=namespace)

    if os.environ.get("SRE_AGENT_LOADGEN_PREVIEW_ONLY") == "1":
        print(json.dumps(generate_plan(profile, targets, duration_seconds=duration_seconds, preview_limit=preview_limit), indent=2))
        return 0
    return run_load(profile, targets, duration_seconds=duration_seconds)


def _choose_route(rng: random.Random, traffic_mix: dict[str, float]) -> str:
    total = sum(float(weight) for weight in traffic_mix.values())
    point = rng.random() * total
    cumulative = 0.0
    last_route = next(iter(traffic_mix))
    for route, weight in traffic_mix.items():
        last_route = route
        cumulative += float(weight)
        if point <= cumulative:
            return route
    return last_route


def _request_with_retries(item: dict[str, Any], attempts: int, base_delay_ms: int) -> dict[str, Any]:
    last_error = ""
    for attempt in range(1, attempts + 1):
        started = time.monotonic()
        try:
            with urllib.request.urlopen(item["url"], timeout=3) as response:
                status = response.status
                response.read()
            return {
                "event": "request",
                "ok": status < 500,
                "status": status,
                "attempt": attempt,
                "duration_ms": round((time.monotonic() - started) * 1000, 3),
                **item,
            }
        except urllib.error.HTTPError as exc:
            exc.read()
            return {
                "event": "request",
                "ok": exc.code < 500,
                "status": exc.code,
                "attempt": attempt,
                "duration_ms": round((time.monotonic() - started) * 1000, 3),
                **item,
            }
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = str(exc)
            if attempt < attempts:
                time.sleep((base_delay_ms / 1000.0) * (2 ** (attempt - 1)))
    return {"event": "request", "ok": False, "status": 0, "attempt": attempts, "error": last_error, **item}


def _retry_value(mapping: dict[str, Any], camel: str, snake: str, *, default: int) -> Any:
    if camel in mapping:
        return mapping[camel]
    if snake in mapping:
        return mapping[snake]
    return default


def _summary(plan: dict[str, Any]) -> dict[str, Any]:
    return {
        "seed": plan["seed"],
        "rps": plan["rps"],
        "concurrency": plan["concurrency"],
        "duration_seconds": plan["duration_seconds"],
        "warmup_seconds": plan["warmup_seconds"],
        "total_requests": plan["total_requests"],
    }


def _log(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, sort_keys=True), flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
