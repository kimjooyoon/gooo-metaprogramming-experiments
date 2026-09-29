#!/usr/bin/env python3
"""Run a cohort while sampling a separate local Laya server with macOS ps."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen


def ps_cpu_seconds(value: str) -> float:
    days = 0
    if "-" in value:
        day_text, value = value.split("-", 1)
        days = int(day_text)
    parts = value.split(":")
    if len(parts) == 3:
        hours, minutes, seconds = int(parts[0]), int(parts[1]), float(parts[2])
    elif len(parts) == 2:
        hours, minutes, seconds = 0, int(parts[0]), float(parts[1])
    else:
        raise ValueError(f"unrecognized ps CPU-time value: {value!r}")
    return days * 86400 + hours * 3600 + minutes * 60 + seconds


def process_sample(pid: int) -> tuple[float, int] | None:
    result = subprocess.run(
        ["ps", "-p", str(pid), "-o", "time=", "-o", "rss="],
        capture_output=True,
        text=True,
        check=False,
    )
    fields = result.stdout.split()
    if result.returncode != 0 or len(fields) < 2:
        return None
    return ps_cpu_seconds(fields[0]), int(fields[1]) * 1024


def health_snapshot(url: str) -> dict[str, Any] | None:
    try:
        with urlopen(url, timeout=2) as response:
            payload = json.loads(response.read())
        return payload if isinstance(payload, dict) else None
    except (URLError, TimeoutError, json.JSONDecodeError):
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", type=int, required=True, help="Laya server PID")
    parser.add_argument("--health-url", required=True, help="Laya /health URL")
    parser.add_argument("--report-file", default="body-codegen-report.json")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--interval-ms", type=int, default=250)
    parser.add_argument("command", nargs=argparse.REMAINDER, help="cohort command after --")
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command or args.interval_ms < 50:
        parser.error("provide a command after -- and an interval of at least 50 ms")

    before = process_sample(args.pid)
    if before is None:
        parser.error(f"Laya server PID {args.pid} is not running")
    health_before = health_snapshot(args.health_url)
    started = time.monotonic()
    child = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    samples = 0
    peak_rss = before[1]
    final = before
    try:
        while child.poll() is None:
            current = process_sample(args.pid)
            if current is not None:
                final = current
                peak_rss = max(peak_rss, current[1])
                samples += 1
            time.sleep(args.interval_ms / 1000)
        stdout, stderr = child.communicate()
    except BaseException:
        child.terminate()
        child.wait()
        raise
    after = process_sample(args.pid)
    if after is not None:
        final = after
        peak_rss = max(peak_rss, after[1])
        samples += 1
    elapsed = time.monotonic() - started
    cpu_seconds = max(0.0, final[0] - before[0])
    logical_cpus = os.cpu_count() or 1
    health_after = health_snapshot(args.health_url)
    health = health_after or health_before or {}
    revisions = health.get("revisions") or {}
    observation = {
        "schema": "gooo/laya-server-process-observation/v1",
        "report_file": Path(args.report_file).name,
        "pid": args.pid,
        "device": health.get("device", "unknown"),
        "model_revision": revisions.get("multilingual", "unknown"),
        "logical_cpu_count": logical_cpus,
        "process_cpu_seconds": round(cpu_seconds, 3),
        "wall_elapsed_seconds": round(elapsed, 3),
        "average_cpu_percent_one_core": round(100 * cpu_seconds / max(elapsed, 1e-9), 2),
        "average_cpu_percent_host": round(100 * cpu_seconds / max(elapsed * logical_cpus, 1e-9), 2),
        "rss_before_bytes": before[1],
        "rss_after_bytes": final[1],
        "rss_peak_sampled_bytes": peak_rss,
        "samples": samples,
        "sampling_interval_ms": args.interval_ms,
        "scope": "separate local Laya server process; excluded from cohort child CPU and RSS totals",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(observation, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if stdout:
        print(stdout, end="")
    if stderr:
        print(stderr, file=sys.stderr, end="")
    print(json.dumps(observation, indent=2, sort_keys=True))
    return child.returncode


if __name__ == "__main__":
    raise SystemExit(main())
