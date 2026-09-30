#!/usr/bin/env python3
"""Offline Linux validator for the original and equivalence-fix 32-case baselines."""
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
import tempfile
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
COHORT = ROOT / "cohorts" / "ir-composition-curriculum-2026-09-30"
OLD = COHORT / "execution" / "original-gooo-cli-baseline"
OLD_CORRECTED = OLD / "go-validation-corrected-v1"
NEW = COHORT / "execution" / "condition-equivalence-60cf7f49"
CANDIDATE_VALIDITY = COHORT / "execution" / "candidate-oracle-attempt-5" / "original-candidate-validity"
EXPECTED_OLD_REVISION = "bb5c1ec2f81cbfb17ac6fb2f7a9e1d7b67168e7f"
EXPECTED_OLD_BINARY = "47b9f3bd1b365d18771ba36b0a2b472b139fdb6a08b404697e188478dce38c6e"
EXPECTED_NEW_REVISION = "60cf7f49b0e302a6bebb42bc8da90f3ed19b2b82"
EXPECTED_NEW_BINARY = "7329b8d255b083bacfd7d44c7271caa4e3c8254bd48cc085068c92665a02591a"
EXPECTED_FAILURES = {
    "bl21_saved_range_predicates:option_a",
    "bl21_saved_range_predicates:option_c",
    "bl23_nonzero_bounded_flag:option_b",
}
EXPECTED_EQUIVALENCE_RECOVERIES = {
    "cc01_inclusive_band", "cc02_nonzero_disjunction", "cc03_two_islands", "cc04_outer_cutoffs",
    "cp17_nonpositive_inclusive", "cp18_exact_release_code", "cp19_range_without_origin",
    "cp20_strict_symmetric_window",
}
MARKER_RE = re.compile(r"FINITERESULT\|(training|evaluation)\|(\d+)\|(-?\d+)\|(-?\d+)\|(-?\d+)\|(true|false)")


class ValidationError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValidationError(message)


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def file_sha(path: Path) -> str:
    return sha(path.read_bytes())


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValidationError(f"invalid or unreadable JSON {path}: {type(exc).__name__}: {exc}") from exc


def dimension(receipt: dict, wanted: str) -> dict:
    comp = receipt.get("completeness_receipt") or {}
    for row in comp.get("dimensions", []):
        if row.get("id") == wanted:
            return row
    return {"id": wanted, "status": "MISSING", "numerator": 0, "denominator": 0}


def changed_json_paths(before: Any, after: Any, prefix: str = "") -> set[str]:
    if isinstance(before, dict) and isinstance(after, dict):
        paths = set()
        for key in set(before) | set(after):
            child = f"{prefix}.{key}" if prefix else key
            if key not in before or key not in after:
                paths.add(child)
            else:
                paths |= changed_json_paths(before[key], after[key], child)
        return paths
    if isinstance(before, list) and isinstance(after, list):
        paths = set()
        if len(before) != len(after):
            paths.add(prefix)
            return paths
        for index, (old, new) in enumerate(zip(before, after)):
            paths |= changed_json_paths(old, new, f"{prefix}[{index}]")
        return paths
    return set() if before == after else {prefix}


def verify_runner_archive(run_dir: Path, metadata: dict, provenance_path: Path,
                          path_key: str, sha_key: str, matches_key: str = "matches_run_metadata") -> dict:
    provenance = read_json(provenance_path)
    source_path = run_dir / provenance[path_key]
    require(source_path.is_file(), f"runner source archive is missing: {source_path}")
    source_sha = file_sha(source_path)
    require(source_sha == metadata.get("runner_script_sha256") == provenance.get(sha_key),
            f"archived runner SHA does not match run metadata: {source_path}")
    require(provenance.get(matches_key) is True,
            f"runner provenance does not attest metadata binding: {provenance_path}")
    return {"path": str(source_path.relative_to(run_dir)), "sha256": source_sha,
            "matches_run_metadata": True, "reconstructed_after_run": bool(provenance.get("reconstructed_after_run"))}


def render_expected_go_test(activity: str, vector: dict, case_id: str) -> bytes:
    def literals(suite: str) -> str:
        return "\n".join(
            f"\t\t{{input: int64({row['input']}), expected: int64({row['expected']})}},"
            for row in vector[suite]
        )
    source = f'''package bodycodegen

import "testing"

type finiteCase struct {{ input, expected int64 }}

func runFinite(t *testing.T, suite string, cases []finiteCase) {{
\tt.Helper()
\tfor index, item := range cases {{
\t\tactual := {activity}(item.input)
\t\tpassed := actual == item.expected
\t\tt.Logf("FINITERESULT|%s|%d|%d|%d|%d|%t", suite, index+1, item.input, item.expected, actual, passed)
\t\tif !passed {{ t.Errorf("%s case %d: {activity}(%d) = %d, want %d", suite, index+1, item.input, actual, item.expected) }}
\t}}
}}

func TestFrozenTrainingVectors_{case_id}(t *testing.T) {{
\tcases := []finiteCase{{
{literals('training')}
\t}}
\trunFinite(t, "training", cases)
}}

func TestFrozenEvaluationVectors_{case_id}(t *testing.T) {{
\tcases := []finiteCase{{
{literals('evaluation')}
\t}}
\trunFinite(t, "evaluation", cases)
}}

'''
    return source.encode("utf-8")


def parse_markers(raw: bytes) -> dict[str, list[dict]]:
    text = raw.decode("utf-8", errors="replace")
    result = {"training": [], "evaluation": []}
    for match in MARKER_RE.finditer(text):
        suite, index, inp, expected, actual, passed = match.groups()
        result[suite].append({"index": int(index), "input": int(inp), "expected": int(expected),
                              "actual": int(actual), "passed": passed == "true"})
    return result


def offline_go_env() -> dict[str, str]:
    env = os.environ.copy()
    for name in list(env):
        if name.startswith("GOOO_LAYA_") or name.startswith("LAYA_") or name in (
            "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY"):
            env.pop(name, None)
    env.update({"GOTOOLCHAIN": "local", "GOPROXY": "off", "GOSUMDB": "off", "GOWORK": "off"})
    return env


def verify_freeze() -> tuple[dict, dict[str, str], dict[str, dict]]:
    freeze_path = COHORT / "design-freeze.json"
    freeze = read_json(freeze_path)
    require(freeze.get("schema") == "gooo/ir-composition-design-freeze/v1", "unexpected design freeze schema")
    frozen_files = freeze.get("files", {})
    require(len(frozen_files) == 142, f"expected 142 frozen source/plan files; found {len(frozen_files)}")
    mismatches = []
    for relative, expected in frozen_files.items():
        path = ROOT / relative
        if not path.is_file() or file_sha(path) != expected:
            mismatches.append(relative)
    require(not mismatches, "frozen input hash mismatch: " + ", ".join(mismatches[:8]))
    vectors = read_json(COHORT / "oracle" / "testdata" / "vectors.json")
    by_id = {row["id"]: row for row in vectors}
    require(len(by_id) == 32, f"expected 32 independent frozen vectors; found {len(by_id)}")
    return freeze, frozen_files, by_id


def verify_old_cli_baseline(vectors: dict[str, dict], freeze: dict) -> tuple[dict, dict, dict]:
    metadata = read_json(OLD / "run-metadata.json")
    report = read_json(OLD / "execution-report.json")
    correction = read_json(OLD_CORRECTED / "corrected-independent-go-report.json")
    old_runner = verify_runner_archive(OLD, metadata, OLD_CORRECTED / "runner-provenance.json",
                                      "capture_runner_path", "capture_runner_sha256",
                                      "capture_runner_matches_run_metadata")
    require(metadata.get("model_calls") == 0 and metadata.get("provider_operations") == 0,
            "original baseline is not model-free")
    require(metadata.get("binary", {}).get("source_revision") == EXPECTED_OLD_REVISION,
            "original baseline compiler source pin mismatch")
    require(metadata.get("binary", {}).get("sha256") == EXPECTED_OLD_BINARY,
            "original baseline compiler binary pin mismatch")
    require(report.get("design_freeze_sha256") == sha((COHORT / "design-freeze.json").read_bytes()),
            "original baseline design freeze hash mismatch")
    require(report.get("execution_policy", {}).get("invocations_attempted") == 32,
            "original CLI baseline does not contain all 32 attempts")
    require(report.get("cli_outcomes", {}).get("generated_source_count") == 22,
            "original CLI baseline source count mismatch")
    old_cases = {row["case_id"]: row for row in report.get("design_results", [])}
    require(len(old_cases) == 32 and set(old_cases) == set(vectors), "original CLI baseline case set mismatch")
    planned_doc = read_json(OLD / "planned-cases.json")
    planned = {row["id"]: row for row in planned_doc.get("cases", [])}
    require(len(planned) == 32 and set(planned) == set(vectors), "original planned case index mismatch")
    catalog = read_json(COHORT / "catalog.json")
    designs = {row["id"]: row for row in catalog.get("designs", [])}
    freeze_files = freeze.get("files", {})
    for case_id, plan in planned.items():
        design = designs[case_id]
        plan_rel, fixture_rel = design["body_fill_plan"], design["fixture"]
        plan_freeze_key = (COHORT.relative_to(ROOT) / plan_rel).as_posix()
        fixture_freeze_key = (COHORT.relative_to(ROOT) / fixture_rel).as_posix()
        require(plan.get("body_fill_plan") == plan_rel and plan.get("fixture") == fixture_rel,
                f"original plan index paths differ from frozen catalog: {case_id}")
        require(plan.get("plan_sha256") == freeze_files.get(plan_freeze_key),
                f"original plan index SHA differs from design freeze: {case_id}")
        require(plan.get("fixture_sha256") == freeze_files.get(fixture_freeze_key),
                f"original fixture index SHA differs from design freeze: {case_id}")
        vector_bytes = (json.dumps(vectors[case_id], ensure_ascii=False, indent=2) + "\n").encode()
        require(plan.get("vector_sha256") == sha(vector_bytes), f"original vector SHA changed: {case_id}")

    for case_id, result in old_cases.items():
        case_dir = OLD / "cases" / case_id
        stdout = case_dir / "cli" / "stdout.raw"
        stderr = case_dir / "cli" / "stderr.raw"
        require(file_sha(stdout) == result["cli"]["stdout_sha256"], f"original stdout hash mismatch: {case_id}")
        require(file_sha(stderr) == result["cli"]["stderr_sha256"], f"original stderr hash mismatch: {case_id}")
        payload = json.loads(stdout.read_bytes())
        payload_report = payload.get("report") if isinstance(payload.get("report"), dict) else payload
        source = payload.get("source", "")
        require(bool(source) == bool(result.get("cli", {}).get("emitted_source_path")),
                f"original raw CLI source presence differs from recorded status: {case_id}")
        if source:
            source_bytes = source.encode("utf-8")
            require(file_sha(case_dir / "generated.go") == result["cli"]["emitted_source_sha256"],
                    f"original emitted Go hash mismatch: {case_id}")
            require(payload_report.get("generated_digest") == "sha256:" + sha(source_bytes),
                    f"original receipt/generated source digest mismatch: {case_id}")
        copied_vector = read_json(OLD / "cases" / case_id / "inputs" / "python-vector.json")
        require(copied_vector == vectors[case_id], f"original copied vector changed: {case_id}")

    old_fitness = correction.get("corrected_independent_go_validation", {})
    require(correction.get("raw_cli_capture_validation", {}).get("all_raw_stdout_and_stderr_hashes_match") is True,
            "corrected original Go replay did not confirm raw CLI hashes")
    require(old_fitness.get("planned_designs") == 32 and old_fitness.get("passed_all_vectors") == 22
            and old_fitness.get("unknown_no_emitted_source") == 10,
            "corrected original independent-Go score does not match the 32-case denominator")
    require(correction.get("original_go_harness_attempt", {}).get("failed_or_incomplete_cases") == 22,
            "original failed harness lineage was not preserved")
    old_measured = sum((row.get("source_unit_completeness") or {}).get("denominator", 0) > 0
                       for row in report.get("design_results", []))
    require(old_measured == 22 and report["source_unit_completeness"]["unknown_receipts"] == 10,
            "original source-unit completeness denominator or unknown count mismatch")
    old_source_rows = report["source_unit_completeness"].get("per_case", [])
    require(len(old_source_rows) == 32
            and sum((row.get("denominator") or 0) > 0 for row in old_source_rows) == 22
            and sum((row.get("denominator") or 0) <= 0 for row in old_source_rows) == 10,
            "original per-case source-unit receipts do not preserve the 22/10 measured/unknown split")
    old_results_by_id = {row["case_id"]: row for row in report["design_results"]}
    for source_row in old_source_rows:
        result = old_results_by_id[source_row["case_id"]]
        has_source = bool(result.get("cli", {}).get("emitted_source_path"))
        measured = (source_row.get("denominator") or 0) > 0
        require(has_source == measured,
                f"original per-case source-unit receipt does not match emitted-source availability: {source_row['case_id']}")
    require(report["source_unit_completeness"]["lowered_semantic_units_total_in_observed_receipts"] == 410
            and report["source_unit_completeness"]["source_semantic_units_total_in_observed_receipts"] == 410,
            "original source-unit completeness totals mismatch")
    metadata["_validated_runner_archive"] = old_runner
    return metadata, report, correction


def verify_new_cli_replay(vectors: dict[str, dict], freeze: dict, old_report: dict) -> tuple[dict, dict]:
    metadata = read_json(NEW / "run-metadata.json")
    report_path = NEW / "execution-report.json"
    source_report_bytes = report_path.read_bytes()
    source_report = json.loads(source_report_bytes)
    runner_archive = verify_runner_archive(NEW, metadata, NEW / "runner-provenance.json",
                                          "runner_source_path", "runner_sha256")
    correction_path = NEW / "derived-summary-correction-v1" / "corrected-execution-report.json"
    correction_receipt_path = NEW / "derived-summary-correction-v1" / "correction-receipt.json"
    correction_receipt = read_json(correction_receipt_path)
    require(correction_receipt.get("source_execution_report_sha256") == sha(source_report_bytes),
            "source-unit correction receipt does not bind the as-run report bytes")
    corrected_bytes = correction_path.read_bytes()
    require(correction_receipt.get("corrected_execution_report_sha256") == sha(corrected_bytes),
            "source-unit correction receipt does not bind corrected report bytes")
    report = json.loads(corrected_bytes)
    allowed_summary_paths = {
        "source_unit_completeness.receipts_available",
        "source_unit_completeness.observed_receipts",
        "source_unit_completeness.unknown_receipts",
    }
    require(changed_json_paths(source_report, report) == allowed_summary_paths,
            "corrected report changes values outside the three source-unit summary fields")
    require(set(item["path"] for item in correction_receipt.get("changed_json_paths", [])) == allowed_summary_paths,
            "correction receipt path whitelist mismatch")
    receipt_diffs = {item["path"]: (item.get("old"), item.get("new"))
                     for item in correction_receipt.get("changed_json_paths", [])}
    require(receipt_diffs == {
        "source_unit_completeness.receipts_available": (None, 32),
        "source_unit_completeness.observed_receipts": (32, 30),
        "source_unit_completeness.unknown_receipts": (0, 2),
    }, "correction receipt does not preserve the exact summary-only 32/0 to 30/2 change")
    source_rows = report.get("source_unit_completeness", {}).get("per_case", [])
    measured_receipts = sum((row.get("denominator") or 0) > 0 for row in source_rows)
    require(report["source_unit_completeness"].get("receipts_available") == 32
            and report["source_unit_completeness"].get("observed_receipts") == measured_receipts == 30
            and report["source_unit_completeness"].get("unknown_receipts") == 2,
            "corrected source-unit measured/unknown denominators do not match per-case receipts")
    require(report["source_unit_completeness"].get("semantic_units_lowered") == 516
            and report["source_unit_completeness"].get("semantic_units_total") == 516,
            "corrected source-unit totals do not match the 30 measured per-case receipts")
    require(metadata.get("model_calls") == 0 and metadata.get("provider_operations") == 0,
            "equivalence replay is not model-free")
    compiler = report.get("new_compiler", {})
    require(compiler.get("source_revision") == EXPECTED_NEW_REVISION,
            "equivalence replay source revision mismatch")
    require(compiler.get("sha256") == EXPECTED_NEW_BINARY, "equivalence replay binary SHA mismatch")
    require(report.get("study_identity", {}).get("new_intent_count") == 0
            and report.get("study_identity", {}).get("frozen_intent_count") == 32,
            "equivalence replay must remain a 32-case before/after comparison")
    require(report.get("run_provenance", {}).get("design_freeze_sha256")
            == sha((COHORT / "design-freeze.json").read_bytes()), "new replay design freeze hash mismatch")
    require(report.get("cli_outcomes", {}).get("planned") == 32
            and report.get("cli_outcomes", {}).get("attempted") == 32,
            "new CLI replay denominator is not 32")
    cases = {row["case_id"]: row for row in report.get("design_results", [])}
    require(len(cases) == 32 and set(cases) == set(vectors), "new CLI replay case set mismatch")
    require(report.get("frozen_input_integrity", {}).get("verified_after_run") is True
            and not report.get("frozen_input_integrity", {}).get("post_run_mismatches"),
            "new replay post-run frozen input integrity failed")
    old_planned = {row["id"]: row for row in read_json(OLD / "planned-cases.json")["cases"]}
    new_planned = {row["id"]: row for row in read_json(NEW / "planned-cases.json")["cases"]}
    require(set(new_planned) == set(old_planned), "new and old replay planned case IDs differ")
    for case_id, row in cases.items():
        old_plan, new_plan = old_planned[case_id], new_planned[case_id]
        require(new_plan["plan_sha256"] == old_plan["plan_sha256"]
                and new_plan["fixture_sha256"] == old_plan["fixture_sha256"]
                and new_plan["vector_sha256"] == old_plan["vector_sha256"],
                f"new replay changed a frozen plan, fixture, or vector: {case_id}")
        design = next(item for item in read_json(COHORT / "catalog.json")["designs"] if item["id"] == case_id)
        case_dir = NEW / "cases" / case_id
        copied_plan = case_dir / "inputs" / "plan.json"
        copied_fixture = case_dir / "inputs" / "fixture.gooo"
        require(file_sha(copied_plan) == new_plan["plan_sha256"] == old_plan["plan_sha256"],
                f"new replay copied plan bytes changed: {case_id}")
        require(file_sha(copied_fixture) == new_plan["fixture_sha256"] == old_plan["fixture_sha256"],
                f"new replay copied fixture bytes changed: {case_id}")
        require(new_plan.get("body_fill_plan") == design["body_fill_plan"]
                and new_plan.get("fixture") == design["fixture"], f"new replay input path changed: {case_id}")
        stdout, stderr = case_dir / "cli" / "stdout.raw", case_dir / "cli" / "stderr.raw"
        require(file_sha(stdout) == row["cli"]["stdout_sha256"], f"new stdout hash mismatch: {case_id}")
        require(file_sha(stderr) == row["cli"]["stderr_sha256"], f"new stderr hash mismatch: {case_id}")
        payload = json.loads(stdout.read_bytes())
        payload_report = payload.get("report") if isinstance(payload.get("report"), dict) else payload
        source = payload.get("source", "")
        require(bool(source) == (row["cli"].get("baseline_status") == "CLI_PASS_WITH_SOURCE"),
                f"new raw CLI source presence differs from recorded status: {case_id}")
        if source:
            source_bytes = source.encode("utf-8")
            require(file_sha(case_dir / "generated.go") == row["cli"]["emitted_source_sha256"],
                    f"new emitted Go hash mismatch: {case_id}")
            require(payload_report.get("generated_digest") == "sha256:" + sha(source_bytes),
                    f"new receipt/source digest mismatch: {case_id}")
            require(payload_report.get("compiler_source_sha") == EXPECTED_NEW_REVISION,
                    f"new source receipt pin mismatch: {case_id}")
    expected_failures = {"bl21_saved_range_predicates", "bl23_nonzero_bounded_flag"}
    observed_failures = {case_id for case_id, row in cases.items()
                         if row["cli"]["baseline_status"] != "CLI_PASS_WITH_SOURCE"}
    require(observed_failures == expected_failures, f"unexpected new CLI failures: {sorted(observed_failures)}")
    expected_old_failures = set(old_report["cli_outcomes"]["failure_case_ids"])
    recovered = expected_old_failures - observed_failures
    require(recovered == EXPECTED_EQUIVALENCE_RECOVERIES,
            f"unexpected before/after condition recoveries: {sorted(recovered)}")
    raw_source = source_report.get("source_unit_completeness", {})
    raw_source_rows = raw_source.get("per_case", [])
    require(len(raw_source_rows) == 32, "as-run source-unit report does not preserve 32 per-case rows")
    raw_source_by_id = {row["case_id"]: row for row in raw_source_rows}
    require(set(raw_source_by_id) == set(vectors), "as-run source-unit row IDs differ from the frozen 32 cases")
    pass_rows = [row for row in raw_source_rows if row.get("status") == "PASS" and (row.get("denominator") or 0) > 0]
    unknown_rows = [row for row in raw_source_rows
                    if row.get("status") == "UNKNOWN" and (row.get("denominator") or 0) == 0]
    require(len(pass_rows) == 30 and len(unknown_rows) == 2
            and {row["case_id"] for row in unknown_rows} == expected_failures,
            "per-case source-unit receipt PASS/UNKNOWN statuses do not reconstruct 30/2")
    for case_id, result in cases.items():
        measured = (raw_source_by_id[case_id].get("denominator") or 0) > 0
        has_source = result["cli"].get("baseline_status") == "CLI_PASS_WITH_SOURCE"
        require(measured == has_source,
                f"as-run per-case source-unit receipt does not match captured source status: {case_id}")
    require(raw_source.get("observed_receipts") == 32 and raw_source.get("unknown_receipts") == 0,
            "the known as-run source-unit aggregate mismatch changed; keep raw report immutable")
    require(correction_receipt.get("reason") and correction_receipt.get("model_calls") == 0
            and correction_receipt.get("raw_cli_outputs_receipts_generated_go_and_finite_scores_modified") is False,
            "source-unit correction provenance does not describe a model-free summary-only derivation")
    metadata["_validated_runner_archive"] = runner_archive
    metadata["_validated_source_unit_correction"] = {
        "receipt_path": str(correction_receipt_path.relative_to(NEW)),
        "receipt_sha256": file_sha(NEW / "derived-summary-correction-v1" / "correction-receipt.json"),
        "as_run_observed_unknown": [raw_source.get("observed_receipts"), raw_source.get("unknown_receipts")],
        "reconstructed_per_case_observed_unknown": [len(pass_rows), len(unknown_rows)],
        "corrected_observed_unknown": [report["source_unit_completeness"]["observed_receipts"],
                                        report["source_unit_completeness"]["unknown_receipts"]],
    }
    return metadata, report


def validate_case_test(go_module: Path, case_id: str, activity: str, vector: dict,
                       go_bin: str, env: dict[str, str], timeout: int) -> dict:
    require((go_module / "go.mod").is_file() and (go_module / "generated.go").is_file()
            and (go_module / "generated_test.go").is_file(), f"saved Go module incomplete: {go_module}")
    test_source = (go_module / "generated_test.go").read_bytes()
    require(test_source == render_expected_go_test(activity, vector, case_id),
            f"saved independent test does not match frozen vectors: {case_id}")
    saved_vectors = read_json(go_module / "frozen-vectors.json")
    require(saved_vectors == {"training": vector["training"], "evaluation": vector["evaluation"]},
            f"saved Go vectors do not match frozen independent vector: {case_id}")
    started = dt.datetime.now(dt.timezone.utc).isoformat()
    try:
        completed = subprocess.run([go_bin, "test", "-count=1", "-v", "./..."], cwd=go_module,
            env=env, capture_output=True, timeout=timeout, check=False)
        stdout, stderr, exit_code = completed.stdout, completed.stderr, completed.returncode
    except subprocess.TimeoutExpired as exc:
        stdout, stderr, exit_code = exc.stdout or b"", exc.stderr or b"", None
    combined = stdout + b"\n" + stderr
    parsed = parse_markers(combined)
    for suite in ("training", "evaluation"):
        planned = vector[suite]
        observed = parsed[suite]
        require(len(observed) == len(planned),
                f"{case_id}/{suite}: expected {len(planned)} FINITERESULT rows, observed {len(observed)}")
        for index, (actual, expected) in enumerate(zip(observed, planned), 1):
            require(actual["index"] == index and actual["input"] == expected["input"]
                    and actual["expected"] == expected["expected"],
                    f"{case_id}/{suite} vector evidence changed at row {index}")
            require(actual["actual"] == expected["expected"] and actual["passed"],
                    f"{case_id}/{suite} generated Go failed frozen vector {index}")
    require(exit_code == 0, f"saved Go test failed for {case_id} with exit code {exit_code}")
    stored_report = read_json(go_module / "go-validation.json")
    require(stored_report.get("status") == "GO_TEST_PASS", f"saved Go validation report is not a pass: {case_id}")
    require(stored_report.get("source_sha256") == file_sha(go_module / "generated.go"),
            f"saved Go source digest mismatch: {case_id}")
    return {"case_id": case_id, "status": "PASS", "go_test_exit_code": exit_code,
            "observed_training": len(parsed["training"]), "observed_evaluation": len(parsed["evaluation"]),
            "stdout_sha256_replayed": sha(stdout), "stderr_sha256_replayed": sha(stderr)}


def verify_saved_go_cases(old_report: dict, new_report: dict, vectors: dict[str, dict],
                          go_bin: str, env: dict[str, str], timeout: int) -> dict:
    runs = []
    per_baseline_fitness = {}
    for label, report, parent in (("original_attempt_2", old_report, OLD),
                                  ("condition_equivalence_60cf7f49", new_report, NEW)):
        emitted = [row for row in report["design_results"]
                   if row.get("cli", {}).get("emitted_source_path")]
        pass_count = 0
        observed_by_suite = {"training": 0, "evaluation": 0}
        for row in emitted:
            case_id = row["case_id"]
            module = (parent / "go-validation-corrected-v1" / "cases" / case_id / "go-validation"
                      if label == "original_attempt_2" else parent / "cases" / case_id / "go-validation")
            case_result = read_json(parent / "cases" / case_id / "case-result.json") if label == "original_attempt_2" else row
            source_case = parent / "cases" / case_id
            expected_source = source_case / "generated.go"
            require(file_sha(module / "generated.go") == file_sha(expected_source),
                    f"saved Go module source differs from captured CLI source: {label}/{case_id}")
            outcome = validate_case_test(module, case_id, row["activity"], vectors[case_id], go_bin, env, timeout)
            pass_count += outcome["status"] == "PASS"
            observed_by_suite["training"] += outcome["observed_training"]
            observed_by_suite["evaluation"] += outcome["observed_evaluation"]
            runs.append({"baseline": label, **outcome})
        require(pass_count == len(emitted), f"not all saved Go cases pass in {label}")
        suite_scores = {}
        for suite in ("training", "evaluation"):
            planned_count = sum(len(row[suite]) for row in vectors.values())
            observed_count = observed_by_suite[suite]
            suite_scores[suite] = {"passed": observed_count, "observed": observed_count,
                "planned": planned_count, "unknown": planned_count - observed_count}
        per_baseline_fitness[label] = {"planned_designs": 32, "emitted_sources": len(emitted),
            "passed_all_vectors": pass_count, "unknown_no_emitted_source": 32 - len(emitted),
            "training": suite_scores["training"], "evaluation": suite_scores["evaluation"]}
    return {"saved_emitted_go_cases_recompiled_and_executed": len(runs),
            "original_attempt_2_cases": sum(row["baseline"] == "original_attempt_2" for row in runs),
            "equivalence_replay_cases": sum(row["baseline"] == "condition_equivalence_60cf7f49" for row in runs),
            "all_pass": True, "per_baseline_finite_fitness": per_baseline_fitness, "per_case": runs}


def verify_candidate_compile_failures(go_bin: str, env: dict[str, str], timeout: int) -> dict:
    report_path = CANDIDATE_VALIDITY.parent / "original-candidate-validity.json"
    recorded = read_json(report_path)
    require(recorded.get("candidate_count") == 96 and recorded.get("valid_count") == 93
            and recorded.get("compile_or_test_failed_count") == 3 and recorded.get("unknown_count") == 0,
            "saved original 96-candidate compile report count mismatch")
    failed_rows = {f"{row['case_id']}:{row['candidate_id']}" for row in recorded["rows"]
                   if row.get("original_source_status") == "compile_or_test_failed"}
    require(failed_rows == EXPECTED_FAILURES, f"recorded three original compiler failures changed: {sorted(failed_rows)}")
    try:
        completed = subprocess.run([go_bin, "test", "-json", "-run", "^$", "./..."], cwd=CANDIDATE_VALIDITY,
            env=env, capture_output=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        raise ValidationError("candidate compile-only replay timed out") from exc
    package_events = []
    for line in completed.stdout.decode("utf-8", errors="replace").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("Action") in ("pass", "fail") and event.get("Package"):
            package_events.append(event)
    failed_packages = {event["Package"].rsplit("/", 1)[-1] for event in package_events
                       if event.get("Action") == "fail"}
    expected_packages = {
        "case21_bl21_saved_range_predicates_option_a",
        "case21_bl21_saved_range_predicates_option_c",
        "case23_bl23_nonzero_bounded_flag_option_b",
    }
    require(completed.returncode != 0, "candidate compile-only replay unexpectedly had no failures")
    require(failed_packages == expected_packages,
            f"candidate compile-only replay failure packages differ: {sorted(failed_packages)}")
    passed_packages = {event["Package"] for event in package_events if event.get("Action") == "pass"}
    require(len(passed_packages) == 93,
            f"expected 93 valid candidate packages, observed {len(passed_packages)}")
    return {"candidate_count": 96, "valid_count": len(passed_packages),
            "compile_fail_count": len(failed_packages), "expected_failure_ids": sorted(failed_rows),
            "observed_failed_packages": sorted(failed_packages),
            "raw_compile_stdout_sha256": sha(completed.stdout),
            "raw_compile_stderr_sha256": sha(completed.stderr),
            "expected_nonzero_exit_code": completed.returncode}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--go-bin", default=shutil.which("go"))
    parser.add_argument("--go-timeout-seconds", type=int, default=180)
    parser.add_argument("--candidate-timeout-seconds", type=int, default=600)
    parser.add_argument("--output", type=Path, help="optional validation report directory, preferably outside checkout")
    args = parser.parse_args()
    require(bool(args.go_bin), "Go executable not found")
    go_bin = str(Path(args.go_bin).resolve())
    go_version = subprocess.run([go_bin, "version"], capture_output=True, text=True, check=False)
    require(go_version.returncode == 0 and "go1.27.0" in go_version.stdout,
            f"Go 1.27.0 required, got {go_version.stdout.strip()!r}")
    freeze, frozen_files, vectors = verify_freeze()
    old_meta, old_report, old_correction = verify_old_cli_baseline(vectors, freeze)
    new_meta, new_report = verify_new_cli_replay(vectors, freeze, old_report)
    env = offline_go_env()
    saved_go = verify_saved_go_cases(old_report, new_report, vectors, go_bin, env, args.go_timeout_seconds)
    old_fitness = old_correction["corrected_independent_go_validation"]
    replayed_old = saved_go["per_baseline_finite_fitness"]["original_attempt_2"]
    replayed_new = saved_go["per_baseline_finite_fitness"]["condition_equivalence_60cf7f49"]
    for baseline_name, report_fitness, replayed in (
        ("original", old_fitness, replayed_old),
        ("equivalence replay", new_report["finite_fitness"], replayed_new),
    ):
        report_passed = report_fitness.get("passed_all_vectors",
                                           report_fitness.get("go_compile_and_vector_passed"))
        require(report_fitness.get("planned_designs") == replayed["planned_designs"]
                and report_passed == replayed["passed_all_vectors"]
                and report_fitness.get("unknown_no_emitted_source") == replayed["unknown_no_emitted_source"],
                f"{baseline_name} aggregate finite-fitness counts differ from replayed modules")
        if "go_compile_or_vector_failures" in report_fitness:
            require(report_fitness["go_compile_or_vector_failures"] == 0,
                    f"{baseline_name} saved Go modules report compile/vector failures")
        for suite in ("training", "evaluation"):
            require(report_fitness[suite] == replayed[suite],
                    f"{baseline_name} {suite} scores/unknown denominator differ from replayed vectors")
    candidate_compile = verify_candidate_compile_failures(go_bin, env, args.candidate_timeout_seconds)

    report = {"schema": "gooo/ir-composition-baseline-validation/v1", "created_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "go_version": go_version.stdout.strip(), "mode": "offline; no Gooo CLI, network, provider, or model calls",
        "frozen_file_count": len(frozen_files), "design_freeze_sha256": sha((COHORT / "design-freeze.json").read_bytes()),
        "original_baseline": {"run_id": old_meta["run_id"], "compiler_revision": EXPECTED_OLD_REVISION,
            "planned": 32, "source_emissions": old_report["cli_outcomes"]["generated_source_count"],
            "cli_failures": old_report["cli_outcomes"]["failure_case_ids"],
            "corrected_go_passed": old_correction["corrected_independent_go_validation"]["passed_all_vectors"]},
        "runner_source_archives": {"original_baseline": old_meta["_validated_runner_archive"],
            "equivalence_replay": new_meta["_validated_runner_archive"]},
        "source_unit_summary_known_issue": new_meta["_validated_source_unit_correction"],
        "equivalence_replay": {"run_id": new_meta["run_id"], "compiler_revision": EXPECTED_NEW_REVISION,
            "planned": 32, "source_emissions": new_report["cli_outcomes"]["passed_with_source"],
            "cli_failures": new_report["cli_outcomes"]["failure_case_ids"],
            "failure_to_pass": new_report["before_after_summary"]["failure_to_pass_case_ids"],
            "finite_fitness": new_report["finite_fitness"]},
        "saved_go_replay": saved_go,
        "original_candidate_compiler_failures": candidate_compile,
        "validation": "PASS"}

    output_dir = args.output.resolve() if args.output else Path(tempfile.mkdtemp(prefix="ir-composition-baseline-validation-"))
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "validation-report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    lines = ["# IR composition baseline validation", "",
        f"Validation passed on {go_version.stdout.strip()} with all model and provider access disabled.", "",
        f"- Original compiler run: {report['original_baseline']['source_emissions']}/32 source emissions; {len(report['original_baseline']['cli_failures'])} CLI failures.",
        f"- Equivalence-fix run: {report['equivalence_replay']['source_emissions']}/32 source emissions; {len(report['equivalence_replay']['cli_failures'])} CLI failures.",
        f"- Saved independent Go modules recompiled and replayed: {saved_go['saved_emitted_go_cases_recompiled_and_executed']}/{saved_go['saved_emitted_go_cases_recompiled_and_executed']} passed.",
        f"- Finite fitness: training {new_report['finite_fitness']['training']['passed']}/{new_report['finite_fitness']['training']['planned']} observed, {new_report['finite_fitness']['training']['unknown']} unknown; evaluation {new_report['finite_fitness']['evaluation']['passed']}/{new_report['finite_fitness']['evaluation']['planned']} observed, {new_report['finite_fitness']['evaluation']['unknown']} unknown.",
        "- Source-unit raw aggregate issue: as-run report says 32 observed / 0 unknown, while its 32 per-case receipts reconstruct to 30 PASS / 2 UNKNOWN; a bound derived correction records 30/2 without changing raw evidence.",
        f"- Frozen original candidate validity: {candidate_compile['valid_count']}/96 compile; exactly {candidate_compile['compile_fail_count']} expected candidate bodies fail compilation.",
        "- Both compiler runs use the same 32 frozen inputs; this is a before/after comparison, not 64 intents.", ""]
    (output_dir / "validation-report.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"validation": "PASS", "output_dir": str(output_dir),
        "saved_go_cases": saved_go["saved_emitted_go_cases_recompiled_and_executed"],
        "candidate_valid": candidate_compile["valid_count"], "candidate_compile_failures": candidate_compile["compile_fail_count"]}, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (ValidationError, OSError, subprocess.SubprocessError) as exc:
        raise SystemExit(f"baseline validation failed: {type(exc).__name__}: {exc}")
