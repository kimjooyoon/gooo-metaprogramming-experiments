"""Small offline probes for validator trust-boundary checks; no compiler/provider calls."""
import copy
import json
import unittest
from pathlib import Path

import validate_saved

RUN = Path(__file__).resolve().parents[1] / "runs" / "final-mock-provider-run-2026-09-30"


class SavedArtifactValidatorTests(unittest.TestCase):
    def test_mutated_summary_disagrees_with_raw_stdout_report(self):
        row = next(r for r in validate_saved.read_json(RUN / "invocations.json")
                   if r["treatment_id"] == "failure_feedback_privacy")
        folder = RUN / "treatments" / row["treatment_id"]
        body = validate_saved.decode_body_search((folder / "stdout.raw").read_bytes())
        validate_saved.assert_summary_matches_body(row, body, "fixture row")

        mutated = copy.deepcopy(row)
        mutated["training_passed"] += 1
        with self.assertRaisesRegex(AssertionError, "training_passed disagrees"):
            validate_saved.assert_summary_matches_body(mutated, body, "mutated summary")

    def test_embedded_json_in_other_field_cannot_hide_holdout_case_pair(self):
        holdout = [{"input": -17, "expected": 0}]
        embedded_case = json.dumps({"input": -17, "expected": 0})
        raw_request = json.dumps({
            "questions": {"body_ir_search": {"criteria": {"zero": "0"}}},
            "diagnostic_note": "provider metadata: {\"opaque\": " + json.dumps(embedded_case) + "} end",
        }).encode()
        with self.assertRaisesRegex(AssertionError, "exact holdout input/expected pair"):
            validate_saved.assert_no_holdout_leak(raw_request, holdout, "nested-string probe")

    def test_embedded_holdout_field_is_rejected_but_unrelated_constants_are_allowed(self):
        holdout = [{"input": -17, "expected": 0}]
        with self.assertRaisesRegex(AssertionError, "holdout field"):
            validate_saved.assert_no_holdout_leak(
                {"misc": "prefix {\"envelope\": {\"HoLdOuT_cases\": []}} suffix"}, holdout)
        validate_saved.assert_no_holdout_leak(
            {"constants": [-17, 0, 1], "choice": "input + 1"}, holdout)


if __name__ == "__main__":
    unittest.main()
