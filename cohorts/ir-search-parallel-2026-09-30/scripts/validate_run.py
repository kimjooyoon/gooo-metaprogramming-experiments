#!/usr/bin/env python3
"""Validate saved parallel-run raw hashes and invocation/event counts without running Gooo or Laya."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
CONDITIONS = ("sequential", "simultaneous")
INTENTS = ("clamp", "absolute")
EXPECTED_BINARY_SHA = "f9f33b86c2114c1adeba01319fddb7d48f666e739aef768bbb5a580adfb7cda9"


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(data: bytes):
    return hashlib.sha256(data).hexdigest()


def require(condition: bool, message: str):
    if not condition:
        raise RuntimeError(message)


class PrivacyScanError(RuntimeError):
    pass


class JSONMap(dict):
    """JSON object retaining duplicate key/value pairs for fail-closed audits."""
    def __init__(self, pairs):
        super().__init__()
        self.raw_pairs = pairs
        for key, value in pairs:
            self[key] = value


def canonical_json(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def holdout_case_pairs(oracle):
    return {
        (canonical_json(input_value), canonical_json(expected_value))
        for input_value, expected_value in zip(oracle["holdout"]["inputs"], oracle["holdout"]["expected"])
    }


def scan_selection_body(raw_body: bytes, forbidden_pairs):
    """Decode JSON recursively, including JSON documents encoded inside any string value."""
    try:
        root = json.loads(raw_body, object_pairs_hook=JSONMap)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise PrivacyScanError(f"selection request is not valid JSON: {exc}") from exc

    decoder = json.JSONDecoder(object_pairs_hook=JSONMap)
    violations = []
    visited_strings = set()
    visited_containers = set()
    container_keepalive = []
    nodes = 0

    def visit(value, path, depth=0):
        nonlocal nodes
        nodes += 1
        if nodes > 100_000 or depth > 64:
            raise PrivacyScanError("selection request exceeds recursive privacy-scan bounds")
        if isinstance(value, dict):
            identity = id(value)
            if identity in visited_containers:
                return
            visited_containers.add(identity)
            container_keepalive.append(value)
            pairs = getattr(value, "raw_pairs", list(value.items()))
            normalized = {}
            for key, child in pairs:
                normalized.setdefault(str(key).lower(), []).append(child)
            for key, _ in pairs:
                if "holdout" in str(key).lower():
                    violations.append(f"{path}.{key}: held-out field name")
            if "input" in normalized and "expected" in normalized:
                for input_value in normalized["input"]:
                    for expected_value in normalized["expected"]:
                        pair = (canonical_json(input_value), canonical_json(expected_value))
                        if pair in forbidden_pairs:
                            violations.append(f"{path}: exact held-out input/expected case-shaped object")
            for key, child in pairs:
                visit(child, f"{path}.{key}", depth + 1)
        elif isinstance(value, list):
            identity = id(value)
            if identity in visited_containers:
                return
            visited_containers.add(identity)
            container_keepalive.append(value)
            for index, child in enumerate(value):
                visit(child, f"{path}[{index}]", depth + 1)
        elif isinstance(value, str):
            if value in visited_strings:
                return
            visited_strings.add(value)
            stripped = value.strip()
            if not stripped:
                return
            # First handle a complete JSON-encoded value (including doubly encoded state.request).
            try:
                decoded = json.loads(stripped)
            except (json.JSONDecodeError, TypeError):
                decoded = None
            full_structured = isinstance(decoded, (dict, list))
            if isinstance(decoded, (dict, list, str)) and decoded != value:
                visit(decoded, f"{path}<embedded-json>", depth + 1)
            # Also inspect JSON objects/arrays embedded in surrounding prose or option text.
            # `raw_decode` only accepts a complete value from the supplied offset.
            offset = 0
            while not full_structured and offset < len(value):
                object_index = min((index for index in (value.find("{", offset), value.find("[", offset)) if index >= 0), default=-1)
                if object_index < 0:
                    break
                try:
                    embedded, end = decoder.raw_decode(value, object_index)
                except json.JSONDecodeError:
                    offset = object_index + 1
                    continue
                if isinstance(embedded, (dict, list)):
                    visit(embedded, f"{path}<embedded-json@{object_index}>", depth + 1)
                offset = max(end, object_index + 1)

    visit(root, "$request")
    if violations:
        unique = list(dict.fromkeys(violations))
        raise PrivacyScanError("; ".join(unique))
    return {"scanned_nodes": nodes, "heldout_fields_or_pairs_found": 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    args = parser.parse_args()
    run_dir = args.run_dir.resolve()
    metadata = read_json(run_dir / "run-metadata.json")
    manifest_path = run_dir / "input-manifest.json"
    manifest = read_json(manifest_path)
    require(sha256(manifest_path.read_bytes()) == metadata["cohort_manifest_sha256"], "run manifest hash mismatch")
    require(metadata["binary_sha256"] == EXPECTED_BINARY_SHA == manifest["binary"]["sha256"], "binary pin mismatch")
    require(metadata["source_revision"] == manifest["binary"]["source_revision"], "source revision mismatch")
    require(metadata["status"] == "complete", f"run is not complete: {metadata['status']}")

    invocation_rows = []
    choice_count = 0
    choice_count_scanned = 0
    event_count = 0
    for condition in CONDITIONS:
        cond_dir = run_dir / "conditions" / condition
        cond = read_json(cond_dir / "condition.json")
        require(cond.get("invocation_count") == 2 and cond.get("all_invocations_exit_zero") is True,
                f"{condition}: condition did not finish with two successful invocations")
        owned = read_json(cond_dir / "laya" / "owned-process.json")
        require(owned.get("owned_by_runner") is True and owned.get("host") == "127.0.0.1",
                f"{condition}: server ownership/bind record invalid")
        for health_name in ("health-before.json", "health-after.json"):
            health = read_json(cond_dir / "laya" / health_name)
            require(health.get("device") == "cpu" and health.get("loaded") == ["english"],
                    f"{condition}: invalid {health_name}")
            require(health.get("revisions", {}).get("english") == manifest["runtime"]["revision"],
                    f"{condition}: model revision mismatch in {health_name}")
        samples_path = cond_dir / "resource-samples.jsonl"
        samples = [json.loads(line) for line in samples_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        labels = [sample.get("label") for sample in samples]
        require("condition_before" in labels and "condition_after" in labels,
                f"{condition}: missing endpoint resource samples")

        for intent in INTENTS:
            invocation_dir = cond_dir / "invocations" / intent
            record = read_json(invocation_dir / "invocation.json")
            require(record.get("condition") == condition and record.get("intent_id") == intent,
                    f"wrong invocation identity in {invocation_dir}")
            require(record.get("exit_code") == 0 and not record.get("harness_timeout") and not record.get("runner_error"),
                    f"invocation failed or timed out: {condition}/{intent}")
            for raw_name, digest_field in (("stdout.raw", "stdout_sha256"), ("stderr.raw", "stderr_sha256")):
                require(sha256((invocation_dir / raw_name).read_bytes()) == record[digest_field],
                        f"{condition}/{intent}: {raw_name} hash mismatch")
            source_inputs = manifest["source_material"]["inputs"][intent]
            oracle = read_json(HERE / source_inputs["finite_oracle"]["path"])
            forbidden_pairs = holdout_case_pairs(oracle)
            for raw_name, source_key in (("fixture.gooo.fixture", "fixture"), ("plan.json", "search_plan")):
                expected = source_inputs[source_key]["sha256"]
                require(sha256((invocation_dir / raw_name).read_bytes()) == expected,
                        f"{condition}/{intent}: copied {raw_name} does not match source pin")
            payload = json.loads((invocation_dir / "stdout.raw").read_bytes())
            body_search = payload.get("report", {}).get("body_search") or payload.get("body_search")
            require(body_search is not None, f"{condition}/{intent}: missing body_search stdout")
            attempts = body_search.get("attempts", [])
            model_attempts = [a for a in attempts if (a.get("decision") or {}).get("mode") == "laya"]
            events_path = invocation_dir / "proxy" / "events.jsonl"
            events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines() if line.strip()]
            event_count += len(events)
            choice_events = [e for e in events if e.get("kind") == "laya_choice"]
            choice_count += len(choice_events)
            require(len(choice_events) == len(model_attempts) == record.get("proxy_choice_events"),
                    f"{condition}/{intent}: model-choice count mismatch")
            require([a.get("candidate_id") for a in model_attempts] == [e.get("selected_candidate_id") for e in choice_events],
                    f"{condition}/{intent}: selected-candidate trace mismatch")
            for event in events:
                require(event.get("invocation_id") == f"{condition}/{intent}",
                        f"{condition}/{intent}: proxy event attributed to another invocation")
                for file_key, hash_key in (("request_file", "request_sha256"), ("response_file", "response_sha256")):
                    raw_path = invocation_dir / event[file_key]
                    require(raw_path.is_file() and sha256(raw_path.read_bytes()) == event[hash_key],
                            f"{condition}/{intent}: raw proxy body hash mismatch: {raw_path}")
                if event.get("kind") == "laya_choice":
                    require(event.get("method") == "POST" and event.get("path") == "/v1/systemone",
                            f"{condition}/{intent}: choice event is not the captured selection POST")
                    request_bytes = (invocation_dir / event["request_file"]).read_bytes()
                    try:
                        scan_selection_body(request_bytes, forbidden_pairs)
                    except PrivacyScanError as exc:
                        raise RuntimeError(f"{condition}/{intent}: held-out data in selection POST: {exc}") from exc
                    choice_count_scanned += 1
            invocation_rows.append(record)

    require(len(invocation_rows) == 4 and choice_count == 6 and event_count == 12,
            f"unexpected capture counts: invocations={len(invocation_rows)}, choice_events={choice_count}, all_events={event_count}")
    report = read_json(run_dir / "report.json")
    require(len(report.get("invocations", [])) == 4 and report.get("privacy_audit", {}).get("choice_requests_scanned") == 6,
            "derived report counts do not match the four-invocation raw run")
    require(choice_count_scanned == report["privacy_audit"]["choice_requests_scanned"],
            "independent raw-body privacy scan count differs from the report count")
    require(report.get("condition_order_randomized") is False and report.get("replicates_per_condition") == 1,
            "report claim scope/order metadata changed")
    print(f"validated {len(invocation_rows)} saved invocations, independently scanned {choice_count_scanned} raw choice POSTs, and verified {event_count} total proxy events; no Go or Laya execution")


if __name__ == "__main__":
    main()
