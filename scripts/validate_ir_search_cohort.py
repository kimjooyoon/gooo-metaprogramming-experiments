#!/usr/bin/env python3
"""Validate the published IR-search evidence and run offline compiler replays.

The saved Laya capture is treated as immutable evidence. Local deterministic and
mock-provider runs are separate protocol checks; the mock is not a model replay
or an evaluation of model quality.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


ROOT = Path(__file__).resolve().parents[1]
COHORT = ROOT / "cohorts" / "ir-search-2026-09-30"
PIN = "29d44bc778d85aee03b9af500bd83dc98f368189"
MAC_BINARY_SHA256 = "f9f33b86c2114c1adeba01319fddb7d48f666e739aef768bbb5a580adfb7cda9"
VARIANTS = ("laya_fill_search", "deterministic_fill_search", "exhaustive_fill_plan")
INT64_MIN = -(1 << 63)
INT64_MAX = (1 << 63) - 1


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_sha(path: Path) -> str:
    return sha256(path.read_bytes())


def run(args, *, cwd=None, env=None, check=True, timeout=120):
    proc = subprocess.run(args, cwd=cwd, env=env, text=True, capture_output=True,
                          check=False, timeout=timeout)
    if check and proc.returncode:
        raise RuntimeError(f"command failed ({proc.returncode}): {args}\n{proc.stderr[-4000:]}")
    return proc


def scoped_path(base: Path, relative: str) -> Path:
    path = (base / relative).resolve()
    require(path == base.resolve() or base.resolve() in path.parents,
            f"path escapes cohort: {relative}")
    return path


def check_source_provenance(compiler: Path, binary: Path, source_sha: str):
    head = run(["git", "rev-parse", "HEAD"], cwd=compiler).stdout.strip()
    dirty = run(["git", "status", "--porcelain"], cwd=compiler).stdout
    require(head == source_sha == PIN, f"compiler source is {head}, expected pinned revision {PIN}")
    require(not dirty.strip(), "compiler checkout has tracked modifications")
    go_version = run(["go", "version"]).stdout.strip()
    require("go1.27.1" in go_version, f"expected Go 1.27.1, got {go_version}")
    build_info = run(["go", "version", "-m", str(binary)]).stdout
    build_settings = {}
    for line in build_info.splitlines():
        stripped = line.strip()
        if stripped.startswith("build\t") and "=" in stripped:
            key, value = stripped.removeprefix("build\t").split("=", 1)
            build_settings[key] = value
    require(build_settings.get("vcs.revision") == PIN, "CI binary build metadata lacks the pinned VCS revision")
    require(build_settings.get("vcs.modified") == "false", "CI binary was built from modified source")
    return {"source_revision": head, "compiler_checkout_clean": True,
            "go_version": go_version, "validation_binary_sha256": file_sha(binary),
            "ci_binary_sha256": file_sha(binary) if os.environ.get("GITHUB_ACTIONS") == "true" else None,
            "binary_vcs_revision": PIN, "binary_vcs_modified": False,
            "execution_environment": "github_actions" if os.environ.get("GITHUB_ACTIONS") == "true" else "local",
            "mac_capture_binary_sha256": MAC_BINARY_SHA256,
            "binary_hashes_compared_across_platforms": False}


def check_cohort_plans(manifest):
    require(manifest.get("schema") == "gooo/ir-search-study-manifest/v1", "unexpected cohort manifest schema")
    require(manifest.get("status") == "primary_run_complete", "published primary run is incomplete")
    require(len(manifest.get("intents", [])) == 4, "expected four declared intents")
    require(manifest.get("expected_invocation_count") == 12, "expected twelve invocations")
    require(manifest.get("invocation_variants") == list(VARIANTS), "unexpected invocation variants")
    require(manifest.get("primary_run") == "runs/primary_run", "primary run path is not canonical")
    require(manifest.get("binary", {}).get("source_revision") == PIN, "manifest source pin differs")
    require(manifest.get("binary", {}).get("sha256") == MAC_BINARY_SHA256, "manifest capture binary hash differs")

    check = run(["python3", str(COHORT / "scripts" / "run_cohort.py"), "--check"], cwd=ROOT)
    for intent in manifest["intents"]:
        search = read_json(scoped_path(COHORT, intent["search_plan"]))
        fill = read_json(scoped_path(COHORT, intent["fill_plan"]))
        oracle = read_json(scoped_path(COHORT, intent["oracle"]))
        fixture = scoped_path(COHORT, intent["fixture"]).read_text(encoding="utf-8")
        require(search.get("schema") == "gooo/body-codegen-ir-search-plan/v1", f"{intent['id']}: search schema")
        require(fill.get("schema") == "gooo/body-codegen-ir-fill-plan/v1", f"{intent['id']}: fill schema")
        require("holdout_test_cases" not in fill, f"{intent['id']}: holdout leaked into fill baseline")
        require(search["candidates"] == fill["candidates"] and search["test_cases"] == fill["test_cases"],
                f"{intent['id']}: search/fill candidate or training mismatch")
        require(len(search["candidates"]) == manifest["candidate_count_per_intent"], f"{intent['id']}: candidate count")
        require(search["max_attempts"] == len(search["candidates"]), f"{intent['id']}: max_attempts")
        require(len(search["test_cases"]) == intent["training_cases"], f"{intent['id']}: training count")
        require(len(search["holdout_test_cases"]) == intent["holdout_cases"], f"{intent['id']}: holdout count")
        require(oracle.get("schema") == "gooo/ir-search-finite-oracle/v1" and oracle.get("intent_id") == intent["id"],
                f"{intent['id']}: independent oracle schema or identity")
        hole = f"__GOOO_BODY_HOLE_{search['hole_id']}__"
        require(fixture.count(hole) == 1, f"{intent['id']}: fixture does not contain exactly one declared hole")
        for suite in ("training", "holdout"):
            cases = search["test_cases"] if suite == "training" else search["holdout_test_cases"]
            require(oracle[suite]["inputs"] == [case["input"] for case in cases], f"{intent['id']}: {suite} inputs mismatch")
            require(oracle[suite]["expected"] == [case["expected"] for case in cases], f"{intent['id']}: {suite} expected mismatch")
    return {"plans_and_finite_oracles": "PASS", "check_stdout": check.stdout.strip()}


def contains_key(value, predicate):
    if isinstance(value, dict):
        return any(predicate(str(key).lower()) or contains_key(child, predicate) for key, child in value.items())
    if isinstance(value, list):
        return any(contains_key(child, predicate) for child in value)
    return False


def check_state_feedback(state, search, oracle, label):
    require(not contains_key(state, lambda key: "holdout" in key), f"{label}: holdout field exposed in model state")
    require("holdout" not in json.dumps(state).lower(), f"{label}: holdout text exposed in model state")
    # Training failures are intentionally fed to the next round. Their inputs,
    # expected outputs, and observed outputs must match the declared training
    # suite and independent finite oracle; no other input/expected payloads are
    # permitted in the request state.
    for key, value in state.items():
        if key != "prior_attempts":
            require(not contains_key(value, lambda nested: nested in ("input", "expected", "actual", "case_results", "failed_cases")),
                    f"{label}: case payload outside prior training feedback")
    training_cases = search["test_cases"]
    case_indexes = {case["input"]: index for index, case in enumerate(training_cases)}
    require(len(case_indexes) == len(training_cases), f"{label}: training inputs must be unique for privacy audit")
    for previous in state.get("prior_attempts", []):
        candidate_id = previous.get("candidate_id")
        require(candidate_id in oracle["candidate_outputs"], f"{label}: feedback candidate missing from oracle")
        if not previous.get("scoring_completed"):
            require(previous.get("failed_cases_total", 0) == 0 and not previous.get("failed_cases"),
                    f"{label}: unscored feedback contains candidate test cases")
            continue
        candidate_actuals = oracle["candidate_outputs"][candidate_id]["training"]
        failed_indexes = [index for index, (actual, expected) in enumerate(zip(candidate_actuals, oracle["training"]["expected"]))
                          if actual != expected]
        cases = previous.get("failed_cases", [])
        require(previous.get("failed_cases_total") == len(failed_indexes), f"{label}: training failure count mismatch")
        require(previous.get("failed_cases_truncated") is (len(failed_indexes) > 8), f"{label}: feedback truncation flag mismatch")
        require(len(cases) == min(len(failed_indexes), 8), f"{label}: bounded training feedback size mismatch")
        for case, index in zip(cases, failed_indexes):
            require(case.get("input") in case_indexes, f"{label}: feedback includes a non-training input")
            observed_index = case_indexes[case["input"]]
            require(observed_index == index and case.get("expected") == training_cases[index]["expected"] and
                    case.get("actual") == candidate_actuals[index] and case.get("passed") is False,
                    f"{label}: feedback differs from training suite/oracle")


def check_request_event(run_dir: Path, event, intent, search, receipt, attempt):
    require(event.get("kind") == "laya_choice" and event.get("method") == "POST" and event.get("path") == "/v1/systemone",
            f"{event.get('seq')}: malformed model-choice event")
    require(event.get("question_id") == "body_ir_search", f"{event.get('seq')}: wrong question id")
    require(event.get("search_state_schema") == "gooo/body-codegen-ir-search-state/v1", f"{event.get('seq')}: wrong state schema")
    require(event.get("search_stage") == "choose_before_candidate_evaluation", f"{event.get('seq')}: wrong search stage")
    require(event.get("holdout_fields_present") is False, f"{event.get('seq')}: capture marked holdout fields present")

    request_path = scoped_path(run_dir, event["request_file"])
    response_path = scoped_path(run_dir, event["response_file"])
    request_bytes, response_bytes = request_path.read_bytes(), response_path.read_bytes()
    require(sha256(request_bytes) == event["request_sha256"], f"{event['seq']}: request hash mismatch")
    require(sha256(response_bytes) == event["response_sha256"], f"{event['seq']}: response hash mismatch")
    outer = json.loads(request_bytes)
    require(set(outer) == {"state", "questions"}, f"{event['seq']}: unexpected outer request fields")
    require(not contains_key(outer, lambda key: "holdout" in key), f"{event['seq']}: holdout field exposed in full request")
    require(set(outer.get("questions", {})) == {"body_ir_search"}, f"{event['seq']}: unexpected request questions")
    question = outer["questions"]["body_ir_search"]
    expected_criteria = {candidate["id"]: f"Try this exact expression: {candidate['expression']}"
                         for candidate in search["candidates"]
                         if candidate["id"] in event.get("candidate_option_ids", [])}
    require(question.get("type") == "choice" and question.get("criteria") == expected_criteria,
            f"{event['seq']}: full request choice criteria differ from remaining candidates")
    require("holdout" not in json.dumps(question).lower(), f"{event['seq']}: holdout text exposed in question")
    state_text = outer.get("state", {}).get("request")
    require(isinstance(state_text, str), f"{event['seq']}: typed state request missing")
    require(sha256(state_text.encode("utf-8")) == event["state_request_sha256"], f"{event['seq']}: typed state hash mismatch")
    state = json.loads(state_text)
    require(state.get("schema") == "gooo/body-codegen-ir-search-state/v1", f"{event['seq']}: nested state schema mismatch")
    require(state.get("stage") == "choose_before_candidate_evaluation", f"{event['seq']}: nested stage mismatch")
    require(state.get("training_test_count") == len(search["test_cases"]), f"{event['seq']}: training count mismatch")
    require(state.get("training_suite_sha256") == receipt["training_suite_sha256"], f"{event['seq']}: training digest mismatch")
    oracle = read_json(COHORT / intent["oracle"])
    check_state_feedback(state, search, oracle, f"event {event['seq']}")
    candidates = [candidate["id"] for candidate in search["candidates"]]
    prior = {item.get("candidate_id") for item in state.get("prior_attempts", [])}
    remaining = [candidate_id for candidate_id in candidates if candidate_id not in prior]
    request_candidate_ids = [item["id"] for item in state.get("remaining_candidates", [])]
    require(request_candidate_ids == remaining, f"{event['seq']}: state remaining-candidate order differs")
    # The request criteria are a Go map and are serialized by key, so the event
    # capture records their sorted order rather than the candidate declaration order.
    require(event.get("candidate_option_ids") == sorted(remaining), f"{event['seq']}: event candidate options differ from state")
    require(event.get("training_test_count") == len(search["test_cases"]), f"{event['seq']}: event training count mismatch")
    require(event.get("training_suite_sha256") == receipt["training_suite_sha256"], f"{event['seq']}: event training digest mismatch")
    selected = json.loads(response_bytes).get("answers", {}).get("body_ir_search", {}).get("choice")
    require(selected == event.get("selected_candidate_id") == attempt.get("candidate_id"),
            f"{event['seq']}: response/event/attempt selection mismatch")
    require(attempt.get("decision", {}).get("mode") == "laya", f"{event['seq']}: attempt is not Laya-backed")
    return {"seq": event["seq"], "invocation_id": event["invocation_id"],
            "request_sha256": event["request_sha256"], "response_sha256": event["response_sha256"],
            "state_sha256": event["state_request_sha256"], "selected_candidate_id": selected,
            "holdout_fields_present": False, "training_count": len(search["test_cases"])}


def independent_go_oracle(source: str, activity: str, oracle: dict, go_env: dict):
    require(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", activity) is not None, f"invalid generated Go function name: {activity}")
    inputs = oracle["training"]["inputs"] + oracle["holdout"]["inputs"]
    expected = oracle["training"]["expected"] + oracle["holdout"]["expected"]
    go_ints = lambda values: ", ".join(str(value) for value in values)
    harness = f'''package bodycodegen
import ("encoding/json"; "fmt"; "testing")
func TestIndependentOracle(t *testing.T) {{
 inputs := []int64{{{go_ints(inputs)}}}
 expected := []int64{{{go_ints(expected)}}}
 actual := make([]int64, len(inputs))
 for i, input := range inputs {{
  actual[i] = {activity}(input)
  if actual[i] != expected[i] {{ t.Errorf("input %d: got %d, expected %d", input, actual[i], expected[i]) }}
 }}
 encoded, err := json.Marshal(actual); if err != nil {{ t.Fatal(err) }}
 fmt.Printf("INDEPENDENT_ORACLE_ACTUALS:%s\\n", encoded)
}}
'''
    with tempfile.TemporaryDirectory(prefix="gooo-ir-search-oracle-") as temp_name:
        work = Path(temp_name)
        (work / "generated.go").write_text(source, encoding="utf-8")
        (work / "oracle_test.go").write_text(harness, encoding="utf-8")
        proc = run(["go", "test", "-v", "-run", "^TestIndependentOracle$", "-count=1"],
                   cwd=work, env={**go_env, "GO111MODULE": "off", "GOWORK": "off"}, check=False)
        require(proc.returncode == 0, f"independent compiled Go oracle failed for {activity}:\n{proc.stdout}\n{proc.stderr}")
        marker = next((line.split("INDEPENDENT_ORACLE_ACTUALS:", 1)[1]
                       for line in proc.stdout.splitlines() if "INDEPENDENT_ORACLE_ACTUALS:" in line), None)
        require(marker is not None, f"compiled oracle output missing for {activity}")
        actual = json.loads(marker)
        require(actual == expected, f"compiled output differs from independent oracle for {activity}")
        training_count = len(oracle["training"]["inputs"])
        return {"function": activity, "training_count": len(oracle["training"]["inputs"]),
                "holdout_count": len(oracle["holdout"]["inputs"]), "compiled_go_matches_oracle": True,
                "training_actuals": actual[:training_count], "holdout_actuals": actual[training_count:],
                "actuals_sha256": sha256(json.dumps(actual, separators=(",", ":")).encode())}


def check_recorded_results(report, output, oracle, variant):
    body = report.get("body_search") if variant != "exhaustive_fill_plan" else report.get("body_fill")
    require(isinstance(body, dict), f"{variant}: required fill receipt is missing")
    require(body.get("selected_candidate_id") in oracle["candidate_outputs"], f"{variant}: selected candidate absent from oracle")
    cid = body["selected_candidate_id"]
    expected_train = oracle["candidate_outputs"][cid]["training"]
    expected_holdout = oracle["candidate_outputs"][cid]["holdout"]
    train_cases = oracle["training"]
    holdout_cases = oracle["holdout"]

    if variant == "exhaustive_fill_plan":
        require(body.get("functional_accuracy_percent") == 100, "fill baseline training score is not exact")
        results = body.get("selected_case_results", [])
        require([row.get("actual") for row in results] == expected_train, "fill baseline training actuals differ from oracle")
        require([row.get("expected") for row in results] == train_cases["expected"], "fill baseline training expectations differ")
        scores = {row["id"]: row for row in body.get("candidate_scores", [])}
        require(set(scores) == set(oracle["candidate_outputs"]), "fill baseline candidate-score set differs")
        for candidate_id, candidate_outputs in oracle["candidate_outputs"].items():
            passed = sum(a == e for a, e in zip(candidate_outputs["training"], train_cases["expected"]))
            score = scores[candidate_id]
            require(score.get("test_cases_passed") == passed and score.get("test_cases_total") == len(train_cases["expected"]),
                    f"fill baseline candidate score differs for {candidate_id}")
            require(score.get("accuracy_percent") == 100 * passed / len(train_cases["expected"]),
                    f"fill baseline candidate accuracy differs for {candidate_id}")
        require(body.get("test_cases_total") == len(train_cases["expected"]), "fill baseline training case count")
        require(body.get("test_cases_passed") == len(train_cases["expected"]), "fill baseline selected pass count")
    else:
        require(body.get("global_best_accuracy_percent") is None, f"{variant}: global best must remain unknown")
        attempts = body.get("attempts", [])
        require(body.get("attempted_candidates") == len(attempts), f"{variant}: attempted candidate count mismatch")
        scored = sum(bool(attempt.get("scoring_completed")) for attempt in attempts)
        require(body.get("evaluated_candidates") == scored, f"{variant}: evaluated candidate count mismatch")
        require(body.get("untested_candidates") == len(oracle["candidate_outputs"]) - len(attempts),
                f"{variant}: untested candidate count mismatch")
        for attempt in attempts:
            if attempt.get("scoring_completed"):
                require(attempt.get("test_cases_total") == len(train_cases["expected"]), f"{variant}: attempt training count")
                passed = sum(row.get("passed") is True for row in attempt.get("case_results", []))
                require(attempt.get("test_cases_passed") == passed, f"{variant}: attempt pass count mismatch")
                require(attempt.get("accuracy_percent") == 100 * passed / len(train_cases["expected"]),
                        f"{variant}: attempt accuracy mismatch")
            else:
                require(attempt.get("accuracy_percent") is None, f"{variant}: unscored attempt accuracy must be null")
        require(body.get("training_total") == len(train_cases["expected"]), f"{variant}: training total")
        require(body.get("holdout_total") == len(holdout_cases["expected"]), f"{variant}: holdout total")
        train_results = body.get("training_case_results", [])
        holdout_results = body.get("holdout_case_results", [])
        require([row.get("actual") for row in train_results] == expected_train, f"{variant}: training actuals differ")
        require([row.get("actual") for row in holdout_results] == expected_holdout, f"{variant}: holdout actuals differ")
        require([row.get("expected") for row in train_results] == train_cases["expected"], f"{variant}: training expectations differ")
        require([row.get("expected") for row in holdout_results] == holdout_cases["expected"], f"{variant}: holdout expectations differ")
        training_passed = sum(a == e for a, e in zip(expected_train, train_cases["expected"]))
        holdout_passed = sum(a == e for a, e in zip(expected_holdout, holdout_cases["expected"]))
        require(body.get("training_passed") == training_passed and
                body.get("training_accuracy_percent") == 100 * training_passed / len(train_cases["expected"]),
                f"{variant}: final training accuracy mismatch")
        require(body.get("holdout_passed") == holdout_passed and
                body.get("holdout_accuracy_percent") == 100 * holdout_passed / len(holdout_cases["expected"]),
                f"{variant}: post-selection holdout accuracy mismatch")
    require(expected_train == train_cases["expected"], f"{variant}: training oracle selected body is incorrect")
    require(expected_holdout == holdout_cases["expected"], f"{variant}: holdout oracle selected body is incorrect")
    require(output.get("source", "").startswith("package bodycodegen"), f"{variant}: source output missing")
    return body


def check_primary_run(manifest, compiler_env):
    run_dir = COHORT / manifest["primary_run"]
    metadata = read_json(run_dir / "run-metadata.json")
    require(metadata.get("schema") == "gooo/ir-search-run-metadata/v1" and metadata.get("status") == "complete",
            "primary run metadata is incomplete")
    require(metadata.get("source_revision") == PIN, "primary run compiler revision mismatch")
    require(metadata.get("binary_sha256") == MAC_BINARY_SHA256, "primary run binary SHA mismatch")
    require(metadata.get("runtime", {}).get("offline_only") is True, "primary runtime is not marked offline")
    report = read_json(run_dir / "report.json")
    require(len(report.get("invocations", [])) == 12, "derived report invocation count mismatch")
    events = [json.loads(line) for line in (run_dir / "proxy" / "events.jsonl").read_text().splitlines() if line]
    laya_events = [event for event in events if event.get("kind") == "laya_choice"]
    require(len(laya_events) == 6, f"expected six captured Laya rounds, got {len(laya_events)}")
    require(len(events) == 12 and sum(event.get("kind") == "health_check" for event in events) == 6,
            "expected twelve linked proxy exchanges: six choices and six health checks")

    evidence, raw_resources, model_rounds, final_searches, compiled_oracle_results = [], [], [], [], []
    event_map = {}
    for event in events:
        require(event.get("status") == 200, f"proxy event {event.get('seq')} failed")
        request = scoped_path(run_dir, event["request_file"]).read_bytes()
        response = scoped_path(run_dir, event["response_file"]).read_bytes()
        require(sha256(request) == event["request_sha256"] and sha256(response) == event["response_sha256"],
                f"proxy event {event.get('seq')} raw hashes do not match")
        event_map[event["seq"]] = event

    resource_manifest = read_json(run_dir / "resource_samples.json")
    require(resource_manifest.get("schema") == "gooo/ir-search-resource-samples/v1", "raw resource manifest schema mismatch")
    require(len(resource_manifest.get("invocations", [])) == 12, "raw resource invocation count mismatch")
    report_rows = {(row["intent_id"], row["variant"]): row for row in report["invocations"]}
    raw_rows = {row["invocation_id"]: row for row in resource_manifest["invocations"]}

    for intent in manifest["intents"]:
        search = read_json(COHORT / intent["search_plan"])
        oracle = read_json(COHORT / intent["oracle"])
        for variant in VARIANTS:
            folder = run_dir / "invocations" / intent["id"] / variant
            record = read_json(folder / "invocation.json")
            key = f"{intent['id']}/{variant}"
            require(record.get("schema") == "gooo/ir-search-invocation-record/v1", f"{key}: invocation record schema")
            require(record.get("invocation_id") == key and record.get("intent_id") == intent["id"] and record.get("variant") == variant,
                    f"{key}: invocation identity mismatch")
            require(record.get("exit_code") == 0, f"{key}: raw invocation failed")
            require(record.get("binary_sha256") == MAC_BINARY_SHA256, f"{key}: raw binary SHA mismatch")
            require(record.get("fixture_path") == intent["fixture"], f"{key}: raw fixture path differs from manifest")
            require(record.get("fixture_sha256") == file_sha(COHORT / intent["fixture"]), f"{key}: fixture SHA mismatch")
            expected_plan = COHORT / (intent["search_plan"] if variant != "exhaustive_fill_plan" else intent["fill_plan"])
            expected_plan_rel = intent["search_plan"] if variant != "exhaustive_fill_plan" else intent["fill_plan"]
            require(record.get("plan_path") == expected_plan_rel, f"{key}: raw plan path differs from manifest")
            require(record.get("plan_sha256") == file_sha(expected_plan), f"{key}: plan SHA mismatch")
            saved_fixture = folder / "fixture.gooo.fixture"
            saved_plan = folder / "plan.json"
            require(saved_fixture.is_file() and file_sha(saved_fixture) == file_sha(COHORT / intent["fixture"]),
                    f"{key}: captured fixture snapshot differs from the cohort fixture")
            require(saved_plan.is_file() and file_sha(saved_plan) == file_sha(expected_plan),
                    f"{key}: captured plan snapshot differs from the cohort plan")
            stdout_path, stderr_path = folder / record["stdout_file"], folder / record["stderr_file"]
            require(file_sha(stdout_path) == record["stdout_sha256"], f"{key}: stdout SHA mismatch")
            require(file_sha(stderr_path) == record["stderr_sha256"], f"{key}: stderr SHA mismatch")
            output = read_json(stdout_path)
            cli_report = output.get("report", {})
            require(cli_report.get("compiler_source_sha") == PIN and cli_report.get("decision") == "PASS", f"{key}: compiler report provenance/status")
            body = check_recorded_results(cli_report, output, oracle, variant)
            independent = independent_go_oracle(output["source"], cli_report["activity"], oracle, compiler_env)
            compiled_oracle_results.append({"intent_id": intent["id"], "variant": variant,
                "training_inputs": oracle["training"]["inputs"], "training_expected": oracle["training"]["expected"],
                "training_actuals": independent["training_actuals"],
                "holdout_inputs": oracle["holdout"]["inputs"], "holdout_expected": oracle["holdout"]["expected"],
                "holdout_actuals": independent["holdout_actuals"],
                "holdout_suite_sha256": body.get("holdout_suite_sha256"),
                "holdout_suite_hash_scope": "compiler receipt digest linked to the disjoint oracle suite and compiled output"})

            row = report_rows.get((intent["id"], variant))
            require(row is not None and row.get("exit_code") == 0, f"{key}: offline report row missing or failed")
            require(row.get("generated_digest") == cli_report.get("generated_digest"), f"{key}: summary/generated digest mismatch")
            require(row.get("selected_candidate_id") == body.get("selected_candidate_id"), f"{key}: summary selection mismatch")
            require(row.get("ir_plan_sha256") == body.get("ir_plan_sha256"), f"{key}: summary/plan digest mismatch")
            expected_training_digest = body.get("training_suite_sha256") if variant != "exhaustive_fill_plan" else body.get("test_suite_sha256")
            require(row.get("training_suite_sha256", row.get("test_suite_sha256")) == expected_training_digest,
                    f"{key}: summary/training-suite digest mismatch")
            if variant != "exhaustive_fill_plan":
                require(row.get("holdout_suite_sha256") == body.get("holdout_suite_sha256"), f"{key}: summary/holdout digest mismatch")
                require(row.get("training", {}).get("total") == body.get("training_total") and
                        row.get("holdout", {}).get("total") == body.get("holdout_total"), f"{key}: summary suite counts mismatch")
            else:
                require(row.get("holdout_measurement") == "independent_candidate_oracle_not_executed_by_fill_plan_command",
                        f"{key}: fill-plan holdout is mislabeled as executed CLI evidence")
            selected_holdout = oracle["candidate_outputs"][body["selected_candidate_id"]]["holdout"]
            if variant != "exhaustive_fill_plan":
                independent_holdout = row.get("independent_holdout_oracle", {})
                require(independent_holdout.get("candidate_outputs") == selected_holdout and
                        independent_holdout.get("expected") == oracle["holdout"]["expected"],
                        f"{key}: summarized holdout candidate outputs differ from the independent oracle")
                require(row.get("holdout_outputs_match_independent_oracle") is True,
                        f"{key}: summary does not confirm independent holdout agreement")
            expected_holdout_passed = sum(a == e for a, e in zip(selected_holdout, oracle["holdout"]["expected"]))
            require(row.get("holdout", {}).get("passed") == expected_holdout_passed and
                    row.get("holdout", {}).get("total") == len(oracle["holdout"]["expected"]),
                    f"{key}: summary holdout accuracy differs from oracle")

            resource = read_json(folder / record.get("resources_file", "resource.json"))
            require(resource.get("schema") == "gooo/ir-search-process-resources/v1", f"{key}: resource schema mismatch")
            samples_path = folder / resource.get("raw_samples", "resource-samples.jsonl")
            sample_bytes = samples_path.read_bytes()
            samples = [json.loads(line) for line in sample_bytes.splitlines() if line]
            require(samples and len(samples) == resource.get("cli_process", {}).get("samples"), f"{key}: raw CPU/RSS sample count mismatch")
            require(all(isinstance(sample.get("cli", {}).get("rss_kb"), (int, float)) for sample in samples), f"{key}: CLI RSS samples missing")
            require(all(isinstance(sample.get("laya_server", {}).get("rss_kb"), (int, float)) for sample in samples), f"{key}: Laya RSS samples missing")
            raw_resource = raw_rows.get(key)
            require(raw_resource is not None and raw_resource.get("schema") == resource["schema"], f"{key}: raw resource record missing")
            require(raw_resource.get("cli_process") == resource.get("cli_process"), f"{key}: CLI resource summary mismatch")
            require(raw_resource.get("laya_server") == resource.get("laya_server"), f"{key}: Laya resource summary mismatch")
            if variant == "laya_fill_search":
                require(2 <= resource["laya_server"].get("samples", 0) <= 6, f"{key}: unexpected provider-run sample count")
                server_resource_interpretation = "Laya server was sampled during provider-backed CLI execution; RSS is the largest observed sample, not a process peak."
            else:
                require(len(samples) == 1 and resource["laya_server"].get("samples") == 1,
                        f"{key}: no-provider control should retain its single raw resource snapshot")
                server_resource_interpretation = ("One snapshot of the already-loaded persistent Laya server; zero CPU delta is unknown by construction, "
                                                  "and its RSS is resident server size rather than control-specific memory cost.")
            # Keep CLI and Laya CPU/RSS evidence as separate per-invocation rows; no cross-process aggregate is made.
            raw_resources.append({"invocation_id": key, "variant": variant, "sample_file_sha256": sha256(sample_bytes),
                                  "sample_count": len(samples), "cli_process": resource["cli_process"],
                                  "laya_server": resource["laya_server"],
                                  "rss_interpretation": "largest observed sample; not a process peak",
                                  "laya_server_interpretation": server_resource_interpretation})

            invocation_events = [event_map[seq] for seq in record.get("proxy_event_sequences", [])]
            choice_events = [event for event in invocation_events if event.get("kind") == "laya_choice"]
            attempts = body.get("attempts", []) if variant != "exhaustive_fill_plan" else []
            laya_attempts = [attempt for attempt in attempts if attempt.get("decision", {}).get("mode") == "laya"]
            if variant == "laya_fill_search":
                require(len(choice_events) == len(laya_attempts), f"{key}: captured requests do not link to Laya attempts")
                require(record.get("proxy_event_sequences"), f"{key}: no proxy events recorded")
                for event, attempt in zip(choice_events, laya_attempts):
                    evidence.append(check_request_event(run_dir, event, intent, search, body, attempt))
                    model_rounds.append({"intent_id": intent["id"], "candidate_id": attempt["candidate_id"],
                                         "training_passed": attempt.get("test_cases_passed"),
                                         "training_total": attempt.get("test_cases_total"),
                                         "scoring_completed": attempt.get("scoring_completed"),
                                         "exact_training_match": bool(attempt.get("scoring_completed")) and
                                             attempt.get("test_cases_passed") == attempt.get("test_cases_total"),
                                         "provider_decision_latency_ms": attempt.get("decision_latency_ms"),
                                         "proxy_round_latency_ms": event.get("duration_ms")})
                final_searches.append({"intent_id": intent["id"],
                                       "selected_candidate_id": body.get("selected_candidate_id"),
                                       "training_passed": body.get("training_passed"),
                                       "training_total": body.get("training_total"),
                                       "training_accuracy_percent": body.get("training_accuracy_percent"),
                                       "holdout_passed": body.get("holdout_passed"),
                                       "holdout_total": body.get("holdout_total"),
                                       "holdout_accuracy_percent": body.get("holdout_accuracy_percent"),
                                       "cli_wall_ms": record.get("wall_ms"),
                                       "provider_budget_used_ms": body.get("provider_budget_used_ms"),
                                       "completed_by_sole_remaining_candidate": bool(body.get("attempts")) and
                                           body["attempts"][-1].get("selection_method") == "sole_remaining_candidate"})
            else:
                require(not laya_attempts and not choice_events, f"{key}: offline invocation made a provider request")
            expected_attempted = body.get("attempted_candidates") if variant != "exhaustive_fill_plan" else None
            require(row.get("attempted_candidates") == expected_attempted,
                    f"{key}: summary attempted count mismatch")
            expected_evaluated = body.get("evaluated_candidates") if variant != "exhaustive_fill_plan" else len(body.get("candidate_scores", []))
            require(row.get("evaluated_candidates") == expected_evaluated,
                    f"{key}: summary evaluated count mismatch")

    require(len(evidence) == 6, "not all six captured Laya decisions were validated")
    exact_rounds = sum(item["exact_training_match"] for item in model_rounds)
    first_choice_exact = 0
    for intent in manifest["intents"]:
        first_output = read_json(run_dir / "invocations" / intent["id"] / "laya_fill_search" / "stdout.raw")
        first_attempts = first_output["report"]["body_search"].get("attempts", [])
        if first_attempts and first_attempts[0].get("scoring_completed") and \
                first_attempts[0].get("test_cases_passed") == first_attempts[0].get("test_cases_total"):
            first_choice_exact += 1
    holdout_digests = {}
    for intent in manifest["intents"]:
        digests = {row.get("holdout_suite_sha256") for row in compiled_oracle_results
                   if row["intent_id"] == intent["id"] and row["variant"] != "exhaustive_fill_plan"}
        require(len(digests) == 1, f"{intent['id']}: Laya/deterministic holdout receipt digests differ")
        holdout_digests[intent["id"]] = next(iter(digests))
    current_manifest_sha = file_sha(COHORT / "manifest.json")
    return {"raw_invocations": 12, "laya_backed_invocations": 4, "captured_laya_rounds": len(evidence),
            "proxy_exchange_counts": {"total": len(events), "choice": len(laya_events),
                                      "health_check": sum(event.get("kind") == "health_check" for event in events)},
            "captured_request_privacy_and_linkage": evidence, "compiled_go_oracle_count": 12,
            "compiled_oracle_results": compiled_oracle_results,
            "holdout_suite_receipt_digests_by_intent": holdout_digests,
            "manifest_snapshot_integrity": {"run_recorded_manifest_sha256": metadata.get("cohort_manifest_sha256"),
                "current_manifest_sha256": current_manifest_sha,
                "comparison": "not asserted: run metadata records a pre-finalization manifest snapshot that is not retained; fixture/plan snapshots and their raw digests are verified"},
            "model_choice_training_metrics": {"exact_laya_choices": exact_rounds, "laya_choices": len(model_rounds),
                "exact_training_match_rate_percent": (100 * exact_rounds / len(model_rounds)) if model_rounds else None,
                "first_choice_exact_intents": first_choice_exact, "intents": len(manifest["intents"]),
                "rounds": model_rounds,
                "interpretation": "Observed training-only model choices; not the final selected-body accuracy."},
            "final_search_and_latency_metrics": {"intents": final_searches,
                "latency_policy": "provider round, cumulative provider budget, and whole CLI wall time are listed separately; no speedup claim"},
            "raw_resource_evidence": raw_resources,
            "resource_policy": "per-invocation CLI and Laya CPU/RSS remain separate; largest observed RSS sample is not a process peak; no aggregate mixing"}


def stable_signature(output):
    report = output["report"]
    body = report["body_search"]
    return {
        "source": output["source"], "generated_digest": report.get("generated_digest"),
        "compiler_source_sha": report.get("compiler_source_sha"), "decision": report.get("decision"),
        "selected_candidate_id": body.get("selected_candidate_id"), "selected_expression": body.get("selected_expression"),
        "training_suite_sha256": body.get("training_suite_sha256"), "holdout_suite_sha256": body.get("holdout_suite_sha256"),
        "training_case_results": body.get("training_case_results"), "holdout_case_results": body.get("holdout_case_results"),
        "stop_reason": body.get("stop_reason"), "attempted_candidates": body.get("attempted_candidates"),
        "evaluated_candidates": body.get("evaluated_candidates"),
        "attempts": [{key: attempt.get(key) for key in ("candidate_id", "expression", "typecheck_passed", "scoring_completed",
                      "test_cases_passed", "test_cases_total", "accuracy_percent", "case_results", "selection_method")}
                     for attempt in body.get("attempts", [])]}


class MockChooser:
    def __init__(self):
        self.states = []
        self.lock = threading.Lock()

    def handler(self):
        chooser = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass
            def do_GET(self):
                payload = json.dumps({"revisions": {}}).encode()
                self.send_response(200); self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload))); self.end_headers(); self.wfile.write(payload)
            def do_POST(self):
                raw = self.rfile.read(int(self.headers.get("Content-Length", "0")))
                outer = json.loads(raw)
                state_text = outer["state"]["request"]
                state = json.loads(state_text)
                choices = state.get("remaining_candidates", [])
                if not choices:
                    self.send_error(400); return
                selected = choices[0]["id"]
                with chooser.lock:
                    chooser.states.append({"state": state, "selected": selected,
                                           "request_sha256": sha256(raw), "state_sha256": sha256(state_text.encode())})
                payload = json.dumps({"model": "offline-mock-protocol-check",
                                      "answers": {"body_ir_search": {"type": "choice", "choice": selected}}}).encode()
                self.send_response(200); self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload))); self.end_headers(); self.wfile.write(payload)
        return Handler


def invoke(binary: Path, fixture: Path, plan: Path, activity: str, temp: Path, provider_url=""):
    env = os.environ.copy()
    env.pop("GOOO_LAYA_API_KEY", None)
    env["GOOO_LAYA_URL"] = provider_url
    proc = run([str(binary), "body-codegen", "--json", "--fill-search", str(plan), "--activity", activity, str(fixture)],
               cwd=temp, env=env, check=False)
    return proc


def check_deterministic_replays(binary: Path, manifest, go_env, output_dir: Path):
    rows = []
    with tempfile.TemporaryDirectory(prefix="gooo-ir-search-deterministic-") as temp_name:
        temp = Path(temp_name)
        for intent in manifest["intents"]:
            fixture, plan = COHORT / intent["fixture"], COHORT / intent["search_plan"]
            activity = read_json(COHORT / intent["oracle"]).get("activity")
            # Activity is source-declared; read it from a prior report for this intent.
            primary = read_json(COHORT / manifest["primary_run"] / "invocations" / intent["id"] /
                                "deterministic_fill_search" / "stdout.raw")
            activity = primary["report"]["activity"]
            first = invoke(binary, fixture, plan, activity, temp)
            second = invoke(binary, fixture, plan, activity, temp)
            require(first.returncode == second.returncode == 0, f"{intent['id']}: deterministic replay failed")
            one, two = json.loads(first.stdout), json.loads(second.stdout)
            sig1, sig2 = stable_signature(one), stable_signature(two)
            require(sig1 == sig2, f"{intent['id']}: deterministic repeats differ")
            primary_signature = stable_signature(primary)
            require(sig1 == primary_signature, f"{intent['id']}: replay differs from saved deterministic output")
            oracle = read_json(COHORT / intent["oracle"])
            compiled = independent_go_oracle(one["source"], activity, oracle, go_env)
            rows.append({"intent_id": intent["id"], "repeats_identical": True,
                         "matches_primary_deterministic": True, "provider_configured": False,
                         "compiled_go_oracle": compiled})
    return rows


def check_mock_replays(binary: Path, manifest, go_env, output_dir: Path):
    chooser = MockChooser()
    server = ThreadingHTTPServer(("127.0.0.1", 0), chooser.handler())
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    rows = []
    try:
        endpoint = f"http://127.0.0.1:{server.server_address[1]}/v1/systemone"
        with tempfile.TemporaryDirectory(prefix="gooo-ir-search-mock-") as temp_name:
            temp = Path(temp_name)
            for intent in manifest["intents"]:
                before = len(chooser.states)
                fixture, plan_path = COHORT / intent["fixture"], COHORT / intent["search_plan"]
                primary = read_json(COHORT / manifest["primary_run"] / "invocations" / intent["id"] /
                                    "deterministic_fill_search" / "stdout.raw")
                proc = invoke(binary, fixture, plan_path, primary["report"]["activity"], temp, endpoint)
                require(proc.returncode == 0, f"{intent['id']}: mock provider protocol replay failed: {proc.stderr}")
                output = json.loads(proc.stdout)
                search = read_json(plan_path)
                own_states = chooser.states[before:]
                mock_attempts = [attempt for attempt in output["report"]["body_search"]["attempts"]
                                 if attempt.get("decision", {}).get("mode") == "laya"]
                require(len(own_states) == len(mock_attempts), f"{intent['id']}: mock round count mismatch")
                require([saved["selected"] for saved in own_states] == [attempt["candidate_id"] for attempt in mock_attempts],
                        f"{intent['id']}: mock response/attempt linkage mismatch")
                for saved in own_states:
                    state = saved["state"]
                    require(state.get("schema") == "gooo/body-codegen-ir-search-state/v1", "mock request state schema mismatch")
                    require(state.get("stage") == "choose_before_candidate_evaluation", "mock request stage mismatch")
                    require(state.get("training_test_count") == len(search["test_cases"]), "mock training count mismatch")
                oracle = read_json(COHORT / intent["oracle"])
                check_state_feedback(state, search, oracle, "mock request")
                compiled = independent_go_oracle(output["source"], primary["report"]["activity"], oracle, go_env)
                rows.append({"intent_id": intent["id"], "mock_rounds": len(own_states),
                             "captured_state_sha256": [item["state_sha256"] for item in own_states],
                             "holdout_exposed": False, "compiled_go_oracle": compiled,
                             "label": "mock provider protocol replay only; not an actual Laya replay or model evaluation"})
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)
    return rows


def check_unscored_failure_probe(binary: Path, manifest):
    chooser = MockChooser()
    server = ThreadingHTTPServer(("127.0.0.1", 0), chooser.handler())
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    try:
        intent = manifest["intents"][0]
        base = read_json(COHORT / intent["search_plan"])
        base["candidates"] = [{"id": "boolvalue", "expression": "true"},
                               {"id": "booltest", "expression": "input == 0"}]
        base["max_attempts"] = 2
        with tempfile.TemporaryDirectory(prefix="gooo-ir-search-null-score-") as temp_name:
            temp = Path(temp_name); plan_path = temp / "invalid-search-plan.json"
            plan_path.write_text(json.dumps(base), encoding="utf-8")
            primary = read_json(COHORT / manifest["primary_run"] / "invocations" / intent["id"] /
                                "deterministic_fill_search" / "stdout.raw")
            endpoint = f"http://127.0.0.1:{server.server_address[1]}/v1/systemone"
            proc = invoke(binary, COHORT / intent["fixture"], plan_path, primary["report"]["activity"], temp, endpoint)
            require(proc.returncode != 0, "invalid-candidate probe unexpectedly succeeded")
            failure = json.loads(proc.stdout)
            receipt = failure.get("body_search")
            require(failure.get("decision") == "FAIL_CLOSED" and isinstance(receipt, dict),
                    f"all-invalid failure omitted the body_search trace: {json.dumps(failure)[:1600]} {proc.stderr[-1000:]}")
            require(receipt.get("attempted_candidates") == 2 and receipt.get("evaluated_candidates") == 0,
                    "all-invalid probe counts mismatch")
            attempts = receipt.get("attempts", [])
            require(len(attempts) == 2, "all-invalid probe attempt trace is incomplete")
            for attempt in attempts:
                require(attempt.get("scoring_completed") is False and attempt.get("accuracy_percent") is None,
                        "unscored rejected candidate must have null accuracy")
            require(receipt.get("global_best_accuracy_percent") is None, "all-invalid probe global best should be unknown")
            return {"decision": "FAIL_CLOSED", "attempted_candidates": 2, "evaluated_candidates": 0,
                    "unscored_accuracies": [None, None], "provider": "local mock chooser only"}
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compiler-root", required=True, type=Path)
    parser.add_argument("--binary", required=True, type=Path)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    compiler, binary, output_dir = args.compiler_root.resolve(), args.binary.resolve(), args.output.resolve()
    require(compiler.is_dir() and binary.is_file(), "compiler source checkout or binary does not exist")
    require(re.fullmatch(r"[0-9a-f]{40}", args.source_sha) is not None, "--source-sha must be a 40-character lowercase SHA")
    output_dir.mkdir(parents=True, exist_ok=True)
    provenance = check_source_provenance(compiler, binary, args.source_sha)
    manifest = read_json(COHORT / "manifest.json")
    plan_validation = check_cohort_plans(manifest)
    go_env = os.environ.copy()
    go_env.pop("GOOO_LAYA_URL", None); go_env.pop("GOOO_LAYA_API_KEY", None)
    primary = check_primary_run(manifest, go_env)
    deterministic = check_deterministic_replays(binary, manifest, go_env, output_dir)
    mock = check_mock_replays(binary, manifest, go_env, output_dir)
    null_probe = check_unscored_failure_probe(binary, manifest)
    result = {
        "schema": "gooo/ir-search-validation-report/v1",
        "cohort_id": manifest["cohort_id"],
        "compiler_provenance": provenance,
        "plan_validation": plan_validation,
        "primary_capture": primary,
        "deterministic_replays": deterministic,
        "mock_protocol_replays": mock,
        "mock_protocol_replay_label": "local mock chooser; no actual Laya calls and no model-quality claim",
        "unscored_failure_probe": null_probe,
        "resource_aggregation": "not performed; raw CPU/RSS remains split by invocation and process",
    }
    report_path = output_dir / "validation-report.json"
    report_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    lines = ["# IR-search cohort validation", "", "All 12 saved CLI outputs were compiled and checked against the independent Go oracle.",
             "The committed Laya capture was read only. The separate local mock-provider replay checks protocol handling and is not a model evaluation.", "",
             f"- Saved invocations: {primary['raw_invocations']}",
             f"- Captured Laya rounds: {primary['captured_laya_rounds']}",
             f"- Exact training-only Laya choices: {primary['model_choice_training_metrics']['exact_laya_choices']}/{primary['model_choice_training_metrics']['laya_choices']}",
             f"- Exact first choices: {primary['model_choice_training_metrics']['first_choice_exact_intents']}/{primary['model_choice_training_metrics']['intents']} intents",
             "- Final selected search bodies: training and post-selection holdout are reported separately in the JSON artifact; no speedup claim is made",
             f"- Deterministic replays: {len(deterministic)} intents, each repeated identically",
             f"- Mock protocol replays: {len(mock)} intents; no Laya calls",
             "- CPU/RSS evidence: separate per-invocation records; sampled RSS is not a process peak, and no-provider controls have one Laya-server snapshot whose zero CPU delta is unknown",
             "- Manifest digest: the run records a pre-finalization snapshot whose bytes were not retained; fixture and plan snapshots are checked directly", ""]
    (output_dir / "validation-report.md").write_text("\n".join(lines), encoding="utf-8")
    print(report_path)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"IR-search validation failed: {exc}", file=__import__("sys").stderr)
        raise SystemExit(1)
