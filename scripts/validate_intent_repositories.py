#!/usr/bin/env python3
"""Validate that the public intent repository index partitions all 100 cases."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORPUS_SHA = "777017fa22638221636897731b64ef9c5f0599c6"


def main():
    catalog = json.loads((ROOT / "catalog/intent-repositories.json").read_text(encoding="utf-8"))
    plan = json.loads((ROOT / "plan-v1.json").read_text(encoding="utf-8"))
    if catalog.get("schema") != "gooo/metaprogramming-public-intent-slices/v1":
        raise SystemExit("unexpected public intent slice catalog schema")
    if catalog.get("upstream_commit") != CORPUS_SHA or catalog.get("experiment_count") != 100:
        raise SystemExit("catalog is not pinned to the 100-case source corpus")

    intents = {item["id"] for item in plan["intents"]}
    repos = catalog.get("repositories", [])
    if len(repos) != 10 or {item.get("intent_id") for item in repos} != intents:
        raise SystemExit("catalog must contain exactly one repository for each of ten intents")
    urls = set()
    listed_cases = 0
    for item in repos:
        intent_id = item["intent_id"]
        slug = intent_id.replace("_", "-")
        expected_url = f"https://github.com/kimjooyoon/gooo-codegen-exp-{slug}"
        if item.get("url") != expected_url or item["url"] in urls:
            raise SystemExit(f"invalid or duplicate public repository URL for {intent_id}")
        urls.add(item["url"])
        if item.get("case_count") != 10:
            raise SystemExit(f"{intent_id} does not declare ten cases")
        if not re.fullmatch(r"https://github.com/kimjooyoon/gooo-codegen-exp-[a-z0-9-]+/actions/runs/[0-9]+", item.get("ci_run_url", "")):
            raise SystemExit(f"invalid successful CI receipt link for {intent_id}")
        source_records = list((ROOT / "experiments").glob(f"*-{intent_id}--*.json"))
        if len(source_records) != item["case_count"]:
            raise SystemExit(f"{intent_id}: catalog count does not match source corpus")
        listed_cases += item["case_count"]
    if listed_cases != catalog["experiment_count"]:
        raise SystemExit("catalog case total does not equal the corpus experiment count")
    print(f"PASS: {len(repos)} public repositories partition {listed_cases} source experiment records")


if __name__ == "__main__":
    main()
