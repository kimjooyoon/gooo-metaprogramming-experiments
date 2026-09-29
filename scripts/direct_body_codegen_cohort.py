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
PACKAGE = "bodycodegen_cohort"


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
            f"let result = {pair['when_false']}\n"
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


def fail_report(path: Path, report: dict[str, Any], message: str) -> int:
    report["decision"] = "FAIL_CLOSED"
    report["failure"] = message
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(message, file=sys.stderr)
    return 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gooo-bin", required=True, type=Path)
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    plan_bytes = args.plan.read_bytes()
    plan = json.loads(plan_bytes)
    domain = [int(value) for value in plan["domain"]]
    cases = make_cases(plan)
    report_path = args.out / "body-codegen-report.json"
    args.out.mkdir(parents=True, exist_ok=True)

    if len(cases) != plan["expected_case_count"]:
        return fail_report(report_path, {"schema": SCHEMA}, f"plan generated {len(cases)} cases, expected {plan['expected_case_count']}")
    if len(domain) * len(cases) != plan["expected_domain_points"]:
        return fail_report(
            report_path,
            {"schema": SCHEMA},
            f"plan yields {len(domain) * len(cases)} outputs, expected {plan['expected_domain_points']}",
        )

    gooo_source_sha = os.environ.get("GOOO_SOURCE_SHA", "")
    if gooo_source_sha and (len(gooo_source_sha) != 40 or any(char not in "0123456789abcdef" for char in gooo_source_sha)):
        return fail_report(report_path, {"schema": SCHEMA}, "GOOO_SOURCE_SHA must be a full lowercase Git commit SHA")

    env = os.environ.copy()
    laya_enabled = bool(env.get("GOOO_LAYA_URL"))
    source_outputs: list[str] = []
    case_reports: list[dict[str, Any]] = []
    wants = {case["case_id"]: expected_values(case, domain) for case in cases}
    invocation_ms: list[float] = []
    replay_mismatches = 0
    generated_points = 0
    matched_points = 0
    construct_units = 0
    lowered_units = 0
    bodies_with_choices = 0
    route_counts: dict[str, int] = {}

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
            first, elapsed = run_command(command, env)
            invocation_ms.append(elapsed)
            if first.returncode != 0:
                return fail_report(report_path, {"schema": SCHEMA, "cases": case_reports}, f"{case['case_id']} body-codegen failed: {first.stderr.strip() or first.stdout.strip()}")
            try:
                first_payload = json.loads(first.stdout)
                result = first_payload["report"]
                generated_source = first_payload["source"]
            except (json.JSONDecodeError, KeyError, TypeError) as error:
                return fail_report(report_path, {"schema": SCHEMA, "cases": case_reports}, f"{case['case_id']} emitted malformed JSON: {error}")

            repeat_equal: bool | None = None
            if not laya_enabled:
                replay, elapsed = run_command(command, env)
                invocation_ms.append(elapsed)
                if replay.returncode != 0:
                    return fail_report(report_path, {"schema": SCHEMA, "cases": case_reports}, f"{case['case_id']} deterministic replay failed: {replay.stderr.strip() or replay.stdout.strip()}")
                try:
                    replay_payload = json.loads(replay.stdout)
                    replay_report = replay_payload["report"]
                    repeat_equal = (
                        replay_report.get("generated_digest") == result.get("generated_digest")
                        and replay_report.get("route") == result.get("route")
                        and replay_payload.get("source") == generated_source
                    )
                except (json.JSONDecodeError, KeyError, TypeError):
                    repeat_equal = False
                if not repeat_equal:
                    replay_mismatches += 1

            required = {
                "decision": result.get("decision") == "PASS",
                "typecheck": result.get("typecheck_passed") is True,
                "internal_replay": result.get("deterministic_replay") is True,
                "zero_repository_writes": result.get("repository_writes") == 0,
                "body_completeness": result.get("completeness_percent") == 100,
                "source_binding": result.get("source_digest") == source_hash,
            }
            if not all(required.values()):
                return fail_report(
                    report_path,
                    {"schema": SCHEMA, "cases": case_reports},
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
                return fail_report(report_path, {"schema": SCHEMA, "cases": case_reports}, f"{case['case_id']} output omitted generated-region marker")
            source_outputs.append(function_source)
            case_reports.append(
                {
                    "case_id": case["case_id"],
                    "activity": case["activity"],
                    "condition_id": case["condition_id"],
                    "result_pair_id": case["result_pair_id"],
                    "body_style": case["body_style"],
                    "source_sha256": source_hash,
                    "generated_sha256": result.get("generated_digest"),
                    "replay_sha256": result.get("replay_digest"),
                    "report_decision": result.get("decision"),
                    "route": route,
                    "route_mode": result.get("route_decision", {}).get("mode"),
                    "route_provider": result.get("route_decision", {}).get("provider"),
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
    test_env["GOTOOLCHAIN"] = "local"
    test_result, test_elapsed_ms = run_command(["go", "test", "-count=1", "./..."], test_env, generated_dir)
    runtime_match = test_result.returncode == 0

    peak_rss = peak_child_rss_bytes()
    total_user_cpu = resource.getrusage(resource.RUSAGE_CHILDREN).ru_utime
    total_system_cpu = resource.getrusage(resource.RUSAGE_CHILDREN).ru_stime
    laya_modes: dict[str, int] = {}
    for item in case_reports:
        mode = str(item.get("route_mode") or "unknown")
        laya_modes[mode] = laya_modes.get(mode, 0) + 1

    report = {
        "schema": SCHEMA,
        "cohort_id": plan["cohort_id"],
        "decision": "PASS" if runtime_match and replay_mismatches == 0 and len(case_reports) == plan["expected_case_count"] else "FAIL_CLOSED",
        "plan_sha256": digest(plan_bytes),
        "gooo_source_sha": gooo_source_sha or "UNBOUND_LOCAL_SOURCE",
        "gooo_binary": str(args.gooo_bin),
        "go_version": subprocess.run(["go", "version"], capture_output=True, text=True, check=False).stdout.strip(),
        "host_platform": platform.platform(),
        "laya_configured": laya_enabled,
        "selection_mode_counts": laya_modes,
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
        "external_repeat_mismatches": replay_mismatches,
        "generated_package_test_passed": runtime_match,
        "generated_package_test_elapsed_ms": round(test_elapsed_ms, 3),
        "gooo_invocations": len(invocation_ms),
        "gooo_invocation_p50_ms": round(percentile(invocation_ms, 0.50), 3),
        "gooo_invocation_p95_ms": round(percentile(invocation_ms, 0.95), 3),
        "children_user_cpu_seconds": round(total_user_cpu, 6),
        "children_system_cpu_seconds": round(total_system_cpu, 6),
        "children_peak_rss_bytes": peak_rss,
        "children_peak_rss_source": "getrusage(RUSAGE_CHILDREN); peak across sequential Gooo CLI and Go compiler/test child processes",
        "repository_writes": 0,
        "generated_go_sha256": digest(go_source.encode("utf-8")),
        "generated_go_bytes": len(go_source.encode("utf-8")),
        "generated_test_output": test_result.stdout.strip(),
        "generated_test_error": test_result.stderr.strip(),
        "cases": case_reports,
    }
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if report["decision"] != "PASS":
        print(test_result.stdout, file=sys.stdout)
        print(test_result.stderr, file=sys.stderr)
        return 1
    print(json.dumps({key: report[key] for key in (
        "decision", "case_count", "checked_output_count", "behavioral_completeness_percent",
        "body_ast_completeness_percent", "eligible_multi_route_cases", "generated_package_test_passed",
        "gooo_invocation_p50_ms", "gooo_invocation_p95_ms", "children_user_cpu_seconds",
        "children_system_cpu_seconds", "children_peak_rss_bytes",
    )}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
