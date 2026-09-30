# Condition equivalence compiler replay

This replays the same 32 frozen plans with the compiler revision below. It adds zero new intents and makes zero model calls.

- Previous compiler `bb5c1ec2f81cbfb17ac6fb2f7a9e1d7b67168e7f`: 22/32 emitted source.
- New compiler `60cf7f49b0e302a6bebb42bc8da90f3ed19b2b82`: 30/32 passed CLI with source; 2 remained failed or unverified.
- Failure-to-pass cases: cc01_inclusive_band, cc02_nonzero_disjunction, cc03_two_islands, cc04_outer_cutoffs, cp17_nonpositive_inclusive, cp18_exact_release_code, cp19_range_without_origin, cp20_strict_symmetric_window.
- Pass-to-failure cases: none.
- Independent Go vectors: 30/32 emitted cases passed all vectors; 2 designs had no emitted source.
- Source-unit completeness and finite vector fitness are reported separately.

| Case | Previous CLI | New CLI | Change | Source units | Independent Go | Training passed / observed / planned | Evaluation passed / observed / planned |
|---|---|---|---|---:|---|---:|---:|
| cc01_inclusive_band | CLI_FAILURE_OR_NO_SOURCE | CLI_PASS_WITH_SOURCE | failure_to_pass | 14/14 | GO_TEST_PASS | 5 / 5 / 5 | 3 / 3 / 3 |
| cc02_nonzero_disjunction | CLI_FAILURE_OR_NO_SOURCE | CLI_PASS_WITH_SOURCE | failure_to_pass | 13/13 | GO_TEST_PASS | 3 / 3 / 3 | 2 / 2 / 2 |
| cc03_two_islands | CLI_FAILURE_OR_NO_SOURCE | CLI_PASS_WITH_SOURCE | failure_to_pass | 14/14 | GO_TEST_PASS | 5 / 5 / 5 | 2 / 2 / 2 |
| cc04_outer_cutoffs | CLI_FAILURE_OR_NO_SOURCE | CLI_PASS_WITH_SOURCE | failure_to_pass | 14/14 | GO_TEST_PASS | 6 / 6 / 6 | 3 / 3 / 3 |
| ni05_negative_then_double | CLI_PASS_WITH_SOURCE | CLI_PASS_WITH_SOURCE | same_pass | 18/18 | GO_TEST_PASS | 5 / 5 / 5 | 3 / 3 / 3 |
| ni06_surcharge_discount | CLI_PASS_WITH_SOURCE | CLI_PASS_WITH_SOURCE | same_pass | 19/19 | GO_TEST_PASS | 5 / 5 / 5 | 3 / 3 / 3 |
| ni07_zero_special_negative_offset | CLI_PASS_WITH_SOURCE | CLI_PASS_WITH_SOURCE | same_pass | 17/17 | GO_TEST_PASS | 4 / 4 / 4 | 3 / 3 / 3 |
| ni08_upper_grade_excess | CLI_PASS_WITH_SOURCE | CLI_PASS_WITH_SOURCE | same_pass | 18/18 | GO_TEST_PASS | 5 / 5 / 5 | 3 / 3 / 3 |
| lr09_compound_total | CLI_PASS_WITH_SOURCE | CLI_PASS_WITH_SOURCE | same_pass | 12/12 | GO_TEST_PASS | 4 / 4 / 4 | 3 / 3 / 3 |
| lr10_floor_then_increment | CLI_PASS_WITH_SOURCE | CLI_PASS_WITH_SOURCE | same_pass | 17/17 | GO_TEST_PASS | 4 / 4 / 4 | 3 / 3 / 3 |
| lr11_nonnegative_doubled_score | CLI_PASS_WITH_SOURCE | CLI_PASS_WITH_SOURCE | same_pass | 22/22 | GO_TEST_PASS | 4 / 4 / 4 | 3 / 3 / 3 |
| lr12_cap_after_adjustment | CLI_PASS_WITH_SOURCE | CLI_PASS_WITH_SOURCE | same_pass | 25/25 | GO_TEST_PASS | 4 / 4 / 4 | 3 / 3 / 3 |
| pr13_subtract_tripled_sum | CLI_PASS_WITH_SOURCE | CLI_PASS_WITH_SOURCE | same_pass | 9/9 | GO_TEST_PASS | 4 / 4 / 4 | 3 / 3 / 3 |
| pr14_product_neighbor_factors | CLI_PASS_WITH_SOURCE | CLI_PASS_WITH_SOURCE | same_pass | 13/13 | GO_TEST_PASS | 4 / 4 / 4 | 3 / 3 / 3 |
| pr15_square_minus_successor_sum | CLI_PASS_WITH_SOURCE | CLI_PASS_WITH_SOURCE | same_pass | 9/9 | GO_TEST_PASS | 4 / 4 / 4 | 3 / 3 / 3 |
| pr16_composed_neighbor_product | CLI_PASS_WITH_SOURCE | CLI_PASS_WITH_SOURCE | same_pass | 14/14 | GO_TEST_PASS | 4 / 4 / 4 | 3 / 3 / 3 |
| cp17_nonpositive_inclusive | CLI_FAILURE_OR_NO_SOURCE | CLI_PASS_WITH_SOURCE | failure_to_pass | 9/9 | GO_TEST_PASS | 3 / 3 / 3 | 3 / 3 / 3 |
| cp18_exact_release_code | CLI_FAILURE_OR_NO_SOURCE | CLI_PASS_WITH_SOURCE | failure_to_pass | 9/9 | GO_TEST_PASS | 3 / 3 / 3 | 3 / 3 / 3 |
| cp19_range_without_origin | CLI_FAILURE_OR_NO_SOURCE | CLI_PASS_WITH_SOURCE | failure_to_pass | 18/18 | GO_TEST_PASS | 5 / 5 / 5 | 3 / 3 / 3 |
| cp20_strict_symmetric_window | CLI_FAILURE_OR_NO_SOURCE | CLI_PASS_WITH_SOURCE | failure_to_pass | 15/15 | GO_TEST_PASS | 6 / 6 / 6 | 3 / 3 / 3 |
| bl21_saved_range_predicates | CLI_FAILURE_OR_NO_SOURCE | CLI_FAILURE_OR_UNVERIFIED | same_failure | 0/0 | unknown_no_emitted_source | 0 / 0 / ? | 0 / 0 / ? |
| bl22_reassigned_valid_flag | CLI_PASS_WITH_SOURCE | CLI_PASS_WITH_SOURCE | same_pass | 19/19 | GO_TEST_PASS | 4 / 4 / 4 | 3 / 3 / 3 |
| bl23_nonzero_bounded_flag | CLI_FAILURE_OR_NO_SOURCE | CLI_FAILURE_OR_UNVERIFIED | same_failure | 0/0 | unknown_no_emitted_source | 0 / 0 / ? | 0 / 0 / ? |
| bl24_selected_nonnegative_codes | CLI_PASS_WITH_SOURCE | CLI_PASS_WITH_SOURCE | same_pass | 25/25 | GO_TEST_PASS | 5 / 5 / 5 | 3 / 3 / 3 |
| tx25_sign_label | CLI_PASS_WITH_SOURCE | CLI_PASS_WITH_SOURCE | same_pass | 22/22 | GO_TEST_PASS | 3 / 3 / 3 | 2 / 2 / 2 |
| tx26_state_label | CLI_PASS_WITH_SOURCE | CLI_PASS_WITH_SOURCE | same_pass | 28/28 | GO_TEST_PASS | 3 / 3 / 3 | 2 / 2 / 2 |
| tx27_lexical_cutoff | CLI_PASS_WITH_SOURCE | CLI_PASS_WITH_SOURCE | same_pass | 21/21 | GO_TEST_PASS | 3 / 3 / 3 | 2 / 2 / 2 |
| tx28_reassigned_text_state | CLI_PASS_WITH_SOURCE | CLI_PASS_WITH_SOURCE | same_pass | 24/24 | GO_TEST_PASS | 3 / 3 / 3 | 2 / 2 / 2 |
| ob29_saturating_increment | CLI_PASS_WITH_SOURCE | CLI_PASS_WITH_SOURCE | same_pass | 11/11 | GO_TEST_PASS | 4 / 4 / 4 | 3 / 3 / 3 |
| ob30_saturating_decrement | CLI_PASS_WITH_SOURCE | CLI_PASS_WITH_SOURCE | same_pass | 15/15 | GO_TEST_PASS | 4 / 4 / 4 | 3 / 3 / 3 |
| ob31_saturating_double | CLI_PASS_WITH_SOURCE | CLI_PASS_WITH_SOURCE | same_pass | 25/25 | GO_TEST_PASS | 5 / 5 / 5 | 6 / 6 / 6 |
| ob32_clamped_absolute | CLI_PASS_WITH_SOURCE | CLI_PASS_WITH_SOURCE | same_pass | 27/27 | GO_TEST_PASS | 4 / 4 / 4 | 3 / 3 / 3 |

## Finite fitness

- Training: 125/135 passed; 125 observed; 10 unknown.
- Evaluation: 87/93 passed; 87 observed; 6 unknown.

All plan and fixture bytes were checked against the frozen manifest before and after the run. Raw CLI output, receipts, generated sources, and Go test evidence are saved per case.
