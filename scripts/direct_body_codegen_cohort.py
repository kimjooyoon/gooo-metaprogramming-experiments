#!/usr/bin/env python3
"""Run a finite, source-bound cohort through Gooo's body-codegen CLI."""

from __future__ import annotations

import argparse
import ast
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

from completeness_receipt import dimension, finalize_receipt, validate_receipt


SCHEMA = "gooo/body-codegen-cohort-report/v1"
PROFILE_ID = "gooo/body-codegen-direct-cohort-100/v4"
PACKAGE = "bodycodegen_cohort"
INT64_EDGE_VALUES = (-(1 << 63), -(1 << 63) + 1, (1 << 63) - 2, (1 << 63) - 1)
INT64_MIN = -(1 << 63)
INT64_MAX = (1 << 63) - 1

REFERENCE_CONDITION_EXPRESSIONS = {
    "negative": "input < 0",
    "at_most_minus_three": "input <= -3",
    "zero": "input == 0",
    "inclusive_neighborhood": "input >= -2 && input <= 2",
    "outside_window": "input < 0 || input > 5",
    "offset_positive": "input + 3 > 5",
    "difference_zero": "input - 2 == 0",
    "double_zero": "input * 2 == 0",
    "triple_offset_boundary": "input * 3 + 5 >= 10",
    "negative_double_boundary": "input * -2 < 7",
}


def digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def reference_condition(condition_id: str, value: int) -> bool:
    """Independent finite-domain oracle for the named plan conditions."""
    def wrap_int64(number: int) -> int:
        return ((number - INT64_MIN) % (1 << 64)) + INT64_MIN

    if condition_id == "negative":
        return value < 0
    if condition_id == "at_most_minus_three":
        return value <= -3
    if condition_id == "zero":
        return value == 0
    if condition_id == "inclusive_neighborhood":
        return -2 <= value <= 2
    if condition_id == "outside_window":
        return value < 0 or value > 5
    if condition_id == "offset_positive":
        return wrap_int64(value + 3) > 5
    if condition_id == "difference_zero":
        return wrap_int64(value - 2) == 0
    if condition_id == "double_zero":
        return wrap_int64(value * 2) == 0
    if condition_id == "triple_offset_boundary":
        return wrap_int64(value * 3 + 5) >= 10
    if condition_id == "negative_double_boundary":
        return wrap_int64(value * -2) < 7
    raise ValueError(f"unknown condition id {condition_id!r}")


class UnsupportedConditionProfile(ValueError):
    pass


def signed_int_literal(node: ast.AST) -> int:
    if isinstance(node, ast.Constant) and type(node.value) is int:
        return node.value
    if (
        isinstance(node, ast.UnaryOp)
        and isinstance(node.op, (ast.UAdd, ast.USub))
        and isinstance(node.operand, ast.Constant)
        and type(node.operand.value) is int
    ):
        return node.operand.value if isinstance(node.op, ast.UAdd) else -node.operand.value
    raise UnsupportedConditionProfile("comparison threshold is not a signed integer literal")


def ceil_div(numerator: int, denominator: int) -> int:
    return -((-numerator) // denominator)


def affine_int64(node: ast.AST) -> tuple[int, int]:
    """Return a bounded linear form (coefficient, offset) modulo int64 width."""
    modulus = 1 << 64
    if isinstance(node, ast.Name) and node.id == "input":
        return 1, 0
    if isinstance(node, ast.Constant) and type(node.value) is int:
        if not INT64_MIN <= node.value <= INT64_MAX:
            raise UnsupportedConditionProfile("affine constants must be signed int64 literals")
        return 0, node.value % modulus
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        coefficient, offset = affine_int64(node.operand)
        if isinstance(node.op, ast.USub):
            coefficient, offset = -coefficient, -offset
        return bounded_affine(coefficient, offset % modulus)
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult)):
        left_a, left_b = affine_int64(node.left)
        right_a, right_b = affine_int64(node.right)
        if isinstance(node.op, ast.Add):
            return bounded_affine(left_a + right_a, (left_b + right_b) % modulus)
        if isinstance(node.op, ast.Sub):
            return bounded_affine(left_a - right_a, (left_b - right_b) % modulus)
        if left_a and right_a:
            raise UnsupportedConditionProfile("multiplication must have one constant operand")
        if left_a:
            multiplier = signed_residue(right_b)
            return bounded_affine(left_a * multiplier, (left_b * multiplier) % modulus)
        if right_a:
            multiplier = signed_residue(left_b)
            return bounded_affine(right_a * multiplier, (right_b * multiplier) % modulus)
        return 0, (left_b * right_b) % modulus
    raise UnsupportedConditionProfile("only affine input arithmetic is supported")


def bounded_affine(coefficient: int, offset: int) -> tuple[int, int]:
    if abs(coefficient) > 8:
        raise UnsupportedConditionProfile("absolute affine coefficient must not exceed 8")
    return coefficient, offset


def signed_residue(value: int) -> int:
    wrapped = value % (1 << 64)
    return wrapped if wrapped <= INT64_MAX else wrapped - (1 << 64)


def affine_comparison_transitions(
    coefficient: int,
    offset: int,
    threshold: int,
) -> set[int]:
    """Derive partition cuts that contain every possible affine truth change."""
    modulus = 1 << 64
    signed_midpoint = 1 << 63
    output_boundaries = {0, signed_midpoint, threshold % modulus, (threshold + 1) % modulus}
    transitions = {0}
    if coefficient == 0:
        return transitions

    # Split at zero because signed int64 input order wraps in its unsigned
    # representation there. Within each half, a*x+offset is monotone before
    # its modulo-2^64 output wraps. The coefficient cap bounds the wrap count.
    for lower, upper in ((INT64_MIN, -1), (0, INT64_MAX)):
        first = coefficient * lower + offset
        last = coefficient * upper + offset
        minimum, maximum = min(first, last), max(first, last)
        first_cycle = minimum // modulus
        last_cycle = maximum // modulus
        for cycle in range(first_cycle, last_cycle + 1):
            for boundary in output_boundaries:
                raw_boundary = cycle * modulus + boundary
                if coefficient > 0:
                    candidate = ceil_div(raw_boundary - offset, coefficient)
                else:
                    candidate = ceil_div(raw_boundary - 1 - offset, coefficient)
                if lower <= candidate <= upper:
                    transitions.add(candidate)
    return {point for point in transitions if INT64_MIN < point <= INT64_MAX}


def int64_comparison_partition(plan: dict[str, Any]) -> dict[str, Any]:
    """Build exact representatives for bounded wrapping-affine int64 conditions."""
    conditions = plan.get("conditions", [])
    transitions: set[int] = set()
    comparison_count = 0

    def visit(node: ast.AST) -> None:
        nonlocal comparison_count
        if isinstance(node, ast.BoolOp) and isinstance(node.op, (ast.And, ast.Or)) and len(node.values) >= 2:
            for value in node.values:
                visit(value)
            return
        if not isinstance(node, ast.Compare) or len(node.ops) != 1 or len(node.comparators) != 1:
            raise UnsupportedConditionProfile("only single affine-to-literal comparisons are supported")
        coefficient, offset = affine_int64(node.left)
        threshold = signed_int_literal(node.comparators[0])
        if threshold < INT64_MIN or threshold > INT64_MAX:
            raise UnsupportedConditionProfile("comparison threshold is outside signed int64")
        operation = type(node.ops[0])
        if operation not in (ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.Eq, ast.NotEq):
            raise UnsupportedConditionProfile("comparison operator is outside the supported profile")
        comparison_count += 1
        transitions.update(affine_comparison_transitions(coefficient, offset, threshold))

    try:
        if not isinstance(conditions, list) or not conditions:
            raise UnsupportedConditionProfile("the plan must declare conditions as a non-empty list")
        if any(not isinstance(condition, dict) for condition in conditions):
            raise UnsupportedConditionProfile("each declared condition must be an object")
        result_pairs = plan.get("result_pairs", [])
        if not isinstance(result_pairs, list) or not result_pairs:
            raise UnsupportedConditionProfile("the plan must declare constant result pairs")
        for pair in result_pairs:
            if not isinstance(pair, dict) or any(
                type(pair.get(key)) is not int
                or pair[key] < INT64_MIN
                or pair[key] > INT64_MAX
                for key in ("when_true", "when_false")
            ):
                raise UnsupportedConditionProfile("result pairs must contain signed int64 integer literals")
        body_styles = plan.get("body_styles", [])
        if not isinstance(body_styles, list) or not body_styles or any(
            not isinstance(style, str) or style not in {"branch_returns", "result_assignment"}
            for style in body_styles
        ):
            raise UnsupportedConditionProfile("body styles are outside the constant-result conditional profile")
        seen_ids: set[str] = set()
        for condition in conditions:
            condition_id = str(condition.get("id", ""))
            expression = str(condition.get("expression", ""))
            if condition_id in seen_ids or REFERENCE_CONDITION_EXPRESSIONS.get(condition_id) != expression:
                raise UnsupportedConditionProfile("condition expression is not bound to its independent oracle")
            seen_ids.add(condition_id)
            normalized = expression.replace("&&", " and ").replace("||", " or ")
            visit(ast.parse(normalized, mode="eval").body)
    except (SyntaxError, ValueError) as error:
        return {
            "schema": "gooo/int64-affine-partition/v2",
            "profile": "bounded_wrapping_affine_int64_comparisons_selecting_constants",
            "profile_supported": False,
            "partition_covers_int64": False,
            "arithmetic_semantics": "signed_int64_modulo_2^64",
            "max_abs_input_coefficient": 8,
            "supported_affine_operators": ["+", "-", "*"],
            "transition_points_are_conservative_cuts": True,
            "transition_points": [],
            "representative_inputs": [],
            "comparison_count": comparison_count,
            "failure_reason": str(error),
        }

    points = [INT64_MIN, *sorted(transitions)]
    return {
        "schema": "gooo/int64-affine-partition/v2",
        "profile": "bounded_wrapping_affine_int64_comparisons_selecting_constants",
        "profile_supported": True,
        "partition_covers_int64": True,
        "arithmetic_semantics": "signed_int64_modulo_2^64",
        "max_abs_input_coefficient": 8,
        "supported_affine_operators": ["+", "-", "*"],
        "transition_points_are_conservative_cuts": True,
        "transition_points": sorted(transitions),
        "representative_inputs": points,
        "comparison_count": comparison_count,
        "condition_count": len(conditions),
        "result_pair_count": len(result_pairs),
        "body_styles": body_styles,
        "partition_cell_count": len(points),
        "proof_basis": "Each signed int64 affine expression is a bounded-slope modular linear function. Its output wraps at most a coefficient-bounded number of times; all possible comparison boundaries and signed-order seams are pulled back into conservative input partition cuts (redundant cuts are allowed). Boolean combinations inherit the union partition, and every representative is executed against the generated function and independent condition oracle.",
    }


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


def validate_compiler_receipt(report: dict[str, Any], expected_source_sha: str) -> tuple[dict[str, Any], str, bool]:
    receipt = report.get("completeness_receipt")
    validate_receipt(receipt)
    expected_source = expected_source_sha or "UNBOUND_LOCAL_SOURCE"
    scope = receipt["scope"]
    if report.get("compiler_source_sha") != expected_source:
        raise ValueError("compiler report revision does not match the pinned source SHA")
    if scope.get("compiler_source_sha") != expected_source:
        raise ValueError("compiler receipt revision is not bound to the pinned source SHA")
    if scope.get("plan_sha256") != report.get("plan_sha256"):
        raise ValueError("compiler receipt plan digest is not bound to its body-codegen report")
    dimensions = {item["id"]: item for item in receipt["dimensions"]}
    core_ids = receipt["core_dimensions"]
    core_passed = all(dimensions[dimension_id]["status"] == "PASS" for dimension_id in core_ids)
    if report.get("decision") == "PASS" and not core_passed:
        raise ValueError("compiler marked code generation PASS while a declared core receipt dimension was not PASS")
    canonical = json.dumps(receipt, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return receipt, digest(canonical), core_passed


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
    partition_proof = report.get("int64_partition_proof", {})
    partition_supported = partition_proof.get("profile_supported") is True
    partition_complete = (
        partition_supported
        and partition_proof.get("partition_covers_int64") is True
        and partition_proof.get("execution_contains_all_representatives") is True
    )
    partition_proven_cases = int(report.get("int64_partition_proven_cases", 0))
    laya_configured = bool(report.get("laya_configured", False))

    def count_true(key: str) -> int:
        return sum(1 for item in cases if item.get(key) is True)

    passed_generation = sum(1 for item in cases if item.get("report_decision") == "PASS")
    compiler_receipt_cases = count_true("compiler_receipt_valid")
    compiler_core_receipt_passes = count_true("compiler_core_dimensions_passed")
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
    partition_failed = runtime_failed or (
        partition_supported
        and (
            not partition_complete
            or partition_proven_cases != expected_cases
            or route_equivalence_passes != expected_cases
        )
    )
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
            "compiler_completeness_receipt_coverage", compiler_receipt_cases, expected_cases,
            "body-codegen reports with a validated compiler completeness receipt",
            "Validates the compiler-emitted v2 receipt and binds its plan and compiler revision to each exact body-codegen report.",
            ["per-case compiler receipt SHA-256", str(report.get("gooo_source_sha", "source revision unavailable"))],
        ),
        dimension(
            "compiler_core_receipt_passes", compiler_core_receipt_passes, expected_cases,
            "compiler receipts whose declared core dimensions all pass",
            "Counts compiler core evidence separately from non-core UNKNOWN dimensions such as generated execution and Laya observation.",
            ["per-case compiler completeness receipt core_dimensions", "per-case dimension status counts"],
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
            "execution_boundary", expected_cases if report.get("generated_package_test_passed") is True else 0,
            expected_cases, "generated functions executed from temporary package files",
            "The compiled behavior checks run from the cohort's temporary output directory; this does not grant generated code repository or external-service authority.",
            ["generated_package_test_passed", "temporary generated package path", "repository_writes"],
            fail_closed=runtime_failed,
        ),
        dimension(
            "permission_boundary", 0, 1, "observed host permission profiles",
            "The cohort measures repository writes but does not capture the local OS user's filesystem permission set.",
            ["repository_write_boundary is measured separately", "no host permission receipt is bound"],
        ),
        dimension(
            "external_network_boundary", int(not laya_configured), 1, "runs with no configured Laya service",
            "A disabled Laya URL proves no model decision was requested in this run; it does not audit every possible process network call.",
            [f"laya_configured:{laya_configured}", "CI sets GOOO_LAYA_URL to an empty value"],
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
            "semantic_profile_delta", 0, 1, "compatible before/after semantic receipts",
            "No prior receipt with the same plan, compiler, toolchain, and runner is bound for per-dimension regression deltas.",
            [str(report.get("plan_sha256", "plan digest unavailable")), str(report.get("gooo_source_sha", "compiler source unavailable")), "no comparable prior receipt"],
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
            "This cohort proves only Boolean combinations of bounded affine int64 conditions with constant outputs; broader .gooo body forms and predicates remain outside the partition.",
            ["partitioned_int64_semantics", "broader body forms and predicates are unmodeled"],
        ),
        dimension(
            "partitioned_int64_semantics", partition_proven_cases, expected_cases,
            "fixture bodies proven over every int64 comparison partition",
            "For Boolean combinations of wrapping int64 affine expressions with absolute input coefficient at most 8 and constant result pairs, every signed-order and comparison transition is represented and executed; this proof applies only to the declared profile.",
            [
                str(report.get("plan_sha256", "plan digest unavailable")),
                str(report.get("gooo_source_sha", "source revision unavailable")),
                str(partition_proof.get("representative_inputs", [])),
            ],
            fail_closed=partition_failed,
        ),
        dimension(
            "route_quality", 0, 1, "independently validated route-quality criteria",
            "Compiler-derived semantic equivalence is measured separately; this cohort has no independent clarity or utility oracle to rank equivalent routes.",
            ["route_semantic_equivalence", "no independent route-clarity or utility measure"],
        ),
    ]
    core_ids = {
        "declaration_coverage", "generation_coverage", "typecheck_coverage",
        "compiler_completeness_receipt_coverage", "compiler_core_receipt_passes",
        "source_ast_coverage", "route_semantic_equivalence", "finite_domain_behavior", "internal_replay_coverage",
        "route_choice_protocol", "source_binding_integrity", "repository_write_boundary",
        "partitioned_int64_semantics",
    }
    next_operations = {
        "laya_decision_observation": "RUN_WITH_A_PINNED_LAYA_SERVICE_AND_RETAIN_MODEL_REVISION",
        "route_semantic_equivalence": "BIND_SOURCE_AND_GENERATED_ENVELOPES_AND_REQUIRE_THE_DECLARED_CANONICAL_FORM_TO_MATCH",
        "resource_baseline_comparison": "BIND_A_REPEAT_RECEIPT_FROM_THE_SAME_COMPILER_AND_RUNNER_PROFILE",
        "real_use_case_coverage": "BIND_INDEPENDENTLY_SOURCED_REAL_WORKFLOW_FIXTURES",
        "reverse_observation_coverage": "ADD_SOURCE_BOUND_GENERATED_TO_SOURCE_OBSERVATION_EVIDENCE",
        "full_domain_semantics": "EXTEND_PARTITION_PROOFS_TO_THE_REST_OF_THE_BODY_GRAMMAR",
        "partitioned_int64_semantics": "EXTEND_THE_SUPPORTED_PARTITION_PROFILE_OR_BIND_A_SEPARATE_PROOF",
        "route_quality": "DEFINE_AN_INDEPENDENT_ROUTE_QUALITY_ORACLE",
        "semantic_profile_delta": "BIND_A_COMPATIBLE_BASELINE_AND_REPORT_PER_DIMENSION_DELTAS",
        "resource_observation": "CAPTURE_WALL_CPU_AND_PEAK_RSS_FOR_EVERY_RUNNER_PROFILE",
        "source_binding_integrity": "BIND_EACH_SOURCE_AND_GENERATED_DIGEST_TO_A_FULL_COMPILER_AND_PLAN_IDENTITY",
        "external_repeat_determinism": "REPEAT_EACH_CLI_DECISION_AND_COMPARE_ROUTE_AND_GENERATED_DIGEST",
        "internal_replay_coverage": "REPAIR_OR_REPLAY_EACH_COMPILER_SELECTED_ROUTE",
        "route_choice_protocol": "BIND_EACH_SELECTED_ROUTE_TO_THE_COMPILER_DECLARED_CANDIDATE_SET",
        "repository_write_boundary": "KEEP_OUTPUT_IN_TEMPORARY_STORAGE_AND_RECHECK_REPOSITORY_STATE",
        "execution_boundary": "BIND_COMPILED_EXECUTION_TO_THE_TEMPORARY_PACKAGE_AND_RECHECK_REPOSITORY_WRITES",
        "permission_boundary": "CAPTURE_THE_HOST_PERMISSION_PROFILE_WITHOUT_GRANTING_ADDITIONAL_AUTHORITY",
        "external_network_boundary": "RECORD_THE_CONFIGURED_PROVIDER_ENDPOINT_AND_AUDIT_THE_ALLOWED_NETWORK_SCOPE",
        "declaration_coverage": "BIND_PLAN_CASES_TO_THE_DECLARED_FIXTURE_DENOMINATOR",
        "generation_coverage": "REPAIR_FAILING_GOOO_BODY_CODEGEN_CASES",
        "compiler_completeness_receipt_coverage": "EMIT_AND_BIND_A_VALID_COMPILER_COMPLETENESS_RECEIPT_FOR_EACH_CASE",
        "compiler_core_receipt_passes": "REPAIR_OR_EXPLAIN_EACH_NONPASS_COMPILER_CORE_DIMENSION",
        "typecheck_coverage": "REPAIR_GENERATED_GO_TYPE_ERRORS",
        "source_ast_coverage": "LOWER_EVERY_ACCEPTED_SOURCE_AST_UNIT_OR_FAIL_CLOSED",
        "finite_domain_behavior": "ADD_THE_MISSING_COMPILED_INPUT_OUTPUT_OBSERVATIONS",
        "int64_extreme_boundary_behavior": "EXECUTE_EVERY_FIXTURE_AT_ALL_DECLARED_INT64_EDGE_VALUES",
    }
    return finalize_receipt(
        profile_id=PROFILE_ID,
        decision_basis="all core fixture dimensions must pass; UNKNOWN dimensions remain explicit and are never converted into a completion percentage",
        scope={
            "domain_scope": "100 synthetic pure activity bodies over bounded wrapping-affine int64 conditions",
            "allowed_investment": "measure source-bound code generation, type checking, finite samples, and conservative full-int64 partitions for this declared profile",
            "excluded_scope": [
                "natural-language intent completeness",
                "real production workflows",
                "unrestricted Gooo body syntax",
                "Laya route quality",
                "runtime-to-source reverse observation",
            ],
            "planned_fixture_cases": expected_cases,
            "observed_fixture_cases": case_count,
            "input_domain": report.get("domain", []),
            "finite_domain_points_per_case": len(report.get("domain", [])),
            "int64_extreme_values": extreme_values,
            "int64_partition_proof": partition_proof,
            "compiler_source_sha": source_sha or "UNBOUND_LOCAL_SOURCE",
            "plan_sha256": report.get("plan_sha256"),
            "toolchain": report.get("go_version", "UNOBSERVED_GO_VERSION"),
            "execution_environment": report.get("host_platform", "UNOBSERVED_RUNNER"),
            "laya_configured": laya_configured,
        },
        dimensions=dimensions,
        core_dimensions=core_ids,
        next_operations=next_operations,
        not_claimed=[
            "coverage of natural-language user intent",
            "coverage of real production workflows",
            "unrestricted Gooo body-codegen behavior over the full int64 domain",
            "reverse observation from generated runtime back to .gooo declarations",
            "calibration or usefulness of Laya route probabilities",
            "readability or utility preference between equivalent generated routes",
            "universal or production language completeness",
        ],
        force_fail_closed_reason=(
            str(report.get("failure") or "cohort execution reported FAIL_CLOSED")
            if report.get("decision") == "FAIL_CLOSED" else ""
        ),
    )


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
    partition_proof = int64_comparison_partition(plan)
    representatives = [int(value) for value in partition_proof.get("representative_inputs", [])]
    partition_proof.update(
        {
            "execution_contains_all_representatives": (
                partition_proof.get("profile_supported") is True
                and set(representatives).issubset(set(domain) | set(representatives))
            ),
            "plan_sha256": digest(plan_bytes),
            "gooo_source_sha": gooo_source_sha or "UNBOUND_LOCAL_SOURCE",
            "compiled_execution_matches_representatives": False,
        }
    )
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
        "int64_partition_proof": partition_proof,
        "int64_partition_expected_observations": len(make_cases(plan)) * len(representatives),
        "int64_partition_observed_matches": 0,
        "int64_partition_proven_cases": 0,
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
    partition_proof = int64_comparison_partition(plan)
    partition_points = [int(value) for value in partition_proof.get("representative_inputs", [])]
    execution_domain = sorted(set(domain) | set(partition_points))
    partition_proof.update(
        {
            "execution_contains_all_representatives": (
                partition_proof.get("profile_supported") is True
                and set(partition_points).issubset(execution_domain)
            ),
            "plan_sha256": digest(plan_bytes),
            "gooo_source_sha": os.environ.get("GOOO_SOURCE_SHA", "") or "UNBOUND_LOCAL_SOURCE",
            "compiled_execution_matches_representatives": False,
        }
    )
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
            try:
                if result.get("decision") != "PASS":
                    raise ValueError(f"compiler report decision is {result.get('decision')!r}")
                compiler_receipt, compiler_receipt_sha256, compiler_core_passed = validate_compiler_receipt(
                    result, gooo_source_sha
                )
            except (KeyError, TypeError, ValueError) as error:
                return fail_report(
                    report_path,
                    partial_report(
                        plan, plan_bytes, domain, gooo_source_sha, laya_enabled,
                        case_reports, external_repeat_observations,
                    ),
                    f"{case['case_id']} compiler completeness receipt is invalid: {error}",
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
                    _, replay_receipt_sha256, _ = validate_compiler_receipt(replay_report, gooo_source_sha)
                    repeat_equal = (
                        replay_report.get("generated_digest") == result.get("generated_digest")
                        and replay_report.get("route") == result.get("route")
                        and replay_payload.get("source") == generated_source
                        and replay_receipt_sha256 == compiler_receipt_sha256
                    )
                    if sample_seed:
                        repeat_equal = repeat_equal and replay_report.get("route_selection") == result.get("route_selection")
                        repeat_equal = repeat_equal and replay_report.get("route_decision", {}).get("model_revision") == result.get("route_decision", {}).get("model_revision")
                except (json.JSONDecodeError, KeyError, TypeError, ValueError):
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
                    "compiler_source_sha": result.get("compiler_source_sha"),
                    "compiler_plan_sha256": result.get("plan_sha256"),
                    "compiler_completeness_receipt": compiler_receipt,
                    "compiler_completeness_receipt_sha256": compiler_receipt_sha256,
                    "compiler_receipt_valid": True,
                    "compiler_core_dimensions_passed": compiler_core_passed,
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
    execution_wants = {case["case_id"]: expected_values(case, execution_domain) for case in cases}
    test_source = make_go_test(cases, execution_domain, execution_wants)
    (generated_dir / "body_codegen_test.go").write_text(test_source, encoding="utf-8")
    (generated_dir / "go.mod").write_text(f"module {PACKAGE}\n\ngo 1.27.1\n", encoding="utf-8")

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
    partition_proven_cases = (
        len(case_reports)
        if (
            runtime_match
            and partition_proof.get("profile_supported") is True
            and partition_proof.get("partition_covers_int64") is True
            and partition_proof.get("execution_contains_all_representatives") is True
            and route_equivalence_passes == len(case_reports)
        )
        else 0
    )
    partition_proof["compiled_execution_matches_representatives"] = partition_proven_cases == len(cases)
    partition_proof["proved_case_count"] = partition_proven_cases

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
    compiler_receipt_status_counts = {"PASS": 0, "PROGRESS": 0, "UNKNOWN": 0, "FAIL_CLOSED": 0}
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
        for dimension_item in item["compiler_completeness_receipt"]["dimensions"]:
            compiler_receipt_status_counts[dimension_item["status"]] += 1

    failure_reasons: list[str] = []
    if not runtime_match:
        failure_reasons.append(
            test_result.stderr.strip() or test_result.stdout.strip() or "generated package execution failed"
        )
    if replay_mismatches:
        failure_reasons.append(f"{replay_mismatches} external deterministic replays diverged")
    if len(case_reports) != plan["expected_case_count"]:
        failure_reasons.append(
            f"generated {len(case_reports)} of {plan['expected_case_count']} planned cases"
        )
    if route_equivalence_passes != len(case_reports):
        failure_reasons.append(
            f"{len(case_reports) - route_equivalence_passes} route-equivalence receipts did not pass"
        )

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
        "int64_partition_proof": partition_proof,
        "int64_partition_expected_observations": (
            len(cases) * len(partition_points) if partition_proof.get("profile_supported") is True else 0
        ),
        "int64_partition_observed_matches": (
            len(case_reports) * len(partition_points) if partition_proven_cases == len(cases) else 0
        ),
        "int64_partition_proven_cases": partition_proven_cases,
        "decision": "FAIL_CLOSED" if failure_reasons else "PASS",
        "failure": "; ".join(failure_reasons) if failure_reasons else None,
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
        "compiler_receipt_valid_case_count": sum(1 for item in case_reports if item.get("compiler_receipt_valid") is True),
        "compiler_core_receipt_passes": sum(1 for item in case_reports if item.get("compiler_core_dimensions_passed") is True),
        "compiler_receipt_status_counts": compiler_receipt_status_counts,
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
        "int64_partition_proven_cases", "int64_partition_expected_observations",
        "body_ast_completeness_percent", "eligible_multi_route_cases", "generated_package_test_passed",
        "route_semantic_equivalence_passes", "route_equivalence_rule_counts",
        "gooo_invocation_p50_ms", "gooo_invocation_p95_ms", "children_user_cpu_seconds",
        "children_system_cpu_seconds", "children_average_cpu_one_core_percent",
        "children_average_cpu_host_percent", "logical_cpu_count", "cohort_wall_elapsed_ms",
        "children_peak_rss_bytes", "external_laya_process_resources_included", "cpu_utilization_basis",
        "compiler_receipt_valid_case_count", "compiler_core_receipt_passes", "compiler_receipt_status_counts",
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
