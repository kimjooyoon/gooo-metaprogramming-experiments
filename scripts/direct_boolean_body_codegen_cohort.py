#!/usr/bin/env python3
"""Exhaust the Boolean input domain for a source-bound Gooo body-codegen cohort."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any


PACKAGE = "bodycodegen_boolean_cohort"
DOMAIN = (False, True)
REFERENCE_EXPRESSIONS = {
    "identity": "input",
    "negation": "!input",
    "conjunction_false": "input && false",
    "disjunction_true": "input || true",
    "false_equal": "input == false",
}


def digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def reference_condition(condition_id: str, value: bool) -> bool:
    if condition_id == "identity":
        return value
    if condition_id == "negation":
        return not value
    if condition_id == "conjunction_false":
        return value and False
    if condition_id == "disjunction_true":
        return value or True
    if condition_id == "false_equal":
        return value == False
    raise ValueError(f"unknown Boolean condition {condition_id!r}")


def make_cases(plan: dict[str, Any]) -> list[dict[str, Any]]:
    cases = []
    for condition in plan["conditions"]:
        for pair in plan["result_pairs"]:
            for style in plan["body_styles"]:
                ordinal = len(cases) + 1
                cases.append(
                    {
                        "case_id": f"case-{ordinal:03d}",
                        "activity": f"Case{ordinal:03d}",
                        "condition_id": condition["id"],
                        "condition_expression": condition["expression"],
                        "result_pair_id": pair["id"],
                        "when_true": pair["when_true"],
                        "when_false": pair["when_false"],
                        "body_style": style,
                        "body": make_body(condition["expression"], pair, style),
                    }
                )
    return cases


def make_body(expression: str, pair: dict[str, Any], style: str) -> str:
    when_true = str(pair["when_true"]).lower()
    when_false = str(pair["when_false"]).lower()
    if style == "branch_returns":
        return f"if {expression} {{ return {when_true} }} else {{ return {when_false} }}"
    initial = {
        "assignment_input": "input",
        "assignment_true": "true",
        "assignment_false": "false",
        "assignment_overwrite": "input",
    }.get(style)
    if initial is None:
        raise ValueError(f"unknown body style {style!r}")
    statements = [f"let result = {initial}"]
    if style == "assignment_overwrite":
        statements.append("result = !input")
    statements.extend(
        [
            f"if {expression} {{ result = {when_true} }} else {{ result = {when_false} }}",
            "return result",
        ]
    )
    return "\n".join(statements)


def expected_outputs(case: dict[str, Any]) -> list[bool]:
    return [
        case["when_true"] if reference_condition(case["condition_id"], value) else case["when_false"]
        for value in DOMAIN
    ]


def go_bool_array(values: list[bool]) -> str:
    return "[]bool{" + ", ".join(str(value).lower() for value in values) + "}"


def make_go_test(cases: list[dict[str, Any]]) -> str:
    rows = []
    for case in cases:
        rows.append(
            "\t\t{name: " + json.dumps(case["case_id"]) + ", call: " + case["activity"]
            + ", want: " + go_bool_array(expected_outputs(case)) + "},"
        )
    return "\n".join(
        [
            f"package {PACKAGE}",
            "",
            'import "testing"',
            "",
            "func TestExhaustiveBooleanBodyCodegenCohort(t *testing.T) {",
            "\tdomain := []bool{false, true}",
            "\tcases := []struct { name string; call func(bool) bool; want []bool }{",
            *rows,
            "\t}",
            "\tfor _, candidate := range cases {",
            "\t\tt.Run(candidate.name, func(t *testing.T) {",
            "\t\t\tfor index, input := range domain {",
            "\t\t\t\tif got := candidate.call(input); got != candidate.want[index] {",
            "\t\t\t\t\tt.Fatalf(\"input %t: got %t, want %t\", input, got, candidate.want[index])",
            "\t\t\t\t}",
            "\t\t\t}",
            "\t\t})",
            "\t}",
            "}",
            "",
        ]
    )


def route_receipt_valid(report: dict[str, Any], source_hash: str, generated_hash: str) -> bool:
    receipt = report.get("route_equivalence")
    candidates = report.get("candidate_routes")
    return (
        isinstance(receipt, dict)
        and receipt.get("schema") == "gooo/body-codegen-route-equivalence/v1"
        and receipt.get("decision") == "PASS"
        and receipt.get("equivalent") is True
        and receipt.get("source_semantic_digest") == receipt.get("generated_semantic_digest")
        and report.get("source_digest") == source_hash
        and report.get("generated_digest") == generated_hash
        and isinstance(candidates, list)
        and report.get("route") in candidates
    )


def completeness_receipt(report: dict[str, Any]) -> dict[str, Any]:
    cases = report.get("cases", [])
    total = int(report.get("expected_case_count", 0))
    outputs = int(report.get("expected_domain_points", 0))
    dimensions = [
        {"id": "generation_coverage", "status": "PASS" if len(cases) == total else "FAIL_CLOSED", "numerator": len(cases), "denominator": total},
        {"id": "route_semantic_equivalence", "status": "PASS" if report.get("route_equivalence_passes") == total else "FAIL_CLOSED", "numerator": int(report.get("route_equivalence_passes", 0)), "denominator": total},
        {"id": "typecheck_coverage", "status": "PASS" if report.get("all_typechecks_passed") else "FAIL_CLOSED", "numerator": sum(item.get("typecheck_passed") is True for item in cases), "denominator": total},
        {"id": "internal_replay_coverage", "status": "PASS" if report.get("all_internal_replays_passed") else "FAIL_CLOSED", "numerator": sum(item.get("internal_replay_passed") is True for item in cases), "denominator": total},
        {"id": "external_repeat_determinism", "status": "PASS" if report.get("external_repeat_matches") == total else "FAIL_CLOSED", "numerator": int(report.get("external_repeat_matches", 0)), "denominator": total},
        {"id": "exhaustive_boolean_domain", "status": "PASS" if report.get("behavioral_matches") == outputs else "FAIL_CLOSED", "numerator": int(report.get("behavioral_matches", 0)), "denominator": outputs},
        {"id": "repository_write_boundary", "status": "PASS" if report.get("repository_writes") == 0 else "FAIL_CLOSED", "numerator": int(report.get("repository_writes", 0) == 0), "denominator": 1},
        {"id": "real_use_case_coverage", "status": "UNKNOWN", "numerator": 0, "denominator": 1},
        {"id": "laya_decision_observation", "status": "UNKNOWN", "numerator": 0, "denominator": 1},
    ]
    core = dimensions[:7]
    decision = "PASS_WITHIN_DECLARED_FIXTURE_SCOPE" if all(item["status"] == "PASS" for item in core) else "FAIL_CLOSED"
    return {
        "schema": "gooo/metaprogramming-completeness-receipt/v1",
        "profile_id": "gooo/body-codegen-boolean-exhaustive/v1",
        "decision": decision,
        "decision_basis": "all core dimensions must pass; UNKNOWN dimensions are explicit and are never scored",
        "scope": {
            "input_type": "Boolean",
            "input_domain": list(DOMAIN),
            "domain_cardinality": len(DOMAIN),
            "planned_fixture_cases": total,
            "checked_outputs": outputs,
            "plan_sha256": report.get("plan_sha256"),
            "gooo_source_sha": report.get("gooo_source_sha"),
        },
        "dimensions": dimensions,
        "aggregate_completeness_score": None,
        "not_claimed": [
            "user-intent completeness",
            "real-workflow coverage",
            "Laya route quality",
            "unrestricted Gooo body-codegen completeness",
        ],
    }


def fail_report(path: Path, report: dict[str, Any], message: str) -> int:
    report["decision"] = "FAIL_CLOSED"
    report["failure"] = message
    report["completeness_receipt"] = completeness_receipt(report)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(message, file=sys.stderr)
    return 1


def run(command: list[str], env: dict[str, str]) -> tuple[subprocess.CompletedProcess[str], float]:
    started = time.perf_counter()
    result = subprocess.run(command, env=env, capture_output=True, text=True, check=False)
    return result, (time.perf_counter() - started) * 1000


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gooo-bin", required=True, type=Path)
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    plan_bytes = args.plan.read_bytes()
    plan = json.loads(plan_bytes)
    report_path = args.out / "boolean-body-codegen-report.json"
    cases = make_cases(plan)
    source_sha = os.environ.get("GOOO_SOURCE_SHA", "")
    base_report: dict[str, Any] = {
        "schema": "gooo/body-codegen-boolean-cohort-report/v1",
        "cohort_id": plan.get("cohort_id"),
        "expected_case_count": int(plan.get("expected_case_count", 0)),
        "expected_domain_points": int(plan.get("expected_domain_points", 0)),
        "condition_count": len(plan.get("conditions", [])),
        "result_pair_count": len(plan.get("result_pairs", [])),
        "body_style_count": len(plan.get("body_styles", [])),
        "plan_sha256": digest(plan_bytes),
        "plan_sha256": digest(plan_bytes),
        "gooo_source_sha": source_sha or "UNBOUND_LOCAL_SOURCE",
        "input_domain": list(DOMAIN),
        "cases": [],
        "repository_writes": 0,
    }
    if plan.get("input_domain") != list(DOMAIN):
        return fail_report(report_path, base_report, "plan input domain must enumerate false and true")
    if any(REFERENCE_EXPRESSIONS.get(item.get("id")) != item.get("expression") for item in plan.get("conditions", [])):
        return fail_report(report_path, base_report, "condition expression is not bound to its independent oracle")
    if len(cases) != plan.get("expected_case_count") or len(cases) * len(DOMAIN) != plan.get("expected_domain_points"):
        return fail_report(report_path, base_report, "plan dimensions do not match generated case and output counts")
    if source_sha and (len(source_sha) != 40 or any(char not in "0123456789abcdef" for char in source_sha)):
        return fail_report(report_path, base_report, "GOOO_SOURCE_SHA must be a full lowercase Git commit SHA")

    env = os.environ.copy()
    env["GOWORK"] = "off"
    generated_sources: list[str] = []
    case_reports: list[dict[str, Any]] = []
    invocation_ms: list[float] = []
    external_repeat_matches = 0
    with tempfile.TemporaryDirectory(prefix="gooo-boolean-codegen-inputs-") as temporary:
        input_root = Path(temporary)
        for case in cases:
            source = (
                f"package {PACKAGE}\nnamespace {PACKAGE}\n"
                'entity Boolean id "bodycodegen://entity/boolean"\n'
                f"activity {case['activity']}(Boolean) -> Boolean computes {json.dumps(case['body'])}\n"
            )
            source_path = input_root / f"{case['case_id']}.gooo.fixture"
            source_path.write_text(source, encoding="utf-8")
            source_hash = digest(source.encode("utf-8"))
            command = [str(args.gooo_bin), "body-codegen", "--json", "--activity", case["activity"], str(source_path)]
            first, elapsed = run(command, env)
            invocation_ms.append(elapsed)
            if first.returncode != 0:
                return fail_report(report_path, {**base_report, "cases": case_reports}, f"{case['case_id']} codegen failed: {first.stderr.strip() or first.stdout.strip()}")
            try:
                payload = json.loads(first.stdout)
                result = payload["report"]
                generated = payload["source"]
            except (json.JSONDecodeError, KeyError, TypeError) as error:
                return fail_report(report_path, {**base_report, "cases": case_reports}, f"{case['case_id']} malformed report: {error}")
            generated_hash = digest(generated.encode("utf-8"))
            if (
                result.get("decision") != "PASS"
                or result.get("typecheck_passed") is not True
                or result.get("deterministic_replay") is not True
                or result.get("completeness_percent") != 100
                or not route_receipt_valid(result, source_hash, generated_hash)
            ):
                return fail_report(report_path, {**base_report, "cases": case_reports}, f"{case['case_id']} failed compiler report invariants")

            replay, elapsed = run(command, env)
            invocation_ms.append(elapsed)
            if replay.returncode != 0:
                return fail_report(report_path, {**base_report, "cases": case_reports}, f"{case['case_id']} replay failed")
            try:
                replay_payload = json.loads(replay.stdout)
                replay_report = replay_payload["report"]
                repeated = (
                    replay_payload.get("source") == generated
                    and replay_report.get("generated_digest") == result.get("generated_digest")
                    and replay_report.get("route") == result.get("route")
                    and replay_report.get("route_selection") == result.get("route_selection")
                )
            except (json.JSONDecodeError, KeyError, TypeError):
                repeated = False
            if not repeated:
                return fail_report(report_path, {**base_report, "cases": case_reports}, f"{case['case_id']} external replay diverged")
            external_repeat_matches += 1
            generated_sources.append(generated.split("\n\n", 1)[-1])
            case_reports.append(
                {
                    "case_id": case["case_id"],
                    "condition_id": case["condition_id"],
                    "result_pair_id": case["result_pair_id"],
                    "body_style": case["body_style"],
                    "source_sha256": source_hash,
                    "generated_sha256": generated_hash,
                    "route": result.get("route"),
                    "candidate_routes": result.get("candidate_routes"),
                    "route_equivalence_passed": True,
                    "typecheck_passed": True,
                    "internal_replay_passed": True,
                    "external_repeat_equal": repeated,
                    "checked_domain_points": len(DOMAIN),
                    "expected_outputs": expected_outputs(case),
                }
            )

    generated_dir = args.out / "generated"
    generated_dir.mkdir(parents=True, exist_ok=True)
    (generated_dir / "body_codegen.go").write_text(f"package {PACKAGE}\n\n" + "\n".join(generated_sources), encoding="utf-8")
    (generated_dir / "body_codegen_test.go").write_text(make_go_test(cases), encoding="utf-8")
    (generated_dir / "go.mod").write_text(f"module {PACKAGE}\n\ngo 1.27\n", encoding="utf-8")
    test_env = os.environ.copy()
    test_env["GOWORK"] = "off"
    test_env["GOTOOLCHAIN"] = os.environ.get("GOTOOLCHAIN", "local")
    go_test = subprocess.run(["go", "test", "-count=1", "./..."], cwd=generated_dir, env=test_env, capture_output=True, text=True, check=False)
    test_passed = go_test.returncode == 0
    report = {
        **base_report,
        "decision": "PASS" if test_passed else "FAIL_CLOSED",
        "case_count": len(case_reports),
        "checked_output_count": len(case_reports) * len(DOMAIN),
        "behavioral_matches": len(case_reports) * len(DOMAIN) if test_passed else 0,
        "full_boolean_domain_complete": test_passed and len(DOMAIN) == 2,
        "generated_package_test_passed": test_passed,
        "all_typechecks_passed": all(item["typecheck_passed"] for item in case_reports),
        "all_internal_replays_passed": all(item["internal_replay_passed"] for item in case_reports),
        "route_equivalence_passes": sum(item["route_equivalence_passed"] for item in case_reports),
        "external_repeat_matches": external_repeat_matches,
        "external_repeat_mismatches": len(case_reports) - external_repeat_matches,
        "gooo_invocation_p50_ms": sorted(invocation_ms)[len(invocation_ms) // 2] if invocation_ms else 0,
        "repository_writes": 0,
        "cases": case_reports,
    }
    report["completeness_receipt"] = completeness_receipt(report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if not test_passed:
        print(go_test.stdout, file=sys.stdout)
        print(go_test.stderr, file=sys.stderr)
        return 1
    summary = {key: report[key] for key in (
        "decision", "case_count", "checked_output_count", "behavioral_matches",
        "full_boolean_domain_complete", "route_equivalence_passes", "external_repeat_matches",
        "gooo_invocation_p50_ms",
    )}
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
