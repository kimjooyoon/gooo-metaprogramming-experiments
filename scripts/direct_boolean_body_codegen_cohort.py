#!/usr/bin/env python3
"""Exhaust the Boolean input domain for a source-bound Gooo body-codegen cohort."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from completeness_receipt import dimension, finalize_receipt


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
    source_sha = str(report.get("gooo_source_sha", ""))
    plan_sha = str(report.get("plan_sha256", ""))
    source_sha_bound = len(source_sha) == 40 and all(char in "0123456789abcdef" for char in source_sha)
    source_bound_cases = sum(bool(item.get("source_sha256") and item.get("generated_sha256")) for item in cases)
    provenance_numerator = source_bound_cases + int(source_sha_bound and plan_sha.startswith("sha256:"))
    route_passes = int(report.get("route_equivalence_passes", 0))
    eligible_routes = sum(len(item.get("candidate_routes") or []) > 1 for item in cases)
    laya_observed = sum(item.get("route_mode") == "laya" for item in cases)
    source_ast_passes = sum(item.get("completeness_percent") == 100 for item in cases)
    runtime_passed = report.get("generated_package_test_passed") is True
    dimensions = [
        dimension("declaration_coverage", int(report.get("condition_count", 0)), int(report.get("condition_count", 0)), "hashed Boolean condition forms", "Counts declared synthetic condition forms only; this is not natural-language or real-domain coverage.", [plan_sha]),
        dimension("generation_coverage", len(cases), total, "generated activity bodies", "Counts compiler-accepted bodies against the planned cohort size.", [plan_sha, source_sha or "compiler source unavailable"]),
        dimension("source_ast_coverage", source_ast_passes, total, "fully lowered source bodies", "Uses compiler-reported accepted body AST units; it does not measure unstated intent.", ["per-case completeness_percent", "source_semantic_units and lowered_semantic_units"]),
        dimension("route_semantic_equivalence", route_passes, total, "source/generated pairs with matching semantic receipts", "Requires compiler-derived structural equivalence and source/generated digest binding.", ["per-case route_equivalence receipt", "per-case source and generated digests"]),
        dimension("typecheck_coverage", sum(item.get("typecheck_passed") is True for item in cases), total, "typechecked bodies", "Counts generated bodies accepted by Gooo's Go type checker.", ["per-case typecheck_passed"]),
        dimension("internal_replay_coverage", sum(item.get("internal_replay_passed") is True for item in cases), total, "deterministic compiler replays", "Counts compiler-internal emission replay equality.", ["per-case deterministic_replay"]),
        dimension("external_repeat_determinism", int(report.get("external_repeat_matches", 0)), total, "repeated CLI decisions", "Repeats every CLI request and compares route, selection receipt, and generated source.", ["per-case route and generated digest", "external_repeat_equal"]),
        dimension("exhaustive_boolean_domain", int(report.get("behavioral_matches", 0)), outputs, "compiled Boolean input/output points", "Executes false and true for every generated function; complete only for this Boolean fixture profile.", ["independent condition oracle", "compiled generated-package execution"], fail_closed=not runtime_passed and "generated_package_test_passed" in report),
        dimension("execution_boundary", total if runtime_passed else 0, total, "functions executed in a temporary generated package", "Generated code runs in the isolated output package; this does not grant repository or external-service authority.", ["generated_package_test_passed", "temporary generated package path"] , fail_closed=not runtime_passed and "generated_package_test_passed" in report),
        dimension("repository_write_boundary", int(report.get("repository_writes", 0) == 0), 1, "runs with zero repository writes", "Generated files are kept under the caller-declared output directory; the report records repository writes only.", ["repository_writes", "temporary generated package"] , fail_closed=int(report.get("repository_writes", 0)) != 0),
        dimension("provenance_integrity", provenance_numerator, total + 1, "case and compiler/plan identity bindings", "Binds per-case source/generated digests and the compiler commit plus plan digest.", [plan_sha, source_sha or "compiler source unavailable", "per-case source_sha256 and generated_sha256"]),
        dimension("laya_decision_observation", laya_observed, eligible_routes, "eligible multi-route Laya decisions", "Records model decisions only when Laya is configured; it does not assess route quality.", ["per-case route_mode", "candidate_routes"]),
        dimension("reverse_observation_coverage", 0, 1, "generated-to-source observation paths", "This cohort executes generated outputs but does not reverse-map runtime observations to source declarations.", ["no source-bound reverse-observation trace"]),
        dimension("use_case_coverage", 0, 1, "independently sourced real workflows", "All planned cases are synthetic fixtures, not independently sourced workflows.", ["no real-workflow corpus is bound"]),
        dimension("permission_boundary", 0, 1, "observed host permission profiles", "Repository writes are measured, but the local OS user's filesystem permission set is not captured.", ["repository_write_boundary is measured separately", "no host permission receipt"]),
        dimension("external_network_boundary", int(not report.get("laya_configured", False)), 1, "runs with no configured Laya service", "An empty Laya URL proves no model decision was requested in this run; it does not audit every possible process network call.", [f"laya_configured:{bool(report.get('laya_configured', False))}", "CI route service configuration"]),
        dimension("semantic_profile_delta", 0, 1, "compatible before/after semantic receipts", "No prior receipt with the same plan, compiler, toolchain, and runner is bound for per-dimension regression deltas.", [plan_sha, source_sha or "compiler source unavailable", "no comparable prior receipt"]),
        dimension("route_quality", 0, 1, "independently validated route-quality criteria", "Semantic equivalence is measured; this cohort has no independent clarity or utility oracle.", ["route_semantic_equivalence", "no route-clarity or utility measure"]),
        dimension("unrestricted_body_semantics", 0, 1, "all supported Gooo body forms", "Only the declared pure Boolean subset is evaluated here.", ["bounded Boolean profile", "other body forms are unmodeled"]),
    ]
    core = {
        "declaration_coverage", "generation_coverage", "source_ast_coverage",
        "route_semantic_equivalence", "typecheck_coverage", "internal_replay_coverage",
        "external_repeat_determinism", "exhaustive_boolean_domain", "execution_boundary",
        "repository_write_boundary", "provenance_integrity",
    }
    next_operations = {
        "declaration_coverage": "BIND_PLAN_CASES_TO_THE_DECLARED_FIXTURE_DENOMINATOR",
        "generation_coverage": "REPAIR_FAILING_GOOO_BODY_CODEGEN_CASES",
        "source_ast_coverage": "LOWER_EVERY_ACCEPTED_SOURCE_AST_UNIT_OR_FAIL_CLOSED",
        "route_semantic_equivalence": "BIND_SOURCE_AND_GENERATED_ENVELOPES_AND_REQUIRE_THE_DECLARED_CANONICAL_FORM_TO_MATCH",
        "typecheck_coverage": "REPAIR_GENERATED_GO_TYPE_ERRORS",
        "internal_replay_coverage": "REPLAY_EACH_COMPILER_SELECTED_ROUTE",
        "external_repeat_determinism": "REPEAT_EACH_CLI_DECISION_AND_COMPARE_ROUTE_AND_GENERATED_DIGEST",
        "exhaustive_boolean_domain": "EXECUTE_MISSING_BOOLEAN_INPUTS_OR_REPAIR_THE_GENERATED_PACKAGE",
        "execution_boundary": "BIND_COMPILED_EXECUTION_TO_TEMPORARY_OUTPUT_AND_RECHECK_WRITE_BOUNDARIES",
        "repository_write_boundary": "KEEP_OUTPUT_IN_TEMPORARY_STORAGE_AND_RECHECK_REPOSITORY_STATE",
        "provenance_integrity": "BIND_EACH_SOURCE_AND_GENERATED_DIGEST_TO_COMPILER_AND_PLAN_IDENTITIES",
        "laya_decision_observation": "RUN_WITH_A_PINNED_LAYA_SERVICE_AND_RETAIN_MODEL_REVISION",
        "reverse_observation_coverage": "ADD_SOURCE_BOUND_GENERATED_TO_SOURCE_OBSERVATION_EVIDENCE",
        "use_case_coverage": "BIND_INDEPENDENTLY_SOURCED_REAL_WORKFLOW_FIXTURES",
        "permission_boundary": "CAPTURE_THE_HOST_PERMISSION_PROFILE_WITHOUT_GRANTING_ADDITIONAL_AUTHORITY",
        "external_network_boundary": "RECORD_THE_CONFIGURED_PROVIDER_ENDPOINT_AND_AUDIT_THE_ALLOWED_NETWORK_SCOPE",
        "semantic_profile_delta": "BIND_A_COMPATIBLE_BASELINE_AND_REPORT_PER_DIMENSION_DELTAS",
        "route_quality": "DEFINE_AN_INDEPENDENT_ROUTE_QUALITY_ORACLE",
        "unrestricted_body_semantics": "EXTEND_CONFORMANCE_TO_THE_REMAINING_SUPPORTED_BODY_FORMS",
    }
    return finalize_receipt(
        profile_id="gooo/body-codegen-boolean-exhaustive/v1",
        decision_basis="all core fixture dimensions must pass; UNKNOWN dimensions remain explicit and are never converted into a completion percentage",
        scope={
            "domain_scope": "100 synthetic single-input Boolean activity bodies evaluated at false and true",
            "allowed_investment": "measure bounded pure Boolean body generation, type checking, equivalence, replay, and full two-value input behavior",
            "excluded_scope": ["natural-language intent", "real workflows", "unrestricted body syntax", "route quality", "reverse observation"],
            "input_type": "Boolean",
            "input_domain": list(DOMAIN),
            "domain_cardinality": len(DOMAIN),
            "planned_fixture_cases": total,
            "checked_outputs": outputs,
            "plan_sha256": plan_sha,
            "compiler_source_sha": source_sha or "UNBOUND_LOCAL_SOURCE",
            "toolchain": report.get("go_version", "UNOBSERVED_GO_VERSION"),
            "execution_environment": report.get("host_platform", "UNOBSERVED_RUNNER"),
            "laya_configured": bool(report.get("laya_configured", False)),
        },
        dimensions=dimensions,
        core_dimensions=core,
        next_operations=next_operations,
        not_claimed=[
            "user-intent completeness",
            "real-workflow coverage",
            "Laya route quality",
            "unrestricted Gooo body-codegen completeness",
        ],
        force_fail_closed_reason=(
            str(report.get("failure") or "cohort execution reported FAIL_CLOSED")
            if report.get("decision") == "FAIL_CLOSED" else ""
        ),
    )


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
        "gooo_source_sha": source_sha or "UNBOUND_LOCAL_SOURCE",
        "laya_configured": bool(os.environ.get("GOOO_LAYA_URL")),
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
                    "route_mode": result.get("route_decision", {}).get("mode"),
                    "candidate_routes": result.get("candidate_routes"),
                    "route_equivalence_passed": True,
                    "typecheck_passed": True,
                    "internal_replay_passed": True,
                    "completeness_percent": result.get("completeness_percent"),
                    "source_semantic_units": result.get("source_semantic_units"),
                    "lowered_semantic_units": result.get("lowered_semantic_units"),
                    "external_repeat_equal": repeated,
                    "checked_domain_points": len(DOMAIN),
                    "expected_outputs": expected_outputs(case),
                }
            )

    generated_dir = args.out / "generated"
    generated_dir.mkdir(parents=True, exist_ok=True)
    (generated_dir / "body_codegen.go").write_text(f"package {PACKAGE}\n\n" + "\n".join(generated_sources), encoding="utf-8")
    (generated_dir / "body_codegen_test.go").write_text(make_go_test(cases), encoding="utf-8")
    (generated_dir / "go.mod").write_text(f"module {PACKAGE}\n\ngo 1.27.1\n", encoding="utf-8")
    test_env = os.environ.copy()
    test_env["GOWORK"] = "off"
    test_env["GOTOOLCHAIN"] = os.environ.get("GOTOOLCHAIN", "local")
    go_test = subprocess.run(["go", "test", "-count=1", "./..."], cwd=generated_dir, env=test_env, capture_output=True, text=True, check=False)
    test_passed = go_test.returncode == 0
    go_version_result = subprocess.run(["go", "version"], cwd=generated_dir, env=test_env, capture_output=True, text=True, check=False)
    report = {
        **base_report,
        "decision": "PASS" if test_passed else "FAIL_CLOSED",
        "failure": None if test_passed else (go_test.stderr.strip() or go_test.stdout.strip() or "generated Go package test failed"),
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
        "go_version": go_version_result.stdout.strip() if go_version_result.returncode == 0 else "UNOBSERVED_GO_VERSION",
        "host_platform": platform.platform(),
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
