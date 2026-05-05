"""kubectl port-forward lifecycle helpers for live scenario evidence."""

from __future__ import annotations

import socket
import subprocess
import time
from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class ForwardedPort:
    service: str
    namespace: str
    remote_port: int
    local_port: int


class PortForwardError(RuntimeError):
    """Raised when a port-forward cannot be established."""


PopenFactory = Callable[..., Any]
PortAllocator = Callable[[], int]
ConnectionChecker = Callable[[str, int, float], bool]
Sleep = Callable[[float], None]
Clock = Callable[[], float]


class PortForwardManager:
    def __init__(
        self,
        kubeconfig_path: str,
        *,
        popen_factory: PopenFactory | None = None,
        port_allocator: PortAllocator | None = None,
        connection_checker: ConnectionChecker | None = None,
        sleep: Sleep = time.sleep,
        clock: Clock = time.monotonic,
        startup_timeout_seconds: float = 10.0,
    ) -> None:
        self.kubeconfig_path = kubeconfig_path
        self._popen = popen_factory or subprocess.Popen
        self._port_allocator = port_allocator or _allocate_unused_local_port
        self._connection_checker = connection_checker or _can_connect
        self._sleep = sleep
        self._clock = clock
        self._startup_timeout_seconds = startup_timeout_seconds
        self._processes: list[Any] = []

    def forward(self, *, service: str, namespace: str, remote_port: int) -> ForwardedPort:
        local_port = self._port_allocator()
        args = [
            "kubectl",
            f"--kubeconfig={self.kubeconfig_path}",
            "port-forward",
            "-n",
            namespace,
            f"svc/{service}",
            f"{local_port}:{remote_port}",
        ]
        process = self._popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self._processes.append(process)
        deadline = self._clock() + self._startup_timeout_seconds
        while self._clock() <= deadline:
            if _process_exited(process):
                raise PortForwardError(f"kubectl port-forward for {namespace}/{service} exited before accepting traffic")
            if self._connection_checker("127.0.0.1", local_port, 0.2):
                return ForwardedPort(
                    service=service,
                    namespace=namespace,
                    remote_port=remote_port,
                    local_port=local_port,
                )
            self._sleep(0.1)
        self._terminate_process(process)
        raise PortForwardError(f"kubectl port-forward for {namespace}/{service} did not accept traffic within 10s")

    def stop_all(self) -> None:
        for process in list(self._processes):
            self._terminate_process(process)
        self._processes.clear()

    def _terminate_process(self, process: Any) -> None:
        if _process_exited(process):
            return
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def _allocate_unused_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _can_connect(host: str, port: int, timeout: float) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _process_exited(process: Any) -> bool:
    return process.poll() is not None
