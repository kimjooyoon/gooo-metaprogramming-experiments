# Corrected independent Go evaluation

This sibling result replays only the 22 original emitted Go files. It makes no Gooo CLI or model calls. The first vector harness attempt is retained in the original run; its multi-row test literals contained duplicate commas, so no vectors ran in that attempt.

- Frozen CLI capture: 32/32 checked; 22 emitted sources; 10 CLI failures retained.
- Corrected Go validation: 22/32 passed all vectors; 0 emitted-source evaluations failed or were incomplete; 10 designs had no source and remain unknown.
- Training vectors: 89/135 passed; 46 unknown.
- Evaluation vectors: 65/93 passed; 28 unknown.
- Source-unit completeness remains in the original report and is separate from finite vector fitness.

| Case | Go result | Training passed / observed / planned | Evaluation passed / observed / planned |
|---|---|---:|---:|
| cc01_inclusive_band | unknown_no_cli_emitted_source | 0 / 0 / 5 | 0 / 0 / 3 |
| cc02_nonzero_disjunction | unknown_no_cli_emitted_source | 0 / 0 / 3 | 0 / 0 / 2 |
| cc03_two_islands | unknown_no_cli_emitted_source | 0 / 0 / 5 | 0 / 0 / 2 |
| cc04_outer_cutoffs | unknown_no_cli_emitted_source | 0 / 0 / 6 | 0 / 0 / 3 |
| ni05_negative_then_double | GO_TEST_PASS | 5 / 5 / 5 | 3 / 3 / 3 |
| ni06_surcharge_discount | GO_TEST_PASS | 5 / 5 / 5 | 3 / 3 / 3 |
| ni07_zero_special_negative_offset | GO_TEST_PASS | 4 / 4 / 4 | 3 / 3 / 3 |
| ni08_upper_grade_excess | GO_TEST_PASS | 5 / 5 / 5 | 3 / 3 / 3 |
| lr09_compound_total | GO_TEST_PASS | 4 / 4 / 4 | 3 / 3 / 3 |
| lr10_floor_then_increment | GO_TEST_PASS | 4 / 4 / 4 | 3 / 3 / 3 |
| lr11_nonnegative_doubled_score | GO_TEST_PASS | 4 / 4 / 4 | 3 / 3 / 3 |
| lr12_cap_after_adjustment | GO_TEST_PASS | 4 / 4 / 4 | 3 / 3 / 3 |
| pr13_subtract_tripled_sum | GO_TEST_PASS | 4 / 4 / 4 | 3 / 3 / 3 |
| pr14_product_neighbor_factors | GO_TEST_PASS | 4 / 4 / 4 | 3 / 3 / 3 |
| pr15_square_minus_successor_sum | GO_TEST_PASS | 4 / 4 / 4 | 3 / 3 / 3 |
| pr16_composed_neighbor_product | GO_TEST_PASS | 4 / 4 / 4 | 3 / 3 / 3 |
| cp17_nonpositive_inclusive | unknown_no_cli_emitted_source | 0 / 0 / 3 | 0 / 0 / 3 |
| cp18_exact_release_code | unknown_no_cli_emitted_source | 0 / 0 / 3 | 0 / 0 / 3 |
| cp19_range_without_origin | unknown_no_cli_emitted_source | 0 / 0 / 5 | 0 / 0 / 3 |
| cp20_strict_symmetric_window | unknown_no_cli_emitted_source | 0 / 0 / 6 | 0 / 0 / 3 |
| bl21_saved_range_predicates | unknown_no_cli_emitted_source | 0 / 0 / 5 | 0 / 0 / 3 |
| bl22_reassigned_valid_flag | GO_TEST_PASS | 4 / 4 / 4 | 3 / 3 / 3 |
| bl23_nonzero_bounded_flag | unknown_no_cli_emitted_source | 0 / 0 / 5 | 0 / 0 / 3 |
| bl24_selected_nonnegative_codes | GO_TEST_PASS | 5 / 5 / 5 | 3 / 3 / 3 |
| tx25_sign_label | GO_TEST_PASS | 3 / 3 / 3 | 2 / 2 / 2 |
| tx26_state_label | GO_TEST_PASS | 3 / 3 / 3 | 2 / 2 / 2 |
| tx27_lexical_cutoff | GO_TEST_PASS | 3 / 3 / 3 | 2 / 2 / 2 |
| tx28_reassigned_text_state | GO_TEST_PASS | 3 / 3 / 3 | 2 / 2 / 2 |
| ob29_saturating_increment | GO_TEST_PASS | 4 / 4 / 4 | 3 / 3 / 3 |
| ob30_saturating_decrement | GO_TEST_PASS | 4 / 4 / 4 | 3 / 3 / 3 |
| ob31_saturating_double | GO_TEST_PASS | 5 / 5 / 5 | 6 / 6 / 6 |
| ob32_clamped_absolute | GO_TEST_PASS | 4 / 4 / 4 | 3 / 3 / 3 |
