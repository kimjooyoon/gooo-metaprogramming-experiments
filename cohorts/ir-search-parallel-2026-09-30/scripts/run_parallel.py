#!/usr/bin/env python3
"""Run one pinned sequential and one simultaneous real-Laya search pair."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

HERE = Path(__file__).resolve().parent.parent
SIBLING_RUNNER = HERE.parent / "ir-search-2026-09-30" / "scripts" / "run_cohort.py"
EXPECTED_SHA = "f9f33b86c2114c1adeba01319fddb7d48f666e739aef768bbb5a580adfb7cda9"
EXPECTED_REVISION = "29d44bc778d85aee03b9af500bd83dc98f368189"
EXPECTED_LAYA_REVISION = "55cf4c4ebb4ebe31b2550e8bdf3bd21b99753851"
HARNESS_TIMEOUT_SECONDS = 60
SAMPLE_INTERVAL_SECONDS = 0.10


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


def write_json(path: Path, payload) -> None:
    write_bytes(path, (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode())


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def load_sibling_runner():
    if not SIBLING_RUNNER.is_file():
        raise RuntimeError(f"missing read-only Laya runner utility: {SIBLING_RUNNER}")
    spec = importlib.util.spec_from_file_location("ir_search_source_runner", SIBLING_RUNNER)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load sibling runner utilities")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def validate_inputs(manifest):
    if manifest.get("schema") != "gooo/ir-search-parallel-study-manifest/v1":
        raise RuntimeError("unexpected parallel cohort schema")
    if manifest.get("design", {}).get("invocation_count") != 4:
        raise RuntimeError("study must remain a four-invocation concurrency observation")
    if manifest.get("design", {}).get("replicates_per_condition") != 1:
        raise RuntimeError("study must remain one replicate per condition")
    expected_source_manifest = manifest["source_material"]["source_manifest_sha256"]
    source_manifest = HERE.parent / "ir-search-2026-09-30" / "manifest.json"
    if sha256(source_manifest.read_bytes()) != expected_source_manifest:
        raise RuntimeError("source cohort manifest changed since this study was prepared")
    if sha256(SIBLING_RUNNER.read_bytes()) != manifest["source_material"]["source_runner_sha256"]:
        raise RuntimeError("source cohort runner changed since this study was prepared")
    for intent_id in manifest["source_material"]["intents"]:
        for kind in ("fixture", "search_plan", "finite_oracle"):
            item = manifest["source_material"]["inputs"][intent_id][kind]
            path = HERE / item["path"]
            if not path.is_file() or sha256(path.read_bytes()) != item["sha256"]:
                raise RuntimeError(f"prepared input hash mismatch: {path}")
        plan = read_json(HERE / manifest["source_material"]["inputs"][intent_id]["search_plan"]["path"])
        if plan.get("schema") != "gooo/body-codegen-ir-search-plan/v1":
            raise RuntimeError(f"{intent_id}: invalid search-plan schema")
        if "holdout_test_cases" not in plan or not plan.get("test_cases"):
            raise RuntimeError(f"{intent_id}: expected nonempty training and holdout suites")
        if {c["input"] for c in plan["test_cases"]} & {c["input"] for c in plan["holdout_test_cases"]}:
            raise RuntimeError(f"{intent_id}: training and holdout inputs overlap")
    if manifest["binary"]["sha256"] != EXPECTED_SHA or manifest["binary"]["source_revision"] != EXPECTED_REVISION:
        raise RuntimeError("manifest binary pin is not the approved study binary")
    if manifest["runtime"]["revision"] != EXPECTED_LAYA_REVISION or manifest["runtime"]["threads"] != 4:
        raise RuntimeError("manifest Laya model/thread pin changed")


class ResourceSampler:
    """Sample one condition's owned server and every registered CLI PID."""
    def __init__(self, path: Path, server_pid: int, cpu_count: int, module):
        self.path = path
        self.server_pid = server_pid
        self.cpu_count = cpu_count
        self.module = module
        self.origin = time.monotonic()
        self.stop_event = threading.Event()
        self.pids = {}
        self.pids_lock = threading.Lock()
        self.write_lock = threading.Lock()
        self.rows = []
        self.thread = None

    def register_cli(self, invocation_id: str, pid: int):
        with self.pids_lock:
            self.pids[invocation_id] = pid
        self.snapshot(f"cli_registered:{invocation_id}")

    def snapshot(self, label: str):
        with self.pids_lock:
            pids = dict(self.pids)
        row = {
            "schema": "gooo/ir-search-parallel-resource-sample/v1",
            "sampled_utc": utc_now(),
            "elapsed_seconds": time.monotonic() - self.origin,
            "label": label,
            "laya_server": self.module.sample_pid(self.server_pid),
            "cli_processes": {name: self.module.sample_pid(pid) for name, pid in pids.items()},
        }
        raw = (json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n").encode()
        with self.write_lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("ab") as handle:
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
            self.rows.append(row)
        return row

    def _loop(self):
        while not self.stop_event.wait(SAMPLE_INTERVAL_SECONDS):
            self.snapshot("periodic")

    def start(self):
        self.snapshot("condition_before")
        self.thread = threading.Thread(target=self._loop, name="parallel-study-resource-sampler", daemon=True)
        self.thread.start()

    def finish(self):
        self.snapshot("condition_after")
        self.stop_event.set()
        if self.thread is not None:
            self.thread.join(timeout=3)


def kill_owned_cli(process):
    if process is None or process.poll() is not None:
        return
    try:
        if os.getpgid(process.pid) == process.pid:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                if process.poll() is None and os.getpgid(process.pid) == process.pid:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=3)
    except (ProcessLookupError, PermissionError):
        pass


def run_invocation(binary: Path, intent_id: str, condition: str, condition_dir: Path,
                   server_port: int, sampler: ResourceSampler, module, launch_barrier=None):
    inputs = read_json(HERE / "manifest.json")["source_material"]["inputs"][intent_id]
    intent_dir = condition_dir / "invocations" / intent_id
    intent_dir.mkdir(parents=True, exist_ok=False)
    fixture = HERE / inputs["fixture"]["path"]
    plan = HERE / inputs["search_plan"]["path"]
    fixture_copy, plan_copy = intent_dir / "fixture.gooo.fixture", intent_dir / "plan.json"
    write_bytes(fixture_copy, fixture.read_bytes())
    write_bytes(plan_copy, plan.read_bytes())
    activity_match = re.search(r"^activity\s+(\w+)\(", fixture_copy.read_text(encoding="utf-8"), re.MULTILINE)
    if not activity_match:
        raise RuntimeError(f"could not read activity declaration in {fixture_copy}")
    activity = activity_match.group(1)
    command = [str(binary), "body-codegen", "--json", "--fill-search", str(plan_copy),
               "--activity", activity, str(fixture_copy)]
    proxy = module.CaptureProxy("127.0.0.1", server_port, intent_dir)
    invocation_id = f"{condition}/{intent_id}"
    proxy.set_invocation(invocation_id)
    env = os.environ.copy()
    env.pop("GOOO_LAYA_API_KEY", None)
    env["GOOO_LAYA_URL"] = proxy.url
    started_utc = utc_now()
    started_mono = time.monotonic()
    process = None
    stdout = b""
    stderr = b""
    exit_code = 127
    runner_timeout = False
    runner_error = ""
    try:
        if launch_barrier is not None:
            launch_barrier.wait(timeout=15)
            started_utc = utc_now()
            started_mono = time.monotonic()
        process = subprocess.Popen(command, cwd=intent_dir, env=env, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, start_new_session=True)
        sampler.register_cli(invocation_id, process.pid)
        try:
            stdout, stderr = process.communicate(timeout=HARNESS_TIMEOUT_SECONDS)
            exit_code = process.returncode
        except subprocess.TimeoutExpired:
            runner_timeout = True
            kill_owned_cli(process)
            try:
                stdout, stderr = process.communicate(timeout=5)
                exit_code = 124
            except subprocess.TimeoutExpired as exc:
                stdout = exc.output or b""
                stderr = exc.stderr or b""
                exit_code = 124
                runner_error = "harness timeout; CLI process did not exit after owned-process termination"
    except Exception as exc:
        runner_error = f"{type(exc).__name__}: {exc}"
    finally:
        completed_utc = utc_now()
        elapsed = max(0.0, time.monotonic() - started_mono)
        proxy.set_invocation(None)
        proxy.stop()
    write_bytes(intent_dir / "stdout.raw", stdout)
    write_bytes(intent_dir / "stderr.raw", stderr)
    write_json(intent_dir / "command.json", {
        "argv": command,
        "environment": {"GOOO_LAYA_URL": proxy.url, "GOOO_LAYA_API_KEY": "unset",
                         "offline_model_calls": True},
        "harness_timeout_seconds": HARNESS_TIMEOUT_SECONDS,
    })
    events = list(proxy.events)
    plan_bytes, fixture_bytes = plan_copy.read_bytes(), fixture_copy.read_bytes()
    record = {
        "schema": "gooo/ir-search-parallel-invocation/v1",
        "invocation_id": invocation_id,
        "condition": condition,
        "intent_id": intent_id,
        "started_utc": started_utc,
        "completed_utc": completed_utc,
        "wall_ms": elapsed * 1000,
        "exit_code": exit_code,
        "harness_timeout": runner_timeout,
        "runner_error": runner_error,
        "argv": command,
        "binary_sha256": sha256(binary.read_bytes()),
        "fixture_path": inputs["fixture"]["path"],
        "fixture_sha256": sha256(fixture_bytes),
        "plan_path": inputs["search_plan"]["path"],
        "plan_sha256": sha256(plan_bytes),
        "stdout_sha256": sha256(stdout),
        "stderr_sha256": sha256(stderr),
        "proxy_event_sequences": [event["seq"] for event in events],
        "proxy_choice_events": sum(event.get("kind") == "laya_choice" for event in events),
        "raw_artifacts": {
            "stdout": "stdout.raw", "stderr": "stderr.raw", "command": "command.json",
            "resources": "../../resource-samples.jsonl", "proxy": "proxy/"
        },
    }
    write_json(intent_dir / "invocation.json", record)
    return record


def run_condition(binary: Path, condition: str, run_dir: Path, venv: Path, module, cpu_count: int):
    condition_dir = run_dir / "conditions" / condition
    condition_dir.mkdir(parents=True, exist_ok=False)
    laya_dir = condition_dir / "laya"
    laya_dir.mkdir()
    server_exe = venv / "bin" / "laya-serve"
    python_exe = venv / "bin" / "python"
    if not server_exe.is_file() or not os.access(server_exe, os.X_OK) or not python_exe.is_file():
        raise RuntimeError(f"installed Laya environment unavailable: {venv}")
    version = subprocess.run([str(python_exe), "-c", "import importlib.metadata as m; print(m.version('laya'))"],
                             capture_output=True, text=True, check=False)
    if version.returncode != 0 or version.stdout.strip() != "0.3.21":
        raise RuntimeError(f"installed Laya version mismatch: {version.stdout.strip()!r}")
    port = module.free_port()
    env = os.environ.copy()
    env.update({"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "HF_HUB_DISABLE_TELEMETRY": "1",
                "LAYA_HOST": "127.0.0.1", "LAYA_PORT": str(port), "LAYA_MODELS": "english",
                "LAYA_DEVICE": "cpu", "LAYA_THREADS": "4", "LAYA_PRELOAD": "1",
                "LAYA_MAX_CONCURRENT": "16"})
    env.pop("GOOO_LAYA_API_KEY", None)
    stdout_handle = (laya_dir / "stdout.log").open("wb")
    stderr_handle = (laya_dir / "stderr.log").open("wb")
    server = None
    sampler = None
    meta = {"schema": "gooo/ir-search-parallel-condition/v1", "condition": condition,
            "started_utc": utc_now(), "port": port, "laya_version": version.stdout.strip(),
            "status": "starting", "runtime_environment": {k: env[k] for k in (
                "HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "HF_HUB_DISABLE_TELEMETRY", "LAYA_HOST",
                "LAYA_PORT", "LAYA_MODELS", "LAYA_DEVICE", "LAYA_THREADS", "LAYA_PRELOAD", "LAYA_MAX_CONCURRENT")}}
    write_json(condition_dir / "condition.json", meta)
    invocations = []
    try:
        server = subprocess.Popen([str(server_exe)], cwd=condition_dir, env=env,
                                  stdin=subprocess.DEVNULL, stdout=stdout_handle, stderr=stderr_handle,
                                  start_new_session=True)
        pgid = server.pid
        write_json(laya_dir / "owned-process.json", {
            "schema": "gooo/ir-search-owned-process/v1", "pid": server.pid,
            "process_group_id": pgid, "started_utc": meta["started_utc"],
            "executable": str(server_exe), "owned_by_runner": True,
            "host": "127.0.0.1", "port": port,
        })
        health = module.wait_for_health(server, port, laya_dir / "health-before.json", timeout_seconds=240)
        meta["laya_health_before"] = {"device": health.get("device"), "loaded": health.get("loaded"),
                                      "revisions": health.get("revisions")}
        meta["status"] = "ready"
        write_json(condition_dir / "condition.json", meta)
        sampler = ResourceSampler(condition_dir / "resource-samples.jsonl", server.pid, cpu_count, module)
        sampler.start()
        if condition == "sequential":
            for intent_id in ("clamp", "absolute"):
                invocations.append(run_invocation(binary, intent_id, condition, condition_dir, port, sampler, module))
        elif condition == "simultaneous":
            barrier = threading.Barrier(3)
            with ThreadPoolExecutor(max_workers=2, thread_name_prefix="gooo-cli") as pool:
                futures = [pool.submit(run_invocation, binary, intent_id, condition, condition_dir,
                                       port, sampler, module, barrier)
                           for intent_id in ("clamp", "absolute")]
                barrier.wait(timeout=15)
                for future in futures:
                    invocations.append(future.result(timeout=HARNESS_TIMEOUT_SECONDS + 20))
        else:
            raise RuntimeError(f"unknown condition: {condition}")
        # Include an explicit after observation while the owned service is still alive.
        sampler.snapshot("condition_after_invocations")
        module.health_snapshot(port, laya_dir / "health-after.json")
        sampler.finish()
        meta["laya_health_after"] = read_json(laya_dir / "health-after.json")
        meta["status"] = "raw_capture_complete"
        meta["completed_utc"] = utc_now()
        meta["invocation_count"] = len(invocations)
        meta["all_invocations_exit_zero"] = len(invocations) == 2 and all(row["exit_code"] == 0 for row in invocations)
        write_json(condition_dir / "condition.json", meta)
    finally:
        if sampler is not None and not sampler.stop_event.is_set():
            sampler.finish()
        if server is not None:
            module.stop_owned_server(server, server.pid, stdout_handle, stderr_handle)
            stdout_handle = stderr_handle = None
        for handle in (stdout_handle, stderr_handle):
            if handle is not None and not handle.closed:
                handle.flush(); os.fsync(handle.fileno()); handle.close()
    return meta


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="check inputs and pins without starting Laya")
    parser.add_argument("--execute", action="store_true", help="run one sequential pair and one simultaneous pair")
    parser.add_argument("--binary", type=Path)
    parser.add_argument("--sha256")
    parser.add_argument("--run-id", default="primary_run")
    parser.add_argument("--laya-venv", type=Path, default=Path("/tmp/meta-ontology-go-laya-venv-20260930"))
    args = parser.parse_args()
    try:
        manifest = read_json(HERE / "manifest.json")
        validate_inputs(manifest)
        if args.check:
            print("parallel cohort inputs and source pins verified; no server started")
            return 0
        if not args.execute:
            parser.error("choose --check or the explicit --execute gate")
        if not args.binary or not args.sha256 or not re.fullmatch(r"[0-9a-fA-F]{64}", args.sha256):
            parser.error("--execute requires --binary and a 64-character --sha256")
        binary = args.binary.resolve()
        if not binary.is_file() or not os.access(binary, os.X_OK):
            raise RuntimeError(f"binary is not executable: {binary}")
        binary_sha = sha256(binary.read_bytes())
        if binary_sha.lower() != args.sha256.lower() or binary_sha != manifest["binary"]["sha256"]:
            raise RuntimeError("binary SHA-256 does not match both the supplied and cohort pin")
        module = load_sibling_runner()
        revision = module.verify_source_revision(binary, EXPECTED_REVISION)
        run_id = args.run_id
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", run_id):
            raise RuntimeError("run id must be path-safe")
        run_dir = HERE / "runs" / run_id
        run_dir.mkdir(parents=True, exist_ok=False)
        manifest_bytes = (HERE / "manifest.json").read_bytes()
        write_bytes(run_dir / "input-manifest.json", manifest_bytes)
        run_meta = {"schema": "gooo/ir-search-parallel-run/v1", "run_id": run_id, "status": "starting",
                    "started_utc": utc_now(), "cohort_manifest_sha256": sha256(manifest_bytes),
                    "binary_sha256": binary_sha, "source_revision": revision,
                    "binary_path": str(binary), "condition_order": ["sequential", "simultaneous"],
                    "replicates_per_condition": 1, "intent_ids": ["clamp", "absolute"],
                    "runtime": manifest["runtime"], "host_logical_cpu_count": os.cpu_count() or 1,
                    "claim_scope": "one observed pair per condition; no statistical, general speed, or deadlock-freedom claim"}
        write_json(run_dir / "run-metadata.json", run_meta)
        venv = args.laya_venv.resolve()
        failures = []
        for condition in ("sequential", "simultaneous"):
            try:
                condition_meta = run_condition(binary, condition, run_dir, venv, module, os.cpu_count() or 1)
                if condition_meta.get("invocation_count") != 2 or not condition_meta.get("all_invocations_exit_zero"):
                    failures.append(f"{condition}: one or more CLI invocations did not exit zero")
            except Exception as exc:
                failures.append(f"{condition}: {type(exc).__name__}: {exc}")
                break
        run_meta["status"] = "raw_capture_complete" if not failures else "partial_raw_capture"
        run_meta["completed_utc"] = utc_now()
        run_meta["failures"] = failures
        write_json(run_dir / "run-metadata.json", run_meta)
        # Reports are derived only after all retained raw CLI/proxy/resource artifacts exist.
        summary_script = HERE / "scripts" / "summarize_parallel.py"
        summary = subprocess.run([sys.executable, str(summary_script), "--run-dir", str(run_dir)],
                                 cwd=HERE, capture_output=True, check=False)
        write_bytes(run_dir / "summary.stdout.raw", summary.stdout)
        write_bytes(run_dir / "summary.stderr.raw", summary.stderr)
        if summary.returncode == 0 and not failures:
            run_meta["status"] = "complete"
        else:
            run_meta["status"] = "report_or_invocation_failure"
            failures.append(f"summarizer exit={summary.returncode}")
            run_meta["failures"] = failures
        write_json(run_dir / "run-metadata.json", run_meta)
        if run_meta["status"] != "complete":
            print(json.dumps(run_meta, indent=2))
            return 1
        print(run_dir / "report.md")
        return 0
    except Exception as exc:
        print(f"parallel study: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
