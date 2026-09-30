#!/usr/bin/env python3
"""Run the pinned, offline Gooo structural baseline after verifying its freeze."""

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


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def verify_freeze():
    manifest_path = COHORT / "frozen-manifest.json"
    if not manifest_path.is_file():
        raise SystemExit("frozen-manifest.json is missing; do not run Gooo before freezing all inputs")
    manifest = read_json(manifest_path)
    if manifest.get("compiler_pin", {}).get("revision") != PIN_REVISION or manifest.get("compiler_pin", {}).get("binary_sha256") != PIN_BINARY_SHA256:
        raise SystemExit("frozen manifest does not bind the supplied clean Gooo compiler pin")
    mismatches = []
    for repo_path, digest in manifest.get("files", {}).items():
        path = ROOT / repo_path
        if not path.is_file() or sha(path.read_bytes()) != digest:
            mismatches.append(repo_path)
    if mismatches:
        raise SystemExit("frozen artifacts changed after freeze: " + ", ".join(mismatches[:8]))
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


def go_test_source(activity, cases, case_id):
    rows = ",\n".join(f"\t\t{{input: {row['input']}, expected: {row['expected']}}}" for row in cases)
    return f'''package bodycodegen

import "testing"

func TestFiniteOracle_{case_id}(t *testing.T) {{
\tcases := []struct {{ input, expected int64 }}{{
{rows}
\t}}
\tfor _, testCase := range cases {{
\t\tif got := {activity}(testCase.input); got != testCase.expected {{
\t\t\tt.Errorf("{case_id}(%d) = %d, want %d", testCase.input, got, testCase.expected)
\t\t}}
\t}}
}}
'''


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", type=Path, default=Path("/tmp/gooo-pinned-context-final-20260930"))
    parser.add_argument("--go-bin", type=Path, required=True, help="shared physical Go 1.27 binary")
    parser.add_argument("--timeout-seconds", type=int, default=30)
    args = parser.parse_args()
    manifest = verify_freeze()
    if os.environ.get("GOOO_LAYA_URL", "").strip() or os.environ.get("GOOO_LAYA_API_KEY", "").strip():
        raise SystemExit("offline structural baseline requires GOOO_LAYA_URL and GOOO_LAYA_API_KEY to be unset")
    if not args.binary.is_file() or sha(args.binary.read_bytes()) != PIN_BINARY_SHA256:
        raise SystemExit("Gooo binary does not match the pinned SHA-256")
    version = subprocess.run([str(args.go_bin), "version"], capture_output=True, text=True, check=False)
    if version.returncode != 0 or "go1.27." not in version.stdout:
        raise SystemExit(f"Go oracle runner requires the shared Go 1.27 binary; got {version.stdout.strip()!r}")

    catalog = read_json(COHORT / "catalog.json")
    vectors = read_json(COHORT / "oracle/testdata/vectors.json")
    vectors_by_id = {item["id"]: item for item in vectors}
    result_dir = COHORT / "execution/pinned-offline-baseline"
    generated_dir = result_dir / "generated"
    test_dir = result_dir / "go-execution"
    receipts_dir = result_dir / "receipts"
    generated_dir.mkdir(parents=True, exist_ok=True)
    test_dir.mkdir(parents=True, exist_ok=True)
    receipts_dir.mkdir(parents=True, exist_ok=True)
    records = []
    generated = []
    env = os.environ.copy()
    env.pop("GOOO_LAYA_URL", None)
    env.pop("GOOO_LAYA_API_KEY", None)
    env["GOTOOLCHAIN"] = "local"
    env["GOPROXY"] = "off"

    for entry in catalog["designs"]:
        case_id = entry["id"]
        fixture = COHORT / entry["fixture"]
        plan = COHORT / entry["body_fill_plan"]
        stdout = b""
        stderr = b""
        exit_code = None
        timeout = False
        payload = None
        error = ""
        try:
            completed = subprocess.run(
                [str(args.binary), "body-codegen", "--json", "--fill-plan", str(plan),
                 "--activity", entry["activity"], str(fixture)],
                cwd=ROOT, env=env, capture_output=True, timeout=args.timeout_seconds, check=False,
            )
            stdout, stderr, exit_code = completed.stdout, completed.stderr, completed.returncode
            if exit_code == 0:
                payload = json.loads(stdout)
            else:
                error = stderr.decode("utf-8", errors="replace")[:800]
        except subprocess.TimeoutExpired as exc:
            timeout = True
            stdout = exc.stdout or b""
            stderr = exc.stderr or b""
            error = f"body-codegen exceeded {args.timeout_seconds}s"
        except Exception as exc:  # Record a failed case and continue the fixed cohort.
            error = f"{type(exc).__name__}: {exc}"[:800]

        report = (payload or {}).get("report", {})
        fill = report.get("body_fill") or {}
        compiler_sha = report.get("compiler_source_sha", "")
        if payload is not None and compiler_sha != PIN_REVISION:
            error = f"compiler source pin mismatch: {compiler_sha!r}"
            exit_code = exit_code if exit_code else 1
        source_text = (payload or {}).get("source", "")
        if exit_code == 0 and source_text:
            (generated_dir / f"{case_id}.go").write_text(source_text, encoding="utf-8")
            generated.append({"case_id": case_id, "activity": entry["activity"], "source": source_text})
        row = {
            "case_id": case_id,
            "exit_code": exit_code,
            "timed_out": timeout,
            "stdout_sha256": sha(stdout),
            "stderr_sha256": sha(stderr),
            "error": error,
            "compiler_source_sha": compiler_sha,
            "source_digest": report.get("source_digest", ""),
            "plan_sha256": report.get("plan_sha256", ""),
            "generated_digest": report.get("generated_digest", ""),
            "decision": report.get("decision", ""),
            "route": report.get("route", ""),
            "provider_operations": 0,
            "model_calls": 0,
            "body_fill": {
                "selected_candidate_id": fill.get("selected_candidate_id", ""),
                "selected_expression": fill.get("selected_expression", ""),
                "best_candidate_id": fill.get("best_candidate_id", ""),
                "candidate_scores": fill.get("candidate_scores", []),
                "training_passed": fill.get("test_cases_passed", 0),
                "training_total": fill.get("test_cases_total", 0),
                "accuracy_scope": fill.get("accuracy_scope", ""),
                "decision_mode": (fill.get("decision") or {}).get("mode", ""),
                "decision_provider": (fill.get("decision") or {}).get("provider", ""),
            },
            "source_unit_completeness": dimension(report, "source_ast_coverage"),
            "source_generated_equivalence": report.get("route_equivalence", {}).get("decision", ""),
            "typecheck_passed": report.get("typecheck_passed", False),
            "deterministic_replay": report.get("deterministic_replay", False),
        }
        write_receipt = receipts_dir / f"{case_id}.json"
        write_receipt.write_text(json.dumps(row, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        records.append(row)

    test_functions = []
    for generated_case in generated:
        vector = vectors_by_id[generated_case["case_id"]]
        all_cases = vector["training"] + vector["evaluation"]
        test_functions.append(go_test_source(generated_case["activity"], all_cases, generated_case["case_id"]))
    (test_dir / "go.mod").write_text("module example.invalid/gooo/ir-composition-pinned-results\n\ngo 1.27.1\n", encoding="utf-8")
    for generated_case in generated:
        (test_dir / f"{generated_case['case_id']}.go").write_text(generated_case["source"], encoding="utf-8")
    (test_dir / "generated_test.go").write_text("\n".join(test_functions), encoding="utf-8")
    go_result = subprocess.run(
        [str(args.go_bin), "test", "-count=1", "./..."],
        cwd=test_dir, env=env, capture_output=True, text=True, timeout=180, check=False,
    )
    go_summary = {
        "command": [str(args.go_bin), "test", "-count=1", "./..."],
        "go_version": version.stdout.strip(),
        "exit_code": go_result.returncode,
        "generated_case_count": len(generated),
        "candidate_cases_executed": sum(
            len(vectors_by_id[row["case_id"]]["training"]) + len(vectors_by_id[row["case_id"]]["evaluation"])
            for row in records if row["exit_code"] == 0 and not row["error"]
        ),
        "output_sha256": sha((go_result.stdout + go_result.stderr).encode("utf-8")),
        "output_summary": (go_result.stdout + go_result.stderr)[-2000:],
    }
    failures = [row["case_id"] for row in records if row["exit_code"] != 0 or row["error"]]
    overall = {
        "schema": "gooo/ir-composition-pinned-offline-execution/v1",
        "cohort": "ir-composition-curriculum-2026-09-30",
        "compiler_pin": manifest["compiler_pin"],
        "binary_sha256_observed": sha(args.binary.read_bytes()),
        "go_version": version.stdout.strip(),
        "provider_endpoint_unset": True,
        "provider_api_key_unset": True,
        "model_calls": 0,
        "method": "finite-candidate structural composition baseline; no free-form code generation",
        "designs_expected": 32,
        "designs_attempted": len(records),
        "generated_designs": len(generated),
        "codegen_failures": failures,
        "offline_generated_go_execution": go_summary,
        "full_domain_claim": False,
        "design_results": records,
    }
    output = result_dir / "execution-report.json"
    output.write_text(json.dumps(overall, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "designs_attempted": len(records), "generated": len(generated),
        "codegen_failures": failures, "go_test_exit_code": go_result.returncode,
        "model_calls": 0, "report": str(output.relative_to(ROOT)),
    }, indent=2))
    if failures or go_result.returncode != 0 or len(records) != 32:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
