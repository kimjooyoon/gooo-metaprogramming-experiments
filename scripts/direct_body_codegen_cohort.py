#!/usr/bin/env python3
"""Run a finite, source-bound cohort through Gooo's body-codegen CLI."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import resource
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any


SCHEMA = "gooo/body-codegen-cohort-report/v1"
PROFILE_ID = "gooo/body-codegen-direct-cohort-100/v2"
PACKAGE = "bodycodegen_cohort"
INT64_EDGE_VALUES = (-(1 << 63), -(1 << 63) + 1, (1 << 63) - 2, (1 << 63) - 1)


def digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def reference_condition(condition_id: str, value: int) -> bool:
    """Independent finite-domain oracle for the named plan conditions."""
    if condition_id == "negative":
        return value < 0
    if condition_id == "at_most_minus_three":
        return value <= -3
    if condition_id == "zero":
        return value == 0
    if condition_id == "positive":
        return value > 0
    if condition_id == "at_least_five":
        return value >= 5
    if condition_id == "not_one":
        return value != 1
    if condition_id == "inclusive_neighborhood":
        return -2 <= value <= 2
    if condition_id == "outside_window":
        return value < 0 or value > 5
    if condition_id == "equal_five":
        return value == 5
    if condition_id == "inside_open_interval":
        return 1 < value < 5
    raise ValueError(f"unknown condition id {condition_id!r}")


def make_cases(plan: dict[str, Any]) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for condition in plan["conditions"]:
        for pair in plan["result_pairs"]:
            for body_style in plan["body_styles"]:
                number = len(cases) + 1
                name = f"Case{number:03d}"
                body = make_body(condition["expression"], pair, body_style)
                cases.append(
                    {
                        "case_id": f"case-{number:03d}",
                        "activity": name,
                        "condition_id": condition["id"],
                        "condition_expression": condition["expression"],
                        "result_pair_id": pair["id"],
                        "when_true": pair["when_true"],
                        "when_false": pair["when_false"],
                        "body_style": body_style,
                        "body": body,
                    }
                )
    return cases


def make_body(expression: str, pair: dict[str, Any], style: str) -> str:
    if style == "branch_returns":
        return (
            f"if {expression} {{ return {pair['when_true']} }} "
            f"else {{ return {pair['when_false']} }}"
        )
    if style == "result_assignment":
        return (
            "let result = input\n"
            f"if {expression} {{ result = {pair['when_true']} }} "
            f"else {{ result = {pair['when_false']} }}\n"
            "return result"
        )
    raise ValueError(f"unknown body style {style!r}")


def run_command(command: list[str], env: dict[str, str], cwd: Path | None = None) -> tuple[subprocess.CompletedProcess[str], float]:
    started = time.perf_counter()
    result = subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True, check=False)
    return result, (time.perf_counter() - started) * 1000


def expected_values(case: dict[str, Any], domain: list[int]) -> list[int]:
    return [
        case["when_true"] if reference_condition(case["condition_id"], value) else case["when_false"]
        for value in domain
    ]


def go_array(values: list[int]) -> str:
    return "[]int64{" + ", ".join(str(value) for value in values) + "}"


def make_go_test(cases: list[dict[str, Any]], domain: list[int], wants: dict[str, list[int]]) -> str:
    rows = []
    for case in cases:
        rows.append(
            "\t\t{name: "
            + json.dumps(case["case_id"])
            + ", call: "
            + case["activity"]
            + ", want: "
            + go_array(wants[case["case_id"]])
            + "},"
        )
    return "\n".join(
        [
            f"package {PACKAGE}",
            "",
            'import "testing"',
            "",
            "func TestDirectBodyCodegenCohort(t *testing.T) {",
            "\tdomain := " + go_array(domain),
            "\tcases := []struct { name string; call func(int64) int64; want []int64 }{",
            *rows,
            "\t}",
            "\tfor _, candidate := range cases {",
            "\t\tt.Run(candidate.name, func(t *testing.T) {",
            "\t\t\tfor index, input := range domain {",
            "\t\t\t\tgot := candidate.call(input)",
            "\t\t\t\tif got != candidate.want[index] {",
            "\t\t\t\t\tt.Fatalf(\"input %d: got %d, want %d\", input, got, candidate.want[index])",
            "\t\t\t\t}",
            "\t\t\t}",
            "\t\t})",
            "\t}",
            "}",
            "",
        ]
    )


def peak_child_rss_bytes() -> int:
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    value = int(usage.ru_maxrss)
    # Linux reports KiB; macOS reports bytes.
    return value if sys.platform == "darwin" else value * 1024


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[max(0, math.ceil(fraction * len(ordered)) - 1)]


def dimension(
    dimension_id: str,
    numerator: int,
    denominator: int,
    unit: str,
    reason: str,
    evidence: list[str],
    *,
    fail_closed: bool = False,
) -> dict[str, Any]:
    if fail_closed:
        status = "FAIL_CLOSED"
    elif denominator <= 0 or numerator <= 0:
        status = "UNKNOWN"
    elif numerator == denominator:
        status = "PASS"
    else:
        status = "PROGRESS"
    return {
        "id": dimension_id,
        "status": status,
        "numerator": numerator,
        "denominator": denominator,
        "unit": unit,
        "reason": reason,
        "evidence": evidence,
    }


def route_equivalence_receipt_valid(item: dict[str, Any]) -> bool:
    receipt = item.get("route_equivalence")
    expected_rule = {
        "preserve": "source-shape-preserving-v1",
        "guard-return": "if-return-else-return-to-guard-return-v1",
        "merge-result": "if-return-else-return-to-explicit-result-join-v1",
    }.get(item.get("route"))
    return (
        isinstance(receipt, dict)
        and receipt.get("schema") == "gooo/body-codegen-route-equivalence/v1"
        and receipt.get("decision") == "PASS"
        and receipt.get("method") == "canonical_control_flow_form/v1"
        and receipt.get("equivalent") is True
        and receipt.get("rule") == expected_rule
        and isinstance(receipt.get("scope"), str)
        and bool(receipt.get("scope"))
        and receipt.get("source_semantic_digest")
        and receipt.get("source_semantic_digest") == receipt.get("generated_semantic_digest")
        and item.get("compiler_source_sha256") == item.get("source_sha256")
        and item.get("compiler_generated_sha256") == item.get("generated_sha256")
    )


def route_equivalence_receipt_failed_closed(item: dict[str, Any]) -> bool:
    receipt = item.get("route_equivalence")
    if receipt is None:
        return False
    if not isinstance(receipt, dict):
        return True
    return receipt.get("decision") != "PASS" or not route_equivalence_receipt_valid(item)


def build_completeness_receipt(report: dict[str, Any]) -> dict[str, Any]:
    """Describe evidence boundaries without collapsing unknowns into a score."""
    cases = report.get("cases", [])
    case_count = len(cases)
    expected_cases = int(report.get("expected_case_count", report.get("case_count", 0)))
    planned_cases = int(report.get("planned_case_count", 0))
    expected_outputs = int(report.get("expected_domain_points", 0))
    expected_extreme_outputs = int(report.get("int64_extreme_expected_outputs", 0))
    matched_extreme_outputs = int(report.get("int64_extreme_behavioral_matches", 0))
    extreme_values = [int(value) for value in report.get("int64_extreme_values", [])]
    laya_configured = bool(report.get("laya_configured", False))

    def count_true(key: str) -> int:
        return sum(1 for item in cases if item.get(key) is True)

    passed_generation = sum(1 for item in cases if item.get("report_decision") == "PASS")
    passed_typechecks = count_true("typecheck_passed")
    passed_replays = count_true("internal_deterministic_replay")
    route_equivalence_passes = sum(1 for item in cases if route_equivalence_receipt_valid(item))
    route_equivalence_failure = any(route_equivalence_receipt_failed_closed(item) for item in cases)
    complete_bodies = sum(1 for item in cases if item.get("completeness_percent") == 100)
    source_bound_cases = sum(
        1 for item in cases if item.get("source_sha256") and item.get("generated_sha256")
    )
    repository_write_free_cases = sum(
        1 for item in cases if item.get("repository_writes") == 0
    )
    protocol_bound_routes = sum(
        1
        for item in cases
        if item.get("route") and item.get("route") in item.get("candidate_routes", [])
    )
    laya_eligible_cases = sum(1 for item in cases if len(item.get("candidate_routes", [])) > 1)
    laya_decided_cases = sum(
        1
        for item in cases
        if len(item.get("candidate_routes", [])) > 1 and item.get("route_mode") == "laya"
    )
    external_repeat_count = int(report.get("external_repeat_observation_count", 0))
    external_repeat_matches = sum(
        1 for item in cases if item.get("external_repeat_equal") is True
    )
    source_sha = str(report.get("gooo_source_sha", ""))
    source_sha_bound = len(source_sha) == 40 and all(
        char in "0123456789abcdef" for char in source_sha
    )
    plan_bound = str(report.get("plan_sha256", "")).startswith("sha256:")
    pinned_identity_count = source_bound_cases + int(source_sha_bound and plan_bound)
    provenance_denominator = expected_cases + 1
    runtime_was_run = "generated_package_test_passed" in report
    runtime_failed = runtime_was_run and report.get("generated_package_test_passed") is False
    observed_outputs = int(report.get("behavioral_matches", 0))
    if report.get("route_sample_seed_sha256"):
        repeat_reason = "Explicitly seeded route draws are repeated and compared with the recorded weights and draw receipt."
    elif laya_configured:
        repeat_reason = "Unseeded live Laya choices are recorded but are not repeated by this cohort."
    else:
        repeat_reason = "Deterministic fallback runs are repeated and compared byte-for-byte."

    dimensions = [
        dimension(
            "declaration_coverage", planned_cases, expected_cases, "planned fixture cases",
            "Measures declared cases in the hashed plan, not user-intent coverage.",
            [str(report.get("plan_sha256", "plan digest unavailable"))],
        ),
        dimension(
            "generation_coverage", passed_generation, expected_cases, "generated activity bodies",
            "Counts accepted Gooo body-codegen reports against all planned cases.",
            ["per-case PASS report", str(report.get("gooo_source_sha", "source revision unavailable"))],
        ),
        dimension(
            "typecheck_coverage", passed_typechecks, expected_cases, "typechecked bodies",
            "Counts bodies whose generated Go passed the compiler's type check.",
            ["body-codegen typecheck_passed"],
        ),
        dimension(
            "source_ast_coverage", complete_bodies, expected_cases, "fully lowered fixture bodies",
            "Uses the compiler's source-AST unit accounting; it does not measure unstated intent.",
            ["per-case completeness_percent", "source_semantic_units and lowered_semantic_units"],
        ),
        dimension(
            "route_semantic_equivalence", route_equivalence_passes, expected_cases,
            "source/generated body pairs with matching compiler-derived semantic digests",
            "Normalizes the declared conditional rewrites and otherwise requires matching accepted Go AST bodies; this does not rank clarity or prove unstated intent.",
            ["per-case route_equivalence receipt", "matching source and generated envelope digests"],
            fail_closed=route_equivalence_failure,
        ),
        dimension(
            "finite_domain_behavior", observed_outputs, expected_outputs, "matching input/output points",
            "Checks only the declared finite domain; any observed mismatch fails closed.",
            ["independent condition oracle", "compiled generated-package execution"],
            fail_closed=runtime_failed,
        ),
        dimension(
            "int64_extreme_boundary_behavior", matched_extreme_outputs, expected_extreme_outputs,
            "compiled outputs at signed int64 extrema and adjacent values",
            "Executes every fixture at the four signed int64 edge values; this is boundary evidence, not a proof over the full domain.",
            [f"values:{extreme_values}", "generated package execution"],
            fail_closed=runtime_failed,
        ),
        dimension(
            "internal_replay_coverage", passed_replays, expected_cases, "deterministic compiler replays",
            "Counts the compiler's independent replay of its selected lowering route.",
            ["generated_digest equals replay_digest"],
        ),
        dimension(
            "external_repeat_determinism", external_repeat_matches, external_repeat_count,
            "repeated CLI decisions",
            repeat_reason,
            ["route and generated digest", "sample draw and normalized weights when seeded"],
        ),
        dimension(
            "route_choice_protocol", protocol_bound_routes, expected_cases, "declared route choices",
            "Every emitted choice must belong to the compiler-declared candidate set.",
            ["candidate_routes", "selected route"],
        ),
        dimension(
            "laya_decision_observation", laya_decided_cases, laya_eligible_cases,
            "eligible multi-route Laya decisions",
            "Records model decisions only when a Laya service is configured; decision quality has no independent oracle here.",
            ["route request digest", "model revision", "probability vector and confidence when supplied"],
        ),
        dimension(
            "source_binding_integrity", pinned_identity_count, provenance_denominator,
            "case/source identity bindings",
            "Binds per-case source and generated digests plus the pinned compiler and plan identities.",
            [str(report.get("plan_sha256", "plan digest unavailable")), source_sha or "compiler revision unavailable"],
        ),
        dimension(
            "repository_write_boundary", repository_write_free_cases, expected_cases,
            "cases with zero repository writes",
            "Generated files are kept in temporary output; this records repository writes only.",
            ["per-case repository_writes", "top-level repository_writes"],
            fail_closed=int(report.get("repository_writes", 0)) != 0,
        ),
        dimension(
            "resource_observation", int(all(key in report for key in (
                "cohort_wall_elapsed_ms", "children_user_cpu_seconds",
                "children_system_cpu_seconds", "children_peak_rss_bytes",
            ))), 1, "complete resource measurement sets",
            "Captures elapsed time, child CPU time, and peak child RSS for this runner only.",
            ["wall-clock duration", "getrusage(RUSAGE_CHILDREN)"],
        ),
        dimension(
            "resource_baseline_comparison", 0, 1, "compatible prior resource receipts",
            "This run records the first core-normalized direct-cohort resource sample; no same-profile baseline is bound yet.",
            ["no prior receipt with this timing and CPU schema"],
        ),
        dimension(
            "real_use_case_coverage", 0, 1, "independently sourced real use-case sets",
            "The 100 cases are synthetic fixtures, not real user workflows.",
            ["no independent real-use-case corpus is bound"],
        ),
        dimension(
            "reverse_observation_coverage", 0, 1, "generated-to-source reverse observations",
            "Generated Go is executed, but this cohort does not reverse-map runtime observations to source declarations.",
            ["no reverse-observation trace in this cohort"],
        ),
        dimension(
            "full_domain_semantics", 0, 1, "complete int64 input domains",
            "Twenty-five points per case do not prove behavior for every int64 input.",
            ["finite domain only"],
        ),
        dimension(
            "route_quality", 0, 1, "independently validated route-quality criteria",
            "Compiler-derived semantic equivalence is measured separately; this cohort has no independent clarity or utility oracle to rank equivalent routes.",
            ["route_semantic_equivalence", "no independent route-clarity or utility measure"],
        ),
    ]
    core_ids = {
        "declaration_coverage", "generation_coverage", "typecheck_coverage",
        "source_ast_coverage", "route_semantic_equivalence", "finite_domain_behavior", "internal_replay_coverage",
        "route_choice_protocol", "source_binding_integrity", "repository_write_boundary",
    }
    core_dimensions = [item for item in dimensions if item["id"] in core_ids]
    if report.get("decision") == "FAIL_CLOSED" or any(
        item["status"] == "FAIL_CLOSED" for item in core_dimensions
    ):
        decision = "FAIL_CLOSED"
    elif all(item["status"] == "PASS" for item in core_dimensions):
        decision = "PASS_WITHIN_DECLARED_FIXTURE_SCOPE"
    else:
        decision = "PROGRESS_WITHIN_DECLARED_FIXTURE_SCOPE"
    status_counts = {
        status: sum(1 for item in dimensions if item["status"] == status)
        for status in ("PASS", "PROGRESS", "UNKNOWN", "FAIL_CLOSED")
    }
    next_operations = {
        "laya_decision_observation": "RUN_WITH_A_PINNED_LAYA_SERVICE_AND_RETAIN_MODEL_REVISION",
        "route_semantic_equivalence": "BIND_SOURCE_AND_GENERATED_ENVELOPES_AND_REQUIRE_THE_DECLARED_CANONICAL_FORM_TO_MATCH",
        "resource_baseline_comparison": "BIND_A_REPEAT_RECEIPT_FROM_THE_SAME_COMPILER_AND_RUNNER_PROFILE",
        "real_use_case_coverage": "BIND_INDEPENDENTLY_SOURCED_REAL_WORKFLOW_FIXTURES",
        "reverse_observation_coverage": "ADD_SOURCE_BOUND_GENERATED_TO_SOURCE_OBSERVATION_EVIDENCE",
        "full_domain_semantics": "ADD_SYMBOLIC_OR_PARTITIONED_PROOF_BEYOND_THE_FINITE_GRID",
        "route_quality": "DEFINE_AN_INDEPENDENT_ROUTE_QUALITY_ORACLE",
    }
    unresolved_dimensions = [
        {
            "id": item["id"],
            "status": item["status"],
            "reason": item["reason"],
            "next_operation": next_operations.get(item["id"], "RESOLVE_SOURCE_BOUND_EVIDENCE_GAP"),
        }
        for item in dimensions
        if item["status"] in ("PROGRESS", "UNKNOWN", "FAIL_CLOSED")
    ]
    return {
        "schema": "gooo/metaprogramming-completeness-receipt/v1",
        "profile_id": PROFILE_ID,
        "decision": decision,
        "decision_basis": "all core fixture dimensions must pass; UNKNOWN dimensions remain explicit and are never converted into a completion percentage",
        "scope": {
            "planned_fixture_cases": expected_cases,
            "observed_fixture_cases": case_count,
            "input_domain": report.get("domain", []),
            "finite_domain_points_per_case": len(report.get("domain", [])),
            "int64_extreme_values": extreme_values,
            "compiler_source_sha": source_sha or "UNBOUND_LOCAL_SOURCE",
            "plan_sha256": report.get("plan_sha256"),
            "laya_configured": laya_configured,
        },
        "dimensions": dimensions,
        "status_counts": status_counts,
        "aggregate_completeness_score": None,
        "first_unresolved": unresolved_dimensions[0] if unresolved_dimensions else None,
        "unresolved_claims": unresolved_dimensions,
        "not_claimed": [
            "coverage of natural-language user intent",
            "coverage of real production workflows",
            "behavior over the full int64 domain",
            "reverse observation from generated runtime back to .gooo declarations",
            "calibration or usefulness of Laya route probabilities",
            "readability or utility preference between equivalent generated routes",
            "universal or production language completeness",
        ],
    }


def fail_report(path: Path, report: dict[str, Any], message: str) -> int:
    report["decision"] = "FAIL_CLOSED"
    report["failure"] = message
    report.setdefault("completeness_receipt", build_completeness_receipt(report))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(message, file=sys.stderr)
    return 1


def partial_report(
    plan: dict[str, Any],
    plan_bytes: bytes,
    domain: list[int],
    gooo_source_sha: str,
    laya_enabled: bool,
    cases: list[dict[str, Any]],
    external_repeat_count: int = 0,
) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "cohort_id": plan.get("cohort_id"),
        "planned_case_count": len(make_cases(plan)),
        "expected_case_count": int(plan.get("expected_case_count", 0)),
        "expected_domain_points": int(plan.get("expected_domain_points", 0)),
        "int64_extreme_values": [int(value) for value in plan.get("int64_extreme_values", [])],
        "int64_extreme_expected_outputs": (
            int(plan.get("expected_case_count", 0)) * len(plan.get("int64_extreme_values", []))
        ),
        "int64_extreme_behavioral_matches": 0,
        "plan_sha256": digest(plan_bytes),
        "domain": domain,
        "gooo_source_sha": gooo_source_sha or "UNBOUND_LOCAL_SOURCE",
        "laya_configured": laya_enabled,
        "route_sample_seed_sha256": (
            digest(os.environ["GOOO_BODY_CODEGEN_SAMPLE_SEED"].encode("utf-8"))
            if os.environ.get("GOOO_BODY_CODEGEN_SAMPLE_SEED") else None
        ),
        "external_repeat_observation_count": external_repeat_count,
        "repository_writes": 0,
        "cases": cases,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gooo-bin", required=True, type=Path)
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    plan_bytes = args.plan.read_bytes()
    plan = json.loads(plan_bytes)
    domain = [int(value) for value in plan["domain"]]
    int64_extreme_values = [int(value) for value in plan.get("int64_extreme_values", [])]
    cases = make_cases(plan)
    report_path = args.out / "body-codegen-report.json"
    args.out.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    laya_enabled = bool(env.get("GOOO_LAYA_URL"))
    sample_seed = env.get("GOOO_BODY_CODEGEN_SAMPLE_SEED", "")
    sample_seed_sha256 = digest(sample_seed.encode("utf-8")) if sample_seed else None
    gooo_source_sha = env.get("GOOO_SOURCE_SHA", "")

    if (
        tuple(int64_extreme_values) != INT64_EDGE_VALUES
        or not set(int64_extreme_values).issubset(domain)
    ):
        return fail_report(
            report_path,
            partial_report(plan, plan_bytes, domain, gooo_source_sha, laya_enabled, []),
            "plan must include the four signed int64 extrema and adjacent values in its executed domain",
        )

    if len(cases) != plan["expected_case_count"]:
        return fail_report(
            report_path,
            partial_report(plan, plan_bytes, domain, gooo_source_sha, laya_enabled, []),
            f"plan generated {len(cases)} cases, expected {plan['expected_case_count']}",
        )
    if len(domain) * len(cases) != plan["expected_domain_points"]:
        return fail_report(
            report_path,
            partial_report(plan, plan_bytes, domain, gooo_source_sha, laya_enabled, []),
            f"plan yields {len(domain) * len(cases)} outputs, expected {plan['expected_domain_points']}",
        )

    if gooo_source_sha and (len(gooo_source_sha) != 40 or any(char not in "0123456789abcdef" for char in gooo_source_sha)):
        return fail_report(
            report_path,
            partial_report(plan, plan_bytes, domain, gooo_source_sha, laya_enabled, []),
            "GOOO_SOURCE_SHA must be a full lowercase Git commit SHA",
        )

    source_outputs: list[str] = []
    case_reports: list[dict[str, Any]] = []
    wants = {case["case_id"]: expected_values(case, domain) for case in cases}
    invocation_ms: list[float] = []
    replay_mismatches = 0
    external_repeat_observations = 0
    generated_points = 0
    matched_points = 0
    construct_units = 0
    lowered_units = 0
    bodies_with_choices = 0
    route_counts: dict[str, int] = {}

    cohort_started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="gooo-body-codegen-inputs-") as temporary:
        input_root = Path(temporary)
        for case in cases:
            source = (
                f"package {PACKAGE}\n"
                f"namespace {PACKAGE}\n"
                'entity Integer id "bodycodegen://entity/integer"\n'
                f"activity {case['activity']}(Integer) -> Integer computes {json.dumps(case['body'])}\n"
            )
            source_path = input_root / f"{case['case_id']}.gooo.fixture"
            source_path.write_text(source, encoding="utf-8")
            source_hash = digest(source.encode("utf-8"))
            command = [str(args.gooo_bin), "body-codegen", "--json", "--activity", case["activity"], str(source_path)]
            if sample_seed:
                command.extend(["--sample-seed", sample_seed])
            first, elapsed = run_command(command, env)
            invocation_ms.append(elapsed)
            if first.returncode != 0:
                return fail_report(
                    report_path,
                    partial_report(
                        plan, plan_bytes, domain, gooo_source_sha, laya_enabled,
                        case_reports, external_repeat_observations,
                    ),
                    f"{case['case_id']} body-codegen failed: {first.stderr.strip() or first.stdout.strip()}",
                )
            try:
                first_payload = json.loads(first.stdout)
                result = first_payload["report"]
                generated_source = first_payload["source"]
            except (json.JSONDecodeError, KeyError, TypeError) as error:
                return fail_report(
                    report_path,
                    partial_report(
                        plan, plan_bytes, domain, gooo_source_sha, laya_enabled,
                        case_reports, external_repeat_observations,
                    ),
                    f"{case['case_id']} emitted malformed JSON: {error}",
                )
            generated_hash = digest(generated_source.encode("utf-8"))

            repeat_equal: bool | None = None
            if not laya_enabled or sample_seed:
                replay, elapsed = run_command(command, env)
                invocation_ms.append(elapsed)
                if replay.returncode != 0:
                    return fail_report(
                        report_path,
                        partial_report(
                            plan, plan_bytes, domain, gooo_source_sha, laya_enabled,
                            case_reports, external_repeat_observations,
                        ),
                        f"{case['case_id']} deterministic replay failed: {replay.stderr.strip() or replay.stdout.strip()}",
                    )
                try:
                    replay_payload = json.loads(replay.stdout)
                    replay_report = replay_payload["report"]
                    repeat_equal = (
                        replay_report.get("generated_digest") == result.get("generated_digest")
                        and replay_report.get("route") == result.get("route")
                        and replay_payload.get("source") == generated_source
                    )
                    if sample_seed:
                        repeat_equal = repeat_equal and replay_report.get("route_selection") == result.get("route_selection")
                        repeat_equal = repeat_equal and replay_report.get("route_decision", {}).get("model_revision") == result.get("route_decision", {}).get("model_revision")
                except (json.JSONDecodeError, KeyError, TypeError):
                    repeat_equal = False
                external_repeat_observations += 1
            if not repeat_equal:
                replay_mismatches += 1

            route_evidence = {
                "route_equivalence": result.get("route_equivalence"),
                "route": result.get("route"),
                "source_sha256": source_hash,
                "compiler_source_sha256": result.get("source_digest"),
                "generated_sha256": generated_hash,
                "compiler_generated_sha256": result.get("generated_digest"),
            }
            required = {
                "decision": result.get("decision") == "PASS",
                "typecheck": result.get("typecheck_passed") is True,
                "internal_replay": result.get("deterministic_replay") is True,
                "zero_repository_writes": result.get("repository_writes") == 0,
                "body_completeness": result.get("completeness_percent") == 100,
                "source_binding": result.get("source_digest") == source_hash,
                "generated_binding": result.get("generated_digest") == generated_hash,
                "route_equivalence": route_equivalence_receipt_valid(route_evidence),
            }
            if not all(required.values()):
                return fail_report(
                    report_path,
                    partial_report(
                        plan, plan_bytes, domain, gooo_source_sha, laya_enabled,
                        case_reports, external_repeat_observations,
                    ),
                    f"{case['case_id']} failed report invariants: {required}; report={result}",
                )

            expected = wants[case["case_id"]]
            points = len(domain)
            generated_points += points
            # Runtime comparison is performed by the temporary generated Go test below.
            matched_points += points
            source_units = int(result.get("source_semantic_units", 0))
            lowered = int(result.get("lowered_semantic_units", 0))
            construct_units += source_units
            lowered_units += min(source_units, lowered)
            candidates = result.get("candidate_routes", [])
            if len(candidates) > 1:
                bodies_with_choices += 1
            route = str(result.get("route", ""))
            route_counts[route] = route_counts.get(route, 0) + 1

            function_source = generated_source.split("\n\n", 1)[-1]
            if not function_source.startswith("//gooo:generated:start "):
                return fail_report(
                    report_path,
                    partial_report(
                        plan, plan_bytes, domain, gooo_source_sha, laya_enabled,
                        case_reports, external_repeat_observations,
                    ),
                    f"{case['case_id']} output omitted generated-region marker",
                )
            source_outputs.append(function_source)
            case_reports.append(
                {
                    "case_id": case["case_id"],
                    "activity": case["activity"],
                    "condition_id": case["condition_id"],
                    "result_pair_id": case["result_pair_id"],
                    "body_style": case["body_style"],
                    **route_evidence,
                    "replay_sha256": result.get("replay_digest"),
                    "report_decision": result.get("decision"),
                    "route_mode": result.get("route_decision", {}).get("mode"),
                    "route_provider": result.get("route_decision", {}).get("provider"),
                    "route_model": result.get("route_decision", {}).get("model"),
                    "route_model_revision": result.get("route_decision", {}).get("model_revision"),
                    "route_request_sha256": result.get("route_decision", {}).get("request_sha256"),
                    "route_probabilities": result.get("route_decision", {}).get("probabilities"),
                    "route_confidence": result.get("route_decision", {}).get("confidence"),
                    "route_answer_confidence": result.get("route_decision", {}).get("answer_confidence"),
                    "route_routing": result.get("route_decision", {}).get("routing"),
                    "route_fallback_reason": result.get("route_decision", {}).get("fallback_reason"),
                    "route_selection": result.get("route_selection"),
                    "candidate_routes": candidates,
                    "route_decision_latency_ms": result.get("route_decision_latency_ms", 0),
                    "source_semantic_units": source_units,
                    "lowered_semantic_units": lowered,
                    "completeness_percent": result.get("completeness_percent"),
                    "typecheck_passed": result.get("typecheck_passed"),
                    "internal_deterministic_replay": result.get("deterministic_replay"),
                    "external_repeat_equal": repeat_equal,
                    "repository_writes": result.get("repository_writes"),
                    "generated_bytes": len(generated_source.encode("utf-8")),
                    "expected_outputs": expected,
                    "checked_domain_points": points,
                }
            )

    go_source = f"package {PACKAGE}\n\n" + "\n".join(source_outputs)
    generated_dir = args.out / "generated"
    generated_dir.mkdir(parents=True, exist_ok=True)
    (generated_dir / "body_codegen.go").write_text(go_source, encoding="utf-8")
    test_source = make_go_test(cases, domain, wants)
    (generated_dir / "body_codegen_test.go").write_text(test_source, encoding="utf-8")
    (generated_dir / "go.mod").write_text(f"module {PACKAGE}\n\ngo 1.27\n", encoding="utf-8")

    test_env = os.environ.copy()
    test_env["GOWORK"] = "off"
    test_env["GOTOOLCHAIN"] = os.environ.get("GOTOOLCHAIN", "local")
    test_result, test_elapsed_ms = run_command(["go", "test", "-count=1", "./..."], test_env, generated_dir)
    go_version_result = subprocess.run(
        ["go", "version"], cwd=generated_dir, env=test_env,
        capture_output=True, text=True, check=False,
    )
    runtime_match = test_result.returncode == 0
    route_equivalence_passes = sum(1 for item in case_reports if route_equivalence_receipt_valid(item))

    cohort_wall_elapsed_ms = (time.perf_counter() - cohort_started) * 1000
    peak_rss = peak_child_rss_bytes()
    child_usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    total_user_cpu = child_usage.ru_utime
    total_system_cpu = child_usage.ru_stime
    total_child_cpu = total_user_cpu + total_system_cpu
    logical_cpu_count = os.cpu_count() or 1
    one_core_utilization = 100 * total_child_cpu / max(cohort_wall_elapsed_ms / 1000, 1e-9)
    laya_modes: dict[str, int] = {}
    route_selection_methods: dict[str, int] = {}
    route_equivalence_decisions: dict[str, int] = {}
    route_equivalence_rules: dict[str, int] = {}
    for item in case_reports:
        mode = str(item.get("route_mode") or "unknown")
        laya_modes[mode] = laya_modes.get(mode, 0) + 1
        selection_method = str((item.get("route_selection") or {}).get("method") or "unknown")
        route_selection_methods[selection_method] = route_selection_methods.get(selection_method, 0) + 1
        equivalence = item.get("route_equivalence") or {}
        equivalence_decision = str(equivalence.get("decision") or "unknown")
        route_equivalence_decisions[equivalence_decision] = route_equivalence_decisions.get(equivalence_decision, 0) + 1
        equivalence_rule = str(equivalence.get("rule") or "unknown")
        route_equivalence_rules[equivalence_rule] = route_equivalence_rules.get(equivalence_rule, 0) + 1

    report = {
        "schema": SCHEMA,
        "cohort_id": plan["cohort_id"],
        "planned_case_count": len(cases),
        "expected_case_count": int(plan["expected_case_count"]),
        "expected_domain_points": int(plan["expected_domain_points"]),
        "int64_extreme_values": [int(value) for value in plan["int64_extreme_values"]],
        "int64_extreme_expected_outputs": int(plan["expected_case_count"]) * len(plan["int64_extreme_values"]),
        "int64_extreme_checked_outputs": (
            len(case_reports) * len(plan["int64_extreme_values"]) if runtime_match else 0
        ),
        "int64_extreme_behavioral_matches": (
            len(case_reports) * len(plan["int64_extreme_values"]) if runtime_match else 0
        ),
        "decision": "PASS" if runtime_match and replay_mismatches == 0 and len(case_reports) == plan["expected_case_count"] and route_equivalence_passes == len(case_reports) else "FAIL_CLOSED",
        "plan_sha256": digest(plan_bytes),
        "gooo_source_sha": gooo_source_sha or "UNBOUND_LOCAL_SOURCE",
        "gooo_binary": args.gooo_bin.name,
        "go_version": go_version_result.stdout.strip(),
        "host_platform": platform.platform(),
        "laya_configured": laya_enabled,
        "route_sample_seed_sha256": sample_seed_sha256,
        "external_repeat_observation_count": external_repeat_observations,
        "selection_mode_counts": laya_modes,
        "route_selection_method_counts": route_selection_methods,
        "route_equivalence_decision_counts": route_equivalence_decisions,
        "route_equivalence_rule_counts": route_equivalence_rules,
        "route_semantic_equivalence_passes": route_equivalence_passes,
        "case_count": len(case_reports),
        "body_style_counts": {
            style: sum(1 for case in cases if case["body_style"] == style)
            for style in plan["body_styles"]
        },
        "eligible_multi_route_cases": bodies_with_choices,
        "candidate_route_counts": route_counts,
        "domain": domain,
        "checked_output_count": generated_points,
        "behavioral_matches": matched_points if runtime_match else 0,
        "behavioral_completeness_percent": 100.0 if runtime_match else 0.0,
        "body_ast_source_units": construct_units,
        "body_ast_lowered_units_capped": lowered_units,
        "body_ast_completeness_percent": (100.0 * lowered_units / construct_units) if construct_units else 0.0,
        "all_typechecks_passed": all(item["typecheck_passed"] for item in case_reports),
        "all_internal_replays_passed": all(item["internal_deterministic_replay"] for item in case_reports),
        "external_repeat_mismatches": None if laya_enabled and not sample_seed else replay_mismatches,
        "generated_package_test_passed": runtime_match,
        "generated_package_test_elapsed_ms": round(test_elapsed_ms, 3),
        "cohort_wall_elapsed_ms": round(cohort_wall_elapsed_ms, 3),
        "gooo_invocations": len(invocation_ms),
        "gooo_invocation_p50_ms": round(percentile(invocation_ms, 0.50), 3),
        "gooo_invocation_p95_ms": round(percentile(invocation_ms, 0.95), 3),
        "children_user_cpu_seconds": round(total_user_cpu, 6),
        "children_system_cpu_seconds": round(total_system_cpu, 6),
        "children_total_cpu_seconds": round(total_child_cpu, 6),
        "logical_cpu_count": logical_cpu_count,
        "children_average_cpu_one_core_percent": round(one_core_utilization, 3),
        "children_average_cpu_host_percent": round(one_core_utilization / logical_cpu_count, 3),
        "cpu_utilization_basis": "aggregate RUSAGE_CHILDREN CPU seconds divided by cohort wall time; one-core percent can exceed 100 when child processes run concurrently",
        "children_peak_rss_bytes": peak_rss,
        "children_peak_rss_source": "getrusage(RUSAGE_CHILDREN); maximum child-process RSS across Gooo CLI and Go compile/test processes",
        "external_laya_process_resources_included": False,
        "repository_writes": 0,
        "generated_go_sha256": digest(go_source.encode("utf-8")),
        "generated_go_bytes": len(go_source.encode("utf-8")),
        "generated_test_output": test_result.stdout.strip(),
        "generated_test_error": test_result.stderr.strip(),
        "cases": case_reports,
    }
    report["completeness_receipt"] = build_completeness_receipt(report)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if report["decision"] != "PASS":
        print(test_result.stdout, file=sys.stdout)
        print(test_result.stderr, file=sys.stderr)
        return 1
    summary_keys = (
        "decision", "case_count", "checked_output_count", "behavioral_completeness_percent",
        "body_ast_completeness_percent", "eligible_multi_route_cases", "generated_package_test_passed",
        "route_semantic_equivalence_passes", "route_equivalence_rule_counts",
        "gooo_invocation_p50_ms", "gooo_invocation_p95_ms", "children_user_cpu_seconds",
        "children_system_cpu_seconds", "children_average_cpu_one_core_percent",
        "children_average_cpu_host_percent", "logical_cpu_count", "cohort_wall_elapsed_ms",
        "children_peak_rss_bytes", "external_laya_process_resources_included", "cpu_utilization_basis",
    )
    summary = {key: report[key] for key in summary_keys}
    summary["completeness_receipt"] = {
        "decision": report["completeness_receipt"]["decision"],
        "status_counts": report["completeness_receipt"]["status_counts"],
        "aggregate_completeness_score": report["completeness_receipt"]["aggregate_completeness_score"],
        "first_unresolved": report["completeness_receipt"]["first_unresolved"],
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
