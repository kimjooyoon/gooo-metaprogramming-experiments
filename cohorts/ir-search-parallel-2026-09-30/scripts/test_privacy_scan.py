import json
import unittest

from validate_run import PrivacyScanError, holdout_case_pairs, scan_selection_body


class SelectionRequestPrivacyScanTests(unittest.TestCase):
    def setUp(self):
        oracle = {
            "holdout": {
                "inputs": [1, -9223372036854775808],
                "expected": [1, 0],
            }
        }
        self.forbidden = holdout_case_pairs(oracle)

    def scan(self, request):
        scan_selection_body(json.dumps(request).encode("utf-8"), self.forbidden)

    def assert_leak_rejected(self, request):
        with self.assertRaises(PrivacyScanError):
            self.scan(request)

    def test_case_shaped_leak_in_question_object_is_rejected(self):
        self.assert_leak_rejected({
            "questions": {
                "body_ir_search": {
                    "instructions": "choose an expression",
                    "metadata": {"input": 1, "expected": 1},
                }
            }
        })

    def test_case_shaped_leak_in_options_json_string_is_rejected(self):
        encoded_case = json.dumps({"input": -9223372036854775808, "expected": 0})
        self.assert_leak_rejected({
            "questions": {
                "body_ir_search": {
                    "options": [{"id": "candidate-a", "description": f"metadata: {encoded_case} attached"}]
                }
            }
        })

    def test_double_encoded_nested_state_string_is_rejected(self):
        case = {"input": 1, "expected": 1}
        inner = json.dumps({"prior": {"failed_cases": [case]}})
        doubly_encoded = json.dumps(inner)
        self.assert_leak_rejected({"state": {"request": doubly_encoded}})

    def test_holdout_field_name_in_embedded_json_is_rejected(self):
        self.assert_leak_rejected({
            "questions": {
                "body_ir_search": {
                    "description": 'debug: {"nested":{"Holdout_Test_Cases":[]}}'
                }
            }
        })

    def test_duplicate_case_keys_cannot_hide_an_exact_pair(self):
        raw = b'{"state":{"request":"{\\"input\\":0, \\"input\\":1, \\"expected\\":1}"}}'
        with self.assertRaises(PrivacyScanError):
            scan_selection_body(raw, self.forbidden)

    def test_legitimate_candidate_constants_and_irrelevant_numbers_are_accepted(self):
        self.scan({
            "questions": {
                "body_ir_search": {
                    "criteria": {
                        "zero": "Try the constant 0",
                        "negate": "Try -input",
                        "boundary": "-9223372036854775808 is an unrelated numeric constant",
                    },
                    "candidate_constants": [0, 1, -9223372036854775808],
                    "other_counts": {"input_count": 3, "expected_count": 7},
                    "unrelated_case_shape": {"input": 1, "expected": 2},
                }
            }
        })


if __name__ == "__main__":
    unittest.main()
