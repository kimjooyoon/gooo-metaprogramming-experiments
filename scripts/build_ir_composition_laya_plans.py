#!/usr/bin/env python3
"""Bind compiled candidate observations and build the three Laya study arms."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COHORT = ROOT / "cohorts/ir-composition-curriculum-2026-09-30"
SEARCH_SCHEMA = "gooo/body-codegen-ir-search-plan/v1"


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def prefixed_sha(data):
    return "sha256:" + hashlib.sha256(data).hexdigest()


def typed_case_sha(cases):
    # Match Go json.Marshal([]IRBodyFillTestCase{Input, Expected}) field order.
    encoded = json.dumps(cases, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return prefixed_sha(encoded)


def main():
    catalog = load(COHORT / "catalog.json")
    executed = load(COHORT / "oracle/candidate-execution.json")
    if catalog["design_count"] != 32 or len(executed.get("designs", [])) != 32:
        raise SystemExit("catalog and compiled candidate execution must each contain 32 designs")
    by_id = {row["id"]: row for row in executed["designs"]}
    if set(by_id) != {row["id"] for row in catalog["designs"]}:
        raise SystemExit("compiled candidate execution does not match the frozen catalog IDs")

    discrimination_rows = []
    feedback_summary = []
    for entry in catalog["designs"]:
        case_id = entry["id"]
        observed = by_id[case_id]
        gold = observed["gold_candidate"]
        training = observed["training"]
        evaluation = observed["evaluation"]
        if not all(row["passed"] for row in training + evaluation):
            raise SystemExit(f"compiled Go reference disagrees with the Python specification for {case_id}")
        if set(observed["candidate_outputs_by_training_input"]) != {"option_a", "option_b", "option_c"}:
            raise SystemExit(f"compiled candidate set is incomplete for {case_id}")
        if set(observed["candidate_outputs_by_evaluation_input"]) != {"option_a", "option_b", "option_c"}:
            raise SystemExit(f"compiled evaluation candidate set is incomplete for {case_id}")

        expected = [row["expected"] for row in training]
        candidate_scores = {}
        separated = {}
        for option, outputs in observed["candidate_outputs_by_training_input"].items():
            if len(outputs) != len(training):
                raise SystemExit(f"candidate output length mismatch for {case_id}/{option}")
            candidate_scores[option] = sum(actual == want for actual, want in zip(outputs, expected))
            if option != gold:
                gold_outputs = observed["candidate_outputs_by_training_input"][gold]
                separated[option] = [row["input"] for row, actual, gold_actual in zip(training, outputs, gold_outputs) if actual != gold_actual]
                if not separated[option]:
                    raise SystemExit(f"training suite does not distinguish {case_id}/{option} from {gold}")
        if candidate_scores[gold] != len(training):
            raise SystemExit(f"intended option {gold} does not pass all training cases for {case_id}")
        failing_options = [option for option in ("option_a", "option_b", "option_c") if option != gold and candidate_scores[option] < len(training)]
        if len(failing_options) != 2:
            raise SystemExit(f"training cases do not distinguish the intended candidate from both distractors for {case_id}")

        fill = load(COHORT / entry["body_fill_plan"])
        source = (COHORT / entry["fixture"]).read_bytes()
        source_digest = prefixed_sha(source)
        cases = fill["test_cases"]
        suite_digest = typed_case_sha(cases)
        # Select an actual compiled losing option with the fewest training failures.
        feedback_id = min(failing_options, key=lambda option: (candidate_scores[option], option))
        actuals = observed["candidate_outputs_by_training_input"][feedback_id]
        observations = [
            {"input": row["input"], "expected": row["expected"], "actual": actual,
             "passed": actual == row["expected"]}
            for row, actual in zip(cases, actuals)
        ]
        if len(observations) != len(cases) or not any(not row["passed"] for row in observations):
            raise SystemExit(f"feedback candidate is not a compiled failing training observation for {case_id}")
        feedback = {
            "source_digest": source_digest,
            "training_suite_sha256": suite_digest,
            "candidate_id": feedback_id,
            "observations": observations,
        }
        write(COHORT / "plans/laya/feedback-artifacts" / f"{case_id}.json", feedback)

        base = {
            "schema": SEARCH_SCHEMA,
            "intent": fill["intent"],
            "hole_id": fill["hole_id"],
            "candidates": fill["candidates"],
            "test_cases": cases,
            "holdout_test_cases": evaluation,
            "max_attempts": 3,
            "provider_model": "english",
        }
        arms = {
            "legacy-no-feedback": dict(base),
            "compact-no-feedback": {**base, "prompt_profile": "compact"},
            "compact-external-feedback": {
                **base, "prompt_profile": "compact", "external_training_feedback": feedback,
            },
        }
        for arm, plan in arms.items():
            write(COHORT / "plans/laya" / arm / f"{case_id}.json", plan)

        discrimination_rows.append({
            "id": case_id,
            "intended_candidate": gold,
            "training_total": len(training),
            "candidate_train_pass_counts": candidate_scores,
            "gold_vs_distractor_training_inputs": separated,
            "evaluation_inputs_not_used_for_candidate_discrimination": [row["input"] for row in evaluation],
            "source_unit_completeness": "reported separately from candidate discrimination after pinned Gooo codegen",
        })
        feedback_summary.append({
            "id": case_id,
            "candidate_id": feedback_id,
            "source_digest": source_digest,
            "training_suite_sha256": suite_digest,
            "observation_count": len(observations),
            "failed_observation_count": sum(not row["passed"] for row in observations),
            "evidence": "compiled Go candidate execution cross-checked against independent Python specification",
            "authority": "advisory prior observation; not authenticated CI proof or semantic authority",
        })

    write(COHORT / "oracle/candidate-discrimination.json", {
        "schema": "gooo/ir-composition-candidate-discrimination/v1",
        "training_only": True,
        "source_unit_completeness_report": "pinned Gooo execution report source_ast_coverage dimension",
        "designs": discrimination_rows,
    })
    write(COHORT / "oracle/feedback-artifact-summary.json", {
        "schema": "gooo/ir-composition-source-bound-feedback-summary/v1",
        "model_calls": 0,
        "designs": feedback_summary,
    })
    print(json.dumps({"designs": 32, "laya_arms_per_design": 3, "plans": 96, "model_calls": 0, "status": "built"}, indent=2))


if __name__ == "__main__":
    main()
