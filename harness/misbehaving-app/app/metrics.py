"""Small Prometheus exposition helper for deterministic tests and runtime."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field


BUCKETS_SECONDS = (0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5)


@dataclass
class MetricsStore:
    version: str
    deploy_time: str
    requests: dict[tuple[str, str], int] = field(default_factory=lambda: defaultdict(int))
    durations: dict[str, list[float]] = field(default_factory=lambda: defaultdict(list))

    def observe_request(self, *, route: str, status: int, duration_ms: int) -> None:
        self.requests[(route, str(status))] += 1
        self.durations[route].append(duration_ms / 1000.0)

    def render(self) -> str:
        lines = [
            "# HELP http_requests_total Total HTTP requests by route and status",
            "# TYPE http_requests_total counter",
        ]
        for (route, status), count in sorted(self.requests.items()):
            lines.append(f'http_requests_total{{route="{route}",status="{status}"}} {count}')

        lines.extend(
            [
                "# HELP http_request_duration_seconds Request duration histogram by route",
                "# TYPE http_request_duration_seconds histogram",
            ]
        )
        for route, values in sorted(self.durations.items()):
            total = 0
            for bucket in BUCKETS_SECONDS:
                count = sum(1 for value in values if value <= bucket)
                total = max(total, count)
                lines.append(
                    f'http_request_duration_seconds_bucket{{route="{route}",le="{_format_bucket(bucket)}"}} {count}'
                )
            lines.append(f'http_request_duration_seconds_bucket{{route="{route}",le="+Inf"}} {len(values)}')
            lines.append(f'http_request_duration_seconds_count{{route="{route}"}} {len(values)}')
            lines.append(f'http_request_duration_seconds_sum{{route="{route}"}} {sum(values):.6f}')

        lines.extend(
            [
                "# HELP app_info Application metadata (version, deploy time)",
                "# TYPE app_info gauge",
                f'app_info{{version="{self.version}",deploy_time="{self.deploy_time}"}} 1',
            ]
        )
        return "\n".join(lines) + "\n"


def _format_bucket(value: float) -> str:
    return f"{value:g}"

