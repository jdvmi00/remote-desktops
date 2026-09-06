"""Local backend overhead only; isolated fake environment, no real streaming.

Run after cargo build --release:
REMOTE_DESKTOPS_BIN=target/release/remote-desktops python3 tests/benchmark.py
"""
import json
import os
from pathlib import Path
import platform
import socket
import statistics
import time

from integration import BackendTests, BIN


def cpu_ticks(pid):
    fields = Path(f"/proc/{pid}/stat").read_text().rsplit(") ", 1)[1].split()
    return int(fields[11]) + int(fields[12])


def main():
    fixture = BackendTests()
    fixture.setUp()
    try:
        pid = fixture.daemon.pid
        time.sleep(.2)
        before = cpu_ticks(pid)
        started = time.monotonic()
        time.sleep(3)
        elapsed = time.monotonic() - started
        ticks = cpu_ticks(pid) - before
        memory = dict(line.split(":", 1) for line in Path(f"/proc/{pid}/status").read_text().splitlines())
        timings = []
        for _ in range(100):
            started = time.perf_counter_ns()
            with socket.socket(socket.AF_UNIX) as connection:
                connection.settimeout(2)
                connection.connect(str(fixture.root / "runtime/remote-desktops/control.sock"))
                connection.sendall(b'{"command":"status"}\n')
                with connection.makefile("rb") as response:
                    assert json.loads(response.readline())["ok"] is True
            timings.append((time.perf_counter_ns() - started) / 1_000_000)
        print(json.dumps({
            "environment": platform.platform(),
            "binary_bytes": BIN.stat().st_size,
            "idle_rss": memory["VmRSS"].strip(),
            "idle_observation_seconds": round(elapsed, 3),
            "idle_cpu_ticks": ticks,
            "clock_ticks_per_second": os.sysconf("SC_CLK_TCK"),
            "status_socket_samples": len(timings),
            "status_socket_p50_ms": round(statistics.median(timings), 3),
            "status_socket_p95_ms": round(sorted(timings)[94], 3),
            "scope": "Empty daemon, no compositor or active clients; excludes CLI startup and streaming",
        }, indent=2))
    finally:
        fixture.tearDown()


if __name__ == "__main__":
    main()
