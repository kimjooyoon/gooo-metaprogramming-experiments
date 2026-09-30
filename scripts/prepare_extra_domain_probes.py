#!/usr/bin/env python3
"""Freeze 128 post-selection probes for the revision-2 composition cohort."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
COHORT = REPO / "cohorts/ir-composition-curriculum-2026-09-30"
REVISION = COHORT / "revision-2"
OUTPUT = COHORT / "extra-domain-probes-128"
REVISION_FREEZE_SHA256 = "9ef3d4bf5c3be68ef4da9c0e7c712eefb313d6bd325446e229e48b8441e33aca"
REVISION_MANIFEST_SHA256 = "d29362bcf9894ac53dc34eb44685cfeaf46b99841574e9473285fac00bfd1dd1"
INT64_MIN, INT64_MAX = -(1 << 63), (1 << 63) - 1

# Values are authored before any Laya/provider selection. There is no random sampler.
PROBES = {
    "cc01_inclusive_band": [-3, 1, 7, 10],
    "cc02_nonzero_disjunction": [-2, 2, INT64_MIN, INT64_MAX],
    "cc03_two_islands": [-6, -3, 3, 6],
    "cc04_outer_cutoffs": [-8, -4, 6, 10],
    "ni05_negative_then_double": [-100, -2, 8, 100],
    "ni06_surcharge_discount": [-2, 2, 99, 102],
    "ni07_zero_special_negative_offset": [-3, 3, 49, 51],
    "ni08_upper_grade_excess": [58, 61, 78, 82],
    "lr09_compound_total": [-6, -4, 9, INT64_MAX],
    "lr10_floor_then_increment": [-2, 2, 100, INT64_MAX],
    "lr11_nonnegative_doubled_score": [-3, 1, (1 << 62) - 1, INT64_MAX],
    "lr12_cap_after_adjustment": [-6, -1, 6, 9],
    "pr13_subtract_tripled_sum": [-3, -1, 4, INT64_MAX],
    "pr14_product_neighbor_factors": [-4, -1, 3, INT64_MIN],
    "pr15_square_minus_successor_sum": [-3, 1, 4, INT64_MAX],
    "pr16_composed_neighbor_product": [-4, -1, 3, INT64_MAX],
    "cp17_nonpositive_inclusive": [-2, 2, -1000, 1000],
    "cp18_exact_release_code": [-7, 5, 10, 700],
    "cp19_range_without_origin": [-2, -1, 1, 5],
    "cp20_strict_symmetric_window": [-7, -3, 3, 7],
    "bl21_saved_range_predicates": [-4, 4, INT64_MIN, INT64_MAX],
    "bl22_reassigned_valid_flag": [-2, 1, 4, 7],
    "bl23_nonzero_bounded_flag": [-3, 2, 3, 6],
    "bl24_selected_nonnegative_codes": [-2, 3, 6, 100],
    "tx25_sign_label": [-2, 2, INT64_MIN, INT64_MAX],
    "tx26_state_label": [-2, 2, 6, INT64_MAX],
    "tx27_lexical_cutoff": [-3, 3, INT64_MIN, INT64_MAX],
    "tx28_reassigned_text_state": [-2, 2, 99, 101],
    "ob29_saturating_increment": [INT64_MAX - 4, INT64_MAX - 5, INT64_MIN, INT64_MIN + 1],
    "ob30_saturating_decrement": [INT64_MIN + 4, INT64_MIN + 5, INT64_MAX, INT64_MAX - 1],
    "ob31_saturating_double": [
        (1 << 62) - 2, (1 << 62) + 1, -(1 << 62) + 1, -(1 << 62) - 2,
    ],
    "ob32_clamped_absolute": [INT64_MIN + 2, INT64_MIN + 3, INT64_MAX - 1, -1],
}

PURPOSES = {
    "conditionals": ["negative_or_low_exterior", "lower_side_interior_or_neighbor", "upper_side_interior_or_neighbor", "positive_or_high_exterior"],
    "nested_if_else": ["far_negative_branch", "negative_or_lower_neighbor", "upper_threshold_neighbor", "far_positive_branch"],
    "let_reassignment": ["lower_boundary_neighbor", "interior_or_nonnegative_neighbor", "upper_boundary_or_large_interior", "large_int64_arithmetic"],
    "expression_precedence": ["negative_neighbor", "small_negative_or_zero_neighbor", "positive_neighbor", "int64_wraparound_probe"],
    "comparison_expressions": ["negative_exterior", "lower_or_zero_neighbor", "upper_or_positive_neighbor", "positive_exterior"],
    "boolean_locals": ["negative_neighbor", "interior_or_lower_side", "upper_or_positive_side", "large_exterior"],
    "text_locals": ["negative_neighbor", "positive_neighbor", "minimum_int64_sign_or_state", "maximum_int64_sign_or_state"],
    "int64_boundaries": ["near_or_beyond_boundary_low", "near_or_beyond_boundary_high", "opposite_sign_or_lower_edge", "opposite_sign_or_upper_edge"],
}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def verify_revision2() -> tuple[dict, dict, dict]:
    freeze_path = REVISION / "design-freeze.json"
    manifest_path = REVISION / "revision-manifest.json"
    if sha256(freeze_path.read_bytes()) != REVISION_FREEZE_SHA256:
        raise ValueError("revision-2 design freeze digest changed")
    if sha256(manifest_path.read_bytes()) != REVISION_MANIFEST_SHA256:
        raise ValueError("revision-2 manifest digest changed")
    freeze, manifest = read_json(freeze_path), read_json(manifest_path)
    for label, base, files in (
        ("revision-2 design", REVISION, freeze.get("files", {})),
        ("revision-2 manifest", REVISION, manifest.get("files", {})),
    ):
        for name, expected in files.items():
            path = base / name
            if not path.is_file() or sha256(path.read_bytes()) != expected:
                raise ValueError(f"{label} frozen file mismatch: {name}")
    catalog = read_json(REVISION / "catalog.json")
    vectors = read_json(REVISION / "oracle/testdata/vectors.json")
    if len(catalog.get("designs", [])) != 32 or len(vectors) != 32:
        raise ValueError("revision-2 must contain exactly 32 frozen designs and vector rows")
    if [row["id"] for row in catalog["designs"]] != [row["id"] for row in vectors]:
        raise ValueError("catalog and frozen vector order/IDs differ")
    return freeze, manifest, {"catalog": catalog, "vectors": vectors}


def region_for(area: str, index: int, value: int) -> str:
    purpose = PURPOSES[area][index]
    if area == "int64_boundaries":
        return purpose
    if "int64" in purpose or abs(value) > 10**12:
        return "large_value:" + purpose
    if value < 0:
        return "negative:" + purpose
    if value == 0:
        return "zero:" + purpose
    return "positive:" + purpose


def build_rows(catalog: dict, vectors: list[dict]) -> list[dict]:
    vector_by_id = {row["id"]: row for row in vectors}
    rows = []
    area_counts: Counter[str] = Counter()
    for design in catalog["designs"]:
        case_id, area = design["id"], design["primary_semantic_area"]
        values = PROBES.get(case_id)
        if values is None or len(values) != 4 or len(set(values)) != 4:
            raise ValueError(f"{case_id} must have four unique, predeclared probes")
        known = {row["input"] for name in ("training", "evaluation")
                 for row in vector_by_id[case_id][name]}
        if any(value in known for value in values):
            raise ValueError(f"{case_id} has a probe duplicated in training or holdout")
        for index, value in enumerate(values):
            if type(value) is not int or not INT64_MIN <= value <= INT64_MAX:
                raise ValueError(f"{case_id} probe is outside signed int64")
            rows.append({
                "probe_id": f"{case_id}/x{index + 1}",
                "design_id": case_id,
                "activity": design["activity"],
                "semantic_area": area,
                "input": value,
                "region_target": region_for(area, index, value),
                "probe_role": PURPOSES[area][index],
            })
            area_counts[area] += 1
    expected_areas = {area: 16 for area in PURPOSES}
    if len(rows) != 128 or dict(area_counts) != expected_areas:
        raise ValueError(f"probe cohort is not balanced 128/8×16: {dict(area_counts)}")
    return rows


def artifacts() -> dict[str, bytes]:
    freeze, revision_manifest, sources = verify_revision2()
    catalog, vectors = sources["catalog"], sources["vectors"]
    rows = build_rows(catalog, vectors)
    bound_files = {
        "design-freeze.json": sha256((REVISION / "design-freeze.json").read_bytes()),
        "revision-manifest.json": sha256((REVISION / "revision-manifest.json").read_bytes()),
        "catalog.json": sha256((REVISION / "catalog.json").read_bytes()),
        "oracle/testdata/vectors.json": sha256((REVISION / "oracle/testdata/vectors.json").read_bytes()),
        "oracle/oracle.go": sha256((REVISION / "oracle/oracle.go").read_bytes()),
        "oracle/go.mod": sha256((REVISION / "oracle/go.mod").read_bytes()),
        "oracle/python_spec.py": sha256((REVISION / "oracle/python_spec.py").read_bytes()),
    }
    rows_bytes = canonical_json({
        "schema": "gooo/ir-composition-extra-domain-probes/v1",
        "classification": "postselection_only; never prompt or selection input",
        "probe_count": len(rows),
        "same_32_design_ids": [row["id"] for row in catalog["designs"]],
        "rows": rows,
    })
    freeze_bytes = canonical_json({
        "schema": "gooo/ir-composition-extra-domain-probe-freeze/v1",
        "cohort": "ir-composition-curriculum-2026-09-30/extra-domain-probes-128",
        "probe_count": 128,
        "design_count": 32,
        "probes_per_design": 4,
        "new_intentions": 0,
        "same_design_ids_as_revision2": True,
        "seed": None,
        "selection_policy": {
            "method": "fixed authored input map in prepare_extra_domain_probes.py; no RNG, no adaptive selection",
            "deduplication": "four inputs unique within each design and disjoint from that design's frozen training and holdout inputs",
            "range": "signed int64",
            "balance": "16 inputs per each of 8 semantic areas",
            "selection_timing": "frozen before Laya/provider capture or candidate choice",
        },
        "reference": {
            "source_path": "revision-2/oracle/oracle.go",
            "source_sha256": bound_files["oracle/oracle.go"],
            "execution": "deferred until the root measurement gate; compile this frozen handwritten reference separately from each captured emitted source",
            "limitation": "the handwritten Go reference is from the same source lineage used for the prior finite oracle; matching it is a correlated-oracle diagnostic, not independent ground truth",
        },
        "revision2_design_freeze_sha256": REVISION_FREEZE_SHA256,
        "revision2_manifest_sha256": REVISION_MANIFEST_SHA256,
        "bound_revision2_files": bound_files,
        "rows_file": "probe-rows.json",
        "rows_sha256": sha256(rows_bytes),
        "expected_values_frozen": False,
        "model_calls": 0,
        "go_executions_during_preparation": 0,
    })
    readme = (
        "# Extra domain probes: 128 inputs\n\n"
        "This freeze adds four unseen signed-int64 inputs for each of the same 32 revision-2 designs. "
        "They are 128 probe treatments, not 128 new intents. Values are fixed in advance; there is no random "
        "sampling seed. Each design's four values are unique and disjoint from its frozen training and holdout values. "
        "The selection is balanced at 16 inputs per semantic area.\n\n"
        "These inputs are post-selection only. Do not copy them into plans, prompts, candidate selection, or feedback. "
        "Expected values are intentionally absent here. After capture, the replay script separately compiles the frozen "
        "revision-2 handwritten Go reference and compares each arm's captured emitted Go source against it. The reference "
        "shares source lineage with the earlier finite oracle, so this is a correlated-oracle diagnostic, not independent "
        "ground truth.\n\n"
        "The probe roles mark designed input regions. They are not dynamic branch-coverage evidence. Report executed probe "
        "count, region-target coverage, unknowns, compile failures, and finite matches separately. Passing these 128 values "
        "does not establish full-domain correctness.\n\n"
        "To verify the unchanged freeze: `python3 scripts/prepare_extra_domain_probes.py --verify`.\n"
    ).encode()
    return {
        "probe-rows.json": rows_bytes,
        "probe-freeze.json": freeze_bytes,
        "README.md": readme,
        "freeze-files.json": canonical_json({
            "schema": "gooo/ir-composition-extra-domain-probe-file-index/v1",
            "files": {"probe-rows.json": sha256(rows_bytes), "probe-freeze.json": sha256(freeze_bytes),
                      "README.md": sha256(readme)},
        }),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", action="store_true", help="verify the existing freeze without writing")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    expected = artifacts()
    output = args.output.resolve()
    if args.verify:
        failures = [name for name, content in expected.items()
                    if not (output / name).is_file() or (output / name).read_bytes() != content]
        extras = sorted(path.name for path in output.iterdir() if path.is_file() and path.name not in expected)
        if failures or extras:
            raise SystemExit(f"freeze verification failed: changed/missing={failures}, extra_files={extras}")
        print(json.dumps({"decision": "PASS", "freeze_sha256": sha256(expected["probe-freeze.json"]),
                          "rows_sha256": sha256(expected["probe-rows.json"]), "probe_count": 128}))
        return
    output.mkdir(parents=True, exist_ok=False)
    for name, content in expected.items():
        (output / name).write_bytes(content)
    print(json.dumps({"decision": "FROZEN", "path": str(output),
                      "freeze_sha256": sha256(expected["probe-freeze.json"]),
                      "rows_sha256": sha256(expected["probe-rows.json"]), "probe_count": 128,
                      "model_calls": 0, "go_executions": 0}))


if __name__ == "__main__":
    main()
