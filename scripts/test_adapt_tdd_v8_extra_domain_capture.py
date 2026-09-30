#!/usr/bin/env python3
"""Model-free unit tests for the TDD v8 capture adapter."""

from __future__ import annotations

import json
import copy
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import adapt_tdd_v8_extra_domain_capture as adapter


class AdapterTests(unittest.TestCase):
    def test_strict_json_rejects_duplicate_keys_and_invalid_utf8(self):
        with self.assertRaisesRegex(ValueError, "duplicate JSON key"):
            adapter.parse_json(b'{"source_digest":"a","source_digest":"b"}', "test")
        with self.assertRaisesRegex(ValueError, "strict UTF-8"):
            adapter.parse_json(b'{"x":"\xff"}', "test")

    def test_path_reader_rejects_traversal_and_symlinks(self):
        with tempfile.TemporaryDirectory(prefix="tdd-v8-adapter-path-") as name:
            root = Path(name)
            (root / "proxy" / "requests").mkdir(parents=True)
            (root / "outside.raw").write_bytes(b"outside")
            with self.assertRaises(ValueError):
                adapter.strict_relative_file(root, "../outside.raw", "test")
            link = root / "proxy" / "requests" / "escape.raw"
            try:
                link.symlink_to(root / "outside.raw")
            except (OSError, NotImplementedError):
                self.skipTest("symlinks are unavailable")
            with self.assertRaisesRegex(ValueError, "symlink"):
                adapter.strict_relative_file(root, "proxy/requests/escape.raw", "test")

    def test_typed_request_hash_binds_declared_candidate_expressions(self):
        candidates = [{"id": "option_a", "expression": "input < 0"},
                      {"id": "option_b", "expression": "input >= 0"}]
        state = {"remaining_candidates": candidates}
        state_wire = json.dumps(state, separators=(",", ":"))
        question = {"type": "choice", "instructions": "select one",
                    "criteria": {row["id"]: "Try this exact expression: " + row["expression"]
                                 for row in candidates}}
        outer = {"model": "multilingual", "state": {"request": state_wire},
                 "questions": {"body_ir_search": question}}
        typed = {"schema": "gooo/typed-decision-request/v1", "state": state_wire,
                 "question": {"id": "body_ir_search", "instructions": "select one",
                              "options": [{"id": row["id"],
                                           "description": "Try this exact expression: " + row["expression"]}
                                          for row in candidates]},
                 "fallback": "option_a", "provider_model": "multilingual"}
        expected = "sha256:" + adapter.digest(adapter.canonical_go_json(typed))
        self.assertEqual(adapter.typed_request_sha(outer), expected)
        outer["questions"]["body_ir_search"]["criteria"]["option_a"] = "Try this exact expression: true"
        with self.assertRaisesRegex(ValueError, "choices differ"):
            adapter.typed_request_sha(outer)

    def test_revision2_candidate_expression_and_attempt_cap_are_bound(self):
        catalog, plans = adapter.load_frozen_designs()
        design_id = next(iter(catalog))
        row = {"max_attempts": 1}
        tdd_plan = copy.deepcopy(plans[design_id])
        tdd_plan.update({"schema": "gooo/body-codegen-ir-search-plan/v1",
                         "provider_model": "multilingual", "prompt_profile": "compact", "max_attempts": 1})
        self.assertTrue(adapter.plans_match_revision2(tdd_plan, plans[design_id], row))
        tdd_plan["candidates"][0]["expression"] += " + 1"
        self.assertFalse(adapter.plans_match_revision2(tdd_plan, plans[design_id], row))

    def test_source_unit_claim_requires_complete_source_ast_ratio(self):
        receipt = {"schema": "gooo/metaprogramming-completeness-receipt/v2", "dimensions": [
            {"id": "source_ast_coverage", "status": "PASS", "numerator": 8, "denominator": 8}]}
        self.assertEqual(adapter.source_unit_status(receipt)[0], True)
        receipt["dimensions"][0]["numerator"] = 7
        self.assertEqual(adapter.source_unit_status(receipt)[0], False)
        receipt["dimensions"][0]["status"] = "UNKNOWN"
        receipt["dimensions"][0]["numerator"] = 8
        self.assertIsNone(adapter.source_unit_status(receipt)[0])

    def test_public_derivative_rebinds_raw_requests_native_outputs_and_sources(self):
        bundle = (adapter.PROBE_DIR / "captures" /
                  "ir-composition-tdd-v8-20260930T104054Z-d868d3ee7f71-public")
        result = adapter.verify_public_bundle(bundle)
        self.assertEqual(result["decision"], "VERIFIED_PUBLIC_DERIVATIVE")
        self.assertEqual(result["planned_cells"], 64)
        self.assertEqual(result["raw_provider_posts_recomputed"], 86)

    def test_public_derivative_rejects_changed_raw_request(self):
        bundle = (adapter.PROBE_DIR / "captures" /
                  "ir-composition-tdd-v8-20260930T104054Z-d868d3ee7f71-public")
        with tempfile.TemporaryDirectory(prefix="tdd-v8-public-review-") as name:
            copy = Path(name) / "bundle"
            shutil.copytree(bundle, copy)
            request = next((copy / "capture/proxy/requests").glob("*.raw"))
            request.write_bytes(request.read_bytes() + b" ")
            with self.assertRaisesRegex(ValueError, "inventory mismatch"):
                adapter.verify_public_bundle(copy)


if __name__ == "__main__":
    unittest.main()
