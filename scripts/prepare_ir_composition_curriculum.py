#!/usr/bin/env python3
"""Prepare the frozen 32-design, finite-candidate IR composition cohort."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COHORT = ROOT / "cohorts/ir-composition-curriculum-2026-09-30"
HOLE = "__GOOO_BODY_HOLE_choice__"
SCHEMA = "gooo/body-codegen-ir-fill-plan/v1"
SEARCH_SCHEMA = "gooo/body-codegen-ir-search-plan/v1"
GO_MODULE = "example.invalid/gooo/ir-composition-oracle"


def d(case_id, area, intent, body, expressions, train, evaluation):
    return {
        "id": case_id,
        "area": area,
        "intent": intent,
        "body": body,
        "expressions": expressions,
        "training_inputs": train,
        "evaluation_inputs": evaluation,
    }


DESIGNS = [
    d("cc01_inclusive_band", "conditionals", "Return 2 for inputs from 3 through 8 inclusive, and -1 otherwise.",
      f"if {HOLE} {{ return 2 }} else {{ return -1 }}",
      ["input >= 3 && input <= 8", "input > 3 && input <= 8", "input >= 3 && input < 8"],
      [-1, 2, 3, 8, 9], [-10, 4, 12]),
    d("cc02_nonzero_disjunction", "conditionals", "Return 1 for every nonzero integer, including both negative and positive values; return 0 only for zero.",
      f"if {HOLE} {{ return 1 }} else {{ return 0 }}",
      ["input < 0 || input > 0", "input < 0 && input > 0", "input >= 0"],
      [-1, 0, 1], [-7, 12]),
    d("cc03_two_islands", "conditionals", "Return 7 only for the two isolated inputs -4 and 4; return 0 for the gap and the exterior.",
      f"if {HOLE} {{ return 7 }} else {{ return 0 }}",
      ["input == -4 || input == 4", "input >= -4 && input <= 4", "input < -4 || input > 4"],
      [-5, -4, 0, 4, 5], [-100, 2]),
    d("cc04_outer_cutoffs", "conditionals", "Return 9 when the input is at most -6 or at least 8; return 0 in the middle interval.",
      f"if {HOLE} {{ return 9 }} else {{ return 0 }}",
      ["input <= -6 || input >= 8", "input <= -8 || input >= 6", "input <= -6 && input >= 8"],
      [-7, -6, -5, 7, 8, 9], [-100, 0, 100]),

    d("ni05_negative_then_double", "nested_if_else", "Return -1 for a negative input, double inputs from 0 through 9, and return 20 from 10 onward.",
      f"if input < 0 {{ return -1 }} else {{ if input < 10 {{ return {HOLE} }} else {{ return 20 }} }}",
      ["input * 2", "input + 2", "input * 3"], [-1, 0, 1, 9, 10], [-5, 5, 11]),
    d("ni06_surcharge_discount", "nested_if_else", "Reject negative quantities as 0, add 10 through quantity 100, then discount quantities above 100 by 10.",
      f"if input < 0 {{ return 0 }} else {{ if input > 100 {{ return input - 10 }} else {{ return {HOLE} }} }}",
      ["input + 10", "input + 9", "input + 11"], [-1, 0, 1, 100, 101], [-5, 50, 111]),
    d("ni07_zero_special_negative_offset", "nested_if_else", "Map zero to 5, positive inputs to 3, and negative inputs to the input plus 2.",
      f"if input >= 0 {{ if input == 0 {{ return 5 }} else {{ return 3 }} }} else {{ return {HOLE} }}",
      ["input + 2", "input - 2", "input + 1"], [-2, -1, 0, 1], [-9, 2, 50]),
    d("ni08_upper_grade_excess", "nested_if_else", "Return -1 below 60, 0 from 60 through 79, and the excess above 80 from 80 onward.",
      f"if input < 60 {{ return -1 }} else {{ if input < 80 {{ return 0 }} else {{ return {HOLE} }} }}",
      ["input - 80", "input - 79", "input - 81"], [59, 60, 79, 80, 81], [-1, 70, 100]),

    d("lr09_compound_total", "let_reassignment", "Add five to an amount, double the updated total, and return that reassigned total.",
      f"let total = input + 5; total = total * 2; return {HOLE}",
      ["total", "input * 2 + 5", "input + 10"], [-5, 0, 1, 4], [-10, 8, 10]),
    d("lr10_floor_then_increment", "let_reassignment", "Replace negative input with zero; otherwise increment it once, then return the updated local.",
      f"let adjusted = input; if adjusted < 0 {{ adjusted = 0 }} else {{ adjusted = adjusted + 1 }}; return {HOLE}",
      ["adjusted", "input", "adjusted + 1"], [-1, 0, 1, 5], [-10, 4, 20]),
    d("lr11_nonnegative_doubled_score", "let_reassignment", "Double the input; add one when the doubled score is nonnegative and reset negative scores to zero.",
      f"let score = input * 2; let nonnegative = score >= 0; if nonnegative {{ score = score + 1 }} else {{ score = 0 }}; return {HOLE}",
      ["score", "input * 2 + 1", "input"], [-2, -1, 0, 2], [-10, 3, 10]),
    d("lr12_cap_after_adjustment", "let_reassignment", "Add three, cap the adjusted amount at ten, subtract one from that capped local, and return it.",
      f"let amount = input; amount = amount + 3; if amount > 10 {{ amount = 10 }} else {{ amount = amount }}; amount = amount - 1; return {HOLE}",
      ["amount", "input + 2", "amount + 1"], [-5, 0, 7, 8], [-20, 10, 100]),

    d("pr13_subtract_tripled_sum", "expression_precedence", "Subtract three times the sum of the input and two from one hundred.",
      f"return 100 - {HOLE} * 3",
      ["input + 2", "input + 3", "input - 2"], [-2, 0, 3, 5], [-10, 7, 20]),
    d("pr14_product_neighbor_factors", "expression_precedence", "Multiply the input plus its successor by the input minus two.",
      f"return (input + {HOLE}) * (input - 2)",
      ["input + 1", "input - 1", "input"], [-3, 0, 2, 5], [-10, 4, 10]),
    d("pr15_square_minus_successor_sum", "expression_precedence", "Subtract the input plus four from the square of the input.",
      f"return input * input - {HOLE}",
      ["input + 4", "input + 2", "input - 4"], [-2, 0, 3, 6], [-10, 5, 20]),
    d("pr16_composed_neighbor_product", "expression_precedence", "Multiply the saved successor by the input plus two, then subtract the original input.",
      f"let next = input + 1; return next * {HOLE} - input",
      ["input + 2", "input + 1", "input + 3"], [-3, 0, 2, 5], [-10, 4, 12]),

    d("cp17_nonpositive_inclusive", "comparison_expressions", "Return 1 for every input at or below zero, including zero, and 0 for positive inputs.",
      f"if {HOLE} {{ return 1 }} else {{ return 0 }}",
      ["input <= 0", "input < 0", "input == 0"], [-1, 0, 1], [-9, 5, 10]),
    d("cp18_exact_release_code", "comparison_expressions", "Return 1 only for release code 7; neighboring codes are not release code 7.",
      f"if {HOLE} {{ return 1 }} else {{ return 0 }}",
      ["input == 7", "input >= 7", "input == 8"], [6, 7, 8], [0, 9, 100]),
    d("cp19_range_without_origin", "comparison_expressions", "Return 1 inside the inclusive range -3 through 3 except at zero; return 0 elsewhere.",
      f"if {HOLE} {{ return 1 }} else {{ return 0 }}",
      ["input >= -3 && input <= 3 && input != 0", "input >= -3 && input <= 3", "input < -3 || input > 3"],
      [-4, -3, 0, 3, 4], [-100, 2, 100]),
    d("cp20_strict_symmetric_window", "comparison_expressions", "Return 4 only strictly between -5 and 5; both endpoints and everything outside return -4.",
      f"if {HOLE} {{ return 4 }} else {{ return -4 }}",
      ["input > -5 && input < 5", "input >= -5 && input <= 5", "input > -5 && input <= 5"],
      [-6, -5, -4, 4, 5, 6], [-100, 0, 100]),

    d("bl21_saved_range_predicates", "boolean_locals", "Save lower and upper range predicates, combine them, and return 1 only for values from -2 through 2.",
      f"let low = input >= -2; let high = input <= 2; let allowed = low && high; if {HOLE} {{ return 1 }} else {{ return 0 }}",
      ["allowed", "low || high", "low && input == 0"], [-3, -2, 0, 2, 3], [-10, 1, 10]),
    d("bl22_reassigned_valid_flag", "boolean_locals", "Build a nonnegative flag, refine it in place to require an input no greater than five, then return 5 only when valid.",
      f"let valid = input >= 0; valid = valid && input <= 5; if {HOLE} {{ return 5 }} else {{ return -5 }}",
      ["valid", "valid || input == 10", "input <= 5"], [-1, 0, 5, 6], [-10, 2, 100]),
    d("bl23_nonzero_bounded_flag", "boolean_locals", "Return 9 only when a saved nonzero predicate and a saved inclusive -4 through 4 range predicate are both true.",
      f"let nonzero = input != 0; let bounded = input >= -4 && input <= 4; if {HOLE} {{ return 9 }} else {{ return 0 }}",
      ["nonzero && bounded", "nonzero || bounded", "nonzero"], [-5, -4, 0, 4, 5], [-100, 3, 100]),
    d("bl24_selected_nonnegative_codes", "boolean_locals", "Select code 2, plus code 4 only when nonnegative; all negative codes and other nonnegative codes return zero.",
      f"let selected = input == 2; if input < 0 {{ selected = false }} else {{ selected = selected || input == 4 }}; if {HOLE} {{ return 6 }} else {{ return 0 }}",
      ["selected", "selected && input != 4", "input == 2"], [-1, 0, 2, 4, 5], [-100, 1, 10]),

    d("tx25_sign_label", "text_locals", "Label the input as negative or nonnegative; return -1 for the negative label and 1 for the other label.",
      f"let label = \"neutral\"; if input < 0 {{ label = \"negative\" }} else {{ label = \"nonnegative\" }}; if label == {HOLE} {{ return -1 }} else {{ return 1 }}",
      ["\"negative\"", "\"nonnegative\"", "\"neutral\""], [-1, 0, 1], [-20, 20]),
    d("tx26_state_label", "text_locals", "Classify zero as closed, positive input as open, and negative input as error; return one only for open.",
      f"let status = \"pending\"; if input == 0 {{ status = \"closed\" }} else {{ if input > 0 {{ status = \"open\" }} else {{ status = \"error\" }} }}; if status == {HOLE} {{ return 1 }} else {{ return 0 }}",
      ["\"open\"", "\"closed\"", "\"error\""], [-1, 0, 1], [-20, 7]),
    d("tx27_lexical_cutoff", "text_locals", "Assign amber to negative inputs and zinc otherwise; return 1 exactly when the label sorts before gold.",
      f"let label = \"plum\"; if input < 0 {{ label = \"amber\" }} else {{ label = \"zinc\" }}; if label < {HOLE} {{ return 1 }} else {{ return 0 }}",
      ["\"gold\"", "\"amber\"", "\"zoo\""], [-1, 0, 1], [-2, 2]),
    d("tx28_reassigned_text_state", "text_locals", "Start with the idle-pending text state, replace it with ready for positive input, and return 2 only for ready.",
      f"let status = \"idle\" + \"-pending\"; if input > 0 {{ status = \"ready\" }} else {{ status = status }}; if status == {HOLE} {{ return 2 }} else {{ return -2 }}",
      ["\"ready\"", "\"idle-pending\"", "\"done\""], [-1, 0, 1], [-10, 100]),

    d("ob29_saturating_increment", "int64_boundaries", "Increment every int64 input except the maximum, which remains at the maximum instead of wrapping.",
      f"if input == 9223372036854775807 {{ return input }} else {{ return {HOLE} }}",
      ["input + 1", "input", "input - 1"], [0, 1, (1 << 63) - 3, (1 << 63) - 2],
      [(1 << 63) - 1, (1 << 63) - 4, -1]),
    d("ob30_saturating_decrement", "int64_boundaries", "Decrement every int64 input except the minimum, which remains at the minimum instead of wrapping.",
      f"if input == (-9223372036854775807 - 1) {{ return input }} else {{ return {HOLE} }}",
      ["input - 1", "input", "input + 1"], [-(1 << 63) + 2, -(1 << 63) + 1, 0, 1],
      [-(1 << 63), -(1 << 63) + 3, 10]),
    d("ob31_saturating_double", "int64_boundaries", "Double values while the product fits; values beyond either half-range saturate at the corresponding int64 endpoint.",
      f"if input > 4611686018427387903 {{ return 9223372036854775807 }} else {{ if input < (-4611686018427387903 - 1) {{ return (-9223372036854775807 - 1) }} else {{ return {HOLE} }} }}",
      ["input * 2", "input * 3", "input + 2"], [-2, -1, 0, 1, 2],
      [(1 << 63) - 1, (1 << 62) - 1, 1 << 62, -(1 << 63), -(1 << 62), -(1 << 62) - 1]),
    d("ob32_clamped_absolute", "int64_boundaries", "Return the nonnegative magnitude; map the unrepresentable absolute value of the minimum int64 to the maximum int64.",
      f"let magnitude = input; if input < 0 {{ magnitude = 0 - magnitude }} else {{ magnitude = input }}; if input == (-9223372036854775807 - 1) {{ return 9223372036854775807 }} else {{ return {HOLE} }}",
      ["magnitude", "input", "0 - magnitude"], [-3, 0, 5, 7],
      [-(1 << 63), -(1 << 63) + 1, (1 << 63) - 1]),
]


GO_REFERENCES = {
    "cc01_inclusive_band": "if x >= 3 && x <= 8 { return 2 }; return -1",
    "cc02_nonzero_disjunction": "if x < 0 || x > 0 { return 1 }; return 0",
    "cc03_two_islands": "if x == -4 || x == 4 { return 7 }; return 0",
    "cc04_outer_cutoffs": "if x <= -6 || x >= 8 { return 9 }; return 0",
    "ni05_negative_then_double": "if x < 0 { return -1 }; if x < 10 { return x * 2 }; return 20",
    "ni06_surcharge_discount": "if x < 0 { return 0 }; if x > 100 { return x - 10 }; return x + 10",
    "ni07_zero_special_negative_offset": "if x >= 0 { if x == 0 { return 5 }; return 3 }; return x + 2",
    "ni08_upper_grade_excess": "if x < 60 { return -1 }; if x < 80 { return 0 }; return x - 80",
    "lr09_compound_total": "return (x + 5) * 2",
    "lr10_floor_then_increment": "if x < 0 { return 0 }; return x + 1",
    "lr11_nonnegative_doubled_score": "score := x * 2; if score >= 0 { return score + 1 }; return 0",
    "lr12_cap_after_adjustment": "amount := x + 3; if amount > 10 { amount = 10 }; return amount - 1",
    "pr13_subtract_tripled_sum": "return 100 - (x + 2) * 3",
    "pr14_product_neighbor_factors": "return (x + x + 1) * (x - 2)",
    "pr15_square_minus_successor_sum": "return x*x - (x + 4)",
    "pr16_composed_neighbor_product": "next := x + 1; return next * (x + 2) - x",
    "cp17_nonpositive_inclusive": "if x <= 0 { return 1 }; return 0",
    "cp18_exact_release_code": "if x == 7 { return 1 }; return 0",
    "cp19_range_without_origin": "if x >= -3 && x <= 3 && x != 0 { return 1 }; return 0",
    "cp20_strict_symmetric_window": "if x > -5 && x < 5 { return 4 }; return -4",
    "bl21_saved_range_predicates": "low := x >= -2; high := x <= 2; allowed := low && high; if allowed { return 1 }; return 0",
    "bl22_reassigned_valid_flag": "valid := x >= 0; valid = valid && x <= 5; if valid { return 5 }; return -5",
    "bl23_nonzero_bounded_flag": "nonzero := x != 0; bounded := x >= -4 && x <= 4; if nonzero && bounded { return 9 }; return 0",
    "bl24_selected_nonnegative_codes": "selected := x == 2; if x < 0 { selected = false } else { selected = selected || x == 4 }; if selected { return 6 }; return 0",
    "tx25_sign_label": "label := \"nonnegative\"; if x < 0 { label = \"negative\" }; if label == \"negative\" { return -1 }; return 1",
    "tx26_state_label": "status := \"error\"; if x == 0 { status = \"closed\" } else if x > 0 { status = \"open\" }; if status == \"open\" { return 1 }; return 0",
    "tx27_lexical_cutoff": "label := \"zinc\"; if x < 0 { label = \"amber\" }; if label < \"gold\" { return 1 }; return 0",
    "tx28_reassigned_text_state": "status := \"idle-pending\"; if x > 0 { status = \"ready\" }; if status == \"ready\" { return 2 }; return -2",
    "ob29_saturating_increment": "if x == 9223372036854775807 { return x }; return x + 1",
    "ob30_saturating_decrement": "if x == (-9223372036854775807 - 1) { return x }; return x - 1",
    "ob31_saturating_double": "if x > 4611686018427387903 { return 9223372036854775807 }; if x < (-4611686018427387903 - 1) { return (-9223372036854775807 - 1) }; return x * 2",
    "ob32_clamped_absolute": "if x == (-9223372036854775807 - 1) { return 9223372036854775807 }; if x < 0 { return 0 - x }; return x",
}


def load_python_spec():
    module_path = COHORT / "oracle/python_spec.py"
    spec = importlib.util.spec_from_file_location("composition_python_spec", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module.expected


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def candidate_options(design):
    # Rotate the intended expression among A/B/C to avoid position cues.
    number = DESIGNS.index(design) + 1
    rotation = (number - 1) % 3
    expressions = design["expressions"]
    ordered = expressions[rotation:] + expressions[:rotation]
    return [
        {"id": f"option_{letter}", "expression": expression}
        for letter, expression in zip("abc", ordered)
    ]


def gold_option_id(design):
    # The first catalog expression is the intended one before the rotation.
    number = DESIGNS.index(design) + 1
    rotation = (number - 1) % 3
    index = (3 - rotation) % 3
    return f"option_{'abc'[index]}"


def case_rows(expected, inputs):
    return [{"input": int(value), "expected": int(expected(value))} for value in inputs]


def typed_suite_sha(cases):
    encoded = json.dumps(cases, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def body_fixture(activity, body):
    return (
        "package bodycodegen\n"
        "namespace bodycodegen\n"
        "entity Integer id \"bodycodegen://entity/integer\"\n"
        f"activity {activity}(Integer) -> Integer computes {json.dumps(body, ensure_ascii=False)}\n"
    )


def emitted_candidate_body(body, expression):
    if body.count(HOLE) != 1:
        raise ValueError(f"expected exactly one body hole, found {body.count(HOLE)}")
    return re.sub(r"\blet\b", "var", body.replace(HOLE, f"({expression})"))


def go_ident(value):
    return re.sub(r"[^A-Za-z0-9_]", "_", value)


def generate_inputs(expected):
    vectors = []
    catalog = []
    counts = {}
    for design in DESIGNS:
        counts[design["area"]] = counts.get(design["area"], 0) + 1
    go_lines = ["package oracle", "", "// Reference functions are independently written Go int64 specifications."]
    candidate_lines = ["package oracle", "", "// Candidate functions compile each frozen Gooo body shell with a finite option."]

    for index, design in enumerate(DESIGNS, start=1):
        case_id = design["id"]
        activity = f"C{index:02d}"
        fixture_path = COHORT / "fixtures" / f"{index:02d}-{case_id}.gooo"
        fill_path = COHORT / "plans/body-fill" / f"{index:02d}-{case_id}.json"
        training = case_rows(lambda x: expected(case_id, x), design["training_inputs"])
        evaluation = case_rows(lambda x: expected(case_id, x), design["evaluation_inputs"])
        options = candidate_options(design)
        gold = gold_option_id(design)
        fixture_path.write_text(body_fixture(activity, design["body"]), encoding="utf-8")
        write_json(fill_path, {
            "schema": SCHEMA,
            "intent": design["intent"],
            "hole_id": "choice",
            "candidates": options,
            "test_cases": training,
        })
        search_base = {
            "schema": SEARCH_SCHEMA,
            "intent": design["intent"],
            "hole_id": "choice",
            "candidates": options,
            "test_cases": training,
            "holdout_test_cases": evaluation,
            "max_attempts": 3,
            "provider_model": "english",
        }
        write_json(COHORT / "plans/laya/legacy-no-feedback" / f"{index:02d}-{case_id}.json", search_base)
        write_json(COHORT / "plans/laya/compact-no-feedback" / f"{index:02d}-{case_id}.json", {
            **search_base, "prompt_profile": "compact",
        })
        vectors.append({"id": case_id, "activity": activity, "training": training, "evaluation": evaluation})
        catalog.append({
            "id": case_id,
            "activity": activity,
            "primary_semantic_area": design["area"],
            "intent": design["intent"],
            "fixture": fixture_path.relative_to(COHORT).as_posix(),
            "body_fill_plan": fill_path.relative_to(COHORT).as_posix(),
            "candidate_discrimination": {
                "source": "compiled Go candidate executions, evaluated on training inputs only",
                "intended_candidate_id": gold,
                "training_inputs": [row["input"] for row in training],
                "evaluation_inputs_withheld_from_prompt": [row["input"] for row in evaluation],
                "pairwise_case_report": "oracle/candidate-discrimination.json",
            },
            "source_unit_completeness": {
                "reported_separately_from_candidate_discrimination": True,
                "source_and_generated_ast_unit_counts": "populated from the pinned Gooo receipt after offline codegen",
                "scope": "finite structural source coverage only; not semantic correctness or full-domain behavior",
            },
        })
        reference = GO_REFERENCES[case_id]
        go_lines.extend([
            "",
            f"func ref{index:02d}(x int64) int64 {{",
            "\t" + reference + ";",
            "}",
        ])
        for option in options:
            option_suffix = option["id"][-1]
            function = f"candidate{index:02d}{option_suffix}"
            candidate_lines.extend([
                "",
                f"func {function}(input int64) int64 {{",
                "\t" + emitted_candidate_body(design["body"], option["expression"]).replace("; ", ";\n\t"),
                "}",
            ])

    write_json(COHORT / "oracle/testdata/vectors.json", vectors)
    write_json(COHORT / "catalog.json", {
        "schema": "gooo/ir-composition-curriculum-catalog/v1",
        "cohort": "ir-composition-curriculum-2026-09-30",
        "design_count": len(DESIGNS),
        "distinct_intentions": len({design["intent"] for design in DESIGNS}),
        "one_expression_hole_per_design": True,
        "candidate_set_is_finite": True,
        "primary_areas": counts,
        "designs": catalog,
    })
    oracle_dir = COHORT / "oracle"
    (oracle_dir / "go.mod").write_text(f"module {GO_MODULE}\n\ngo 1.27\n", encoding="utf-8")
    (oracle_dir / "oracle.go").write_text("\n".join(go_lines) + "\n", encoding="utf-8")
    (oracle_dir / "candidates.go").write_text("\n".join(candidate_lines) + "\n", encoding="utf-8")

    oracle_test = '''package oracle

import (
    "encoding/json"
    "os"
    "testing"
)

type caseVector struct {
    ID string `json:"id"`
    Training []struct { Input int64 `json:"input"`; Expected int64 `json:"expected"` } `json:"training"`
    Evaluation []struct { Input int64 `json:"input"`; Expected int64 `json:"expected"` } `json:"evaluation"`
}

func TestIndependentGoReferenceOraclesMatchPythonInt64Vectors(t *testing.T) {
    data, err := os.ReadFile("testdata/vectors.json")
    if err != nil { t.Fatal(err) }
    var vectors []caseVector
    if err := json.Unmarshal(data, &vectors); err != nil { t.Fatal(err) }
    refs := map[string]func(int64) int64{
'''
    for index, design in enumerate(DESIGNS, start=1):
        oracle_test += f'        "{design["id"]}": ref{index:02d},\n'
    oracle_test += '''    }
    if len(vectors) != 32 || len(refs) != len(vectors) { t.Fatalf("vectors=%d references=%d, want 32", len(vectors), len(refs)) }
    for _, vector := range vectors {
        reference, ok := refs[vector.ID]
        if !ok { t.Fatalf("missing reference oracle for %s", vector.ID) }
        for _, group := range [][]struct { Input int64 `json:"input"`; Expected int64 `json:"expected"` }{vector.Training, vector.Evaluation} {
            for _, row := range group {
                if got := reference(row.Input); got != row.Expected { t.Errorf("%s(%d)=%d, Python expected %d", vector.ID, row.Input, got, row.Expected) }
            }
        }
    }
}
'''
    (oracle_dir / "oracle_test.go").write_text(oracle_test, encoding="utf-8")

    report_dir = oracle_dir / "cmd/oracle-report"
    report_dir.mkdir(parents=True, exist_ok=True)
    candidate_map = []
    for index, design in enumerate(DESIGNS, start=1):
        candidate_map.append(f'"{design["id"]}": {{"option_a": candidate{index:02d}a, "option_b": candidate{index:02d}b, "option_c": candidate{index:02d}c}},')
    report_source = '''package main

import (
    "encoding/json"
    "fmt"
    "os"
    oracle "example.invalid/gooo/ir-composition-oracle"
)

type row struct { Input int64 `json:"input"`; Expected int64 `json:"expected"` }
type vector struct { ID string `json:"id"`; Training []row `json:"training"`; Evaluation []row `json:"evaluation"` }
type designResult struct { ID string `json:"id"`; Training []rowResult `json:"training"`; Evaluation []rowResult `json:"evaluation"`; CandidateTrainingOutputs map[string][]int64 `json:"candidate_outputs_by_training_input"`; CandidateEvaluationOutputs map[string][]int64 `json:"candidate_outputs_by_evaluation_input"`; GoldCandidate string `json:"gold_candidate"`; DiscriminatingInputs map[string][]int64 `json:"gold_discriminating_inputs"` }
type rowResult struct { Input int64 `json:"input"`; Expected int64 `json:"expected"`; Actual int64 `json:"actual"`; Passed bool `json:"passed"` }
type candidateFunc func(int64) int64
var candidates = map[string]map[string]candidateFunc{
'''
    report_source += "\n".join(candidate_map)
    report_source += '''
}
var references = map[string]func(int64) int64{
'''
    for index, design in enumerate(DESIGNS, start=1):
        report_source += f'"{design["id"]}": oracleRef{index:02d},\n'
    report_source += '''}

// These bridge functions expose the independent package references without sharing candidate bodies.
'''
    for index in range(1, len(DESIGNS) + 1):
        report_source += f'func oracleRef{index:02d}(input int64) int64 {{ return oracle.Reference("{DESIGNS[index-1]["id"]}", input) }}\n'
    report_source += '''
func main() {
    data, err := os.ReadFile("../testdata/vectors.json")
    if err != nil { panic(err) }
    var vectors []vector
    if err := json.Unmarshal(data, &vectors); err != nil { panic(err) }
    results := make([]designResult, 0, len(vectors))
    for index, item := range vectors {
        options := candidates[item.ID]
        optionIDs := []string{"option_a", "option_b", "option_c"}
        ordered := make([]rowResult, 0, len(item.Training))
        eval := make([]rowResult, 0, len(item.Evaluation))
        outputs := map[string][]int64{}
        evalOutputs := map[string][]int64{}
        discrimination := map[string][]int64{}
        gold := optionIDs[index%3]
        for _, optionID := range optionIDs {
            outputs[optionID] = make([]int64, 0, len(item.Training))
            evalOutputs[optionID] = make([]int64, 0, len(item.Evaluation))
            discrimination[optionID] = []int64{}
        }
        for _, test := range item.Training {
            actual := references[item.ID](test.Input)
            ordered = append(ordered, rowResult{Input:test.Input, Expected:test.Expected, Actual:actual, Passed:actual==test.Expected})
            goldValue := options[gold](test.Input)
            for _, optionID := range optionIDs {
                value := options[optionID](test.Input)
                outputs[optionID] = append(outputs[optionID], value)
                if optionID != gold && value != goldValue { discrimination[optionID] = append(discrimination[optionID], test.Input) }
            }
        }
        for _, test := range item.Evaluation {
            actual := references[item.ID](test.Input)
            eval = append(eval, rowResult{Input:test.Input, Expected:test.Expected, Actual:actual, Passed:actual==test.Expected})
            for _, optionID := range optionIDs { evalOutputs[optionID] = append(evalOutputs[optionID], options[optionID](test.Input)) }
        }
        results = append(results, designResult{ID:item.ID, Training:ordered, Evaluation:eval, CandidateTrainingOutputs:outputs, CandidateEvaluationOutputs:evalOutputs, GoldCandidate:gold, DiscriminatingInputs:discrimination})
    }
    output := struct { Schema string `json:"schema"`; ModelCalls int `json:"model_calls"`; Designs []designResult `json:"designs"` }{Schema:"gooo/ir-composition-go-oracle-execution/v1", ModelCalls:0, Designs:results}
    encoder := json.NewEncoder(os.Stdout); encoder.SetIndent("", "  ")
    if err := encoder.Encode(output); err != nil { fmt.Fprintln(os.Stderr, err); os.Exit(1) }
}
'''
    # Expose references to the report subcommand without conflating them with generated candidates.
    export = "\nfunc Reference(id string, input int64) int64 { switch id {\n"
    for index, design in enumerate(DESIGNS, start=1):
        export += f'case "{design["id"]}": return ref{index:02d}(input)\n'
    export += 'default: panic("unknown reference id: " + id)\n} }\n'
    (oracle_dir / "oracle.go").write_text("\n".join(go_lines) + export + "\n", encoding="utf-8")
    (oracle_dir / "cmd/oracle-report/main.go").write_text(report_source, encoding="utf-8")

    README = """# IR composition curriculum — 2026-09-30

This is a structural, offline baseline for 32 distinct Gooo Integer-to-Integer
body-fill intentions. Each design has exactly one expression hole and a closed
set of three candidate expressions. It does **not** measure free-form code
generation. The set is finite and the measured train/evaluation values are not
a proof over the int64 domain.

The 32 primary areas are balanced four apiece: conditionals, nested if/else,
let/reassignment, expression composition and precedence, comparison
expressions, Boolean locals, Text locals, and int64 boundary/overflow handling.
Each case is a new intention; the prior four body-fill intents and repeated
calls from previous cohorts are not counted.

`oracle/python_spec.py` is the Python-integer reference specification with
explicit signed-int64 wrapping. `oracle/oracle.go` is a separate compiled Go
reference implementation. `oracle/candidates.go` compiles each finite option
inside the frozen source-body shell so training discrimination is measured
from actual Go execution. Training and evaluation inputs are disjoint. Search
plans place evaluation inputs only in the holdout field; the model prompt is
limited to training cases. Candidate-discriminating training cases and
source-unit completeness are reported as separate measures.

The Laya plan matrix has three packaging arms: legacy without external
feedback, compact without external feedback, and compact with source-bound
compiled-Go training observations. Prompt packaging is independent of whether
feedback is present. External observations are advisory inputs, not authenticated
CI proof or semantic authority. No provider is called by preparation, the Go
oracle, or the structural Gooo baseline.

The pinned Gooo binary run is intentionally a later phase. It must verify the
frozen manifest before any offline codegen. Even if every finite case passes,
the result is only evidence for the declared finite suite and structural source
coverage—not a full-domain correctness claim.
"""
    (COHORT / "README.md").write_text(README, encoding="utf-8")
    write_json(COHORT / "oracle/testdata/vectors.json", vectors)
    write_json(COHORT / "catalog.json", {
        "schema": "gooo/ir-composition-curriculum-catalog/v1",
        "cohort": "ir-composition-curriculum-2026-09-30",
        "design_count": len(DESIGNS),
        "distinct_intentions": len({design["intent"] for design in DESIGNS}),
        "one_expression_hole_per_design": True,
        "candidate_set_is_finite": True,
        "primary_areas": counts,
        "designs": catalog,
    })


def main():
    if len(DESIGNS) != 32 or len({item["id"] for item in DESIGNS}) != 32:
        raise SystemExit("the cohort must contain 32 distinct design IDs")
    if len({item["intent"] for item in DESIGNS}) != 32:
        raise SystemExit("the 32 intentions must be distinct")
    counts = {}
    for design in DESIGNS:
        counts[design["area"]] = counts.get(design["area"], 0) + 1
        if len(design["expressions"]) != 3:
            raise SystemExit(f"{design['id']} must have exactly three candidates")
        if set(design["training_inputs"]) & set(design["evaluation_inputs"]):
            raise SystemExit(f"{design['id']} leaks an evaluation input into training")
        if design["body"].count(HOLE) != 1:
            raise SystemExit(f"{design['id']} must contain exactly one expression hole")
        if design["id"] not in GO_REFERENCES:
            raise SystemExit(f"{design['id']} has no independent Go oracle")
    if len(counts) != 8 or set(counts.values()) != {4}:
        raise SystemExit(f"semantic areas are not balanced four apiece: {counts}")
    expected = load_python_spec()
    generate_inputs(expected)
    print(json.dumps({"designs": 32, "areas": counts, "status": "prepared"}, indent=2))


if __name__ == "__main__":
    main()
