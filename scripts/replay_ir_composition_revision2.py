#!/usr/bin/env python3
"""Replay frozen candidate evidence in a temporary copy, without models."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

REPO = Path(__file__).resolve().parents[1]
COHORT = Path("cohorts/ir-composition-curriculum-2026-09-30")
REVISION = COHORT / "revision-2"
DESIGN_SHA = "9ef3d4bf5c3be68ef4da9c0e7c712eefb313d6bd325446e229e48b8441e33aca"
MANIFEST_SHA = "d29362bcf9894ac53dc34eb44685cfeaf46b99841574e9473285fac00bfd1dd1"


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(base, files):
    for name, digest in files.items():
        path = base / name
        if not path.is_file() or sha(path) != digest:
            raise ValueError("frozen file mismatch: " + name)


def summarize(root, revised):
    base = root / (REVISION if revised else COHORT)
    catalog = load(base / "catalog.json")["designs"]
    vectors = {row["id"]: row for row in load(base / "oracle/testdata/vectors.json")}
    module = root / REVISION / "evaluation" / ("revision2-candidates" if revised else "original-candidates")
    valid = failed = 0
    rows = []
    invalid = {("bl21_saved_range_predicates", "option_a"),
               ("bl21_saved_range_predicates", "option_c"),
               ("bl23_nonzero_bounded_flag", "option_b")}
    for number, design in enumerate(catalog, 1):
        plan = load(base / design["body_fill_plan"])
        candidates = {}
        for option in plan["candidates"]:
            path = module / f"case{number:02d}_{design['id']}_{option['id']}" / "candidate-results.json"
            if not revised and (design["id"], option["id"]) in invalid:
                if path.exists():
                    raise ValueError("invalid original candidate emitted results")
                failed += 1
                candidates[option["id"]] = {"status": "compile_failure", "observed": 0}
                continue
            actual = load(path)
            expected = [{"split": split, "input": item["input"], "expected": item["expected"]}
                        for split in ("training", "evaluation") for item in vectors[design["id"]][split]]
            if [{key: item[key] for key in ("split", "input", "expected")} for item in actual] != expected:
                raise ValueError("fresh candidate rows differ from frozen vectors")
            valid += 1
            scores = {split: {"passed": sum(item["actual"] == item["expected"] for item in actual if item["split"] == split),
                              "total": sum(item["split"] == split for item in actual)}
                      for split in ("training", "evaluation")}
            candidates[option["id"]] = {"status": "compiled_and_executed", **scores}
        if revised:
            gold = design["gold_candidate_id"]
            for identifier, score in candidates.items():
                perfect = score["training"]["passed"] == score["training"]["total"]
                if perfect != (identifier == gold):
                    raise ValueError("fresh gold/distractor discrimination failure: " + design["id"])
        rows.append({"id": design["id"], "candidates": candidates})
    expected_valid = 96 if revised else 93
    if len(rows) != 32 or valid != expected_valid or failed != 96 - expected_valid:
        raise ValueError("candidate denominator mismatch")
    return {"designs": 32, "candidates_planned": 96, "compiled_and_executed": valid,
            "compile_failed": failed, "unknown": 0, "design_results": rows}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--go-bin", type=Path, default=Path(shutil.which("go") or "go"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    revision = REPO / REVISION
    if sha(revision / "design-freeze.json") != DESIGN_SHA or sha(revision / "revision-manifest.json") != MANIFEST_SHA:
        raise ValueError("revision-2 freeze pin mismatch")
    design = load(revision / "design-freeze.json")
    manifest = load(revision / "revision-manifest.json")
    original = load(REPO / COHORT / "design-freeze.json")
    verify(REPO, original["files"])
    verify(revision, design["files"])
    verify(revision, manifest["files"])
    with tempfile.TemporaryDirectory(prefix="gooo-revision2-replay-") as temporary:
        copied = Path(temporary) / "checkout"
        for name in list(original["files"]) + [str(COHORT / "design-freeze.json"), "scripts/prepare_ir_composition_revision2.py"]:
            target = copied / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(REPO / name, target)
        shutil.copytree(revision, copied / REVISION)
        environment = os.environ.copy()
        environment.update({"PYTHONDONTWRITEBYTECODE": "1", "GOTOOLCHAIN": "local",
                            "GOPROXY": "off", "GOSUMDB": "off", "GOWORK": "off",
                            "GOOO_LAYA_URL": "", "GOOO_LAYA_API_KEY": ""})
        result = subprocess.run([sys.executable, str(copied / REVISION / "ci/validate_revision2.py"),
                                 "--replay", "--go-bin", str(args.go_bin.resolve())],
                                cwd=copied, env=environment, capture_output=True, timeout=900, check=False)
        (output / "validator-stdout.raw").write_bytes(result.stdout)
        (output / "validator-stderr.raw").write_bytes(result.stderr)
        if result.returncode:
            raise ValueError("candidate replay failed; see preserved validator output")
        # A replay may write outputs in its temporary tree. Their bytes must
        # still match the precommitted evidence, including all 189 result files.
        verify(copied / REVISION, manifest["files"])
        verify(copied / REVISION, design["files"])
        report = {"schema": "gooo/ir-composition-revision2-independent-replay/v1", "decision": "PASS",
                  "model_calls": 0, "gooo_cli_calls": 0, "design_freeze_sha256": DESIGN_SHA,
                  "revision_manifest_sha256": MANIFEST_SHA, "runner_sha256": sha(Path(__file__)),
                  "original": summarize(copied, False), "revision_2": summarize(copied, True),
                  "same_32_intentions": True, "fresh_discrimination_recomputed": True,
                  "scope": "Finite candidate behavior; source AST completeness is a separate Gooo receipt dimension."}
    verify(revision, manifest["files"])
    verify(REPO, original["files"])
    (output / "independent-replay-report.json").write_text(json.dumps(report, indent=2) + "\n")
    (output / "independent-replay-report.md").write_text(
        "# Revision-2 independent replay\n\nDecision: **PASS**. Model and Gooo CLI calls: **0**.\n\n"
        "Original candidates: 93/96 compiled and executed, 3 compile failures, 0 unknown.\n"
        "Revision-2 candidates: 96/96 compiled and executed; all 32 training suites distinguish both distractors.\n\n"
        "Same 32 intentions in both versions. All 189 fresh candidate-result files match frozen evidence.\n"
        "Execution used temporary copies; published evidence remained unchanged. Finite cases are not full-domain proof.\n")
    print(json.dumps({"decision": "PASS", "output": str(output), "model_calls": 0}))


if __name__ == "__main__":
    main()
