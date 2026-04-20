"""Prometheus-style metrics counters/gauges with /metrics HTTP endpoint.

Light-weight so it runs in-process. For serious ops, scrape into a
Prometheus instance and graph in Grafana.
"""

from __future__ import annotations

import asyncio
import time
from threading import Lock


class Metrics:
    def __init__(self) -> None:
        self._counters: dict[str, float] = {}
        self._gauges: dict[str, float] = {}
        self._lock = Lock()
        self.started_at = time.time()

    def inc(self, name: str, by: float = 1.0) -> None:
        with self._lock:
            self._counters[name] = self._counters.get(name, 0) + by

    def set(self, name: str, value: float) -> None:
        with self._lock:
            self._gauges[name] = value

    def render(self) -> str:
        with self._lock:
            out = [f"# bot uptime={time.time() - self.started_at:.0f}s"]
            for name, val in sorted(self._counters.items()):
                out.append(f"bot_{name} {val}")
            for name, val in sorted(self._gauges.items()):
                out.append(f"bot_{name} {val}")
            return "\n".join(out) + "\n"


async def serve(metrics: Metrics, port: int = 9100) -> None:
    """Start a minimal /metrics HTTP server. Single-threaded, no deps."""

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            await reader.readuntil(b"\r\n\r\n")
        except Exception:
            writer.close()
            return
        body = metrics.render()
        response = (
            "HTTP/1.1 200 OK\r\n"
            "Content-Type: text/plain; version=0.0.4\r\n"
            f"Content-Length: {len(body)}\r\n"
            "Connection: close\r\n\r\n"
            + body
        )
        writer.write(response.encode())
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(handle, "0.0.0.0", port)
    async with server:
        await server.serve_forever()
