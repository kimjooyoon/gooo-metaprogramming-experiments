#!/usr/bin/env python3
"""Export each matrix candidate as a small reviewable experiment record."""

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("report", type=Path)
    parser.add_argument("--out", type=Path, default=ROOT / "experiments")
    args = parser.parse_args()

    plan = json.loads((ROOT / "plan-v1.json").read_text())
    report = json.loads(args.report.read_text())
    intents = {item["id"]: item for item in plan["intents"]}
    routes = {item["id"]: item for item in plan["routes"]}
    decisions = {item["intent_id"]: item for item in report["decisions"]}
    args.out.mkdir(parents=True, exist_ok=True)

    for number, candidate in enumerate(report["candidates"], start=1):
        intent = intents[candidate["intent_id"]]
        route = routes[candidate["route_id"]]
        decision = decisions[intent["id"]]
        result = {
            "schema": "gooo/metaprogramming-experiment/v1",
            "experiment_number": number,
            "experiment_id": candidate["experiment_id"],
            "intent": {
                "id": intent["id"],
                "task": intent["task"],
                "requirements": intent["requirements"],
                "reachable_rule_count": candidate["clauses_total"],
            },
            "lowering_route": {
                "id": route["id"],
                "description": route["description"],
                "style": route["style"],
                "constructs": route["constructs"],
            },
            "result": candidate,
            "selection": {
                "laya_top1": decision["top1_route"] == route["id"],
                "seeded_probability_sample": decision["sampled_route"] == route["id"],
                "deterministic_fallback": plan["fallback"] == route["id"],
                "laya_revision": decision["receipt"].get("model_revision"),
            },
        }
        name = f"{number:03d}-{intent['id']}--{route['id']}.json"
        (args.out / name).write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")

    count = len(list(args.out.glob("*.json")))
    if count != 100:
        raise SystemExit(f"exported {count} experiment records; expected 100")


if __name__ == "__main__":
    main()
