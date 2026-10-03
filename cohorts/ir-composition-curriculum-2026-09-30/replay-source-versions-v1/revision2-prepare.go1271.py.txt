#!/usr/bin/env python3
"""Prepare and evaluate a corrected revision of the frozen 32-design cohort."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ORIGINAL = REPO / "cohorts/ir-composition-curriculum-2026-09-30"
REVISION = ORIGINAL / "revision-2"
HOLE = "__GOOO_BODY_HOLE_choice__"
GO_VERSION = "go1.27.1"
PIN_REVISION = "bb5c1ec2f81cbfb17ac6fb2f7a9e1d7b67168e7f"
PIN_BINARY_SHA256 = "47b9f3bd1b365d18771ba36b0a2b472b139fdb6a08b404697e188478dce38c6e"
SCRIPT_PATH = Path(__file__).resolve()
MODULE = "example.invalid/gooo/ir-composition-revision2"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def digest_path(path: Path) -> str:
    return digest(path.read_bytes())


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def verify_original_freeze() -> dict:
    manifest = read_json(ORIGINAL / "design-freeze.json")
    changed = []
    for relative, expected in manifest.get("files", {}).items():
        path = REPO / relative
        if not path.is_file() or digest_path(path) != expected:
            changed.append(relative)
    if changed:
        raise SystemExit("original 32-design freeze changed: " + ", ".join(changed[:8]))
    return manifest


def expected_spec():
    return load_module(ORIGINAL / "oracle/python_spec.py", "gooo_original_python_spec")


def revised_rows(spec, case_id: str, inputs: list[int]) -> list[dict]:
    return [{"input": int(value), "expected": int(spec.expected(case_id, value))} for value in inputs]


def extract_functions(source: str) -> dict[str, str]:
    lines = source.splitlines()
    functions = {}
    index = 0
    while index < len(lines):
        match = re.match(r"^func (candidate\d+[abc])\(input int64\) int64 \{$", lines[index])
        if not match:
            index += 1
            continue
        block = [lines[index]]
        depth = lines[index].count("{") - lines[index].count("}")
        index += 1
        while index < len(lines) and depth > 0:
            block.append(lines[index])
            depth += lines[index].count("{") - lines[index].count("}")
            index += 1
        if depth != 0:
            raise ValueError("candidate source has unbalanced braces")
        functions[match.group(1)] = "\n".join(block)
    return functions


def fixture_text(activity: str, body: str) -> str:
    encoded = json.dumps(body, ensure_ascii=False)
    return (
        "package bodycodegen\n"
        "namespace bodycodegen\n"
        'entity Integer id "bodycodegen://entity/integer"\n'
        f"activity {activity}(Integer) -> Integer computes {encoded}\n"
    )


def go_candidate_body(body: str, expression: str) -> str:
    if body.count(HOLE) != 1:
        raise ValueError("each revised body must have exactly one expression hole")
    return re.sub(r"\blet\b", "var", body.replace(HOLE, f"({expression})"))


def revision_data() -> tuple[list[dict], dict[str, str]]:
    prep = load_module(REPO / "scripts/prepare_ir_composition_curriculum.py", "gooo_original_composition_prep")
    catalog = read_json(ORIGINAL / "catalog.json")
    catalog_by_id = {row["id"]: row for row in catalog["designs"]}
    design_by_id = {row["id"]: row for row in prep.DESIGNS}
    spec = expected_spec()
    revisions = []
    bodies = {}
    for number, case_id in enumerate(catalog_by_id, start=1):
        old = design_by_id[case_id]
        row = {
            "id": case_id,
            "activity": catalog_by_id[case_id]["activity"],
            "area": old["area"],
            "intent": old["intent"],
            "body": old["body"],
            "expressions": list(old["expressions"]),
            "training_inputs": list(old["training_inputs"]),
            "evaluation_inputs": list(old["evaluation_inputs"]),
            "gold_candidate_id": catalog_by_id[case_id]["candidate_discrimination"]["intended_candidate_id"],
            "changes": ["correct_candidate_rotation_metadata"],
        }
        if case_id == "bl21_saved_range_predicates":
            row["body"] = (
                "let low = input >= -2; let high = input <= 2; let allowed = low && high; "
                f"if allowed && {HOLE} {{ return 1 }} else {{ return 0 }}"
            )
            row["expressions"] = ["true", "input > -2", "input != 0"]
            row["training_inputs"] = [-3, -2, 0, 2, 3]
            row["evaluation_inputs"] = [-100, -1, 1, 100]
            row["changes"].append("use_low_high_and_allowed_in_shared_guard_then_test_predicates_in_hole")
        elif case_id == "bl22_reassigned_valid_flag":
            row["training_inputs"] = [-1, 0, 5, 6, 10]
            row["changes"].append("add_input_10_to_separate_option_b_from_gold")
        elif case_id == "bl23_nonzero_bounded_flag":
            row["body"] = (
                "let nonzero = input != 0; let bounded = input >= -4 && input <= 4; "
                "let eligible = nonzero && bounded; "
                f"if eligible && {HOLE} {{ return 9 }} else {{ return 0 }}"
            )
            row["expressions"] = ["true", "input != -1", "input > 0"]
            row["training_inputs"] = [-5, -4, -1, 0, 4, 5]
            row["evaluation_inputs"] = [-100, -2, 1, 100]
            row["changes"].append("use_nonzero_bounded_and_eligible_in_shared_guard_then_test_predicates_in_hole")

        original_gold = row["gold_candidate_id"]
        rotation = (number - 1) % 3
        option_index = (3 - rotation) % 3
        derived_gold = f"option_{'abc'[option_index]}"
        if derived_gold != original_gold:
            raise SystemExit(f"gold rotation does not match frozen catalog for {case_id}: {derived_gold} != {original_gold}")
        ordered_expressions = row["expressions"][rotation:] + row["expressions"][:rotation]
        row["candidates"] = [
            {"id": f"option_{letter}", "expression": expression}
            for letter, expression in zip("abc", ordered_expressions)
        ]
        row["gold_candidate_id"] = derived_gold
        training = revised_rows(spec, case_id, row["training_inputs"])
        evaluation = revised_rows(spec, case_id, row["evaluation_inputs"])
        if {item["input"] for item in training} & {item["input"] for item in evaluation}:
            raise SystemExit(f"train/evaluation overlap for {case_id}")
        row["test_cases"] = training
        row["holdout_test_cases"] = evaluation
        revisions.append(row)
        bodies[case_id] = row["body"]
    return revisions, bodies


def candidate_test_source(function: str, training: list[dict], evaluation: list[dict]) -> str:
    cases = []
    for split, rows in (("training", training), ("evaluation", evaluation)):
        for item in rows:
            cases.append(
                f'{{split: "{split}", input: {item["input"]}, expected: {item["expected"]}}},'
            )
    literal = "\n".join("\t\t" + item for item in cases)
    return f'''package candidateeval

import (
    "encoding/json"
    "os"
    "testing"
)

func TestCompiledCandidateFiniteCases(t *testing.T) {{
    cases := []struct {{ split string; input, expected int64 }}{{
{literal}
    }}
    results := make([]struct {{
        Split string `json:"split"`
        Input int64 `json:"input"`
        Expected int64 `json:"expected"`
        Actual int64 `json:"actual"`
    }}, 0, len(cases))
    for _, item := range cases {{
        results = append(results, struct {{
            Split string `json:"split"`
            Input int64 `json:"input"`
            Expected int64 `json:"expected"`
            Actual int64 `json:"actual"`
        }}{{Split:item.split, Input:item.input, Expected:item.expected, Actual:{function}(item.input)}})
    }}
    encoded, err := json.Marshal(results)
    if err != nil {{ t.Fatal(err) }}
    if err := os.WriteFile("candidate-results.json", encoded, 0o644); err != nil {{ t.Fatal(err) }}
}}
'''


def write_candidate_module(path: Path, module_name: str, designs: list[dict], candidate_source: str) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "go.mod").write_text(f"module {module_name}\n\ngo 1.27.1\n", encoding="utf-8")
    functions = extract_functions(candidate_source)
    for index, design in enumerate(designs, start=1):
        for option in design["candidates"]:
            function = f"candidate{index:02d}{option['id'][-1]}"
            package_name = f"case{index:02d}_{design['id']}_{option['id']}"
            package = path / package_name
            package.mkdir()
            (package / "candidate.go").write_text(
                "package candidateeval\n\n" + functions[function] + "\n", encoding="utf-8",
            )
            (package / "candidate_test.go").write_text(
                candidate_test_source(function, design["test_cases"], design["holdout_test_cases"]),
                encoding="utf-8",
            )


def load_original_designs() -> list[dict]:
    original = read_json(ORIGINAL / "catalog.json")
    spec = expected_spec()
    plans = []
    for entry in original["designs"]:
        plan = read_json(ORIGINAL / entry["body_fill_plan"])
        vectors = read_json(ORIGINAL / "oracle/testdata/vectors.json")
        vector = next(item for item in vectors if item["id"] == entry["id"])
        plans.append({
            "id": entry["id"],
            "activity": entry["activity"],
            "gold_candidate_id": entry["candidate_discrimination"]["intended_candidate_id"],
            "candidates": plan["candidates"],
            "test_cases": vector["training"],
            "holdout_test_cases": vector["evaluation"],
        })
    return plans


def parse_test_results(stdout: str, module_path: str) -> tuple[dict, dict]:
    statuses = {}
    output = {}
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        package = event.get("Package", "")
        if package != module_path and not package.startswith(module_path + "/"):
            continue
        key = package.rsplit("/", 1)[-1]
        if event.get("Action") == "output":
            output[key] = output.get(key, "") + event.get("Output", "")
        if event.get("Action") in {"pass", "fail"} and "Test" not in event:
            statuses[key] = event["Action"]
    return statuses, output


def make_candidate_observations(revisions: list[dict], results: dict[str, dict]) -> tuple[list[dict], list[dict]]:
    candidate_rows = []
    design_rows = []
    for design in revisions:
        outputs = {option["id"]: results.get(f"{design['id']}/{option['id']}") for option in design["candidates"]}
        statuses = {option_id: (record or {}).get("status", "unknown") for option_id, record in outputs.items()}
        scores = {}
        separated = {}
        gold = design["gold_candidate_id"]
        expected = [row["expected"] for row in design["test_cases"]]
        for option_id, record in outputs.items():
            actuals = [row["actual"] for row in (record or {}).get("rows", []) if row["split"] == "training"]
            scores[option_id] = sum(actual == want for actual, want in zip(actuals, expected)) if len(actuals) == len(expected) else -1
            if option_id != gold and record:
                gold_record = outputs[gold]
                gold_actuals = [row["actual"] for row in (gold_record or {}).get("rows", []) if row["split"] == "training"]
                separated[option_id] = [
                    row["input"] for row, actual, gold_actual in zip(design["test_cases"], actuals, gold_actuals)
                    if actual != gold_actual
                ] if len(actuals) == len(expected) and len(gold_actuals) == len(expected) else []
        if any(status != "compiled_and_executed" for status in statuses.values()):
            accepted = False
        else:
            accepted = scores[gold] == len(design["test_cases"]) and all(separated.values())
        for option in design["candidates"]:
            record = outputs[option["id"]]
            candidate_rows.append({
                "case_id": design["id"],
                "candidate_id": option["id"],
                "compile_status": statuses[option["id"]],
                "training_total": len(design["test_cases"]),
                "evaluation_total": len(design["holdout_test_cases"]),
                "training_passed": scores[option["id"]],
                "training_accuracy_scope": "actual compiled candidate output compared with independent Python int64 expected rows",
                "execution_result_path": (record or {}).get("result_path", ""),
            })
        design_rows.append({
            "id": design["id"],
            "intended_candidate_id": gold,
            "original_candidate_compile_status": statuses,
            "training_pass_counts": scores,
            "gold_vs_distractor_training_inputs": separated,
            "both_distractors_separated": all(separated.values()),
            "all_candidates_compiled_and_executed": all(status == "compiled_and_executed" for status in statuses.values()),
            "feedback_ready": accepted,
        })
    return candidate_rows, design_rows


def suite_sha(cases: list[dict]) -> str:
    encoded = json.dumps(cases, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return "sha256:" + digest(encoded)


def feedback_plans(revisions: list[dict], results: dict[str, dict]) -> list[dict]:
    outputs = []
    for design in revisions:
        candidates = []
        for option in design["candidates"]:
            record = results[f"{design['id']}/{option['id']}"]
            training_rows = [row for row in record["rows"] if row["split"] == "training"]
            failed = sum(row["actual"] != row["expected"] for row in training_rows)
            if option["id"] != design["gold_candidate_id"] and failed:
                candidates.append((failed, option["id"], training_rows))
        if not candidates:
            raise SystemExit(f"no actual compiled failing training candidate available for {design['id']}")
        _, candidate_id, observed = min(candidates, key=lambda item: (item[0], item[1]))
        fixture = REVISION / "fixtures" / f"{design['id']}.gooo"
        feedback = {
            "source_digest": "sha256:" + digest_path(fixture),
            "training_suite_sha256": suite_sha(design["test_cases"]),
            "candidate_id": candidate_id,
            "observations": [
                {"input": row["input"], "expected": row["expected"], "actual": row["actual"], "passed": row["actual"] == row["expected"]}
                for row in observed
            ],
        }
        outputs.append({"design_id": design["id"], "feedback": feedback})
    return outputs


def write_laya_plan_arms(revisions: list[dict], feedback_rows: list[dict]) -> None:
    feedback_by_id = {row["design_id"]: row["feedback"] for row in feedback_rows}
    for index, design in enumerate(revisions, start=1):
        base = {
            "schema": "gooo/body-codegen-ir-search-plan/v1",
            "intent": design["intent"],
            "hole_id": "choice",
            "candidates": design["candidates"],
            "test_cases": design["test_cases"],
            "holdout_test_cases": design["holdout_test_cases"],
            "max_attempts": 3,
            "provider_model": "english",
        }
        basename = f"{index:02d}-{design['id']}.json"
        write_json(REVISION / "plans/laya/legacy-no-feedback" / basename, base)
        write_json(REVISION / "plans/laya/compact-no-feedback" / basename, {**base, "prompt_profile": "compact"})
        write_json(REVISION / "plans/laya/compact-external-feedback" / basename, {
            **base, "prompt_profile": "compact", "external_training_feedback": feedback_by_id[design["id"]],
        })
        write_json(REVISION / "plans/laya/feedback-artifacts" / basename, feedback_by_id[design["id"]])


def reference_test_module(path: Path, vectors: list[dict], source_files: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "go.mod").write_text("module example.invalid/gooo/ir-composition-reference\n\ngo 1.27.1\n", encoding="utf-8")
    (path / "oracle.go").write_bytes((source_files / "oracle.go").read_bytes())
    (path / "oracle_test.go").write_bytes((source_files / "oracle_test.go").read_bytes())
    write_json(path / "testdata/vectors.json", vectors)


def workflow_and_validator_source() -> tuple[str, str]:
    workflow = '''schema: gooo/ir-composition-revision2-ci-plan/v1
python: standard library only
go: "1.27.1" (direct physical binary; GOTOOLCHAIN=local, GOPROXY=off, GOSUMDB=off, GOWORK=off)
network: disabled for the replay; provider endpoints and API keys unset
command: python3 cohorts/ir-composition-curriculum-2026-09-30/revision-2/ci/validate_revision2.py --replay --go-bin "$GO1_27_BIN"
steps:
  - verify revision-manifest.json and design-freeze.json hashes
  - run independent Go reference tests for original and revision-2 finite vectors
  - replay all original candidate packages; expect 93 compiled and 3 source compile failures
  - replay all revision-2 candidate packages; expect 96 compiled and executed
  - compare actual compiled outputs with independent Python int64 expected rows
  - verify gold passes training and both distractors are separated on training only
  - verify 32 legacy, 32 compact, and 32 compact-feedback plans and source bindings
  - report original and revision-2 denominators separately; do not count them as 64 intentions
'''
    validator = r'''#!/usr/bin/env python3
"""Stdlib-only integrity and replay checks for the revision-2 cohort."""
from __future__ import annotations
import argparse, hashlib, importlib.util, json, os, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[2]

def sha(data): return hashlib.sha256(data).hexdigest()
def load(path): return json.loads(path.read_text(encoding="utf-8"))
def suite_sha(cases): return "sha256:" + sha(json.dumps(cases, ensure_ascii=False, separators=(",", ":")).encode())

def verify_files(manifest_path, base, files):
    bad=[]
    for rel, expected in files.items():
        p=base/rel
        if not p.is_file() or sha(p.read_bytes()) != expected: bad.append(rel)
    if bad: raise SystemExit("hash mismatch: " + ", ".join(bad[:8]))

def go_test(go, directory):
    env=os.environ.copy()
    env.update({"GOTOOLCHAIN":"local","GOPROXY":"off","GOSUMDB":"off","GOWORK":"off"})
    env.pop("GOOO_LAYA_URL",None); env.pop("GOOO_LAYA_API_KEY",None)
    env["PATH"]=str(go.parent)+os.pathsep+env.get("PATH","")
    return subprocess.run([str(go),"test","-json","-count=1","./..."],cwd=directory,env=env,capture_output=True,text=True,timeout=180,check=False)

def package_status(output, prefix):
    out={}
    for line in output.splitlines():
        try: event=json.loads(line)
        except json.JSONDecodeError: continue
        package=event.get("Package","")
        if (package == prefix or package.startswith(prefix + "/")) and event.get("Action") in {"pass","fail"} and "Test" not in event:
            out[package.rsplit("/",1)[-1]]=event["Action"]
    return out

def python_expected(spec_path, case_id, value):
    spec=importlib.util.spec_from_file_location("revision2_python_spec", spec_path)
    module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return int(module.expected(case_id, value))

def check_candidate_outputs(module_dir, catalog, cohort_dir, vectors_path, expected_failures, statuses):
    passed=0; failed=0; unknown=0
    vectors={row["id"]:row for row in load(vectors_path)}
    for index, design in enumerate(catalog["designs"],1):
        plan=load(cohort_dir/design["body_fill_plan"])
        case_vectors=vectors[design["id"]]
        training=case_vectors["training"]
        evaluation=case_vectors["evaluation"]
        for option in plan["candidates"]:
            package=f"case{index:02d}_{design['id']}_{option['id']}"
            status=statuses.get(package)
            path=module_dir/package/"candidate-results.json"
            if status=="pass" and path.is_file():
                passed+=1; rows=load(path)
                expected_rows=[{"split":"training","input":row["input"],"expected":row["expected"]} for row in training]
                expected_rows += [{"split":"evaluation","input":row["input"],"expected":row["expected"]} for row in evaluation]
                actual_rows=[{key:row[key] for key in ("split","input","expected")} for row in rows]
                if actual_rows!=expected_rows: raise SystemExit(f"candidate rows differ from frozen cases: {design['id']}/{option['id']}")
                for row in rows:
                    gold=python_expected(ROOT/"oracle/python_spec.py",design["id"],row["input"])
                    if gold!=row["expected"]: raise SystemExit(f"candidate expected value differs from Python oracle: {design['id']} input {row['input']}")
            elif status=="fail" and (design["id"],option["id"]) in expected_failures:
                failed+=1
                if path.exists(): raise SystemExit(f"invalid candidate unexpectedly emitted results: {design['id']}/{option['id']}")
            elif status is None:
                unknown+=1
            else:
                raise SystemExit(f"unexpected candidate replay status: {design['id']}/{option['id']} {status}")
    return {"passed":passed,"failed":failed,"unknown":unknown}

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--replay",action="store_true")
    parser.add_argument("--go-bin",type=Path)
    args=parser.parse_args()
    manifest=load(ROOT/"revision-manifest.json")
    verify_files(ROOT/"revision-manifest.json",ROOT,manifest["files"])
    design=load(ROOT/"design-freeze.json")
    verify_files(ROOT/"design-freeze.json",ROOT,design["files"])
    preparer=REPO/"scripts/prepare_ir_composition_revision2.py"
    if sha(preparer.read_bytes()) != manifest["preparer_sha256"]: raise SystemExit("preparer hash mismatch")
    original_freeze=REPO/"cohorts/ir-composition-curriculum-2026-09-30/design-freeze.json"
    if sha(original_freeze.read_bytes()) != manifest["original_design_freeze_sha256"]: raise SystemExit("original freeze hash mismatch")
    catalog=load(ROOT/"catalog.json"); original=load(REPO/"cohorts/ir-composition-curriculum-2026-09-30/catalog.json")
    ids=[r["id"] for r in catalog["designs"]]
    if len(ids)!=32 or len(set(ids))!=32 or ids != [r["id"] for r in original["designs"]]: raise SystemExit("revision must retain the original 32 intention IDs")
    if len({r["intent"] for r in catalog["designs"]})!=32: raise SystemExit("intention texts must remain unique")
    original_report=load(ROOT/"evaluation/original-candidate-evaluation.json")
    revised_report=load(ROOT/"evaluation/revision2-candidate-evaluation.json")
    if original_report["candidate_denominator"]!=96 or original_report["compiled_candidates"]!=93 or original_report["compile_failed_candidates"]!=3 or original_report["unknown_candidates"]!=0: raise SystemExit("original candidate denominator drift")
    if revised_report["candidate_denominator"]!=96 or revised_report["compiled_candidates"]!=96 or revised_report["compile_failed_candidates"]!=0 or revised_report["unknown_candidates"]!=0: raise SystemExit("revision-2 candidate denominator drift")
    revised_vectors=load(ROOT/"oracle/testdata/vectors.json")
    if revised_report["reference_go_test_exit_code"]!=0 or revised_report["reference_python_case_count"]!=sum(len(r["training"])+len(r["evaluation"]) for r in revised_vectors): raise SystemExit("revision-2 Go/Python reference suite incomplete")
    discrimination=load(ROOT/"evaluation/revision2-candidate-discrimination.json")
    if len(discrimination["designs"])!=32 or not all(r["both_distractors_separated"] and r["gold_passes_all_training"] for r in discrimination["designs"]): raise SystemExit("revision-2 candidate discrimination incomplete")
    feedback_total=0
    vectors={row["id"]:row for row in load(ROOT/"oracle/testdata/vectors.json")}
    for entry in catalog["designs"]:
        base_name=entry["plan_basename"]
        fill=load(ROOT/"plans/body-fill"/base_name)
        vector=vectors[entry["id"]]
        original_suite=vector["training"]
        if fill["test_cases"]!=original_suite: raise SystemExit("body-fill suite differs from frozen vectors")
        for arm in ("legacy-no-feedback","compact-no-feedback","compact-external-feedback"):
            plan=load(ROOT/"plans/laya"/arm/base_name)
            if plan.get("provider_model")!="english" or plan.get("test_cases")!=original_suite: raise SystemExit("plan routing or suite mismatch")
            if plan.get("holdout_test_cases")!=vector["evaluation"]: raise SystemExit("holdout mismatch")
            if arm=="compact-no-feedback" and plan.get("prompt_profile")!="compact": raise SystemExit("compact profile missing")
            if arm=="legacy-no-feedback" and "prompt_profile" in plan: raise SystemExit("legacy prompt profile drift")
            if arm=="compact-external-feedback":
                feedback=plan["external_training_feedback"]
                fixture=(ROOT/entry["fixture"]).read_bytes()
                if feedback["source_digest"]!="sha256:"+sha(fixture): raise SystemExit("feedback source binding mismatch")
                if feedback["training_suite_sha256"]!=suite_sha(original_suite): raise SystemExit("feedback suite binding mismatch")
                expected={row["input"]:row["expected"] for row in original_suite}
                seen=set()
                if feedback["candidate_id"] not in {c["id"] for c in plan["candidates"]}: raise SystemExit("feedback candidate is undeclared")
                for obs in feedback["observations"]:
                    if obs["input"] in seen or obs["input"] not in expected or obs["expected"]!=expected[obs["input"]]: raise SystemExit("feedback observation not uniquely training-bound")
                    if obs["passed"] != (obs["actual"]==obs["expected"]): raise SystemExit("feedback passed flag mismatch")
                    seen.add(obs["input"])
                package_index=ids.index(entry["id"])+1
                actual_path=ROOT/"evaluation/revision2-candidates"/f"case{package_index:02d}_{entry['id']}_{feedback['candidate_id']}"/"candidate-results.json"
                actual_rows=[row for row in load(actual_path) if row["split"]=="training"]
                observed=[{"input":row["input"],"expected":row["expected"],"actual":row["actual"],"passed":row["actual"]==row["expected"]} for row in actual_rows]
                if feedback["observations"]!=observed or {obs["input"] for obs in observed}!=set(expected): raise SystemExit("feedback differs from complete compiled training observations")
                feedback_total+=1
    if feedback_total!=32: raise SystemExit("feedback plan denominator drift")
    if args.replay:
        if not args.go_bin: raise SystemExit("--replay requires --go-bin")
        version=subprocess.run([str(args.go_bin),"version"],capture_output=True,text=True,check=False)
        if version.returncode or "go1.27.1" not in version.stdout: raise SystemExit("replay requires physical Go 1.27.1")
        modules=[
            (ROOT/"evaluation/original-reference","example.invalid/gooo/ir-composition-reference",0),
            (ROOT/"evaluation/revision2-reference","example.invalid/gooo/ir-composition-reference",0),
            (ROOT/"evaluation/original-candidates","example.invalid/gooo/ir-composition-revision2-original",1),
            (ROOT/"evaluation/revision2-candidates","example.invalid/gooo/ir-composition-revision2-revised",0),
        ]
        replay=[]; package_statuses=[]
        for module,prefix,want_exit in modules:
            result=go_test(args.go_bin,module); statuses=package_status(result.stdout,prefix)
            if result.returncode!=want_exit: raise SystemExit(f"unexpected Go exit status in {module.relative_to(ROOT)}: {result.returncode}")
            replay.append({"module":module.relative_to(ROOT).as_posix(),"exit_code":result.returncode,"package_count":len(statuses)})
            package_statuses.append(statuses)
        if replay[0]["package_count"]!=1 or replay[1]["package_count"]!=1: raise SystemExit("reference Go test package missing")
        original_catalog=load(REPO/"cohorts/ir-composition-curriculum-2026-09-30/catalog.json")
        revised_catalog=load(ROOT/"catalog.json")
        invalid={("bl21_saved_range_predicates","option_a"),("bl21_saved_range_predicates","option_c"),("bl23_nonzero_bounded_flag","option_b")}
        old_counts=check_candidate_outputs(ROOT/"evaluation/original-candidates",original_catalog,REPO/"cohorts/ir-composition-curriculum-2026-09-30",REPO/"cohorts/ir-composition-curriculum-2026-09-30/oracle/testdata/vectors.json",invalid,package_statuses[2])
        new_counts=check_candidate_outputs(ROOT/"evaluation/revision2-candidates",revised_catalog,ROOT,ROOT/"oracle/testdata/vectors.json",set(),package_statuses[3])
        if old_counts!={"passed":93,"failed":3,"unknown":0}: raise SystemExit("original candidate replay denominator drift")
        if new_counts!={"passed":96,"failed":0,"unknown":0}: raise SystemExit("revision-2 candidate replay denominator drift")
        if replay[2]["package_count"]!=96 or replay[3]["package_count"]!=96: raise SystemExit("candidate replay package denominator drift")
        print(json.dumps({"validation":"passed","go_version":version.stdout.strip(),"replay":replay,"original_candidate_counts":old_counts,"revision2_candidate_counts":new_counts},indent=2))
    else:
        print(json.dumps({"validation":"passed","designs":32,"original_candidates":96,"revision2_candidates":96,"laya_plans":96,"stdlib_only":True},indent=2))

if __name__=="__main__": main()
'''
    return validator, workflow


def prepare() -> None:
    if REVISION.exists():
        raise SystemExit("revision-2 already exists; preserve it and use a new revision number")
    original_freeze = verify_original_freeze()
    catalog = read_json(ORIGINAL / "catalog.json")
    original_prep = load_module(REPO / "scripts/prepare_ir_composition_curriculum.py", "gooo_original_composition_prep")
    revisions, bodies = revision_data()
    REVISION.mkdir(parents=True)

    # Keep the original evidence inside the new comparison tree without changing its freeze.
    write_json(REVISION / "original-baseline/source-freeze-reference.json", {
        "original_cohort": "cohorts/ir-composition-curriculum-2026-09-30",
        "design_freeze_sha256": digest_path(ORIGINAL / "design-freeze.json"),
        "original_candidate_validity_sha256": digest_path(ORIGINAL / "execution/candidate-oracle-attempt-5/original-candidate-validity.json"),
        "original_candidate_compile_errors_sha256": digest_path(ORIGINAL / "execution/candidate-oracle-attempt-5/original-candidate-compile-errors.json"),
        "denominator": 96,
        "compiled_candidates": 93,
        "compile_failed_candidates": 3,
        "unknown_candidates": 0,
        "note": "The original and revision-2 cohorts are two revisions of the same 32 intent IDs, not 64 distinct intentions.",
    })
    write_json(REVISION / "original-baseline/candidate-validity.json", read_json(ORIGINAL / "execution/candidate-oracle-attempt-5/original-candidate-validity.json"))
    write_json(REVISION / "original-baseline/candidate-compile-errors.json", read_json(ORIGINAL / "execution/candidate-oracle-attempt-5/original-candidate-compile-errors.json"))

    original_vectors = read_json(ORIGINAL / "oracle/testdata/vectors.json")
    old_by_id = {row["id"]: row for row in original_vectors}
    generated_vectors = []
    new_catalog = []
    go_candidate_source = ["package oracle", "", "// Candidate functions are exact Go translations of each revision-2 body shell and finite option."]
    justifications = []

    for index, design in enumerate(revisions, start=1):
        source = fixture_text(design["activity"], design["body"])
        fixture_path = REVISION / "fixtures" / f"{design['id']}.gooo"
        fixture_path.parent.mkdir(parents=True, exist_ok=True)
        fixture_path.write_text(source, encoding="utf-8")
        fill_plan = {
            "schema": "gooo/body-codegen-ir-fill-plan/v1",
            "intent": design["intent"],
            "hole_id": "choice",
            "candidates": design["candidates"],
            "test_cases": design["test_cases"],
        }
        basename = f"{index:02d}-{design['id']}.json"
        write_json(REVISION / "plans/body-fill" / basename, fill_plan)
        design["plan_basename"] = basename
        base = {
            "schema": "gooo/body-codegen-ir-search-plan/v1",
            "intent": design["intent"],
            "hole_id": "choice",
            "candidates": design["candidates"],
            "test_cases": design["test_cases"],
            "holdout_test_cases": design["holdout_test_cases"],
            "max_attempts": 3,
            "provider_model": "english",
        }
        write_json(REVISION / "plans/laya/legacy-no-feedback" / basename, base)
        write_json(REVISION / "plans/laya/compact-no-feedback" / basename, {**base, "prompt_profile": "compact"})
        generated_vectors.append({
            "id": design["id"],
            "activity": design["activity"],
            "gold_candidate_id": design["gold_candidate_id"],
            "training": design["test_cases"],
            "evaluation": design["holdout_test_cases"],
        })
        for option in design["candidates"]:
            function = f"candidate{index:02d}{option['id'][-1]}"
            go_candidate_source.extend(["", f"func {function}(input int64) int64 {{", "\t" + go_candidate_body(design["body"], option["expression"]).replace("; ", ";\n\t"), "}"])
        original_row = next(item for item in catalog["designs"] if item["id"] == design["id"])
        old_candidates = read_json(ORIGINAL / original_row["body_fill_plan"])["candidates"]
        old_body = original_prep.DESIGNS[index-1]["body"]
        old_gold = original_row["candidate_discrimination"]["intended_candidate_id"]
        old_vectors = old_by_id[design["id"]]
        gold_formula_old = f"option_{'abc'[(index - 1) % 3]}"
        changed_ids = []
        if design["id"] == "bl21_saved_range_predicates": changed_ids = ["skeleton", "candidate_set", "training_cases"]
        elif design["id"] == "bl22_reassigned_valid_flag": changed_ids = ["training_cases"]
        elif design["id"] == "bl23_nonzero_bounded_flag": changed_ids = ["skeleton", "candidate_set", "training_cases"]
        justifications.append({
            "id": design["id"],
            "same_intent_id": True,
            "original_intent": original_row["intent"],
            "revised_intent": design["intent"],
            "changes": design["changes"],
            "original_gold_candidate_id_from_catalog": old_gold,
            "gold_candidate_id_in_revision2": design["gold_candidate_id"],
            "legacy_report_formula_candidate_id": gold_formula_old,
            "gold_rotation_corrected": gold_formula_old != design["gold_candidate_id"],
            "body_changed": old_body != design["body"],
            "candidate_expressions_changed": old_candidates != design["candidates"],
            "training_inputs_before": [row["input"] for row in old_vectors["training"]],
            "training_inputs_after": [row["input"] for row in design["test_cases"]],
            "evaluation_inputs_before": [row["input"] for row in old_vectors["evaluation"]],
            "evaluation_inputs_after": [row["input"] for row in design["holdout_test_cases"]],
            "structural_deltas": changed_ids,
        })
        new_catalog.append({
            "id": design["id"],
            "activity": design["activity"],
            "primary_semantic_area": design["area"],
            "intent": design["intent"],
            "gold_candidate_id": design["gold_candidate_id"],
            "fixture": f"fixtures/{design['id']}.gooo",
            "body_fill_plan": f"plans/body-fill/{basename}",
            "plan_basename": basename,
            "original_intent_id": design["id"],
            "candidate_discrimination": "measured from separately compiled candidate bodies on training cases only",
            "source_unit_completeness": "separate pinned Gooo receipt dimension; not inferred from Go candidate evaluation",
        })
        design["original_candidates"] = old_candidates

    vectors_path = REVISION / "oracle/testdata/vectors.json"
    write_json(vectors_path, generated_vectors)
    write_json(REVISION / "catalog.json", {
        "schema": "gooo/ir-composition-curriculum-catalog/v2",
        "cohort": "ir-composition-curriculum-2026-09-30/revision-2",
        "design_count": 32,
        "distinct_intentions": 32,
        "same_intention_ids_as_original": True,
        "original_and_revision2_count_as_64_intentions": False,
        "one_expression_hole_per_design": True,
        "finite_candidates_per_design": 3,
        "provider_model": "english",
        "primary_areas": catalog["primary_areas"],
        "designs": new_catalog,
    })
    (REVISION / "oracle/go.mod").write_text("module example.invalid/gooo/ir-composition-revision2-reference\n\ngo 1.27.1\n", encoding="utf-8")
    (REVISION / "oracle/oracle.go").write_bytes((ORIGINAL / "oracle/oracle.go").read_bytes())
    (REVISION / "oracle/oracle_test.go").write_bytes((ORIGINAL / "oracle/oracle_test.go").read_bytes())
    (REVISION / "oracle/candidates.go").write_text("\n".join(go_candidate_source) + "\n", encoding="utf-8")
    (REVISION / "oracle/python_spec.py").write_bytes((ORIGINAL / "oracle/python_spec.py").read_bytes())
    original_candidates_source = (ORIGINAL / "oracle/candidates.go").read_text(encoding="utf-8")
    original_designs = load_original_designs()
    write_candidate_module(REVISION / "evaluation/original-candidates", f"{MODULE}-original", original_designs, original_candidates_source)
    write_candidate_module(REVISION / "evaluation/revision2-candidates", f"{MODULE}-revised", revisions, "\n".join(go_candidate_source))
    reference_test_module(REVISION / "evaluation/original-reference", original_vectors, ORIGINAL / "oracle")
    reference_test_module(REVISION / "evaluation/revision2-reference", generated_vectors, REVISION / "oracle")

    README = """# IR composition curriculum — revision 2

Revision 2 is a corrected version of the same 32 intent IDs in the parent
cohort. It is not 32 additional intentions. The original 142-file design
freeze and its candidate failures remain intact under the parent directory.

Every design still has one expression hole and three fixed candidate
expressions; this is finite-choice body fill, not free-form code generation.
Training and evaluation inputs are disjoint. The independent Python reference
uses arbitrary-precision arithmetic with explicit signed-int64 wrapping, and
the Go reference oracle is compiled separately. Candidate source bodies are
also compiled and run individually against both finite suites.

The revision corrects gold-candidate rotation labels, adds input 10 to the
reassigned-valid-flag training suite, and restructures the Boolean-local
skeletons so shared locals are used by the common guard in every candidate.
No unused-local blank assignments are inserted. Change reasons and before/after
vectors are in `revision-justifications.json`.

Original and revision-2 candidate validity, executions, and discrimination
have separate denominators. Source-unit completeness is a separate pinned
Gooo receipt dimension. Passing the declared values is not a full-domain
correctness claim. The external feedback arm is generated only from actual
compiled revision-2 candidate outputs, and observations remain advisory rather
than authenticated CI proof or semantic authority. Preparation and Go replay
make zero provider calls.
"""
    (REVISION / "README.md").write_text(README, encoding="utf-8")
    write_json(REVISION / "revision-justifications.json", {
        "schema": "gooo/ir-composition-revision-justification/v1",
        "source_design_freeze_sha256": digest_path(ORIGINAL / "design-freeze.json"),
        "revision_count": 32,
        "same_32_intention_ids": True,
        "intentions_added": 0,
        "global_correction": "Go candidate reporting now consumes explicit gold_candidate_id from each vector, checked against the frozen plan; it does not infer truth from an incorrect rotation formula.",
        "per_design": justifications,
    })
    validator, workflow = workflow_and_validator_source()
    (REVISION / "ci/validate_revision2.py").parent.mkdir(parents=True, exist_ok=True)
    (REVISION / "ci/validate_revision2.py").write_text(validator, encoding="utf-8")
    (REVISION / "ci/workflow-plan.yml").write_text(workflow, encoding="utf-8")
    freeze_revision_design(original_freeze)
    print(json.dumps({"status": "prepared", "designs": 32, "body_fill_plans": 32, "laya_no_feedback_plans": 64, "model_calls": 0, "design_freeze": str((REVISION / 'design-freeze.json').relative_to(REPO))}, indent=2))


def freeze_revision_design(original_freeze: dict) -> None:
    artifacts = sorted(
        (path for path in REVISION.rglob("*") if path.is_file() and path.name != "design-freeze.json"),
        key=lambda path: path.relative_to(REVISION).as_posix(),
    )
    files = {path.relative_to(REVISION).as_posix(): digest_path(path) for path in artifacts}
    write_json(REVISION / "design-freeze.json", {
        "schema": "gooo/ir-composition-revision2-design-freeze/v1",
        "revision": "revision-2",
        "original_design_freeze_sha256": digest_path(ORIGINAL / "design-freeze.json"),
        "original_source_revision": original_freeze["compiler_pin"]["revision"],
        "design_count": 32,
        "same_intention_ids_as_original": True,
        "one_expression_hole_per_design": True,
        "finite_candidates_per_design": 3,
        "plan_counts_before_go_execution": {"body_fill": 32, "legacy_no_feedback": 32, "compact_no_feedback": 32},
        "provider_model": "english",
        "holdout_withheld": True,
        "model_calls": 0,
        "files": files,
        "preparer_sha256": digest_path(SCRIPT_PATH),
    })


def go_environment(go_bin: Path) -> dict[str, str]:
    env = os.environ.copy()
    env.update({"GOTOOLCHAIN": "local", "GOPROXY": "off", "GOSUMDB": "off", "GOWORK": "off"})
    env.pop("GOOO_LAYA_URL", None)
    env.pop("GOOO_LAYA_API_KEY", None)
    env["PATH"] = str(go_bin.parent) + os.pathsep + env.get("PATH", "")
    return env


def verify_revision_design() -> dict:
    manifest = read_json(REVISION / "design-freeze.json")
    changed = []
    for relative, expected in manifest.get("files", {}).items():
        path = REVISION / relative
        if not path.is_file() or digest_path(path) != expected:
            changed.append(relative)
    if changed:
        raise SystemExit("revision-2 design changed after freeze: " + ", ".join(changed[:8]))
    if digest_path(SCRIPT_PATH) != manifest.get("preparer_sha256"):
        raise SystemExit("revision-2 preparer changed after design freeze")
    verify_original_freeze()
    return manifest


def run_module(go_bin: Path, path: Path) -> dict:
    result = subprocess.run(
        [str(go_bin), "test", "-json", "-count=1", "./..."], cwd=path,
        env=go_environment(go_bin), capture_output=True, text=True, timeout=240, check=False,
    )
    module_line = next((line for line in (path / "go.mod").read_text(encoding="utf-8").splitlines() if line.startswith("module ")), "")
    if not module_line:
        raise SystemExit(f"missing module declaration: {path}")
    statuses, messages = parse_test_results(result.stdout, module_line.removeprefix("module ").strip())
    return {
        "exit_code": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "statuses": statuses,
        "messages": messages,
    }


def parse_candidate_module(go_bin: Path, path: Path, designs: list[dict], expected_invalid: set[tuple[str, str]]) -> tuple[dict[str, dict], dict]:
    result = run_module(go_bin, path)
    candidates = {}
    errors = []
    for index, design in enumerate(designs, start=1):
        for option in design["candidates"]:
            package_name = f"case{index:02d}_{design['id']}_{option['id']}"
            package_status = result["statuses"].get(package_name, "unknown")
            output_path = path / package_name / "candidate-results.json"
            if output_path.is_file() and package_status == "pass":
                status = "compiled_and_executed"
            elif package_status == "fail":
                status = "compile_or_execution_failed"
            else:
                status = "unknown"
            row = {"status": status}
            if output_path.is_file():
                row["rows"] = read_json(output_path)
                row["result_path"] = output_path.relative_to(REVISION).as_posix()
            else:
                row["rows"] = []
                row["error"] = result["messages"].get(package_name, "")[-1200:]
            key = f"{design['id']}/{option['id']}"
            candidates[key] = row
            if row["status"] != "compiled_and_executed":
                errors.append({"case_id": design["id"], "candidate_id": option["id"], "package_status": package_status, "expected_original_invalid": (design["id"], option["id"]) in expected_invalid, "error": row.get("error", "")})
    summary = {
        "go_test_exit_code": result["exit_code"],
        "candidate_denominator": sum(len(design["candidates"]) for design in designs),
        "compiled_candidates": sum(item["status"] == "compiled_and_executed" for item in candidates.values()),
        "compile_failed_candidates": sum(item["status"] == "compile_or_execution_failed" for item in candidates.values()),
        "unknown_candidates": sum(item["status"] == "unknown" for item in candidates.values()),
        "actual_input_rows": sum(len(item.get("rows", [])) for item in candidates.values()),
        "candidate_input_rows_planned": sum(
            len(design["test_cases"]) + len(design["holdout_test_cases"])
            for design in designs for _ in design["candidates"]
        ),
        "errors": errors,
        "stdout_sha256": digest(result["stdout"].encode("utf-8")),
        "stderr_sha256": digest(result["stderr"].encode("utf-8")),
    }
    return candidates, summary


def run_evaluation(go_bin: Path) -> None:
    freeze = verify_revision_design()
    version = subprocess.run([str(go_bin), "version"], capture_output=True, text=True, check=False)
    if version.returncode or GO_VERSION not in version.stdout:
        raise SystemExit(f"evaluation requires physical {GO_VERSION}; got {version.stdout.strip()!r}")
    if os.environ.get("GOOO_LAYA_URL", "").strip() or os.environ.get("GOOO_LAYA_API_KEY", "").strip():
        raise SystemExit("revision-2 evaluation is offline; clear provider endpoint and API key")
    catalog = read_json(REVISION / "catalog.json")
    revisions, _ = revision_data()
    for design, row in zip(revisions, catalog["designs"]):
        design["plan_basename"] = row["plan_basename"]
        design["fixture"] = row["fixture"]
    original_designs = load_original_designs()
    original_reference = run_module(go_bin, REVISION / "evaluation/original-reference")
    revised_reference = run_module(go_bin, REVISION / "evaluation/revision2-reference")
    write_json(REVISION / "evaluation/original-reference-result.json", {
        "exit_code": original_reference["exit_code"],
        "stdout_sha256": digest(original_reference["stdout"].encode()),
        "stderr_sha256": digest(original_reference["stderr"].encode()),
        "python_case_count": sum(len(row["training"]) + len(row["evaluation"]) for row in read_json(ORIGINAL / "oracle/testdata/vectors.json")),
    })
    write_json(REVISION / "evaluation/revision2-reference-result.json", {
        "exit_code": revised_reference["exit_code"],
        "stdout_sha256": digest(revised_reference["stdout"].encode()),
        "stderr_sha256": digest(revised_reference["stderr"].encode()),
        "python_case_count": sum(len(row["training"]) + len(row["evaluation"]) for row in read_json(REVISION / "oracle/testdata/vectors.json")),
    })
    if original_reference["exit_code"] or revised_reference["exit_code"]:
        raise SystemExit("independent Go reference oracle must agree with Python vectors before candidate evaluation")

    invalid = {
        ("bl21_saved_range_predicates", "option_a"),
        ("bl21_saved_range_predicates", "option_c"),
        ("bl23_nonzero_bounded_flag", "option_b"),
    }
    original_results, original_summary = parse_candidate_module(
        go_bin, REVISION / "evaluation/original-candidates", original_designs, invalid,
    )
    revised_results, revised_summary = parse_candidate_module(
        go_bin, REVISION / "evaluation/revision2-candidates", revisions, set(),
    )
    write_json(REVISION / "evaluation/original-candidate-evaluation.json", {
        "schema": "gooo/ir-composition-original-candidate-evaluation/v1",
        "denominator_basis": "96 declared original candidates; compilation, execution, and unknown are separate counts",
        "reference_go_test_exit_code": original_reference["exit_code"],
        "reference_python_case_count": sum(len(row["training"]) + len(row["evaluation"]) for row in read_json(ORIGINAL / "oracle/testdata/vectors.json")),
        **original_summary,
        "designs": original_results,
    })
    candidate_rows, revised_discrimination = make_candidate_observations(revisions, revised_results)
    write_json(REVISION / "evaluation/revision2-candidate-evaluation.json", {
        "schema": "gooo/ir-composition-revision2-candidate-evaluation/v1",
        "denominator_basis": "96 declared revision-2 candidates; compilation, execution, and unknown are separate counts",
        "reference_go_test_exit_code": revised_reference["exit_code"],
        "reference_python_case_count": sum(len(row["training"]) + len(row["evaluation"]) for row in read_json(REVISION / "oracle/testdata/vectors.json")),
        **revised_summary,
        "designs": revised_results,
    })
    write_json(REVISION / "evaluation/revision2-candidate-discrimination.json", {
        "schema": "gooo/ir-composition-revision2-candidate-discrimination/v1",
        "training_only": True,
        "source_unit_completeness": "measured separately by pinned Gooo receipts; not part of this Go evaluation",
        "designs": [{
            **row,
            "gold_passes_all_training": row["training_pass_counts"].get(row["intended_candidate_id"]) == len(next(item for item in revisions if item["id"] == row["id"])["test_cases"]),
        } for row in revised_discrimination],
    })

    original_validity = read_json(REVISION / "original-baseline/candidate-validity.json")
    original_discrimination = []
    original_plan_by_id = {row["id"]: row for row in original_designs}
    for design in original_designs:
        records = {option["id"]: original_results[f"{design['id']}/{option['id']}"] for option in design["candidates"]}
        expected = [case["expected"] for case in design["test_cases"]]
        scores = {
            option_id: sum(actual["actual"] == want for actual, want in zip(
                [row for row in record["rows"] if row["split"] == "training"], expected,
            ))
            for option_id, record in records.items()
        }
        statuses = {option_id: record["status"] for option_id, record in records.items()}
        original_discrimination.append({
            "id": design["id"],
            "original_candidate_compile_status": statuses,
            "training_pass_counts_for_compiled_candidates": scores,
            "both_distractors_separated": None if any(status != "compiled_and_executed" for status in statuses.values()) else all(
                any(a["actual"] != b["actual"] for a, b in zip(
                    [row for row in records[option_id]["rows"] if row["split"] == "training"],
                    [row for row in records[design["gold_candidate_id"]]["rows"] if row["split"] == "training"],
                )) for option_id in records if option_id != design["gold_candidate_id"]
            ),
        })
    write_json(REVISION / "evaluation/original-candidate-discrimination.json", {
        "schema": "gooo/ir-composition-original-candidate-discrimination/v1",
        "training_only": True,
        "candidate_denominator": 96,
        "compile_validity_denominator": original_validity["candidate_count"],
        "compiled_candidates": original_summary["compiled_candidates"],
        "compile_failed_candidates": original_summary["compile_failed_candidates"],
        "unknown_candidates": original_summary["unknown_candidates"],
        "designs": original_discrimination,
    })

    feedback_rows = []
    if revised_summary["candidate_denominator"] == 96 and revised_summary["compiled_candidates"] == 96 and revised_summary["compile_failed_candidates"] == 0 and revised_summary["unknown_candidates"] == 0 and all(row["feedback_ready"] for row in revised_discrimination):
        feedback_rows = feedback_plans(revisions, revised_results)
        write_laya_plan_arms(revisions, feedback_rows)
        write_json(REVISION / "evaluation/feedback-artifact-summary.json", {
            "schema": "gooo/ir-composition-revision2-source-bound-feedback/v1",
            "model_calls": 0,
            "evidence": "actual Go 1.27 compiled revision-2 candidate outputs on training cases",
            "authority": "advisory prior observations; not authenticated CI proof or semantic authority",
            "designs": [{
                "id": row["design_id"],
                "candidate_id": row["feedback"]["candidate_id"],
                "source_digest": row["feedback"]["source_digest"],
                "training_suite_sha256": row["feedback"]["training_suite_sha256"],
                "observation_count": len(row["feedback"]["observations"]),
                "failed_observation_count": sum(not obs["passed"] for obs in row["feedback"]["observations"]),
            } for row in feedback_rows],
        })

    candidate_eval = read_json(REVISION / "evaluation/revision2-candidate-evaluation.json")
    original_eval = read_json(REVISION / "evaluation/original-candidate-evaluation.json")
    original_counts = {
        "denominator": original_eval["candidate_denominator"],
        "compiled": original_eval["compiled_candidates"],
        "compile_failed": original_eval["compile_failed_candidates"],
        "unknown": original_eval["unknown_candidates"],
    }
    revision_counts = {
        "denominator": candidate_eval["candidate_denominator"],
        "compiled": candidate_eval["compiled_candidates"],
        "compile_failed": candidate_eval["compile_failed_candidates"],
        "unknown": candidate_eval["unknown_candidates"],
    }
    build_final_manifest(original_freeze_hash=digest_path(ORIGINAL / "design-freeze.json"), original_counts=original_counts, revision_counts=revision_counts, feedback_plan_count=len(feedback_rows) if feedback_rows else 0)
    print(json.dumps({
        "original_candidate_counts": original_counts,
        "revision2_candidate_counts": revision_counts,
        "revision2_discrimination_passed": sum(row["feedback_ready"] for row in revised_discrimination),
        "feedback_plans": len(feedback_rows),
        "model_calls": 0,
        "revision_manifest": str((REVISION / "revision-manifest.json").relative_to(REPO)),
    }, indent=2))
    if original_counts["denominator"] != 96 or original_counts["unknown"] != 0 or revision_counts != {"denominator": 96, "compiled": 96, "compile_failed": 0, "unknown": 0} or not feedback_rows:
        raise SystemExit("revision-2 evaluation incomplete; preserve both denominators in revision-manifest.json")


def build_final_manifest(original_freeze_hash: str, original_counts: dict, revision_counts: dict, feedback_plan_count: int) -> None:
    files = {}
    for path in sorted((item for item in REVISION.rglob("*") if item.is_file() and item.name != "revision-manifest.json"), key=lambda item: item.relative_to(REVISION).as_posix()):
        files[path.relative_to(REVISION).as_posix()] = digest_path(path)
    design_freeze = read_json(REVISION / "design-freeze.json")
    catalog = read_json(REVISION / "catalog.json")
    justifications = read_json(REVISION / "revision-justifications.json")
    write_json(REVISION / "revision-manifest.json", {
        "schema": "gooo/ir-composition-revision2-manifest/v1",
        "revision": "revision-2",
        "original_design_freeze_sha256": original_freeze_hash,
        "revision2_design_freeze_sha256": digest_path(REVISION / "design-freeze.json"),
        "preparer_sha256": digest_path(SCRIPT_PATH),
        "design_count": 32,
        "same_32_intention_ids_as_original": True,
        "new_intentions_added": 0,
        "gold_rotation_corrected_in_plan_metadata": True,
        "structural_repairs": ["bl22 training adds input 10", "bl21 and bl23 shared Boolean guards consume their declared locals for every candidate"],
        "design_deltas": justifications["per_design"],
        "original_candidate_counts": original_counts,
        "revision2_candidate_counts": revision_counts,
        "revision2_reference_go_case_count": read_json(REVISION / "evaluation/revision2-candidate-evaluation.json")["reference_python_case_count"],
        "candidate_discrimination_design_count": len(read_json(REVISION / "evaluation/revision2-candidate-discrimination.json")["designs"]),
        "feedback_plan_count": feedback_plan_count,
        "laya_plan_counts": {
            "legacy-no-feedback": len(list((REVISION / "plans/laya/legacy-no-feedback").glob("*.json"))),
            "compact-no-feedback": len(list((REVISION / "plans/laya/compact-no-feedback").glob("*.json"))),
            "compact-external-feedback": len(list((REVISION / "plans/laya/compact-external-feedback").glob("*.json"))),
        },
        "provider_model_pinned": "english",
        "holdout_withheld": True,
        "source_unit_completeness": "not measured here; separate pinned Gooo receipt dimension",
        "full_domain_claim": False,
        "model_calls": 0,
        "ci_validation": "revision-2/ci/validate_revision2.py uses Python standard library only; --replay invokes the direct physical Go 1.27 toolchain",
        "files": files,
    })


def main() -> None:
    parser = argparse.ArgumentParser()
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--prepare", action="store_true")
    modes.add_argument("--evaluate", action="store_true")
    parser.add_argument("--go-bin", type=Path)
    args = parser.parse_args()
    if args.evaluate:
        if not args.go_bin:
            raise SystemExit("--evaluate requires --go-bin <physical Go 1.27 binary>")
        run_evaluation(args.go_bin)
    else:
        prepare()


if __name__ == "__main__":
    main()
