#!/usr/bin/env python3
"""Hash the exact cohort, plans, and oracle artifacts before pinned codegen."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COHORT = ROOT / "cohorts/ir-composition-curriculum-2026-09-30"
PIN = {
    "revision": "bb5c1ec2f81cbfb17ac6fb2f7a9e1d7b67168e7f",
    "binary_path": "/tmp/gooo-pinned-context-final-20260930",
    "binary_sha256": "47b9f3bd1b365d18771ba36b0a2b472b139fdb6a08b404697e188478dce38c6e",
    "go_version": "go1.27.0",
    "goos": "darwin",
    "goarch": "arm64",
    "cgo_enabled": True,
    "trimpath": True,
    "vcs_modified": False,
}
SCRIPTS = [
    "scripts/prepare_ir_composition_curriculum.py",
    "scripts/build_ir_composition_laya_plans.py",
    "scripts/freeze_ir_composition_design.py",
    "scripts/freeze_ir_composition_curriculum.py",
    "scripts/run_ir_composition_curriculum.py",
]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    catalog = json.loads((COHORT / "catalog.json").read_text(encoding="utf-8"))
    go_result = json.loads((COHORT / "oracle/candidate-execution.json").read_text(encoding="utf-8"))
    discrimination = json.loads((COHORT / "oracle/candidate-discrimination.json").read_text(encoding="utf-8"))
    feedback_summary = json.loads((COHORT / "oracle/feedback-artifact-summary.json").read_text(encoding="utf-8"))
    if catalog.get("design_count") != 32 or len(catalog.get("designs", [])) != 32:
        raise SystemExit("freeze requires exactly 32 catalogued designs")
    if len(go_result.get("designs", [])) != 32 or go_result.get("model_calls") != 0:
        raise SystemExit("freeze requires the complete compiled Go candidate execution and zero model calls")
    if len(discrimination.get("designs", [])) != 32 or len(feedback_summary.get("designs", [])) != 32:
        raise SystemExit("freeze requires discrimination and source-bound feedback artifacts for all designs")
    laya_arms = {
        "legacy-no-feedback": len(list((COHORT / "plans/laya/legacy-no-feedback").glob("*.json"))),
        "compact-no-feedback": len(list((COHORT / "plans/laya/compact-no-feedback").glob("*.json"))),
        "compact-external-feedback": len(list((COHORT / "plans/laya/compact-external-feedback").glob("*.json"))),
    }
    if laya_arms != {"legacy-no-feedback": 32, "compact-no-feedback": 32, "compact-external-feedback": 32}:
        raise SystemExit(f"freeze requires 32 plans in each of the three arms: {laya_arms}")
    bad_feedback = [item["id"] for item in feedback_summary["designs"] if item["failed_observation_count"] < 1]
    if bad_feedback:
        raise SystemExit("feedback artifacts must contain a compiled training failure: " + ", ".join(bad_feedback))

    artifacts = []
    for path in COHORT.rglob("*"):
        if not path.is_file() or path.name == "frozen-manifest.json" or "execution" in path.relative_to(COHORT).parts:
            continue
        artifacts.append(path)
    artifacts.extend(ROOT / script for script in SCRIPTS)
    artifacts = sorted(set(artifacts), key=lambda path: path.relative_to(ROOT).as_posix())
    files = {path.relative_to(ROOT).as_posix(): digest(path) for path in artifacts}
    manifest = {
        "schema": "gooo/ir-composition-curriculum-freeze/v1",
        "cohort": "ir-composition-curriculum-2026-09-30",
        "design_count": 32,
        "distinct_intentions": 32,
        "one_expression_hole_per_design": True,
        "finite_candidates_per_design": 3,
        "balanced_primary_areas": catalog.get("primary_areas", {
            "conditionals": 4,
            "nested_if_else": 4,
            "let_reassignment": 4,
            "expression_precedence": 4,
            "comparison_expressions": 4,
            "boolean_locals": 4,
            "text_locals": 4,
            "int64_boundaries": 4,
        }),
        "study_arms": laya_arms,
        "provider_model_pinned_in_all_laya_plans": "english",
        "training_and_evaluation_disjoint": True,
        "external_feedback_authority": "advisory only; compiled Go candidate observations, not authenticated CI proof or semantic authority",
        "go_oracle": {
            "python_spec_sha256": files.get(
                "cohorts/ir-composition-curriculum-2026-09-30/oracle/python_spec.py"
            ),
            "compiled_go_candidate_execution_sha256": digest(COHORT / "oracle/candidate-execution.json"),
            "designs_crosschecked": 32,
            "training_and_evaluation_cases_crosschecked": sum(len(row["training"]) + len(row["evaluation"]) for row in go_result["designs"]),
        },
        "compiler_pin": PIN,
        "model_calls_during_preparation_and_oracles": 0,
        "files": files,
    }
    output = COHORT / "frozen-manifest.json"
    output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"frozen_files": len(files), "designs": 32, "laya_plans": 96, "manifest": str(output.relative_to(ROOT))}, indent=2))


if __name__ == "__main__":
    main()
