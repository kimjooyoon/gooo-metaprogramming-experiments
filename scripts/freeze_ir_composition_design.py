#!/usr/bin/env python3
"""Freeze the design and model-ready no-feedback plans before code execution."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COHORT = ROOT / "cohorts/ir-composition-curriculum-2026-09-30"
PIN = {
    "revision": "bb5c1ec2f81cbfb17ac6fb2f7a9e1d7b67168e7f",
    "binary_sha256": "47b9f3bd1b365d18771ba36b0a2b472b139fdb6a08b404697e188478dce38c6e",
    "go_version": "go1.27.0",
    "goos": "darwin",
    "goarch": "arm64",
    "cgo_enabled": True,
    "trimpath": True,
    "vcs_modified": False,
}
SCRIPT_PATHS = [
    "scripts/prepare_ir_composition_curriculum.py",
    "scripts/build_ir_composition_laya_plans.py",
    "scripts/freeze_ir_composition_design.py",
    "scripts/freeze_ir_composition_curriculum.py",
    "scripts/run_ir_composition_curriculum.py",
]
PLAN_GROUPS = {
    "body_fill": "plans/body-fill",
    "legacy_no_feedback": "plans/laya/legacy-no-feedback",
    "compact_no_feedback": "plans/laya/compact-no-feedback",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def plan_files(relative_dir: str) -> list[Path]:
    return sorted((COHORT / relative_dir).glob("*.json"))


def main() -> None:
    catalog = json.loads((COHORT / "catalog.json").read_text(encoding="utf-8"))
    designs = catalog.get("designs", [])
    if catalog.get("design_count") != 32 or len(designs) != 32:
        raise SystemExit("design freeze requires 32 catalogued intentions")
    if catalog.get("distinct_intentions") != 32 or len({row["intent"] for row in designs}) != 32:
        raise SystemExit("design freeze requires 32 distinct intentions")
    if catalog.get("one_expression_hole_per_design") is not True:
        raise SystemExit("catalog must declare exactly one expression hole per design")

    artifacts = [COHORT / "README.md", COHORT / "catalog.json"]
    artifacts += sorted((COHORT / "fixtures").glob("*.gooo"))
    artifacts += sorted((COHORT / "oracle").rglob("*.go"))
    artifacts += [COHORT / "oracle/go.mod", COHORT / "oracle/python_spec.py"]
    artifacts += sorted((COHORT / "oracle/testdata").glob("*.json"))
    for group, relative_dir in PLAN_GROUPS.items():
        plans = plan_files(relative_dir)
        if len(plans) != 32:
            raise SystemExit(f"design freeze requires 32 {group} plans; found {len(plans)}")
        for plan_path in plans:
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            if group == "body_fill":
                continue
            if plan.get("provider_model") != "english":
                raise SystemExit(f"{plan_path.name} must pin provider_model to english")
            if plan.get("external_training_feedback") is not None:
                raise SystemExit(f"{plan_path.name} unexpectedly contains feedback before Go execution")
            if group == "compact_no_feedback" and plan.get("prompt_profile") != "compact":
                raise SystemExit(f"{plan_path.name} must declare compact prompt packaging")
            if group == "legacy_no_feedback" and "prompt_profile" in plan:
                raise SystemExit(f"{plan_path.name} must preserve legacy prompt packaging")
            if plan.get("test_cases") != json.loads(
                (COHORT / "plans/body-fill" / plan_path.name).read_text(encoding="utf-8")
            ).get("test_cases"):
                raise SystemExit(f"{plan_path.name} has inconsistent training cases")
        artifacts += plans

    expected_areas = {
        "conditionals": 4,
        "nested_if_else": 4,
        "let_reassignment": 4,
        "expression_precedence": 4,
        "comparison_expressions": 4,
        "boolean_locals": 4,
        "text_locals": 4,
        "int64_boundaries": 4,
    }
    if catalog.get("primary_areas") != expected_areas:
        raise SystemExit("primary semantic areas must remain balanced four apiece")

    artifacts.extend(ROOT / path for path in SCRIPT_PATHS)
    artifacts = sorted(set(artifacts), key=lambda path: path.relative_to(ROOT).as_posix())
    files = {path.relative_to(ROOT).as_posix(): sha256(path) for path in artifacts}
    manifest = {
        "schema": "gooo/ir-composition-design-freeze/v1",
        "cohort": "ir-composition-curriculum-2026-09-30",
        "stage": "design_and_plans_frozen_before_compiled_go_or_gooo_execution",
        "design_count": 32,
        "distinct_intentions": 32,
        "one_expression_hole_per_design": True,
        "finite_candidates_per_design": 3,
        "balanced_primary_areas": expected_areas,
        "plan_counts": {group: 32 for group in PLAN_GROUPS},
        "model_ready_arms_prepared": ["legacy-no-feedback", "compact-no-feedback"],
        "feedback_arm_status": "deferred_until_compiled_go_candidate_outputs_exist",
        "provider_model": "english",
        "holdout_cases_withheld_from_search_prompt": True,
        "candidate_discrimination_and_source_unit_completeness_separate": True,
        "semantic_scope": "one_expression_hole_with_three_finite_candidates; not free-form code generation or full-domain proof",
        "execution_status": "not_run",
        "model_calls": 0,
        "compiler_pin": PIN,
        "files": files,
    }
    output = COHORT / "design-freeze.json"
    output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"designs": 32, "frozen_files": len(files), "model_calls": 0, "manifest": output.relative_to(ROOT).as_posix()}, indent=2))


if __name__ == "__main__":
    main()
