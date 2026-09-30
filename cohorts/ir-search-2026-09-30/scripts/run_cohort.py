#!/usr/bin/env python3
"""Validate or run the bounded offline Gooo IR-search cohort."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid


HERE = Path(__file__).resolve().parent.parent
REPO = HERE.parents[3]
MANIFEST_PATH = HERE / "manifest.json"
EXPECTED_REVISION = "55cf4c4ebb4ebe31b2550e8bdf3bd21b99753851"
INT64_MIN = -(1 << 63)
INT64_MAX = (1 << 63) - 1


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


def utc_now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_manifest():
    return read_json(MANIFEST_PATH)


def signed_int64(value):
    value &= (1 << 64) - 1
    return value - (1 << 64) if value >= (1 << 63) else value


def predicate(intent_id, value):
    if intent_id in ("clamp", "absolute", "piecewise"):
        return value < 0
    if intent_id == "compound-precedence":
        return value < 0 or (value >= 10 and value != 12)
    raise ValueError(f"unknown intent {intent_id}")


def evaluate_candidate(intent_id, expression, value):
    if not predicate(intent_id, value):
        return value
    if expression == "input":
        return value
    if expression == "-input":
        return signed_int64(-value)
    try:
        result = int(expression, 10)
    except ValueError as exc:
        raise ValueError(f"oracle checker does not support expression {expression!r}") from exc
    if result < INT64_MIN or result > INT64_MAX:
        raise ValueError(f"oracle expression is outside int64: {expression!r}")
    return result


def check_cohort():
    manifest = load_manifest()
    if manifest.get("schema") != "gooo/ir-search-study-manifest/v1":
        raise ValueError("unexpected cohort manifest schema")
    if len(manifest["intents"]) != 4 or manifest["expected_invocation_count"] != 12:
        raise ValueError("cohort must contain four intents and twelve planned invocations")
    for intent in manifest["intents"]:
        fixture_path = HERE / intent["fixture"]
        search_path = HERE / intent["search_plan"]
        fill_path = HERE / intent["fill_plan"]
        oracle_path = HERE / intent["oracle"]
        fixture = fixture_path.read_text(encoding="utf-8")
        search, fill, oracle = read_json(search_path), read_json(fill_path), read_json(oracle_path)
        if search.get("schema") != "gooo/body-codegen-ir-search-plan/v1":
            raise ValueError(f"{intent['id']}: invalid search plan schema")
        if fill.get("schema") != "gooo/body-codegen-ir-fill-plan/v1":
            raise ValueError(f"{intent['id']}: invalid exhaustive plan schema")
        if "holdout_test_cases" in fill:
            raise ValueError(f"{intent['id']}: fill-plan must not contain holdout cases")
        if search["candidates"] != fill["candidates"] or search["test_cases"] != fill["test_cases"]:
            raise ValueError(f"{intent['id']}: search and exhaustive plan candidates/training cases differ")
        if len(search["candidates"]) != 3 or search["max_attempts"] != 3:
            raise ValueError(f"{intent['id']}: expected three candidates and max_attempts=3")
        if len(search["test_cases"]) != intent["training_cases"] or len(search["holdout_test_cases"]) != intent["holdout_cases"]:
            raise ValueError(f"{intent['id']}: manifest test counts do not match plan")
        if search["intent"] != fill["intent"] or search["hole_id"] != fill["hole_id"]:
            raise ValueError(f"{intent['id']}: plan metadata mismatch")
        if f"__GOOO_BODY_HOLE_{search['hole_id']}__" not in fixture:
            raise ValueError(f"{intent['id']}: fixture does not contain the declared single hole")
        training_inputs = [case["input"] for case in search["test_cases"]]
        holdout_inputs = [case["input"] for case in search["holdout_test_cases"]]
        if set(training_inputs) & set(holdout_inputs):
            raise ValueError(f"{intent['id']}: training and holdout inputs overlap")
        if oracle.get("schema") != "gooo/ir-search-finite-oracle/v1" or oracle.get("intent_id") != intent["id"]:
            raise ValueError(f"{intent['id']}: oracle schema or identity mismatch")
        for name, cases in (("training", search["test_cases"]), ("holdout", search["holdout_test_cases"])):
            oracle_suite = oracle[name]
            if oracle_suite["inputs"] != [case["input"] for case in cases] or oracle_suite["expected"] != [case["expected"] for case in cases]:
                raise ValueError(f"{intent['id']}: oracle {name} cases differ from plan")
        for candidate in search["candidates"]:
            candidate_id, expression = candidate["id"], candidate["expression"]
            recorded = oracle["candidate_outputs"].get(candidate_id)
            if recorded is None:
                raise ValueError(f"{intent['id']}: oracle missing candidate {candidate_id}")
            for suite_name, cases in (("training", search["test_cases"]), ("holdout", search["holdout_test_cases"])):
                actual = [evaluate_candidate(intent["id"], expression, case["input"]) for case in cases]
                if actual != recorded[suite_name]:
                    raise ValueError(f"{intent['id']}/{candidate_id}: oracle {suite_name} outputs are incorrect")
                if any(value < INT64_MIN or value > INT64_MAX for value in actual):
                    raise ValueError(f"{intent['id']}/{candidate_id}: oracle value outside int64")
    return manifest


def parse_cputime(raw):
    parts = raw.strip().split(":")
    if len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    if len(parts) == 2:
        return int(parts[0]) * 60 + float(parts[1])
    return float(parts[0])


def sample_pid(pid):
    if not pid:
        return None
    proc = subprocess.run(["ps", "-p", str(pid), "-o", "cputime=,rss=,pid="], capture_output=True, text=True, check=False)
    raw = proc.stdout.strip()
    if proc.returncode != 0 or not raw:
        return {"pid": pid, "alive": False, "ps_raw": raw}
    parts = raw.split()
    if len(parts) < 3:
        return {"pid": pid, "alive": True, "ps_raw": raw}
    return {"pid": int(parts[-1]), "alive": True, "cpu_seconds": parse_cputime(parts[0]), "rss_kb": int(parts[1]), "ps_raw": raw}


def process_summary(samples, key, elapsed_seconds, cpu_count):
    available = [row[key] for row in samples if row.get(key) and row[key].get("alive") and "cpu_seconds" in row[key]]
    if not available:
        return {"samples": 0, "cpu_seconds_delta": None, "rss_peak_kb": None, "max_rss_mib": None,
                "cpu_percent_one_core": None, "cpu_percent_host_normalized": None}
    first, last = available[0], available[-1]
    delta = max(0.0, last["cpu_seconds"] - first["cpu_seconds"])
    peak_kb = max(row["rss_kb"] for row in available)
    one_core = delta / elapsed_seconds * 100 if elapsed_seconds > 0 else None
    normalized = one_core / cpu_count if one_core is not None and cpu_count else None
    return {"samples": len(available), "cpu_seconds_delta": delta, "rss_peak_kb": peak_kb,
            "max_rss_mib": peak_kb / 1024, "cpu_percent_one_core": one_core,
            "cpu_percent_host_normalized": normalized, "measurement": "owned_process_cumulative_cpu_time_delta_over_invocation_wall_time"}


class CaptureProxy:
    def __init__(self, host, port, run_dir):
        self.target_host, self.target_port = host, port
        self.run_dir = run_dir
        self.lock = threading.Lock()
        self.current_invocation = None
        self.seq = 0
        self.events = []
        proxy = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, _format, *_args):
                return

            def do_GET(self):
                self._forward("GET")

            def do_POST(self):
                self._forward("POST")

            def do_PUT(self):
                self._forward("PUT")

            def _forward(self, method):
                if self.path not in ("/health", "/v1/systemone") or (self.path == "/v1/systemone" and method != "POST"):
                    self.send_error(404)
                    return
                size = int(self.headers.get("Content-Length", "0"))
                if size > 2 * 1024 * 1024:
                    self.send_error(413)
                    return
                request_body = self.rfile.read(size) if size else b""
                started = time.monotonic()
                started_utc = utc_now()
                with proxy.lock:
                    proxy.seq += 1
                    seq = proxy.seq
                    invocation_id = proxy.current_invocation
                request_path = proxy.run_dir / "proxy" / "requests" / f"{seq:04d}.request.raw"
                response_path = proxy.run_dir / "proxy" / "responses" / f"{seq:04d}.response.raw"
                request_path.parent.mkdir(parents=True, exist_ok=True)
                response_path.parent.mkdir(parents=True, exist_ok=True)
                request_path.write_bytes(request_body)
                with request_path.open("rb") as saved:
                    os.fsync(saved.fileno())
                kind = "health_check" if self.path == "/health" else "laya_choice"
                request_meta = proxy.inspect_request(request_body) if kind == "laya_choice" else {}
                try:
                    upstream = http.client.HTTPConnection(proxy.target_host, proxy.target_port, timeout=100)
                    headers = {key: value for key, value in self.headers.items() if key.lower() not in ("host", "connection", "content-length", "transfer-encoding")}
                    headers["Content-Length"] = str(len(request_body))
                    upstream.request(method, self.path, body=request_body, headers=headers)
                    upstream_response = upstream.getresponse()
                    response_body = upstream_response.read(2 * 1024 * 1024 + 1)
                    if len(response_body) > 2 * 1024 * 1024:
                        response_body = response_body[:2 * 1024 * 1024]
                        status = 502
                    else:
                        status = upstream_response.status
                    response_headers = {key: value for key, value in upstream_response.getheaders() if key.lower() in ("content-type", "content-encoding", "cache-control")}
                    upstream.close()
                except Exception as exc:  # preserve the failed exchange too
                    response_body = json.dumps({"error": str(exc)}).encode()
                    response_headers, status = {"Content-Type": "application/json"}, 502
                response_path.write_bytes(response_body)
                with response_path.open("rb") as saved:
                    os.fsync(saved.fileno())
                try:
                    parsed_response = json.loads(response_body)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    parsed_response = None
                selected = None
                if isinstance(parsed_response, dict):
                    answer = parsed_response.get("answers", {}).get("body_ir_search", {})
                    selected = answer.get("choice") if isinstance(answer, dict) else None
                event = {
                    "seq": seq,
                    "kind": kind,
                    "invocation_id": invocation_id,
                    "method": method,
                    "path": self.path,
                    "started_utc": started_utc,
                    "completed_utc": utc_now(),
                    "duration_ms": (time.monotonic() - started) * 1000,
                    "status": status,
                    "request_file": str(request_path.relative_to(proxy.run_dir)),
                    "response_file": str(response_path.relative_to(proxy.run_dir)),
                    "request_sha256": sha256(request_body),
                    "response_sha256": sha256(response_body),
                    "selected_candidate_id": selected,
                    **request_meta,
                }
                proxy.append_event(event)
                self.send_response(status)
                for key, value in response_headers.items():
                    self.send_header(key, value)
                self.send_header("Content-Length", str(len(response_body)))
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(response_body)
                self.close_connection = True

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, name="gooo-laya-capture-proxy", daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/v1/systemone"

    @staticmethod
    def inspect_request(raw):
        try:
            outer = json.loads(raw)
            encoded = outer.get("state", {}).get("request", "")
            state = json.loads(encoded) if encoded else {}
            question_id = next(iter(outer.get("questions", {})), None)
            return {
                "question_id": question_id,
                "search_state_schema": state.get("schema"),
                "search_stage": state.get("stage"),
                "candidate_option_ids": sorted(outer.get("questions", {}).get(question_id, {}).get("criteria", {})) if question_id else [],
                "training_test_count": state.get("training_test_count"),
                "training_suite_sha256": state.get("training_suite_sha256"),
                "holdout_fields_present": any("holdout" in key.lower() for key in state),
                "state_request_sha256": sha256(encoded.encode("utf-8")),
            }
        except (ValueError, TypeError, AttributeError):
            return {"request_parse_error": "captured request is not the expected Laya JSON shape"}

    def append_event(self, event):
        with self.lock:
            self.events.append(event)
            path = self.run_dir / "proxy" / "events.jsonl"
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
                handle.flush()
                os.fsync(handle.fileno())

    def set_invocation(self, invocation_id):
        with self.lock:
            self.current_invocation = invocation_id

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)


def free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def fetch_health(port, timeout=3):
    url = f"http://127.0.0.1:{port}/health"
    with urllib.request.urlopen(url, timeout=timeout) as response:
        body = response.read(65536)
    return body, json.loads(body)


def wait_for_health(process, port, output_path, timeout_seconds=240):
    started = time.monotonic()
    last_error = None
    while time.monotonic() - started < timeout_seconds:
        if process.poll() is not None:
            raise RuntimeError(f"owned Laya server exited early with status {process.returncode}")
        try:
            body, health = fetch_health(port)
            output_path.write_bytes(body)
            with output_path.open("rb") as saved:
                os.fsync(saved.fileno())
            revisions = health.get("revisions", {})
            revision = revisions.get("english")
            if health.get("device") != "cpu" or health.get("loaded") != ["english"]:
                raise RuntimeError(f"Laya is not loaded as pinned CPU/english: {health!r}")
            if revision != EXPECTED_REVISION:
                raise RuntimeError(f"Laya model revision mismatch: expected {EXPECTED_REVISION}, got {revision!r}")
            return health
        except (OSError, urllib.error.URLError, json.JSONDecodeError, RuntimeError) as exc:
            last_error = exc
            if isinstance(exc, RuntimeError) and ("revision mismatch" in str(exc) or "not loaded" in str(exc)):
                raise
            time.sleep(1.0)
    raise RuntimeError(f"timed out waiting for owned offline Laya server: {last_error}")


def stop_owned_server(process, pgid, stdout_handle, stderr_handle):
    if process is not None and process.poll() is None:
        try:
            if os.getpgid(process.pid) == pgid == process.pid:
                os.killpg(pgid, signal.SIGTERM)
                try:
                    process.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    if process.poll() is None and os.getpgid(process.pid) == pgid:
                        os.killpg(pgid, signal.SIGKILL)
                        process.wait(timeout=4)
        except (ProcessLookupError, PermissionError):
            pass
    for handle in (stdout_handle, stderr_handle):
        if handle is not None:
            handle.flush()
            os.fsync(handle.fileno())
            handle.close()


def health_snapshot(port, path):
    body, parsed = fetch_health(port)
    path.write_bytes(body)
    with path.open("rb") as saved:
        os.fsync(saved.fileno())
    return parsed


def run_one(binary: Path, cohort, intent, variant, run_dir: Path, server_pid, proxy: CaptureProxy | None, cpu_count):
    variant_dir = run_dir / "invocations" / intent["id"] / variant
    variant_dir.mkdir(parents=True, exist_ok=False)
    plan_rel = intent["search_plan"] if variant != "exhaustive_fill_plan" else intent["fill_plan"]
    fixture_path, plan_path = HERE / intent["fixture"], HERE / plan_rel
    fixture_copy, plan_copy = variant_dir / "fixture.gooo.fixture", variant_dir / "plan.json"
    shutil.copyfile(fixture_path, fixture_copy)
    shutil.copyfile(plan_path, plan_copy)
    with fixture_copy.open("rb") as saved:
        os.fsync(saved.fileno())
    with plan_copy.open("rb") as saved:
        os.fsync(saved.fileno())
    mode_flag = "--fill-plan" if variant == "exhaustive_fill_plan" else "--fill-search"
    activity = re.search(r"^activity\s+(\w+)\(", fixture_copy.read_text(encoding="utf-8"), re.MULTILINE).group(1)
    command = [str(binary), "body-codegen", "--json", mode_flag, str(plan_copy), "--activity", activity, str(fixture_copy)]
    env = os.environ.copy()
    env.pop("GOOO_LAYA_API_KEY", None)
    if variant == "laya_fill_search":
        if proxy is None:
            raise RuntimeError("Laya proxy is not available")
        env["GOOO_LAYA_URL"] = proxy.url
    else:
        env.pop("GOOO_LAYA_URL", None)
    started_utc, start_mono = utc_now(), time.monotonic()
    invocation_id = f"{intent['id']}/{variant}"
    if proxy:
        proxy.set_invocation(invocation_id)
    samples = []
    stop_sampling = threading.Event()
    cli_process = None

    def sample_loop():
        while not stop_sampling.is_set():
            mark = {"sampled_utc": utc_now(), "elapsed_seconds": time.monotonic() - start_mono,
                    "cli": sample_pid(cli_process.pid if cli_process else None), "laya_server": sample_pid(server_pid)}
            samples.append(mark)
            raw_path = variant_dir / "resource-samples.jsonl"
            with raw_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(mark, sort_keys=True) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            stop_sampling.wait(0.15)

    stdout_bytes = b""
    stderr_bytes = b""
    exit_code = 124
    sampler = None
    try:
        cli_process = subprocess.Popen(command, cwd=variant_dir, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                       start_new_session=True)
        sampler = threading.Thread(target=sample_loop, name=f"samples-{intent['id']}-{variant}", daemon=True)
        sampler.start()
        try:
            stdout_bytes, stderr_bytes = cli_process.communicate(timeout=180)
            exit_code = cli_process.returncode
        except subprocess.TimeoutExpired:
            if cli_process.poll() is None and os.getpgid(cli_process.pid) == cli_process.pid:
                os.killpg(cli_process.pid, signal.SIGTERM)
            try:
                stdout_bytes, stderr_bytes = cli_process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                if cli_process.poll() is None and os.getpgid(cli_process.pid) == cli_process.pid:
                    os.killpg(cli_process.pid, signal.SIGKILL)
                stdout_bytes, stderr_bytes = cli_process.communicate(timeout=5)
            exit_code = 124
            stderr_bytes += b"\nrunner: invocation timed out after 180 seconds\n"
    finally:
        stop_sampling.set()
        if sampler:
            sampler.join(timeout=3)
        if proxy:
            proxy.set_invocation(None)
    (variant_dir / "stdout.raw").write_bytes(stdout_bytes)
    (variant_dir / "stderr.raw").write_bytes(stderr_bytes)
    for path in (variant_dir / "stdout.raw", variant_dir / "stderr.raw"):
        with path.open("rb") as saved:
            os.fsync(saved.fileno())
    elapsed = time.monotonic() - start_mono
    completed_utc = utc_now()
    (variant_dir / "command.json").write_text(json.dumps({"argv": command, "environment": {
        "GOOO_LAYA_URL": proxy.url if variant == "laya_fill_search" and proxy else "",
        "GOOO_LAYA_API_KEY": "unset", "offline_model_calls": variant == "laya_fill_search",
    }}, indent=2) + "\n", encoding="utf-8")
    cpu_cli = process_summary(samples, "cli", elapsed, cpu_count)
    cpu_server = process_summary(samples, "laya_server", elapsed, cpu_count)
    resources = {
        "schema": "gooo/ir-search-process-resources/v1",
        "wall_ms": elapsed * 1000,
        "logical_cpu_count": cpu_count,
        "cli_process": cpu_cli,
        "laya_server": cpu_server,
        "raw_samples": "resource-samples.jsonl",
        "sampling_interval_ms": 150,
    }
    write_json(variant_dir / "resource.json", resources)
    capture_events = proxy.events if proxy else []
    relevant_events = [event for event in capture_events if event.get("invocation_id") == invocation_id]
    invocation = {
        "schema": "gooo/ir-search-invocation-record/v1",
        "invocation_id": invocation_id,
        "intent_id": intent["id"],
        "variant": variant,
        "started_utc": started_utc,
        "completed_utc": completed_utc,
        "wall_ms": elapsed * 1000,
        "exit_code": exit_code,
        "argv": command,
        "binary_sha256": sha256(binary.read_bytes()),
        "fixture_path": intent["fixture"],
        "fixture_sha256": sha256(fixture_copy.read_bytes()),
        "plan_path": plan_rel,
        "plan_sha256": sha256(plan_copy.read_bytes()),
        "stdout_sha256": sha256(stdout_bytes),
        "stderr_sha256": sha256(stderr_bytes),
        "stdout_file": "stdout.raw",
        "stderr_file": "stderr.raw",
        "resources_file": "resource.json",
        "proxy_event_sequences": [event["seq"] for event in relevant_events],
    }
    write_json(variant_dir / "invocation.json", invocation)
    return invocation, resources


def verify_source_revision(binary, expected):
    result = subprocess.run(["go", "version", "-m", str(binary)], capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"go version -m failed for supplied binary: {result.stderr.strip()}")
    revision = None
    modified = None
    for line in result.stdout.splitlines():
        match = re.search(r"\bvcs\.revision=(\S+)", line)
        if match:
            revision = match.group(1)
        match = re.search(r"\bvcs\.modified=(\S+)", line)
        if match:
            modified = match.group(1)
    if revision != expected or modified != "false":
        raise RuntimeError(f"binary is not the expected clean revision: revision={revision!r}, vcs.modified={modified!r}")
    return revision


def start_run(args, manifest):
    binary = args.binary.resolve()
    if not binary.is_file() or not os.access(binary, os.X_OK):
        raise RuntimeError(f"Gooo binary is not executable: {binary}")
    actual_sha = sha256(binary.read_bytes())
    if actual_sha.lower() != args.sha256.lower():
        raise RuntimeError(f"binary SHA-256 mismatch: expected {args.sha256}, got {actual_sha}")
    expected_revision = manifest.get("binary", {}).get("source_revision")
    if not expected_revision:
        raise RuntimeError("manifest binary.source_revision must be pinned before execution")
    source_revision = verify_source_revision(binary, expected_revision)

    run_id = args.run_id
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", run_id):
        raise RuntimeError("run id must be a simple path-safe name")
    run_dir = HERE / "runs" / run_id
    if run_dir.exists():
        raise RuntimeError(f"run directory already exists; preserving prior evidence: {run_dir}")
    run_dir.mkdir(parents=True)
    (run_dir / "laya").mkdir()
    (run_dir / "proxy").mkdir()
    (run_dir / "invocations").mkdir()
    venv = Path(args.laya_venv).resolve()
    server_exe = venv / "bin" / "laya-serve"
    python_exe = venv / "bin" / "python"
    if not server_exe.is_file() or not os.access(server_exe, os.X_OK) or not python_exe.is_file():
        raise RuntimeError(f"installed Laya venv is unavailable: {venv}")
    version = subprocess.run([str(python_exe), "-c", "import importlib.metadata as m; print(m.version('laya'))"],
                             capture_output=True, text=True, check=False)
    if version.returncode != 0 or version.stdout.strip() != manifest["runtime"]["version"]:
        raise RuntimeError(f"installed Laya version mismatch: {version.stdout.strip()!r}; expected {manifest['runtime']['version']}")
    port = free_port()
    laya_env = os.environ.copy()
    laya_env.update({
        "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "HF_HUB_DISABLE_TELEMETRY": "1",
        "LAYA_HOST": "127.0.0.1", "LAYA_PORT": str(port), "LAYA_MODELS": "english",
        "LAYA_DEVICE": "cpu", "LAYA_THREADS": "4", "LAYA_PRELOAD": "1",
    })
    # Make the server use the already installed virtualenv packages and prevent API credentials leaking into it.
    laya_env.pop("GOOO_LAYA_API_KEY", None)
    started_utc = utc_now()
    manifest_snapshot_path = run_dir / "cohort-manifest-preexecution.json"
    manifest_snapshot_path.write_bytes(MANIFEST_PATH.read_bytes())
    with manifest_snapshot_path.open("rb") as saved:
        os.fsync(saved.fileno())
    metadata = {
        "schema": "gooo/ir-search-run-metadata/v1", "run_id": run_id, "status": "starting",
        "started_utc": started_utc, "binary_sha256": actual_sha, "source_revision": source_revision,
        "binary_path": str(binary), "runtime": {**manifest["runtime"], "virtualenv": str(venv), "port": port},
        "cohort_manifest_sha256": sha256(MANIFEST_PATH.read_bytes()),
        "cohort_manifest_snapshot_file": manifest_snapshot_path.name,
        "cohort_manifest_snapshot_saved_at_run_start": True,
        "host_logical_cpu_count": os.cpu_count(),
        "network_policy": "offline model-loading flags; loopback-only service and capture proxy; no external endpoint configured",
    }
    write_json(run_dir / "run-metadata.json", metadata)
    laya_stdout = (run_dir / "laya" / "stdout.log").open("wb")
    laya_stderr = (run_dir / "laya" / "stderr.log").open("wb")
    server = None
    pgid = None
    proxy = None
    server_stdout = laya_stdout
    server_stderr = laya_stderr
    complete = False
    invocations = []
    resources = []
    try:
        server = subprocess.Popen([str(server_exe)], cwd=run_dir, env=laya_env,
                                  stdin=subprocess.DEVNULL, stdout=server_stdout, stderr=server_stderr,
                                  start_new_session=True)
        pgid = server.pid
        write_json(run_dir / "laya" / "owned-process.json", {
            "schema": "gooo/ir-search-owned-process/v1", "pid": server.pid, "process_group_id": pgid,
            "started_utc": started_utc, "executable": str(server_exe), "owned_by_runner": True,
            "host": "127.0.0.1", "port": port,
        })
        health = wait_for_health(server, port, run_dir / "laya" / "health-before.json")
        health_after_path = run_dir / "laya" / "health-after.json"
        proxy = CaptureProxy("127.0.0.1", port, run_dir)
        metadata["status"] = "running"
        metadata["laya_health"] = {"device": health.get("device"), "loaded": health.get("loaded"), "revisions": health.get("revisions")}
        metadata["capture_proxy_url"] = proxy.url
        write_json(run_dir / "run-metadata.json", metadata)
        for intent in manifest["intents"]:
            for variant in manifest["invocation_variants"]:
                invocation, resource = run_one(binary, manifest, intent, variant, run_dir, server.pid, proxy, os.cpu_count() or 1)
                invocations.append(invocation)
                resources.append({"invocation_id": invocation["invocation_id"], **resource})
        health_after = health_snapshot(port, health_after_path)
        metadata["laya_health_after"] = {"device": health_after.get("device"), "loaded": health_after.get("loaded"), "revisions": health_after.get("revisions")}
        metadata["completed_utc"] = utc_now()
        metadata["status"] = "raw_capture_complete"
        write_json(run_dir / "resource_samples.json", {"schema": "gooo/ir-search-resource-samples/v1", "invocations": resources})
        write_json(run_dir / "run-metadata.json", metadata)
        # Persist the capture event log and resources before asking the offline summarizer to derive a report.
        if len(invocations) != manifest["expected_invocation_count"]:
            raise RuntimeError(f"captured {len(invocations)} invocations; expected {manifest['expected_invocation_count']}")
        if any(item["exit_code"] != 0 for item in invocations):
            raise RuntimeError("one or more CLI invocations failed; raw artifacts were retained and no primary report is published")
        if len([e for e in proxy.events if e.get("kind") == "laya_choice"]) < 1:
            raise RuntimeError("no Laya choice requests were captured")
        proxy.stop()
        proxy = None
        stop_owned_server(server, pgid, server_stdout, server_stderr)
        server = None
        server_stdout = server_stderr = None
        metadata["completed_utc"] = utc_now()
        metadata["status"] = "raw_capture_complete"
        write_json(run_dir / "run-metadata.json", metadata)
        result = subprocess.run([sys.executable, str(HERE / "scripts" / "summarize_saved.py"), "--run-dir", str(run_dir)],
                                cwd=HERE, capture_output=True, text=True, check=False)
        (run_dir / "summary.stdout.raw").write_text(result.stdout, encoding="utf-8")
        (run_dir / "summary.stderr.raw").write_text(result.stderr, encoding="utf-8")
        if result.returncode != 0:
            raise RuntimeError(f"saved-artifact summarizer failed; raw evidence remains at {run_dir}: {result.stderr.strip()}")
        metadata["status"] = "complete"
        write_json(run_dir / "run-metadata.json", metadata)
        manifest["binary"] = {"source_revision": source_revision, "sha256": actual_sha, "path": None}
        manifest["primary_run"] = f"runs/{run_id}"
        manifest["status"] = "primary_run_complete"
        write_json(MANIFEST_PATH, manifest)
        complete = True
        print(run_dir / "report.md")
    finally:
        if proxy is not None:
            proxy.stop()
        if server is not None:
            stop_owned_server(server, pgid, server_stdout, server_stderr)
            if server_stdout is not None:
                server_stdout = server_stderr = None
        if not complete:
            if server_stdout is not None or server_stderr is not None:
                stop_owned_server(server, pgid, server_stdout, server_stderr)
            metadata["status"] = "incomplete_raw_capture"
            metadata["completed_utc"] = utc_now()
            try:
                write_json(run_dir / "resource_samples.json", {"schema": "gooo/ir-search-resource-samples/v1", "invocations": resources})
                write_json(run_dir / "run-metadata.json", metadata)
            except OSError:
                pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="validate all plans, fixture holes, disjoint suites, and oracle outputs without starting processes")
    parser.add_argument("--execute", action="store_true", help="run the 12-invocation cohort; requires a pinned binary and SHA-256")
    parser.add_argument("--binary", type=Path)
    parser.add_argument("--sha256")
    parser.add_argument("--run-id", default="primary_run")
    parser.add_argument("--laya-venv", default=os.environ.get("LAYA_VENV", "/tmp/meta-ontology-go-laya-venv-20260930"))
    args = parser.parse_args()
    try:
        manifest = check_cohort()
        if args.check or not args.execute:
            print(f"validated {len(manifest['intents'])} intents, {manifest['expected_invocation_count']} planned invocations, and independent finite oracles")
            if args.execute:
                return
            if not args.check:
                parser.error("select --check for offline validation or --execute for the explicitly gated local run")
            return
        if not args.binary or not args.sha256 or not re.fullmatch(r"[0-9a-fA-F]{64}", args.sha256):
            parser.error("--execute requires --binary and a 64-character --sha256")
        start_run(args, manifest)
    except Exception as exc:
        print(f"cohort runner: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
