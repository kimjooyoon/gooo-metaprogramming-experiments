#!/usr/bin/env python3
"""Run every frozen design independently through offline Gooo and Go."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COHORT = ROOT / "cohorts/ir-composition-curriculum-2026-09-30"
PIN_REVISION = "bb5c1ec2f81cbfb17ac6fb2f7a9e1d7b67168e7f"
PIN_BINARY_SHA256 = "47b9f3bd1b365d18771ba36b0a2b472b139fdb6a08b404697e188478dce38c6e"
GO_VERSION = "go1.27.1"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def verify_design_freeze() -> dict:
    path = COHORT / "design-freeze.json"
    manifest = read_json(path)
    changed = []
    for relative, expected in manifest.get("files", {}).items():
        artifact = ROOT / relative
        if not artifact.is_file() or sha(artifact.read_bytes()) != expected:
            changed.append(relative)
    if changed:
        raise SystemExit("frozen design changed: " + ", ".join(changed[:8]))
    if manifest.get("design_count") != 32 or manifest.get("provider_model") != "english":
        raise SystemExit("design freeze does not match the 32-design English-pinned cohort")
    return manifest


def dimension(report, wanted):
    receipt = report.get("completeness_receipt") or {}
    for item in receipt.get("dimensions", []):
        if item.get("id") == wanted:
            return {
                "id": wanted,
                "status": item.get("status"),
                "numerator": item.get("numerator"),
                "denominator": item.get("denominator"),
                "unit": item.get("unit"),
            }
    return {"id": wanted, "status": "MISSING", "numerator": 0, "denominator": 0}


def go_test_source(activity, training, evaluation):
    cases = []
    for split, rows in (("training", training), ("evaluation", evaluation)):
        cases.extend(
            f'{{split: "{split}", input: {row["input"]}, expected: {row["expected"]}}}'
            for row in rows
        )
    body = ",\n".join("\t\t" + row for row in cases)
    return f'''package bodycodegen

import (
    "encoding/json"
    "os"
    "testing"
)

func TestFrozenTrainingAndEvaluationCases(t *testing.T) {{
    cases := []struct {{ split string; input, expected int64 }}{{
{body}
    }}
    results := make([]struct {{
        Split string `json:"split"`
        Input int64 `json:"input"`
        Expected int64 `json:"expected"`
        Actual int64 `json:"actual"`
        Passed bool `json:"passed"`
    }}, 0, len(cases))
    for _, item := range cases {{
        actual := {activity}(item.input)
        results = append(results, struct {{
            Split string `json:"split"`
            Input int64 `json:"input"`
            Expected int64 `json:"expected"`
            Actual int64 `json:"actual"`
            Passed bool `json:"passed"`
        }}{{Split:item.split, Input:item.input, Expected:item.expected, Actual:actual, Passed:actual==item.expected}})
    }}
    encoded, err := json.Marshal(results)
    if err != nil {{ t.Fatal(err) }}
    if err := os.WriteFile("execution-results.json", encoded, 0o644); err != nil {{ t.Fatal(err) }}
    for _, item := range results {{
        if !item.Passed {{ t.Errorf("%s(%d) = %d, want %d", item.Split, item.Input, item.Actual, item.Expected) }}
    }}
}}
'''


def parse_go_events(output: str, prefix: str):
    statuses = {}
    messages = {}
    for line in output.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        package = event.get("Package", "")
        if not package.startswith(prefix):
            continue
        if event.get("Action") == "output":
            messages[package] = messages.get(package, "") + event.get("Output", "")
        if event.get("Action") in {"pass", "fail"} and "Test" not in event:
            statuses[package.rsplit("/", 1)[-1]] = event["Action"]
    return statuses, messages


def execution_counts(path: Path):
    if not path.is_file():
        return {"status": "go_test_did_not_reach_case_execution", "training": {"passed": 0, "total": 0}, "evaluation": {"passed": 0, "total": 0}, "results": []}
    rows = read_json(path)
    output = {}
    for split in ("training", "evaluation"):
        subset = [row for row in rows if row["split"] == split]
        output[split] = {"passed": sum(row["passed"] for row in subset), "total": len(subset)}
    output["status"] = "passed" if all(row["passed"] for row in rows) else "mismatched"
    output["results"] = rows
    return output


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", type=Path, default=Path("/tmp/gooo-pinned-context-final-20260930"))
    parser.add_argument("--go-bin", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=int, default=30)
    args = parser.parse_args()
    manifest = verify_design_freeze()
    if os.environ.get("GOOO_LAYA_URL", "").strip() or os.environ.get("GOOO_LAYA_API_KEY", "").strip():
        raise SystemExit("offline run requires GOOO_LAYA_URL and GOOO_LAYA_API_KEY to be unset")
    if not args.binary.is_file() or sha(args.binary.read_bytes()) != PIN_BINARY_SHA256:
        raise SystemExit("Gooo binary does not match the frozen clean pin")
    version = subprocess.run([str(args.go_bin), "version"], capture_output=True, text=True, check=False)
    if version.returncode != 0 or GO_VERSION not in version.stdout:
        raise SystemExit(f"Go runner requires physical {GO_VERSION}; got {version.stdout.strip()!r}")

    output_root = COHORT / "execution/pinned-offline-attempt-1"
    if output_root.exists():
        raise SystemExit("offline attempt 1 already exists; preserve it and use a new attempt directory")
    (output_root / "receipts").mkdir(parents=True)
    (output_root / "generated").mkdir()
    (output_root / "go-execution").mkdir()

    env = os.environ.copy()
    env.pop("GOOO_LAYA_URL", None)
    env.pop("GOOO_LAYA_API_KEY", None)
    env.update({"GOTOOLCHAIN": "local", "GOPROXY": "off", "GOSUMDB": "off", "GOWORK": "off"})
    env["PATH"] = str(args.go_bin.parent) + os.pathsep + env.get("PATH", "")
    catalog = read_json(COHORT / "catalog.json")
    vectors = {item["id"]: item for item in read_json(COHORT / "oracle/testdata/vectors.json")}
    validity_path = COHORT / "execution/candidate-oracle-attempt-5/original-candidate-validity.json"
    validity = read_json(validity_path) if validity_path.is_file() else None
    validity_rows = {(row["case_id"], row["candidate_id"]): row["original_source_status"] for row in (validity or {}).get("rows", [])}
    records = []
    generated = []

    for entry in catalog["designs"]:
        case_id = entry["id"]
        fixture = COHORT / entry["fixture"]
        # Body-codegen uses the frozen fill plan; Laya search plans remain uncalled study inputs.
        plan = COHORT / entry["body_fill_plan"]
        stdout = b""
        stderr = b""
        exit_code = None
        timed_out = False
        error = ""
        payload = None
        try:
            completed = subprocess.run(
                [str(args.binary), "body-codegen", "--json", "--fill-plan", str(plan), "--activity", entry["activity"], str(fixture)],
                cwd=ROOT, env=env, capture_output=True, timeout=args.timeout_seconds, check=False,
            )
            stdout, stderr, exit_code = completed.stdout, completed.stderr, completed.returncode
            if exit_code == 0:
                payload = json.loads(stdout)
            else:
                error = stderr.decode("utf-8", errors="replace")[:1200]
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            stdout = exc.stdout or b""
            stderr = exc.stderr or b""
            error = f"body-codegen exceeded {args.timeout_seconds}s"
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"[:1200]

        report = (payload or {}).get("report", {})
        fill = report.get("body_fill") or {}
        compiler_sha = report.get("compiler_source_sha", "")
        if payload is not None and compiler_sha != PIN_REVISION:
            error = f"compiler source pin mismatch: {compiler_sha!r}"
        source_text = (payload or {}).get("source", "")
        accepted_source = bool(exit_code == 0 and not error and compiler_sha == PIN_REVISION and source_text)
        package_name = f'case_{entry["activity"].lower()}_{case_id}'
        if accepted_source:
            package = output_root / "go-execution" / package_name
            package.mkdir()
            (package / "generated.go").write_text(source_text, encoding="utf-8")
            vector = vectors[case_id]
            (package / "generated_test.go").write_text(
                go_test_source(entry["activity"], vector["training"], vector["evaluation"]), encoding="utf-8",
            )
            generated.append({"case_id": case_id, "package": package_name, "activity": entry["activity"]})
            (output_root / "generated" / f"{case_id}.go").write_text(source_text, encoding="utf-8")

        selected = fill.get("selected_candidate_id", "")
        row = {
            "case_id": case_id,
            "activity": entry["activity"],
            "codegen_status": "generated" if accepted_source else "failed_or_unverified",
            "exit_code": exit_code,
            "timed_out": timed_out,
            "error": error,
            "stdout_sha256": sha(stdout),
            "stderr_sha256": sha(stderr),
            "compiler_source_sha": compiler_sha,
            "source_digest": report.get("source_digest", ""),
            "plan_sha256": report.get("plan_sha256", ""),
            "generated_digest": report.get("generated_digest", ""),
            "selected_candidate_id": selected,
            "selected_candidate_original_go_validity": validity_rows.get((case_id, selected), "unknown"),
            "candidate_scores": fill.get("candidate_scores", []),
            "training_passed": fill.get("test_cases_passed", 0),
            "training_total": fill.get("test_cases_total", 0),
            "accuracy_scope": fill.get("accuracy_scope", ""),
            "typecheck_passed": report.get("typecheck_passed", False),
            "deterministic_replay": report.get("deterministic_replay", False),
            "source_unit_completeness": dimension(report, "source_ast_coverage"),
            "source_generated_equivalence": report.get("route_equivalence", {}).get("decision", ""),
        }
        receipt_path = output_root / "receipts" / f"{case_id}.json"
        receipt_path.write_text(json.dumps(row, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        records.append(row)

    go_execution = {"status": "not_run_no_generated_sources", "exit_code": None, "training": {"passed": 0, "total": 0}, "evaluation": {"passed": 0, "total": 0}}
    if generated:
        test_root = output_root / "go-execution"
        (test_root / "go.mod").write_text("module example.invalid/gooo/ir-composition-generated-attempt-1\n\ngo 1.27.1\n", encoding="utf-8")
        result = subprocess.run(
            [str(args.go_bin), "test", "-json", "-count=1", "./..."], cwd=test_root,
            env=env, capture_output=True, text=True, timeout=180, check=False,
        )
        statuses, messages = parse_go_events(result.stdout, "example.invalid/gooo/ir-composition-generated-attempt-1/")
        go_execution = {
            "status": "passed" if result.returncode == 0 else "some_packages_failed",
            "exit_code": result.returncode,
            "go_version": version.stdout.strip(),
            "package_statuses": statuses,
            "package_output": {key: value[-1600:] for key, value in messages.items() if value.strip()},
            "stdout_sha256": sha(result.stdout.encode("utf-8")),
            "stderr_sha256": sha(result.stderr.encode("utf-8")),
            "training": {"passed": 0, "total": 0},
            "evaluation": {"passed": 0, "total": 0},
            "per_design": {},
        }
        for generated_case in generated:
            case_id = generated_case["case_id"]
            package = test_root / generated_case["package"]
            execution = execution_counts(package / "execution-results.json")
            go_execution["per_design"][case_id] = execution
            for split in ("training", "evaluation"):
                go_execution[split]["passed"] += execution[split]["passed"]
                go_execution[split]["total"] += execution[split]["total"]
            record = next(row for row in records if row["case_id"] == case_id)
            record["generated_go_execution"] = {
                "status": execution["status"],
                "training": execution["training"],
                "evaluation": execution["evaluation"],
                "package_status": statuses.get("example.invalid/gooo/ir-composition-generated-attempt-1/" + generated_case["package"], "unknown"),
            }
            (output_root / "receipts" / f"{case_id}.json").write_text(
                json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
            )

    failures = [row["case_id"] for row in records if row["codegen_status"] != "generated"]
    failed_execution = [row["case_id"] for row in records if row.get("generated_go_execution", {}).get("status") != "passed"]
    output = {
        "schema": "gooo/ir-composition-offline-baseline-attempt/v1",
        "cohort": "ir-composition-curriculum-2026-09-30",
        "attempt": 1,
        "design_freeze_sha256": sha((COHORT / "design-freeze.json").read_bytes()),
        "runner_sha256": sha(Path(__file__).read_bytes()),
        "compiler_pin": manifest["compiler_pin"],
        "binary_sha256_observed": sha(args.binary.read_bytes()),
        "go_version": version.stdout.strip(),
        "provider_endpoint_unset": True,
        "provider_api_key_unset": True,
        "model_calls": 0,
        "method": "finite-candidate structural baseline; not free-form code generation",
        "designs_expected": 32,
        "designs_attempted": len(records),
        "generated_designs": len(generated),
        "codegen_failures": failures,
        "generated_go_execution": go_execution,
        "go_execution_failures_or_unknown": failed_execution,
        "candidate_validity_artifact": str(validity_path.relative_to(ROOT)) if validity else "missing",
        "candidate_validity_denominator": validity.get("candidate_count") if validity else 0,
        "candidate_validity_valid": validity.get("valid_count") if validity else 0,
        "candidate_validity_failed": validity.get("compile_or_test_failed_count") if validity else 0,
        "candidate_validity_scope": "original declared candidate bodies compiled individually; separate from Gooo source completeness and selected-output execution",
        "full_domain_claim": False,
        "design_results": records,
    }
    report_path = output_root / "execution-report.json"
    report_path.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "designs_attempted": len(records),
        "generated": len(generated),
        "codegen_failures": failures,
        "go_execution_failures_or_unknown": failed_execution,
        "model_calls": 0,
        "candidate_validity": {
            "denominator": output["candidate_validity_denominator"],
            "valid": output["candidate_validity_valid"],
            "failed": output["candidate_validity_failed"],
        },
        "report": str(report_path.relative_to(ROOT)),
    }, indent=2))
    if len(records) != 32 or failures or failed_execution:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
