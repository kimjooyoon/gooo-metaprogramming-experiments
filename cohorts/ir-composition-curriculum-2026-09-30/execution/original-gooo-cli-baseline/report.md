# Original Gooo CLI baseline — IR composition curriculum

This offline run attempted 32/32 frozen plans with compiler `bb5c1ec2f81cbfb17ac6fb2f7a9e1d7b67168e7f`. It made 0 model calls.

Source-unit completeness and finite vector fitness are reported separately. Evaluation values come from the frozen independent Python vector file; they are not added to the search prompt.

| Case | CLI | Source-unit units | Gooo training score | Independent Go training | Independent Go evaluation |
|---|---|---:|---:|---:|---:|
| cc01_inclusive_band | CLI_FAILURE_OR_NO_SOURCE | 0/0 | unknown | unknown | unknown |
| cc02_nonzero_disjunction | CLI_FAILURE_OR_NO_SOURCE | 0/0 | unknown | unknown | unknown |
| cc03_two_islands | CLI_FAILURE_OR_NO_SOURCE | 0/0 | unknown | unknown | unknown |
| cc04_outer_cutoffs | CLI_FAILURE_OR_NO_SOURCE | 0/0 | unknown | unknown | unknown |
| ni05_negative_then_double | CLI_PASS_WITH_SOURCE | 18/18 | 5/5 | 0/5 (observed 0, unknown 5) | 0/3 (observed 0, unknown 3) |
| ni06_surcharge_discount | CLI_PASS_WITH_SOURCE | 19/19 | 5/5 | 0/5 (observed 0, unknown 5) | 0/3 (observed 0, unknown 3) |
| ni07_zero_special_negative_offset | CLI_PASS_WITH_SOURCE | 17/17 | 4/4 | 0/4 (observed 0, unknown 4) | 0/3 (observed 0, unknown 3) |
| ni08_upper_grade_excess | CLI_PASS_WITH_SOURCE | 18/18 | 5/5 | 0/5 (observed 0, unknown 5) | 0/3 (observed 0, unknown 3) |
| lr09_compound_total | CLI_PASS_WITH_SOURCE | 12/12 | 4/4 | 0/4 (observed 0, unknown 4) | 0/3 (observed 0, unknown 3) |
| lr10_floor_then_increment | CLI_PASS_WITH_SOURCE | 17/17 | 4/4 | 0/4 (observed 0, unknown 4) | 0/3 (observed 0, unknown 3) |
| lr11_nonnegative_doubled_score | CLI_PASS_WITH_SOURCE | 22/22 | 4/4 | 0/4 (observed 0, unknown 4) | 0/3 (observed 0, unknown 3) |
| lr12_cap_after_adjustment | CLI_PASS_WITH_SOURCE | 25/25 | 4/4 | 0/4 (observed 0, unknown 4) | 0/3 (observed 0, unknown 3) |
| pr13_subtract_tripled_sum | CLI_PASS_WITH_SOURCE | 9/9 | 4/4 | 0/4 (observed 0, unknown 4) | 0/3 (observed 0, unknown 3) |
| pr14_product_neighbor_factors | CLI_PASS_WITH_SOURCE | 13/13 | 4/4 | 0/4 (observed 0, unknown 4) | 0/3 (observed 0, unknown 3) |
| pr15_square_minus_successor_sum | CLI_PASS_WITH_SOURCE | 9/9 | 4/4 | 0/4 (observed 0, unknown 4) | 0/3 (observed 0, unknown 3) |
| pr16_composed_neighbor_product | CLI_PASS_WITH_SOURCE | 14/14 | 4/4 | 0/4 (observed 0, unknown 4) | 0/3 (observed 0, unknown 3) |
| cp17_nonpositive_inclusive | CLI_FAILURE_OR_NO_SOURCE | 0/0 | unknown | unknown | unknown |
| cp18_exact_release_code | CLI_FAILURE_OR_NO_SOURCE | 0/0 | unknown | unknown | unknown |
| cp19_range_without_origin | CLI_FAILURE_OR_NO_SOURCE | 0/0 | unknown | unknown | unknown |
| cp20_strict_symmetric_window | CLI_FAILURE_OR_NO_SOURCE | 0/0 | unknown | unknown | unknown |
| bl21_saved_range_predicates | CLI_FAILURE_OR_NO_SOURCE | 0/0 | unknown | unknown | unknown |
| bl22_reassigned_valid_flag | CLI_PASS_WITH_SOURCE | 19/19 | 4/4 | 0/4 (observed 0, unknown 4) | 0/3 (observed 0, unknown 3) |
| bl23_nonzero_bounded_flag | CLI_FAILURE_OR_NO_SOURCE | 0/0 | unknown | unknown | unknown |
| bl24_selected_nonnegative_codes | CLI_PASS_WITH_SOURCE | 25/25 | 5/5 | 0/5 (observed 0, unknown 5) | 0/3 (observed 0, unknown 3) |
| tx25_sign_label | CLI_PASS_WITH_SOURCE | 22/22 | 3/3 | 0/3 (observed 0, unknown 3) | 0/2 (observed 0, unknown 2) |
| tx26_state_label | CLI_PASS_WITH_SOURCE | 28/28 | 3/3 | 0/3 (observed 0, unknown 3) | 0/2 (observed 0, unknown 2) |
| tx27_lexical_cutoff | CLI_PASS_WITH_SOURCE | 21/21 | 3/3 | 0/3 (observed 0, unknown 3) | 0/2 (observed 0, unknown 2) |
| tx28_reassigned_text_state | CLI_PASS_WITH_SOURCE | 24/24 | 3/3 | 0/3 (observed 0, unknown 3) | 0/2 (observed 0, unknown 2) |
| ob29_saturating_increment | CLI_PASS_WITH_SOURCE | 11/11 | 4/4 | 0/4 (observed 0, unknown 4) | 0/3 (observed 0, unknown 3) |
| ob30_saturating_decrement | CLI_PASS_WITH_SOURCE | 15/15 | 4/4 | 0/4 (observed 0, unknown 4) | 0/3 (observed 0, unknown 3) |
| ob31_saturating_double | CLI_PASS_WITH_SOURCE | 25/25 | 5/5 | 0/5 (observed 0, unknown 5) | 0/6 (observed 0, unknown 6) |
| ob32_clamped_absolute | CLI_PASS_WITH_SOURCE | 27/27 | 4/4 | 0/4 (observed 0, unknown 4) | 0/3 (observed 0, unknown 3) |

## Summary

- Gooo CLI: 22/32 emitted source; 10 failures retained.
- Source-unit completeness: 410/410 units across 22 receipts; 10 receipt rows unknown.
- Independent Go tests: 0/32 passed all vectors; 10 designs had no emitted source to compile.
- Independent training fitness: 0/135 passed, 0 observed, 135 unknown.
- Independent evaluation fitness: 0/93 passed, 0 observed, 93 unknown.
- Model calls: 0; provider endpoint and API key were removed from each CLI child environment.

## Limits

- The cohort measures one expression hole with three finite candidates per source fixture; it is not free-form code generation.
- Finite vector fitness is separate from source-unit completeness and is not a proof over the full int64 domain.
- Evaluation inputs are the frozen independent Python vectors and remain separate from Gooo's training plan.
- A failed Gooo CLI invocation remains one failed design in the fixed denominator of 32; no failed plan or candidate was repaired or replaced.

Raw CLI stdout/stderr, extracted compiler receipts, emitted Go source, per-case Go module and tests, Go test stdout/stderr, and per-case outcome records are retained under `cases/`.
