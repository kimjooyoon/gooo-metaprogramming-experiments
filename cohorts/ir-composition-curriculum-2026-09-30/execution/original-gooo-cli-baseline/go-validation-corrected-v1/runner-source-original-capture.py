#!/usr/bin/env python3
"""Run the frozen 32-case Gooo --fill-plan baseline and independently execute outputs."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
COHORT = ROOT / "cohorts" / "ir-composition-curriculum-2026-09-30"
FREEZE_PATH = COHORT / "design-freeze.json"
PIN_REVISION = "bb5c1ec2f81cbfb17ac6fb2f7a9e1d7b67168e7f"
PIN_BINARY_SHA256 = "47b9f3bd1b365d18771ba36b0a2b472b139fdb6a08b404697e188478dce38c6e"
DEFAULT_BINARY = Path("/tmp/gooo-pinned-context-final-20260930")
DEFAULT_GO_BIN = Path("/Users/alice/go/pkg/mod/golang.org/toolchain@v0.0.1-go1.27.0.darwin-arm64/bin/go")
DEFAULT_OUTPUT = COHORT / "execution" / "original-gooo-cli-baseline"
PREDECESSOR_ATTEMPT_DIR = COHORT / "execution" / "pinned-offline-attempt-1"
FILL_SCHEMA = "gooo/body-codegen-ir-fill-plan/v1"
RESULT_SCHEMA = "gooo/ir-composition-original-cli-baseline/v1"
GO_TEST_MARKER = "FINITERESULT|"
GO_RESULT_RE = re.compile(r"FINITERESULT\|(training|evaluation)\|(\d+)\|(-?\d+)\|(-?\d+)\|(-?\d+)\|(true|false)")
CONNECTION_ENV_PREFIXES = ("GOOO_LAYA_", "LAYA_")
SENSITIVE_PROVIDER_ENV = ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY")


def now_utc() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def read_bytes(path: Path) -> bytes:
    return path.read_bytes()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_bytes(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())


def write_json(path: Path, value: Any) -> bytes:
    raw = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
    write_bytes(path, raw)
    return raw


def rel(root: Path, path: Path) -> str:
    return str(path.resolve().relative_to(root.resolve()))


def verify_freeze() -> tuple[dict, dict[str, str], bytes]:
    if not FREEZE_PATH.is_file():
        raise RuntimeError("frozen design file is missing")
    freeze_bytes = FREEZE_PATH.read_bytes()
    freeze = json.loads(freeze_bytes)
    if freeze.get("schema") != "gooo/ir-composition-design-freeze/v1":
        raise RuntimeError("unexpected design-freeze schema")
    if freeze.get("cohort") != COHORT.name or freeze.get("stage") != "design_and_plans_frozen_before_compiled_go_or_gooo_execution":
        raise RuntimeError("design freeze identity or stage mismatch")
    pin = freeze.get("compiler_pin", {})
    if (pin.get("revision") != PIN_REVISION or pin.get("binary_sha256") != PIN_BINARY_SHA256
            or pin.get("go_version") != "go1.27.0" or pin.get("goos") != "darwin"
            or pin.get("goarch") != "arm64" or pin.get("cgo_enabled") is not True
            or pin.get("trimpath") is not True or pin.get("vcs_modified") is not False):
        raise RuntimeError("design freeze does not bind the required clean compiler build")
    files = freeze.get("files", {})
    if len(files) != 142:
        raise RuntimeError(f"design freeze expected 142 source/plan files, found {len(files)}")
    mismatches = []
    for repo_path, expected in files.items():
        path = ROOT / repo_path
        if not path.is_file() or sha(path.read_bytes()) != expected:
            mismatches.append(repo_path)
    if mismatches:
        raise RuntimeError("frozen input SHA mismatch: " + ", ".join(mismatches[:8]))
    return freeze, files, freeze_bytes


def verify_design_inputs(freeze: dict, files: dict[str, str]) -> tuple[dict, list[dict], dict[str, dict], bytes]:
    catalog_path = COHORT / "catalog.json"
    vectors_path = COHORT / "oracle" / "testdata" / "vectors.json"
    catalog_bytes = catalog_path.read_bytes()
    vectors_bytes = vectors_path.read_bytes()
    catalog = json.loads(catalog_bytes)
    vectors_list = json.loads(vectors_bytes)
    if catalog.get("schema") != "gooo/ir-composition-catalog/v1" or catalog.get("design_count") != 32:
        # Accept the cohort's frozen catalogue schema while keeping count strict.
        if catalog.get("design_count") != 32 or len(catalog.get("designs", [])) != 32:
            raise RuntimeError("frozen catalog does not describe exactly 32 designs")
    designs = catalog.get("designs", [])
    vectors = {item.get("id"): item for item in vectors_list}
    if len(designs) != 32 or len(vectors) != 32 or set(vectors) != {item.get("id") for item in designs}:
        raise RuntimeError("catalog and independent Python vectors do not have the same 32 identities")
    # design-freeze paths are repository relative, including the cohorts prefix.
    for path in (catalog_path, vectors_path):
        key = str(path.relative_to(ROOT))
        if key not in files or sha(path.read_bytes()) != files[key]:
            raise RuntimeError(f"frozen design file is not bound: {key}")

    seen: set[str] = set()
    for item in designs:
        case_id = item.get("id")
        if not case_id or case_id in seen:
            raise RuntimeError(f"duplicate or empty design ID: {case_id!r}")
        seen.add(case_id)
        plan_path = COHORT / item["body_fill_plan"]
        fixture_path = COHORT / item["fixture"]
        for path in (plan_path, fixture_path):
            key = str(path.relative_to(ROOT))
            if key not in files or not path.is_file() or sha(path.read_bytes()) != files[key]:
                raise RuntimeError(f"design input differs from the frozen manifest: {key}")
        plan = json.loads(plan_path.read_bytes())
        vector = vectors[case_id]
        if plan.get("schema") != FILL_SCHEMA:
            raise RuntimeError(f"{case_id}: unexpected body fill plan schema")
        if plan.get("intent") != item.get("intent") or item.get("activity") != vector.get("activity"):
            raise RuntimeError(f"{case_id}: catalog, plan, and Python vector identities differ")
        if plan.get("test_cases") != vector.get("training"):
            raise RuntimeError(f"{case_id}: body fill training inputs differ from the frozen Python vector")
        if not vector.get("training") or not vector.get("evaluation"):
            raise RuntimeError(f"{case_id}: missing frozen training or evaluation cases")
    return catalog, designs, vectors, catalog_bytes


def predecessor_attempt_lineage() -> tuple[dict, bytes, bytes]:
    """Bind the prior diagnostic run without treating it as a complete raw capture."""
    report_path = PREDECESSOR_ATTEMPT_DIR / "execution-report.json"
    if not report_path.is_file():
        raise RuntimeError("expected predecessor attempt-1 report is missing")
    report_bytes = report_path.read_bytes()
    report = json.loads(report_bytes)
    freeze_sha = sha(FREEZE_PATH.read_bytes())
    if (report.get("attempt") != 1 or report.get("cohort") != COHORT.name
            or report.get("design_freeze_sha256") != freeze_sha
            or report.get("binary_sha256_observed") != PIN_BINARY_SHA256
            or report.get("model_calls") != 0 or report.get("designs_attempted") != 32):
        raise RuntimeError("predecessor attempt-1 report does not match this frozen cohort and compiler")
    files = sorted(path for path in PREDECESSOR_ATTEMPT_DIR.rglob("*") if path.is_file())
    inventory_rows = [{"path": str(path.relative_to(PREDECESSOR_ATTEMPT_DIR)),
                       "sha256": sha(path.read_bytes()), "bytes": path.stat().st_size}
                      for path in files]
    inventory_bytes = json.dumps(inventory_rows, sort_keys=True, separators=(",", ":")).encode()
    raw_exchange_files = [item for item in inventory_rows
                          if Path(item["path"]).name in ("stdout.raw", "stderr.raw", "stdout.txt", "stderr.txt")]
    lineage = {
        "schema": "gooo/ir-composition-baseline-lineage/v1",
        "attempt_number": 2,
        "predecessor": {
            "attempt": 1, "path": str(PREDECESSOR_ATTEMPT_DIR.relative_to(ROOT)),
            "execution_report_sha256": sha(report_bytes),
            "runner_sha256": report.get("runner_sha256"),
            "design_freeze_sha256": report.get("design_freeze_sha256"),
            "binary_sha256": report.get("binary_sha256_observed"),
            "attempted": report.get("designs_attempted"),
            "generated": report.get("generated_designs"),
            "cli_failure_case_ids": report.get("codegen_failures", []),
            "model_calls": report.get("model_calls"),
            "file_count": len(files),
            "tree_inventory_sha256": sha(inventory_bytes),
            "exact_raw_cli_stdout_stderr_files": len(raw_exchange_files),
            "reused_for_primary_raw_cli_evidence": False,
            "reuse_reason": "Attempt 1 has stdout/stderr hashes and derived receipts/source, but no exact raw per-case CLI stdout/stderr bytes; its Go test harness was reported to fail during setup.",
            "source_report": {key: report.get(key) for key in (
                "schema", "designs_expected", "designs_attempted", "generated_designs",
                "codegen_failures", "model_calls", "provider_endpoint_unset", "provider_api_key_unset",
                "generated_go_execution", "go_execution_failures_or_unknown")},
        },
        "attempt_2_role": "separate complete-raw-capture repeat required because predecessor raw stdout/stderr bytes are unavailable",
    }
    return lineage, report_bytes, inventory_bytes


def binary_build_receipt(binary: Path, expected_sha: str, expected_revision: str) -> dict:
    if not binary.is_file():
        raise RuntimeError(f"pinned Gooo binary not found: {binary}")
    raw = binary.read_bytes()
    digest = sha(raw)
    if digest != expected_sha:
        raise RuntimeError(f"pinned Gooo binary SHA-256 mismatch: {digest}")
    result = subprocess.run(["go", "version", "-m", str(binary)], capture_output=True, text=True, check=False)
    if result.returncode:
        raise RuntimeError(f"cannot inspect Gooo binary metadata: {result.stderr.strip()}")
    revision = modified = goos = goarch = None
    for line in result.stdout.splitlines():
        if match := re.search(r"\bvcs\.revision=(\S+)", line):
            revision = match.group(1)
        if match := re.search(r"\bvcs\.modified=(\S+)", line):
            modified = match.group(1)
        if match := re.search(r"\bGOOS=(\S+)", line):
            goos = match.group(1)
        if match := re.search(r"\bGOARCH=(\S+)", line):
            goarch = match.group(1)
    if revision != expected_revision or modified != "false":
        raise RuntimeError(f"Gooo binary is not the clean source pin: revision={revision}, modified={modified}")
    return {"path": str(binary), "sha256": digest, "source_revision": revision,
            "vcs_modified": modified, "goos": goos, "goarch": goarch,
            "build_info_raw_sha256": sha(result.stdout.encode())}


def dimension(report: dict, wanted: str) -> dict:
    receipt = report.get("completeness_receipt") or {}
    for item in receipt.get("dimensions", []):
        if item.get("id") == wanted:
            return {key: item.get(key) for key in ("id", "status", "numerator", "denominator", "unit", "reason")}
    return {"id": wanted, "status": "MISSING", "numerator": 0, "denominator": 0, "unit": None}


def score_from_receipt(report: dict) -> dict:
    fill = report.get("body_fill") or {}
    return {
        "gooo_training": {"passed": fill.get("test_cases_passed"),
                          "total": fill.get("test_cases_total"),
                          "accuracy_percent": fill.get("functional_accuracy_percent"),
                          "scope": fill.get("accuracy_scope")},
        "candidate_scores": fill.get("candidate_scores", []),
    }


def go_test_source(activity: str, vector: dict, case_id: str) -> str:
    def row_literal(row: dict) -> str:
        return f"{{input: int64({row['input']}), expected: int64({row['expected']})}},"

    training = ",\n".join("\t\t" + row_literal(row) for row in vector["training"])
    evaluation = ",\n".join("\t\t" + row_literal(row) for row in vector["evaluation"])
    # Input/output vectors are integer-to-integer for all 32 frozen designs.
    return f'''package bodycodegen

import "testing"

type finiteCase struct {{ input, expected int64 }}

func runFinite(t *testing.T, suite string, cases []finiteCase) {{
\tt.Helper()
\tfor index, item := range cases {{
\t\tactual := {activity}(item.input)
\t\tpassed := actual == item.expected
\t\tt.Logf("{GO_TEST_MARKER}%s|%d|%d|%d|%d|%t", suite, index+1, item.input, item.expected, actual, passed)
\t\tif !passed {{ t.Errorf("%s case %d: {activity}(%d) = %d, want %d", suite, index+1, item.input, actual, item.expected) }}
\t}}
}}

func TestFrozenTrainingVectors_{case_id}(t *testing.T) {{
\tcases := []finiteCase{{
{training}
\t}}
\trunFinite(t, "training", cases)
}}

func TestFrozenEvaluationVectors_{case_id}(t *testing.T) {{
\tcases := []finiteCase{{
{evaluation}
\t}}
\trunFinite(t, "evaluation", cases)
}}

'''


def parse_go_finite_results(raw: bytes) -> dict:
    text = raw.decode("utf-8", errors="replace")
    result = {"training": [], "evaluation": []}
    for match in GO_RESULT_RE.finditer(text):
        suite, index, input_value, expected, actual, passed = match.groups()
        result[suite].append({"index": int(index), "input": int(input_value), "expected": int(expected),
                              "actual": int(actual), "passed": passed == "true"})
    return result


def independent_score(actual: dict, planned: dict, go_exit_code: int | None, timed_out: bool) -> dict:
    suites = {}
    for suite in ("training", "evaluation"):
        rows = actual.get(suite, [])
        planned_count = len(planned.get(suite, []))
        suites[suite] = {
            "passed": sum(bool(row["passed"]) for row in rows),
            "observed": len(rows),
            "planned": planned_count,
            "unknown": max(0, planned_count - len(rows)),
            "all_observed_cases_passed": bool(rows) and len(rows) == planned_count
                                          and all(row["passed"] for row in rows),
            "go_test_exit_code": go_exit_code,
            "timed_out": timed_out,
        }
    return suites


def go_harness_preflight(go_bin: Path, env: dict[str, str]) -> dict:
    """Compile the generated test harness against a tiny stub before any Gooo CLI calls."""
    smoke_vector = {"training": [{"input": 4, "expected": 4}],
                    "evaluation": [{"input": -2, "expected": -2}]}
    test_source = go_test_source("HarnessSmoke", smoke_vector, "harness_smoke")
    stub_source = "package bodycodegen\n\nfunc HarnessSmoke(input int64) int64 { return input }\n"
    with tempfile.TemporaryDirectory(prefix="gooo-ir-composition-harness-preflight-") as temp_name:
        temp = Path(temp_name)
        (temp / "go.mod").write_text("module example.invalid/gooo/ir-composition-harness-preflight\n\ngo 1.27\n",
                                     encoding="utf-8")
        (temp / "stub.go").write_text(stub_source, encoding="utf-8")
        (temp / "generated_test.go").write_text(test_source, encoding="utf-8")
        command = [str(go_bin), "test", "-count=1", "-v", "./..."]
        started_ns = time.monotonic_ns()
        completed = subprocess.run(command, cwd=temp, env=env, capture_output=True, timeout=60, check=False)
        elapsed_ms = (time.monotonic_ns() - started_ns) / 1_000_000
    result = {
        "schema": "gooo/ir-composition-go-test-harness-preflight/v1",
        "command": command, "go_version": "go1.27.0", "exit_code": completed.returncode,
        "elapsed_ms": elapsed_ms, "status": "PASS" if completed.returncode == 0 else "FAIL",
        "stub_source_sha256": sha(stub_source.encode()), "test_source_sha256": sha(test_source.encode()),
        "stdout_sha256": sha(completed.stdout), "stderr_sha256": sha(completed.stderr),
        "stdout": completed.stdout, "stderr": completed.stderr,
        "stub_source": stub_source.encode(), "test_source": test_source.encode(),
    }
    if completed.returncode != 0:
        raise RuntimeError("independent Go test harness preflight failed before Gooo CLI calls: "
                           + completed.stderr.decode("utf-8", errors="replace")[-2000:])
    return result


def cli_one(binary: Path, item: dict, plan_path: Path, fixture_path: Path,
            case_dir: Path, timeout_seconds: int, env: dict[str, str]) -> dict:
    cli_dir = case_dir / "cli"
    cli_dir.mkdir(parents=True)
    command = [str(binary), "body-codegen", "--json", "--fill-plan", str(plan_path),
               "--activity", item["activity"], str(fixture_path)]
    started = now_utc()
    start_ns = time.monotonic_ns()
    stdout = stderr = b""
    exit_code: int | None = None
    timed_out = False
    launch_error = None
    try:
        completed = subprocess.run(command, cwd=case_dir, env=env, capture_output=True,
                                   timeout=timeout_seconds, check=False)
        stdout, stderr, exit_code = completed.stdout, completed.stderr, completed.returncode
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        stdout = exc.stdout or b""
        stderr = exc.stderr or b""
        launch_error = f"TimeoutExpired after {timeout_seconds}s"
    except Exception as exc:
        launch_error = f"{type(exc).__name__}: {exc}"
        stderr = (launch_error + "\n").encode()
    ended = now_utc()
    elapsed_ms = (time.monotonic_ns() - start_ns) / 1_000_000
    write_bytes(cli_dir / "stdout.raw", stdout)
    write_bytes(cli_dir / "stderr.raw", stderr)

    payload = None
    parse_error = None
    if stdout:
        try:
            payload = json.loads(stdout)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            parse_error = f"{type(exc).__name__}: {exc}"
    report = payload.get("report", {}) if isinstance(payload, dict) else {}
    if report:
        write_json(cli_dir / "compiler-report.parsed.json", report)
    source_text = payload.get("source", "") if isinstance(payload, dict) else ""
    source_bytes = source_text.encode("utf-8") if isinstance(source_text, str) and source_text else b""
    if source_bytes:
        write_bytes(case_dir / "generated.go", source_bytes)
    fill = report.get("body_fill") or {}
    decision = (fill.get("decision") or {}) if isinstance(fill, dict) else {}
    result = {
        "schema": "gooo/ir-composition-original-cli-case/v1",
        "case_id": item["id"], "activity": item["activity"],
        "primary_semantic_area": item["primary_semantic_area"],
        "candidate_discrimination": item["candidate_discrimination"],
        "cli": {
            "command": command, "cwd": str(case_dir), "started_utc": started, "ended_utc": ended,
            "elapsed_ms": elapsed_ms, "timeout_seconds": timeout_seconds, "timed_out": timed_out,
            "exit_code": exit_code, "launch_error": launch_error, "json_parse_error": parse_error,
            "stdout_path": "cli/stdout.raw", "stdout_sha256": sha(stdout), "stdout_bytes": len(stdout),
            "stderr_path": "cli/stderr.raw", "stderr_sha256": sha(stderr), "stderr_bytes": len(stderr),
            "parsed_report_path": "cli/compiler-report.parsed.json" if report else None,
            "emitted_source_path": "generated.go" if source_bytes else None,
            "emitted_source_sha256": sha(source_bytes) if source_bytes else None,
        },
        "compiler_receipt": {
            "available": bool(report),
            "decision": report.get("decision"),
            "compiler_source_sha": report.get("compiler_source_sha"),
            "plan_sha256": report.get("plan_sha256"),
            "source_digest": report.get("source_digest"),
            "generated_digest": report.get("generated_digest"),
            "activity_id": report.get("activity_id"),
            "typecheck_passed": report.get("typecheck_passed"),
            "deterministic_replay": report.get("deterministic_replay"),
            "route_equivalence_decision": (report.get("route_equivalence") or {}).get("decision"),
            "source_unit_completeness": dimension(report, "source_ast_coverage"),
            "provider_operations_reported": report.get("provider_operations", 0),
            "model_calls_reported": report.get("model_calls", 0),
            "body_fill_decision_mode": decision.get("mode"),
            "body_fill_decision_provider": decision.get("provider"),
            "body_fill_fallback_reason": decision.get("fallback_reason"),
            "body_fill_selected_candidate_id": fill.get("selected_candidate_id"),
            "body_fill_selected_expression": fill.get("selected_expression"),
            "body_fill_finite_score": score_from_receipt(report),
            "reported_error": report.get("error") or (payload.get("error") if isinstance(payload, dict) else None),
            "reported_diagnostics": report.get("diagnostics") or (payload.get("diagnostics") if isinstance(payload, dict) else None),
            "generated_source_sha256_matches_receipt": (
                bool(source_bytes) and report.get("generated_digest") == "sha256:" + sha(source_bytes)),
        },
        "source_unit_completeness": dimension(report, "source_ast_coverage"),
        "finite_fitness": {
            "gooo_training": score_from_receipt(report)["gooo_training"],
            "independent_generated_go": None,
        },
        "go_validation": {"status": "not_started"},
    }
    success = (exit_code == 0 and not timed_out and not launch_error and parse_error is None
               and isinstance(payload, dict) and report.get("decision") == "PASS" and bool(source_bytes)
               and report.get("compiler_source_sha") == PIN_REVISION
               and report.get("generated_digest") == "sha256:" + sha(source_bytes))
    result["cli"]["baseline_status"] = "CLI_PASS_WITH_SOURCE" if success else "CLI_FAILURE_OR_NO_SOURCE"
    result["cli"]["valid_source_pin"] = report.get("compiler_source_sha") == PIN_REVISION
    result["_source_for_independent_go"] = source_bytes if success else b""
    result["_cli_success"] = success
    write_json(case_dir / "case-result.partial.json", {key: value for key, value in result.items()
                                                        if not key.startswith("_")})
    return result


def independent_go_one(item: dict, vector: dict, case_dir: Path, go_bin: Path,
                       timeout_seconds: int, env: dict[str, str], source_bytes: bytes) -> dict:
    go_dir = case_dir / "go-validation"
    go_dir.mkdir(parents=True, exist_ok=True)
    (go_dir / "go.mod").write_text(
        f"module example.invalid/gooo/ir-composition-original-cli/{item['id']}\n\ngo 1.27\n", encoding="utf-8")
    write_bytes(go_dir / "frozen-vectors.json",
                json.dumps({"training": vector["training"], "evaluation": vector["evaluation"]},
                           ensure_ascii=False, indent=2).encode() + b"\n")
    test_source = go_test_source(item["activity"], vector, item["id"])
    write_bytes(go_dir / "generated_test.go", test_source.encode())
    # This per-case module contains exactly the original CLI-emitted source and an
    # independent Go test that runs the frozen Python reference vectors.
    if not source_bytes:
        return {"status": "no_generated_source", "planned_training": len(vector["training"]),
                "planned_evaluation": len(vector["evaluation"])}
    write_bytes(go_dir / "generated.go", source_bytes)
    command = [str(go_bin), "test", "-count=1", "-v", "./..."]
    start_ns = time.monotonic_ns()
    started = now_utc()
    stdout = stderr = b""
    exit_code = None
    timed_out = False
    launch_error = None
    try:
        completed = subprocess.run(command, cwd=go_dir, env=env, capture_output=True,
                                   timeout=timeout_seconds, check=False)
        stdout, stderr, exit_code = completed.stdout, completed.stderr, completed.returncode
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        stdout, stderr = exc.stdout or b"", exc.stderr or b""
        launch_error = f"TimeoutExpired after {timeout_seconds}s"
    except Exception as exc:
        launch_error = f"{type(exc).__name__}: {exc}"
        stderr = (launch_error + "\n").encode()
    elapsed_ms = (time.monotonic_ns() - start_ns) / 1_000_000
    ended = now_utc()
    write_bytes(go_dir / "stdout.raw", stdout)
    write_bytes(go_dir / "stderr.raw", stderr)
    parsed = parse_go_finite_results(stdout + b"\n" + stderr)
    score = independent_score(parsed, vector, exit_code, timed_out)
    observed = sum(len(parsed[suite]) for suite in ("training", "evaluation"))
    planned = len(vector["training"]) + len(vector["evaluation"])
    go_report = {
        "schema": "gooo/ir-composition-independent-go-validation/v1",
        "case_id": item["id"], "activity": item["activity"],
        "status": "GO_TEST_PASS" if exit_code == 0 and not timed_out and observed == planned
                  and all(row["passed"] for suite in parsed.values() for row in suite)
                  else "GO_TEST_FAILURE_OR_INCOMPLETE",
        "go_version": "go1.27.0", "command": command,
        "started_utc": started, "ended_utc": ended, "elapsed_ms": elapsed_ms,
        "timeout_seconds": timeout_seconds, "timed_out": timed_out, "exit_code": exit_code,
        "launch_error": launch_error,
        "source_sha256": sha(source_bytes), "test_source_sha256": sha(test_source.encode()),
        "vector_counts": {"training": len(vector["training"]), "evaluation": len(vector["evaluation"]),
                          "planned_total": planned, "observed_total": observed,
                          "unknown_total": planned - observed},
        "finite_fitness": score,
        "actual_results": parsed,
        "stdout_path": "go-validation/stdout.raw", "stdout_sha256": sha(stdout),
        "stderr_path": "go-validation/stderr.raw", "stderr_sha256": sha(stderr),
    }
    write_json(go_dir / "go-validation.json", go_report)
    return go_report


def update_index(output: Path, results: list[dict], planned: list[dict]) -> None:
    by_id = {row["case_id"]: row for row in results}
    rows = []
    for item in planned:
        row = by_id.get(item["id"])
        rows.append({"sequence": item["sequence"], "case_id": item["id"],
                     "activity": item["activity"], "status": row.get("status", "not_started") if row else "not_started",
                     "case_dir": f"cases/{item['id']}",
                     "result_path": f"cases/{item['id']}/case-result.json" if row else None,
                     "cli_exit_code": (row.get("cli") or {}).get("exit_code") if row else None,
                     "go_exit_code": ((row.get("go_validation") or {}).get("exit_code")
                                      if row and isinstance(row.get("go_validation"), dict) else None)})
    write_json(output / "case-index.json", {"schema": "gooo/ir-composition-case-index/v1",
                                              "planned": 32, "records": rows})


def summarize(results: list[dict], planned: list[dict], vectors: dict[str, dict],
              freeze_status: dict, lineage: dict) -> tuple[dict, dict, dict]:
    cli_successes = [row for row in results
                     if row.get("cli", {}).get("baseline_status") == "CLI_PASS_WITH_SOURCE"]
    cli_failures = [row["case_id"] for row in results
                    if row.get("cli", {}).get("baseline_status") != "CLI_PASS_WITH_SOURCE"]
    source_observed = [row for row in results if row.get("source_unit_completeness", {}).get("status") != "MISSING"]
    src_semantic = sum((row.get("source_unit_completeness", {}).get("denominator") or 0)
                       for row in source_observed)
    lowered_units = sum((row.get("source_unit_completeness", {}).get("numerator") or 0)
                        for row in source_observed)
    src_unknown = 32 - len(source_observed)
    go_rows = [row for row in results if isinstance(row.get("go_validation"), dict)
               and row["go_validation"].get("status") in ("GO_TEST_PASS", "GO_TEST_FAILURE_OR_INCOMPLETE")]
    go_passes = sum(row["go_validation"].get("status") == "GO_TEST_PASS" for row in go_rows)
    go_failures = sum(row["go_validation"].get("status") != "GO_TEST_PASS" for row in go_rows)
    planned_training = sum(len(vectors[item["id"]]["training"]) for item in planned)
    planned_evaluation = sum(len(vectors[item["id"]]["evaluation"]) for item in planned)
    observed_training = sum(row["go_validation"].get("finite_fitness", {}).get("training", {}).get("observed", 0)
                            for row in go_rows)
    passed_training = sum(row["go_validation"].get("finite_fitness", {}).get("training", {}).get("passed", 0)
                          for row in go_rows)
    observed_evaluation = sum(row["go_validation"].get("finite_fitness", {}).get("evaluation", {}).get("observed", 0)
                              for row in go_rows)
    passed_evaluation = sum(row["go_validation"].get("finite_fitness", {}).get("evaluation", {}).get("passed", 0)
                            for row in go_rows)
    unknown_training = max(0, planned_training - observed_training)
    unknown_evaluation = max(0, planned_evaluation - observed_evaluation)
    provider_decisions_observed = sum(
        row.get("compiler_receipt", {}).get("body_fill_decision_mode") in ("laya", "provider")
        for row in results)

    source_completeness = {
        "schema": "gooo/ir-composition-source-unit-completeness-summary/v1",
        "measure": "source AST semantic-unit lowering from the pinned Gooo receipt; kept separate from finite behavior",
        "planned_designs": 32, "observed_receipts": len(source_observed), "unknown_receipts": src_unknown,
        "source_semantic_units_total_in_observed_receipts": src_semantic,
        "lowered_semantic_units_total_in_observed_receipts": lowered_units,
        "source_unit_coverage_percent_observed": (100.0 * lowered_units / src_semantic if src_semantic else None),
        "all_observed_receipts_complete": all(
            row["source_unit_completeness"].get("status") == "PASS"
            and row["source_unit_completeness"].get("numerator") == row["source_unit_completeness"].get("denominator")
            for row in source_observed),
        "per_case": [{"case_id": row["case_id"], **row.get("source_unit_completeness", {"status": "UNKNOWN"})}
                     for row in results],
    }
    finite_fitness = {
        "schema": "gooo/ir-composition-finite-fitness-summary/v1",
        "measure": "independently compiled emitted Go executed over the frozen disjoint training/evaluation vectors",
        "planned_designs": 32,
        "go_compile_validation": {"planned_designs": 32, "attempted_successful_cli_outputs": len(go_rows),
                                  "passed_all_vectors": go_passes, "go_test_failures_or_incomplete": go_failures,
                                  "unknown_no_compile_attempt": 32 - len(go_rows)},
        "training": {"passed": passed_training, "observed": observed_training,
                     "planned": planned_training, "unknown": unknown_training},
        "evaluation": {"passed": passed_evaluation, "observed": observed_evaluation,
                       "planned": planned_evaluation, "unknown": unknown_evaluation},
        "per_case": [{"case_id": row["case_id"], "go_validation_status": row.get("go_validation", {}).get("status"),
                      "training": row.get("go_validation", {}).get("finite_fitness", {}).get("training"),
                      "evaluation": row.get("go_validation", {}).get("finite_fitness", {}).get("evaluation"),
                      "gooo_training_receipt": row.get("finite_fitness", {}).get("gooo_training")}
                     for row in results],
    }
    execution_report = {
        "schema": RESULT_SCHEMA,
        "cohort": "ir-composition-curriculum-2026-09-30",
        "run_id": DEFAULT_OUTPUT.name,
        "created_utc": now_utc(),
        "design_freeze_sha256": freeze_status["design_freeze_sha256"],
        "frozen_file_count": freeze_status["frozen_file_count"],
        "frozen_input_integrity": freeze_status,
        "compiler": freeze_status["compiler"],
        "execution_policy": {
            "attempt_number": 2,
            "invocations_planned": 32, "invocations_attempted": len(results),
            "failed_invocations_retained_in_denominator": 32,
            "independent_go_compile_is_per_case": True,
            "gooo_laya_url_unset": True, "gooo_laya_api_key_unset": True,
            "provider_operations": 0, "model_calls": 0,
            "provider_decisions_reported_by_receipts": provider_decisions_observed,
            "provider_env_removed_from_children": True,
            "mode": "body-codegen --json --fill-plan; original frozen fixture and plan bytes",
        },
        "cli_outcomes": {"planned": 32, "attempted": len(results), "passed_with_emitted_source": len(cli_successes),
                         "failed_or_no_source": len(cli_failures), "failure_case_ids": cli_failures,
                         "generated_source_count": sum(bool(row.get("cli", {}).get("emitted_source_path"))
                                                        for row in results)},
        "source_unit_completeness": source_completeness,
        "finite_fitness": finite_fitness,
        "lineage": lineage,
        "design_results": [{key: value for key, value in row.items() if not key.startswith("_")}
                            for row in results],
        "semantic_limits": [
            "The cohort measures one expression hole with three finite candidates per source fixture; it is not free-form code generation.",
            "Finite vector fitness is separate from source-unit completeness and is not a proof over the full int64 domain.",
            "Evaluation inputs are the frozen independent Python vectors and remain separate from Gooo's training plan.",
            "A failed Gooo CLI invocation remains one failed design in the fixed denominator of 32; no failed plan or candidate was repaired or replaced.",
        ],
    }
    return execution_report, source_completeness, finite_fitness


def render_markdown(report: dict) -> str:
    lines = [
        "# Original Gooo CLI baseline — IR composition curriculum", "",
        f"This offline run attempted {report['execution_policy']['invocations_attempted']}/32 frozen plans with compiler `{report['compiler']['source_revision']}`. It made 0 model calls.", "",
        "Source-unit completeness and finite vector fitness are reported separately. Evaluation values come from the frozen independent Python vector file; they are not added to the search prompt.", "",
        "| Case | CLI | Source-unit units | Gooo training score | Independent Go training | Independent Go evaluation |", "|---|---|---:|---:|---:|---:|",
    ]
    for row in report["design_results"]:
        source = row.get("source_unit_completeness", {})
        numerator, denominator = source.get("numerator"), source.get("denominator")
        unit_score = f"{numerator}/{denominator}" if isinstance(numerator, int) and isinstance(denominator, int) else "unknown"
        training = row.get("finite_fitness", {}).get("gooo_training") or {}
        gscore = (f"{training.get('passed')}/{training.get('total')}" if training.get("passed") is not None
                  else "unknown")
        independent = row.get("go_validation", {}).get("finite_fitness", {})
        def fmt_suite(name: str) -> str:
            score = independent.get(name)
            if not score:
                return "unknown"
            return f"{score['passed']}/{score['planned']} (observed {score['observed']}, unknown {score['unknown']})"
        lines.append(f"| {row['case_id']} | {row.get('cli', {}).get('baseline_status', 'not run')} | {unit_score} | {gscore} | {fmt_suite('training')} | {fmt_suite('evaluation')} |")

    source = report["source_unit_completeness"]
    fitness = report["finite_fitness"]
    lines.extend([
        "", "## Summary", "",
        f"- Gooo CLI: {report['cli_outcomes']['passed_with_emitted_source']}/32 emitted source; {report['cli_outcomes']['failed_or_no_source']} failures retained.",
        f"- Source-unit completeness: {source['lowered_semantic_units_total_in_observed_receipts']}/{source['source_semantic_units_total_in_observed_receipts']} units across {source['observed_receipts']} receipts; {source['unknown_receipts']} receipt rows unknown.",
        f"- Independent Go tests: {fitness['go_compile_validation']['passed_all_vectors']}/32 passed all vectors; {fitness['go_compile_validation']['unknown_no_compile_attempt']} designs had no emitted source to compile.",
        f"- Independent training fitness: {fitness['training']['passed']}/{fitness['training']['planned']} passed, {fitness['training']['observed']} observed, {fitness['training']['unknown']} unknown.",
        f"- Independent evaluation fitness: {fitness['evaluation']['passed']}/{fitness['evaluation']['planned']} passed, {fitness['evaluation']['observed']} observed, {fitness['evaluation']['unknown']} unknown.",
        "- Model calls: 0; provider endpoint and API key were removed from each CLI child environment.",
        "", "## Limits", "", *[f"- {item}" for item in report["semantic_limits"]], "",
        "Raw CLI stdout/stderr, extracted compiler receipts, emitted Go source, per-case Go module and tests, Go test stdout/stderr, and per-case outcome records are retained under `cases/`.", "",
    ])
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, default=DEFAULT_BINARY)
    parser.add_argument("--go-bin", type=Path, default=DEFAULT_GO_BIN)
    parser.add_argument("--timeout-seconds", type=int, default=45)
    parser.add_argument("--go-timeout-seconds", type=int, default=120)
    parser.add_argument("--run-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    if args.timeout_seconds <= 0 or args.go_timeout_seconds <= 0:
        raise RuntimeError("timeouts must be positive")
    run_dir = args.run_dir.resolve()
    if run_dir.exists():
        raise RuntimeError(f"refusing to overwrite original baseline artifacts: {run_dir}")

    # Fail closed if a Laya or other model endpoint/key is present in the parent shell.
    configured_connection_env = [name for name in os.environ
                                 if any(name.startswith(prefix) for prefix in CONNECTION_ENV_PREFIXES)
                                 and bool(os.environ.get(name))]
    if configured_connection_env:
        raise RuntimeError("clear configured GOOO_LAYA_/LAYA_ endpoint/key variables before this offline run")
    parent_model_key_presence = {name: bool(os.environ.get(name)) for name in SENSITIVE_PROVIDER_ENV}

    freeze, frozen_files, freeze_bytes = verify_freeze()
    catalog, designs, vectors, catalog_bytes = verify_design_inputs(freeze, frozen_files)
    lineage, predecessor_report_bytes, predecessor_inventory_bytes = predecessor_attempt_lineage()
    binary = args.binary.resolve()
    compiler = binary_build_receipt(binary, PIN_BINARY_SHA256, PIN_REVISION)
    go_bin = args.go_bin.resolve()
    go_version = subprocess.run([str(go_bin), "version"], capture_output=True, text=True, check=False)
    if go_version.returncode or "go1.27.0" not in go_version.stdout:
        raise RuntimeError(f"independent vector execution requires physical Go 1.27.0; got {go_version.stdout.strip()!r}")

    child_env = os.environ.copy()
    for name in list(child_env):
        if any(name.startswith(prefix) for prefix in CONNECTION_ENV_PREFIXES) or name in SENSITIVE_PROVIDER_ENV:
            child_env.pop(name, None)
    child_env["GOTOOLCHAIN"] = "local"
    child_env["GOPROXY"] = "off"
    child_env["GOSUMDB"] = "off"
    child_env["GOWORK"] = "off"

    # Validate the exact test-source generator before creating the attempt or
    # starting any Gooo CLI process. This catches harness syntax defects early.
    harness = go_harness_preflight(go_bin, child_env)

    run_dir.mkdir(parents=True)
    (run_dir / "cases").mkdir()
    (run_dir / "inputs").mkdir()
    (run_dir / "lineage").mkdir()
    (run_dir / "preflight" / "go-test-harness").mkdir(parents=True)
    vectors_path = COHORT / "oracle" / "testdata" / "vectors.json"
    vectors_bytes = vectors_path.read_bytes()
    write_bytes(run_dir / "inputs" / "design-freeze.json", freeze_bytes)
    write_bytes(run_dir / "inputs" / "catalog.json", catalog_bytes)
    write_bytes(run_dir / "inputs" / "vectors.json", vectors_bytes)
    write_bytes(run_dir / "lineage" / "attempt-1-execution-report.json", predecessor_report_bytes)
    write_bytes(run_dir / "lineage" / "attempt-1-tree-inventory.canonical.json", predecessor_inventory_bytes)
    write_json(run_dir / "lineage" / "attempt-1-lineage.json", lineage)
    harness_dir = run_dir / "preflight" / "go-test-harness"
    write_bytes(harness_dir / "stub.go", harness.pop("stub_source"))
    write_bytes(harness_dir / "generated_test.go", harness.pop("test_source"))
    write_bytes(harness_dir / "stdout.raw", harness.pop("stdout"))
    write_bytes(harness_dir / "stderr.raw", harness.pop("stderr"))
    write_json(harness_dir / "harness-result.json", harness)
    freeze_status = {
        "verified_before_run": True, "verified_after_run": None,
        "design_freeze_path": str(FREEZE_PATH), "design_freeze_sha256": sha(freeze_bytes),
        "frozen_file_count": len(frozen_files), "compiler": compiler,
        "catalog_sha256": sha(catalog_bytes), "vectors_sha256": sha(vectors_bytes),
        "all_32_plans_and_fixtures_verified": True,
    }
    metadata = {
        "schema": "gooo/ir-composition-original-cli-run-metadata/v1",
        "run_id": run_dir.name, "attempt": 2, "status": "starting", "started_utc": now_utc(),
        "runner_script_sha256": sha(Path(__file__).read_bytes()),
        "run_dir": str(run_dir), "binary": compiler, "go_bin": str(go_bin),
        "go_version": go_version.stdout.strip(), "design_freeze_sha256": sha(freeze_bytes),
        "design_count": 32, "plan_file_count": freeze.get("plan_counts", {}).get("body_fill"),
        "parent_sensitive_provider_key_presence_only": parent_model_key_presence,
        "child_environment_policy": {
            "GOOO_LAYA_URL": "unset", "GOOO_LAYA_API_KEY": "unset", "LAYA_API_KEY": "unset",
            "other GOOO_LAYA_ and LAYA_ variables": "removed",
            "OPENAI_API_KEY_ANTHROPIC_API_KEY_GEMINI_API_KEY": "removed",
        },
        "provider_endpoint_unset": True, "provider_api_key_unset": True,
        "provider_operations": 0, "model_calls": 0,
        "go_test_harness_preflight": {key: value for key, value in harness.items() if key != "command"},
        "lineage": lineage,
        "execution_method": "32 independent body-codegen --json --fill-plan CLI processes; one Go test module per emitted source",
    }
    write_json(run_dir / "run-metadata.json", metadata)

    planned = []
    for sequence, item in enumerate(designs, start=1):
        plan_path = COHORT / item["body_fill_plan"]
        fixture_path = COHORT / item["fixture"]
        plan_bytes = plan_path.read_bytes()
        fixture_bytes = fixture_path.read_bytes()
        case_dir = run_dir / "cases" / item["id"]
        (case_dir / "inputs").mkdir(parents=True)
        write_bytes(case_dir / "inputs" / "plan.json", plan_bytes)
        write_bytes(case_dir / "inputs" / "fixture.gooo", fixture_bytes)
        vector_bytes_for_case = json.dumps(vectors[item["id"]], ensure_ascii=False, indent=2).encode() + b"\n"
        write_bytes(case_dir / "inputs" / "python-vector.json", vector_bytes_for_case)
        planned.append({
            "sequence": sequence, "id": item["id"], "activity": item["activity"],
            "primary_semantic_area": item["primary_semantic_area"],
            "intent": item["intent"], "fixture": item["fixture"], "body_fill_plan": item["body_fill_plan"],
            "plan_sha256": sha(plan_bytes), "fixture_sha256": sha(fixture_bytes),
            "vector_sha256": sha(vector_bytes_for_case),
            "intended_candidate_id": item["candidate_discrimination"].get("intended_candidate_id"),
        })
    write_json(run_dir / "planned-cases.json", {"schema": "gooo/ir-composition-original-cli-plan/v1",
                                                  "planned": 32, "cases": planned})
    update_index(run_dir, [], planned)

    results: list[dict] = []
    metadata.update({"status": "cli_running", "cli_started_utc": now_utc()})
    write_json(run_dir / "run-metadata.json", metadata)
    for item, frozen in zip(designs, planned):
        case_dir = run_dir / "cases" / item["id"]
        plan_path = COHORT / item["body_fill_plan"]
        fixture_path = COHORT / item["fixture"]
        cli_result = cli_one(binary, item, plan_path, fixture_path, case_dir,
                             args.timeout_seconds, child_env)
        cli_result["sequence"] = frozen["sequence"]
        cli_result["plan_sha256"] = frozen["plan_sha256"]
        cli_result["fixture_sha256"] = frozen["fixture_sha256"]
        cli_result["vector_sha256"] = frozen["vector_sha256"]
        cli_result["status"] = "cli_complete"
        cli_result["go_validation"] = {"status": "pending" if cli_result.get("_cli_success") else "not_run_no_successful_emission"}
        results.append(cli_result)
        write_json(case_dir / "case-result.partial.json", {key: value for key, value in cli_result.items()
                                                            if not key.startswith("_")})
        update_index(run_dir, results, planned)
        metadata.update({"status": "cli_running", "cli_completed": len(results), "last_cli_case": item["id"]})
        write_json(run_dir / "run-metadata.json", metadata)
        print(json.dumps({"event": "cli_case_complete", "case_id": item["id"],
                          "status": cli_result["cli"]["baseline_status"],
                          "exit_code": cli_result["cli"]["exit_code"],
                          "stdout_bytes": cli_result["cli"]["stdout_bytes"],
                          "stderr_bytes": cli_result["cli"]["stderr_bytes"]}), flush=True)

    # After all individual CLI outputs are durable, run independent Go checks
    # one case at a time. One type/compile failure cannot block later cases.
    metadata.update({"status": "independent_go_running", "cli_finished_utc": now_utc(),
                     "go_validation_started_utc": now_utc()})
    write_json(run_dir / "run-metadata.json", metadata)
    for item, result in zip(designs, results):
        case_dir = run_dir / "cases" / item["id"]
        source_bytes = result.pop("_source_for_independent_go", b"")
        result.pop("_cli_success", None)
        if source_bytes:
            go_result = independent_go_one(item, vectors[item["id"]], case_dir,
                                           go_bin, args.go_timeout_seconds, child_env, source_bytes)
            result["go_validation"] = go_result
            result["finite_fitness"]["independent_generated_go"] = go_result.get("finite_fitness")
        else:
            result["go_validation"] = {"status": "not_run_no_successful_emission",
                                        "planned_training": len(vectors[item["id"]]["training"]),
                                        "planned_evaluation": len(vectors[item["id"]]["evaluation"])}
            result["finite_fitness"]["independent_generated_go"] = None
        result["status"] = "complete"
        write_json(case_dir / "case-result.json", result)
        (case_dir / "case-result.partial.json").unlink(missing_ok=True)
        update_index(run_dir, results, planned)
        metadata.update({"status": "independent_go_running", "go_validation_completed": sum(
            row.get("status") == "complete" for row in results), "last_go_case": item["id"]})
        write_json(run_dir / "run-metadata.json", metadata)

    post_mismatches = []
    for repo_path, expected in frozen_files.items():
        path = ROOT / repo_path
        if not path.is_file() or sha(path.read_bytes()) != expected:
            post_mismatches.append(repo_path)
    freeze_status["verified_after_run"] = not post_mismatches
    freeze_status["post_run_mismatches"] = post_mismatches
    if post_mismatches:
        metadata["status"] = "complete_with_frozen_input_integrity_failure"
    else:
        metadata["status"] = "complete"
    metadata["completed_utc"] = now_utc()
    write_json(run_dir / "frozen-input-integrity.json", freeze_status)

    # Final per-case results contain only JSON-safe evidence; all raw bytes remain separately saved.
    final_results = [read_json(run_dir / "cases" / item["id"] / "case-result.json") for item in designs]
    report, source_report, fitness_report = summarize(final_results, planned, vectors, freeze_status, lineage)
    report["run_id"] = run_dir.name
    report["environment"] = {
        "model_endpoint_unset": True, "model_api_key_unset": True, "model_calls": 0,
        "configured_parent_provider_keys_removed": parent_model_key_presence,
    }
    write_json(run_dir / "source-unit-completeness.json", source_report)
    write_json(run_dir / "finite-fitness.json", fitness_report)
    write_json(run_dir / "execution-report.json", report)
    (run_dir / "report.md").write_text(render_markdown(report), encoding="utf-8")
    metadata.update({"status": "complete" if not post_mismatches else "complete_with_frozen_input_integrity_failure",
                     "completed_utc": now_utc(), "attempted": len(final_results),
                     "cli_successful_emissions": report["cli_outcomes"]["passed_with_emitted_source"],
                     "independent_go_validations": report["finite_fitness"]["go_compile_validation"],
                     "model_calls": 0, "provider_operations": 0})
    write_json(run_dir / "run-metadata.json", metadata)
    print(json.dumps({
        "run_dir": str(run_dir), "planned": 32, "attempted": len(final_results),
        "cli_emitted_sources": report["cli_outcomes"]["passed_with_emitted_source"],
        "cli_failures": report["cli_outcomes"]["failure_case_ids"],
        "independent_go_passed": report["finite_fitness"]["go_compile_validation"]["passed_all_vectors"],
        "independent_go_failures": report["finite_fitness"]["go_compile_validation"]["go_test_failures_or_incomplete"],
        "model_calls": 0, "report": str(run_dir / "execution-report.json"),
    }, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"original Gooo baseline setup failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(2)
