#!/usr/bin/env python3
"""Replay the same 32 frozen IR-composition plans with the equivalence-fix compiler."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_ir_composition_original_cli as baseline


ROOT = Path(__file__).resolve().parents[1]
COHORT = ROOT / "cohorts" / "ir-composition-curriculum-2026-09-30"
OLD_RUN = COHORT / "execution" / "original-gooo-cli-baseline"
OLD_REPORT = OLD_RUN / "execution-report.json"
OLD_CORRECTED_REPORT = OLD_RUN / "go-validation-corrected-v1" / "corrected-independent-go-report.json"
DEFAULT_BINARY = Path("/tmp/gooo-condition-equivalence-60cf7f49-20260930")
DEFAULT_GO_BIN = Path("/Users/alice/go/pkg/mod/golang.org/toolchain@v0.0.1-go1.27.0.darwin-arm64/bin/go")
DEFAULT_OUTPUT = COHORT / "execution" / "condition-equivalence-60cf7f49"
SOURCE_REVISION = "60cf7f49b0e302a6bebb42bc8da90f3ed19b2b82"
BINARY_SHA256 = "7329b8d255b083bacfd7d44c7271caa4e3c8254bd48cc085068c92665a02591a"
RESULT_SCHEMA = "gooo/ir-composition-condition-equivalence-replay/v1"
CONNECTION_PREFIXES = ("GOOO_LAYA_", "LAYA_")
PROVIDER_KEYS = ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY")


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def write_json(path: Path, value: Any) -> bytes:
    raw = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
    baseline.write_bytes(path, raw)
    return raw


def dimension(receipt: dict, wanted: str) -> dict:
    return baseline.dimension(receipt, wanted)


def load_old_inputs(freeze: dict, designs: list[dict]) -> tuple[dict, dict, bytes, bytes]:
    if not OLD_REPORT.is_file() or not OLD_CORRECTED_REPORT.is_file():
        raise RuntimeError("required original attempt-2 baseline or corrected independent-Go report is missing")
    old_meta = baseline.read_json(OLD_RUN / "run-metadata.json")
    old_report_bytes = OLD_REPORT.read_bytes()
    old_report = json.loads(old_report_bytes)
    old_corrected_bytes = OLD_CORRECTED_REPORT.read_bytes()
    old_corrected = json.loads(old_corrected_bytes)
    if old_meta.get("attempt") != 2 or old_meta.get("model_calls") != 0:
        raise RuntimeError("original baseline is not the expected offline attempt 2")
    if (old_report.get("design_freeze_sha256") != sha((COHORT / "design-freeze.json").read_bytes())
            or old_report.get("cli_outcomes", {}).get("planned") != 32
            or len(old_report.get("design_results", [])) != 32):
        raise RuntimeError("original baseline is not bound to the same 32-case frozen study")
    if old_corrected.get("corrected_independent_go_validation", {}).get("planned_designs") != 32:
        raise RuntimeError("corrected original vector report has an unexpected denominator")
    old_planned = baseline.read_json(OLD_RUN / "planned-cases.json").get("cases", [])
    if len(old_planned) != 32:
        raise RuntimeError("original attempt-2 plan index does not have 32 rows")
    old_by_id = {item["id"]: item for item in old_planned}
    for item in designs:
        old = old_by_id.get(item["id"])
        if not old:
            raise RuntimeError(f"original baseline is missing frozen case {item['id']}")
        plan_path = COHORT / item["body_fill_plan"]
        fixture_path = COHORT / item["fixture"]
        vector_path = COHORT / "oracle" / "testdata" / "vectors.json"
        vector = json.loads(vector_path.read_bytes())
        expected_plan_sha = sha(plan_path.read_bytes())
        expected_fixture_sha = sha(fixture_path.read_bytes())
        if old.get("plan_sha256") != expected_plan_sha or old.get("fixture_sha256") != expected_fixture_sha:
            raise RuntimeError(f"new replay would not use byte-identical frozen plan/fixture for {item['id']}")
        if item["id"] not in {row.get("id") for row in vector}:
            raise RuntimeError(f"frozen vector is missing for {item['id']}")
    return old_meta, old_report, old_report_bytes, old_corrected_bytes


def child_environment() -> dict[str, str]:
    env = os.environ.copy()
    for name in list(env):
        if any(name.startswith(prefix) for prefix in CONNECTION_PREFIXES) or name in PROVIDER_KEYS:
            env.pop(name, None)
    env.update({"GOTOOLCHAIN": "local", "GOPROXY": "off", "GOSUMDB": "off", "GOWORK": "off"})
    return env


def run_cli(binary: Path, item: dict, plan: Path, fixture: Path, case_dir: Path,
            timeout_seconds: int, env: dict[str, str]) -> dict:
    cli_dir = case_dir / "cli"
    cli_dir.mkdir(parents=True)
    command = [str(binary), "body-codegen", "--json", "--fill-plan", str(plan),
               "--activity", item["activity"], str(fixture)]
    started = utc_now()
    start_ns = time.monotonic_ns()
    timed_out = False
    launch_error = None
    exit_code: int | None = None
    stdout = stderr = b""
    try:
        completed = subprocess.run(command, cwd=case_dir, env=env, capture_output=True,
                                   timeout=timeout_seconds, check=False)
        stdout, stderr, exit_code = completed.stdout, completed.stderr, completed.returncode
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        stdout, stderr = exc.stdout or b"", exc.stderr or b""
        launch_error = f"TimeoutExpired after {timeout_seconds}s"
    except Exception as exc:
        launch_error = f"{type(exc).__name__}: {exc}"
        stderr = (launch_error + "\n").encode()
    ended = utc_now()
    elapsed_ms = (time.monotonic_ns() - start_ns) / 1_000_000
    baseline.write_bytes(cli_dir / "stdout.raw", stdout)
    baseline.write_bytes(cli_dir / "stderr.raw", stderr)

    payload = None
    parse_error = None
    if stdout:
        try:
            payload = json.loads(stdout)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            parse_error = f"{type(exc).__name__}: {exc}"
    payload = payload if isinstance(payload, dict) else {}
    report = payload.get("report") if isinstance(payload.get("report"), dict) else payload
    if report:
        write_json(cli_dir / "response.parsed.json", payload)
    source_text = payload.get("source", "")
    source_bytes = source_text.encode("utf-8") if isinstance(source_text, str) and source_text else b""
    if source_bytes:
        baseline.write_bytes(case_dir / "generated.go", source_bytes)
    compiler_sha = report.get("compiler_source_sha")
    generated_digest = report.get("generated_digest")
    generated_digest_matches = bool(source_bytes) and generated_digest == "sha256:" + sha(source_bytes)
    receipt = {
        "available": bool(report), "schema": report.get("schema"),
        "decision": report.get("decision"), "compiler_source_sha": compiler_sha,
        "plan_sha256": report.get("plan_sha256"), "source_digest": report.get("source_digest"),
        "generated_digest": generated_digest, "generated_digest_matches_bytes": generated_digest_matches,
        "activity_id": report.get("activity_id"), "error": report.get("error"),
        "typecheck_passed": report.get("typecheck_passed"),
        "route_equivalence_decision": (report.get("route_equivalence") or {}).get("decision"),
        "body_fill_selected_candidate_id": (report.get("body_fill") or {}).get("selected_candidate_id"),
        "body_fill_selected_expression": (report.get("body_fill") or {}).get("selected_expression"),
        "body_fill_training": baseline.score_from_receipt(report).get("gooo_training"),
        "provider_operations_reported": report.get("provider_operations", 0),
        "model_calls_reported": report.get("model_calls", 0),
        "source_unit_completeness": dimension(report, "source_ast_coverage"),
        "completeness_decision": ((report.get("completeness_receipt") or {}).get("decision")),
    }
    cli_pass = (exit_code == 0 and not timed_out and not launch_error and parse_error is None
                and report.get("decision") == "PASS" and bool(source_bytes)
                and compiler_sha == SOURCE_REVISION and generated_digest_matches)
    status = "CLI_PASS_WITH_SOURCE" if cli_pass else "CLI_FAILURE_OR_UNVERIFIED"
    result = {
        "schema": "gooo/ir-composition-equivalence-replay-case/v1",
        "case_id": item["id"], "activity": item["activity"],
        "cli": {"command": command, "cwd": str(case_dir), "started_utc": started, "ended_utc": ended,
            "elapsed_ms": elapsed_ms, "timeout_seconds": timeout_seconds, "timed_out": timed_out,
            "exit_code": exit_code, "launch_error": launch_error, "json_parse_error": parse_error,
            "baseline_status": status, "stdout_path": "cli/stdout.raw", "stdout_sha256": sha(stdout),
            "stdout_bytes": len(stdout), "stderr_path": "cli/stderr.raw", "stderr_sha256": sha(stderr),
            "stderr_bytes": len(stderr), "parsed_response_path": "cli/response.parsed.json" if report else None,
            "emitted_source_path": "generated.go" if source_bytes else None,
            "emitted_source_sha256": sha(source_bytes) if source_bytes else None},
        "compiler_receipt": receipt,
        "source_unit_completeness": receipt["source_unit_completeness"],
        "finite_fitness": {"gooo_training": receipt["body_fill_training"], "independent_generated_go": None},
        "go_validation": {"status": "pending" if source_bytes else "not_run_no_emitted_source"},
        "_source_bytes": source_bytes,
    }
    return result


def update_index(run_dir: Path, results: list[dict], plan_rows: list[dict]) -> None:
    by_id = {row["case_id"]: row for row in results}
    rows = []
    for plan in plan_rows:
        row = by_id.get(plan["id"])
        rows.append({"sequence": plan["sequence"], "case_id": plan["id"],
            "status": row.get("status", "not_started") if row else "not_started",
            "result_path": f"cases/{plan['id']}/case-result.json" if row else None,
            "cli_exit_code": (row.get("cli") or {}).get("exit_code") if row else None,
            "go_status": (row.get("go_validation") or {}).get("status") if row else None})
    write_json(run_dir / "case-index.json", {"schema": "gooo/ir-composition-equivalence-case-index/v1",
                                              "planned": 32, "records": rows})


def suite_total(rows: list[dict], vectors: dict[str, dict], suite: str) -> dict:
    passed = observed = 0
    planned = sum(len(vectors[row["case_id"]][suite]) for row in rows)
    for row in rows:
        part = ((row.get("go_validation") or {}).get("finite_fitness") or {}).get(suite) or {}
        passed += int(part.get("passed", 0))
        observed += int(part.get("observed", 0))
    return {"passed": passed, "observed": observed, "planned": planned,
            "unknown": max(0, planned - observed)}


def build_report(results: list[dict], plans: list[dict], vectors: dict[str, dict],
                 freeze_status: dict, old_meta: dict, old_report: dict,
                 old_report_sha: str, old_corrected_sha: str, binary_info: dict,
                 runner_sha: str, harness: dict) -> dict:
    old_by_id = {row["case_id"]: row for row in old_report["design_results"]}
    rows = []
    for row in results:
        plain = {key: value for key, value in row.items() if not key.startswith("_")}
        old = old_by_id[row["case_id"]]
        plain["before_after"] = {
            "old_compiler_revision": old_meta["binary"]["source_revision"],
            "old_cli_status": old.get("cli", {}).get("baseline_status"),
            "new_compiler_revision": SOURCE_REVISION,
            "new_cli_status": row["cli"]["baseline_status"],
            "transition": ("failure_to_pass" if old.get("cli", {}).get("baseline_status") != "CLI_PASS_WITH_SOURCE"
                            and row["cli"]["baseline_status"] == "CLI_PASS_WITH_SOURCE" else
                           "pass_to_failure" if old.get("cli", {}).get("baseline_status") == "CLI_PASS_WITH_SOURCE"
                            and row["cli"]["baseline_status"] != "CLI_PASS_WITH_SOURCE" else
                           "same_pass" if row["cli"]["baseline_status"] == "CLI_PASS_WITH_SOURCE" else "same_failure")}
        rows.append(plain)
    cli_pass = sum(row["cli"]["baseline_status"] == "CLI_PASS_WITH_SOURCE" for row in results)
    with_source = sum(bool(row.get("cli", {}).get("emitted_source_path")) for row in results)
    cli_failures = [row["case_id"] for row in results if row["cli"]["baseline_status"] != "CLI_PASS_WITH_SOURCE"]
    source_observed = [row for row in results if row.get("compiler_receipt", {}).get("available")]
    source_semantic = sum((row["source_unit_completeness"].get("denominator") or 0) for row in source_observed)
    lowered = sum((row["source_unit_completeness"].get("numerator") or 0) for row in source_observed)
    go_pass = sum(row.get("go_validation", {}).get("status") == "GO_TEST_PASS" for row in results)
    go_fail = sum(row.get("go_validation", {}).get("status") == "GO_TEST_FAILURE_OR_INCOMPLETE" for row in results)
    old_cli_pass = old_report["cli_outcomes"]["passed_with_emitted_source"]
    recovered = [r["case_id"] for r in rows if r["before_after"]["transition"] == "failure_to_pass"]
    regressed = [r["case_id"] for r in rows if r["before_after"]["transition"] == "pass_to_failure"]
    old_corrected = baseline.read_json(OLD_CORRECTED_REPORT)
    old_go = old_corrected["corrected_independent_go_validation"]
    plan_rows = [{key: value for key, value in row.items() if key != "_source_bytes"} for row in plans]
    return {
        "schema": RESULT_SCHEMA,
        "cohort": COHORT.name,
        "run_id": DEFAULT_OUTPUT.name,
        "created_utc": utc_now(),
        "study_identity": {"frozen_intent_count": 32, "new_intent_count": 0,
            "description": "Same byte-identical 32 frozen plans rerun under a compiler pin with outer-parentheses route equivalence normalization."},
        "new_compiler": binary_info,
        "old_baseline": {"run_id": old_meta["run_id"], "compiler_source_revision": old_meta["binary"]["source_revision"],
            "compiler_binary_sha256": old_meta["binary"]["sha256"], "execution_report_path": str(OLD_REPORT.relative_to(ROOT)),
            "execution_report_sha256": old_report_sha, "corrected_independent_go_report_path": str(OLD_CORRECTED_REPORT.relative_to(ROOT)),
            "corrected_independent_go_report_sha256": old_corrected_sha,
            "cli_pass_with_source": old_cli_pass, "cli_failures": old_report["cli_outcomes"]["failure_case_ids"],
            "independent_go_passed": old_go["passed_all_vectors"],
            "training": old_go["training"], "evaluation": old_go["evaluation"]},
        "run_provenance": {"source_revision": SOURCE_REVISION, "binary_sha256": BINARY_SHA256,
            "design_freeze_sha256": freeze_status["design_freeze_sha256"], "runner_script_sha256": runner_sha,
            "input_files_byte_identical_to_frozen_plan": True, "provider_endpoint_unset": True,
            "provider_api_key_unset": True, "provider_operations": 0, "model_calls": 0,
            "gooo_cli_calls_planned": 32, "gooo_cli_calls_attempted": len(results),
            "harness_preflight": {key: value for key, value in harness.items() if key not in ("stdout", "stderr", "stub_source", "test_source")}},
        "frozen_input_integrity": freeze_status,
        "cli_outcomes": {"planned": 32, "attempted": len(results), "passed_with_source": cli_pass,
            "emitted_source_bytes": with_source, "failed_or_unverified": len(cli_failures),
            "failure_case_ids": cli_failures},
        "source_unit_completeness": {"planned_designs": 32, "observed_receipts": len(source_observed),
            "unknown_receipts": 32 - len(source_observed), "semantic_units_lowered": lowered,
            "semantic_units_total": source_semantic,
            "coverage_percent_observed": 100.0 * lowered / source_semantic if source_semantic else None,
            "per_case": [{"case_id": row["case_id"], **row["source_unit_completeness"]} for row in results]},
        "finite_fitness": {"planned_designs": 32,
            "go_compile_and_vector_passed": go_pass, "go_compile_or_vector_failures": go_fail,
            "unknown_no_emitted_source": 32 - with_source,
            "training": suite_total(results, vectors, "training"),
            "evaluation": suite_total(results, vectors, "evaluation")},
        "before_after_summary": {"old_cli_pass_with_source": old_cli_pass,
            "new_cli_pass_with_source": cli_pass, "new_failed_or_unverified": len(cli_failures),
            "failure_to_pass_case_ids": recovered, "pass_to_failure_case_ids": regressed,
            "original_failure_ids": old_report["cli_outcomes"]["failure_case_ids"],
            "remaining_failures": cli_failures},
        "design_results": rows,
        "plan_index": plan_rows,
        "semantic_limits": [
            "This is a before/after compiler comparison over the same frozen 32 plans, fixtures, and vectors; it contributes zero new intents.",
            "Finite Go vectors are bounded observations and do not prove full-domain behavior.",
            "CLI failures and their full raw stdout/stderr remain in the planned denominator; no failed plan or candidate was repaired or retried.",
        ],
    }


def render_markdown(report: dict) -> str:
    lines = [
        "# Condition equivalence compiler replay", "",
        "This replays the same 32 frozen plans with the compiler revision below. It adds zero new intents and makes zero model calls.", "",
        f"- Previous compiler `{report['old_baseline']['compiler_source_revision']}`: {report['old_baseline']['cli_pass_with_source']}/32 emitted source.",
        f"- New compiler `{report['new_compiler']['source_revision']}`: {report['cli_outcomes']['passed_with_source']}/32 passed CLI with source; {report['cli_outcomes']['failed_or_unverified']} remained failed or unverified.",
        f"- Failure-to-pass cases: {', '.join(report['before_after_summary']['failure_to_pass_case_ids']) or 'none'}.",
        f"- Pass-to-failure cases: {', '.join(report['before_after_summary']['pass_to_failure_case_ids']) or 'none'}.",
        f"- Independent Go vectors: {report['finite_fitness']['go_compile_and_vector_passed']}/32 emitted cases passed all vectors; {report['finite_fitness']['unknown_no_emitted_source']} designs had no emitted source.",
        "- Source-unit completeness and finite vector fitness are reported separately.", "",
        "| Case | Previous CLI | New CLI | Change | Source units | Independent Go | Training passed / observed / planned | Evaluation passed / observed / planned |",
        "|---|---|---|---|---:|---|---:|---:|",
    ]
    for row in report["design_results"]:
        before = row["before_after"]
        unit = row.get("source_unit_completeness", {})
        unit_score = f"{unit.get('numerator', 0)}/{unit.get('denominator', 0)}" if unit.get("status") != "MISSING" else "unknown"
        go = row.get("go_validation", {}).get("status", "unknown")
        finite = ((row.get("go_validation") or {}).get("finite_fitness") or {})
        def score(suite: str) -> str:
            part = finite.get(suite, {})
            planned = row.get("go_validation", {}).get("vector_counts", {}).get(suite)
            return f"{part.get('passed', 0)} / {part.get('observed', 0)} / {planned if planned is not None else '?'}"
        lines.append(f"| {row['case_id']} | {before['old_cli_status']} | {before['new_cli_status']} | {before['transition']} | {unit_score} | {go} | {score('training')} | {score('evaluation')} |")
    lines.extend(["", "## Finite fitness", "",
        f"- Training: {report['finite_fitness']['training']['passed']}/{report['finite_fitness']['training']['planned']} passed; {report['finite_fitness']['training']['observed']} observed; {report['finite_fitness']['training']['unknown']} unknown.",
        f"- Evaluation: {report['finite_fitness']['evaluation']['passed']}/{report['finite_fitness']['evaluation']['planned']} passed; {report['finite_fitness']['evaluation']['observed']} observed; {report['finite_fitness']['evaluation']['unknown']} unknown.",
        "", "All plan and fixture bytes were checked against the frozen manifest before and after the run. Raw CLI output, receipts, generated sources, and Go test evidence are saved per case.", ""])
    return "\n".join(lines)


def main() -> None:
    import argparse
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
        raise RuntimeError(f"refusing to overwrite equivalence replay artifacts: {run_dir}")
    endpoint_vars = [name for name in os.environ if any(name.startswith(p) for p in CONNECTION_PREFIXES)
                     and os.environ.get(name)]
    if endpoint_vars:
        raise RuntimeError("provider endpoint/key variables must be unset for offline replay")

    freeze, frozen_files, freeze_bytes = baseline.verify_freeze()
    catalog, designs, vector_by_id, catalog_bytes = baseline.verify_design_inputs(freeze, frozen_files)
    old_meta, old_report, old_report_bytes, old_corrected_bytes = load_old_inputs(freeze, designs)
    binary = args.binary.resolve()
    compiler = baseline.binary_build_receipt(binary, BINARY_SHA256, SOURCE_REVISION)
    go_bin = args.go_bin.resolve()
    go_version = subprocess.run([str(go_bin), "version"], capture_output=True, text=True, check=False)
    if go_version.returncode or "go1.27.0" not in go_version.stdout:
        raise RuntimeError(f"independent Go validation requires physical Go 1.27.0; got {go_version.stdout.strip()!r}")

    env = child_environment()
    harness = baseline.go_harness_preflight(go_bin, env)
    run_dir.mkdir(parents=True)
    for dirname in ("cases", "inputs", "preflight"):
        (run_dir / dirname).mkdir()
    baseline.write_bytes(run_dir / "inputs" / "design-freeze.json", freeze_bytes)
    baseline.write_bytes(run_dir / "inputs" / "catalog.json", catalog_bytes)
    vector_bytes = (COHORT / "oracle" / "testdata" / "vectors.json").read_bytes()
    baseline.write_bytes(run_dir / "inputs" / "vectors.json", vector_bytes)
    baseline.write_bytes(run_dir / "inputs" / "old-execution-report.json", old_report_bytes)
    baseline.write_bytes(run_dir / "inputs" / "old-corrected-independent-go-report.json", old_corrected_bytes)
    harness_dir = run_dir / "preflight" / "go-test-harness"
    harness_dir.mkdir()
    baseline.write_bytes(harness_dir / "stub.go", harness["stub_source"])
    baseline.write_bytes(harness_dir / "generated_test.go", harness["test_source"])
    baseline.write_bytes(harness_dir / "stdout.raw", harness["stdout"])
    baseline.write_bytes(harness_dir / "stderr.raw", harness["stderr"])
    write_json(harness_dir / "harness-result.json", {key: value for key, value in harness.items()
              if key not in ("stdout", "stderr", "stub_source", "test_source")})

    input_sha = sha(freeze_bytes)
    freeze_status = {"verified_before_run": True, "verified_after_run": None,
        "design_freeze_path": str((COHORT / "design-freeze.json").relative_to(ROOT)),
        "design_freeze_sha256": input_sha, "frozen_file_count": len(frozen_files),
        "all_32_plans_fixtures_and_vectors_verified": True, "post_run_mismatches": []}
    runner_sha = sha(Path(__file__).read_bytes())
    old_report_sha = sha(old_report_bytes)
    old_corrected_sha = sha(old_corrected_bytes)
    metadata = {"schema": "gooo/ir-composition-equivalence-replay-metadata/v1",
        "run_id": run_dir.name, "started_utc": utc_now(), "status": "starting",
        "runner_script_sha256": runner_sha, "new_compiler": compiler,
        "go_bin": str(go_bin), "go_version": go_version.stdout.strip(),
        "design_freeze_sha256": input_sha, "design_count": 32,
        "old_report_sha256": old_report_sha, "old_corrected_go_report_sha256": old_corrected_sha,
        "provider_endpoint_unset": True, "provider_api_key_unset": True,
        "provider_operations": 0, "model_calls": 0,
        "same_frozen_plans_as_original": True, "new_intent_count": 0,
        "go_test_harness_preflight": {key: value for key, value in harness.items()
            if key not in ("stdout", "stderr", "stub_source", "test_source")}}
    write_json(run_dir / "run-metadata.json", metadata)

    planned: list[dict] = []
    for sequence, item in enumerate(designs, start=1):
        plan_path = COHORT / item["body_fill_plan"]
        fixture_path = COHORT / item["fixture"]
        plan_bytes, fixture_bytes = plan_path.read_bytes(), fixture_path.read_bytes()
        case_dir = run_dir / "cases" / item["id"]
        (case_dir / "inputs").mkdir(parents=True)
        baseline.write_bytes(case_dir / "inputs" / "plan.json", plan_bytes)
        baseline.write_bytes(case_dir / "inputs" / "fixture.gooo", fixture_bytes)
        vbytes = json.dumps(vector_by_id[item["id"]], ensure_ascii=False, indent=2).encode() + b"\n"
        baseline.write_bytes(case_dir / "inputs" / "python-vector.json", vbytes)
        old_case = next(row for row in old_report["design_results"] if row["case_id"] == item["id"])
        planned.append({"sequence": sequence, "id": item["id"], "activity": item["activity"],
            "primary_semantic_area": item["primary_semantic_area"], "intent": item["intent"],
            "body_fill_plan": item["body_fill_plan"], "fixture": item["fixture"],
            "plan_sha256": sha(plan_bytes), "fixture_sha256": sha(fixture_bytes), "vector_sha256": sha(vbytes),
            "old_cli_status": old_case.get("cli", {}).get("baseline_status"),
            "old_cli_stdout_sha256": old_case.get("cli", {}).get("stdout_sha256"),
            "intended_candidate_id": item["candidate_discrimination"].get("intended_candidate_id")})
    write_json(run_dir / "planned-cases.json", {"schema": "gooo/ir-composition-equivalence-plan-index/v1",
        "planned": 32, "same_as_frozen_original_design": True, "cases": planned})
    results: list[dict] = []
    update_index(run_dir, results, planned)
    metadata.update({"status": "cli_running", "cli_started_utc": utc_now()})
    write_json(run_dir / "run-metadata.json", metadata)

    for item, frozen in zip(designs, planned):
        case_dir = run_dir / "cases" / item["id"]
        result = run_cli(binary, item, COHORT / item["body_fill_plan"], COHORT / item["fixture"],
                         case_dir, args.timeout_seconds, env)
        result["sequence"] = frozen["sequence"]
        result["plan_sha256"] = frozen["plan_sha256"]
        result["fixture_sha256"] = frozen["fixture_sha256"]
        result["vector_sha256"] = frozen["vector_sha256"]
        result["status"] = "cli_complete"
        (case_dir / "case-result.partial.json").write_bytes(json.dumps(
            {k: v for k, v in result.items() if not k.startswith("_")}, ensure_ascii=False, indent=2,
            sort_keys=True).encode() + b"\n")
        results.append(result)
        update_index(run_dir, results, planned)
        metadata.update({"status": "cli_running", "cli_completed": len(results), "last_cli_case": item["id"]})
        write_json(run_dir / "run-metadata.json", metadata)
        print(json.dumps({"event": "cli_case_complete", "case_id": item["id"],
            "status": result["cli"]["baseline_status"], "exit_code": result["cli"]["exit_code"]}), flush=True)

    metadata.update({"status": "independent_go_running", "cli_finished_utc": utc_now(),
                     "go_validation_started_utc": utc_now()})
    write_json(run_dir / "run-metadata.json", metadata)
    for item, result in zip(designs, results):
        source_bytes = result.pop("_source_bytes")
        case_dir = run_dir / "cases" / item["id"]
        if source_bytes:
            go_result = baseline.independent_go_one({"id": item["id"], "activity": item["activity"]},
                vector_by_id[item["id"]], case_dir, go_bin, args.go_timeout_seconds, env, source_bytes)
            result["go_validation"] = go_result
            result["finite_fitness"]["independent_generated_go"] = go_result.get("finite_fitness")
        else:
            result["go_validation"] = {"status": "unknown_no_emitted_source",
                "planned_training": len(vector_by_id[item["id"]]["training"]),
                "planned_evaluation": len(vector_by_id[item["id"]]["evaluation"])}
        result["status"] = "complete"
        write_json(case_dir / "case-result.json", result)
        (case_dir / "case-result.partial.json").unlink(missing_ok=True)
        update_index(run_dir, results, planned)
        metadata.update({"status": "independent_go_running", "go_validation_completed": sum(
            row.get("status") == "complete" for row in results), "last_go_case": item["id"]})
        write_json(run_dir / "run-metadata.json", metadata)

    mismatches = []
    for repo_path, expected in frozen_files.items():
        path = ROOT / repo_path
        if not path.is_file() or sha(path.read_bytes()) != expected:
            mismatches.append(repo_path)
    freeze_status["verified_after_run"] = not mismatches
    freeze_status["post_run_mismatches"] = mismatches
    write_json(run_dir / "frozen-input-integrity.json", freeze_status)
    final_rows = [baseline.read_json(run_dir / "cases" / item["id"] / "case-result.json") for item in designs]
    report = build_report(final_rows, planned, vector_by_id, freeze_status, old_meta, old_report,
        old_report_sha, old_corrected_sha, compiler, runner_sha, harness)
    write_json(run_dir / "execution-report.json", report)
    (run_dir / "report.md").write_text(render_markdown(report), encoding="utf-8")
    metadata.update({"status": "complete" if not mismatches else "complete_with_frozen_input_integrity_failure",
        "completed_utc": utc_now(), "attempted": len(final_rows),
        "cli_pass_with_source": report["cli_outcomes"]["passed_with_source"],
        "cli_failure_case_ids": report["cli_outcomes"]["failure_case_ids"],
        "finite_fitness": report["finite_fitness"], "model_calls": 0, "provider_operations": 0})
    write_json(run_dir / "run-metadata.json", metadata)
    print(json.dumps({"run_dir": str(run_dir), "planned": 32, "attempted": len(final_rows),
        "cli_pass_with_source": report["cli_outcomes"]["passed_with_source"],
        "cli_failure_case_ids": report["cli_outcomes"]["failure_case_ids"],
        "go_passed": report["finite_fitness"]["go_compile_and_vector_passed"],
        "training": report["finite_fitness"]["training"],
        "evaluation": report["finite_fitness"]["evaluation"], "model_calls": 0}, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"condition equivalence replay failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(2)
