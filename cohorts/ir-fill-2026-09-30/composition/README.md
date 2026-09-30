# Gooo body-codegen fixed rerun

- Fixed binary SHA-256: `28c5906f4cb9581f8833cebabfad8d977c8d142aed5e5a3f8361d7da4340fa35`; embedded clean revision `ec4bf3e5f4119118b501c1b45862936eb46b95b7`; `vcs.modified=false`; Go 1.27.0.
- Baseline binary SHA-256: `4e9836ac6781d236e9279584bec9da61a88219612c4b94fa2729fcb68f139dc4`; embedded revision `2fc19ea5b094f424f550e2b0a9ebe6477759d1a2`.
- Fixed commit: `ec4bf3e5f4119118b501c1b45862936eb46b95b7`. No Laya endpoint was configured.
- The original 12 cases and 2 probes are preserved. Two revised boolean plans are separate additions; they use `local` and `local + 0` so both candidate bodies reference the declared local.
- Gooo functional accuracy is the declared-suite AST-interpreter score. Independent Go results are separate compile-and-run oracles on seen inputs and disjoint held-out inputs.

| # | Original case | Baseline CLI | Fixed CLI | Fixed Gooo score | Go seen | Go held-out |
|---:|---|---|---|---:|---:|---:|
| 1 | nested_clamp | 0 / PASS | 0 / PASS | 100% | 7/7 | 4/4 |
| 2 | nested_else_if | 0 / PASS | 0 / PASS | 100% | 8/8 | 4/4 |
| 3 | sibling_locals_assignment | 0 / PASS | 0 / PASS | 100% | 5/5 | 3/3 |
| 4 | composed_locals | 0 / PASS | 0 / PASS | 100% | 5/5 | 3/3 |
| 5 | short_circuit_and | 0 / PASS | 0 / PASS | 100% | 6/6 | 3/3 |
| 6 | short_circuit_or | 0 / PASS | 0 / PASS | 100% | 7/7 | 3/3 |
| 7 | constant_fold | 0 / PASS | 0 / PASS | 100% | 5/5 | 3/3 |
| 8 | guarded_int64_increment | 0 / PASS | 0 / PASS | 100% | 6/6 | 3/3 |
| 9 | seen_heldout_mismatch | 0 / PASS | 0 / PASS | 100% | 2/2 | 0/4 |
| 10 | compound_hole_precedence | 0 / PASS | 0 / PASS | 100% | 3/3 | 3/3 |
| 11 | false_identifier_shadow | 0 / empty | 1 / FAIL_CLOSED | — | not run | not run |
| 12 | int64_min_literal | 0 / empty | 0 / PASS | 100% | 1/1 | 2/2 |

## Exact before and after

- **Compound-hole precedence:** baseline emitted `(input - input + 1) * 2`, scored 0%, reported PASS, and independent Go matched 0/3 seen + 0/3 held-out. Fixed emits `(input - (input + 1)) * 2`, scores 100%, and passes all 3 seen + 3 held-out checks.
- **Boolean locals:** baseline direct evaluator reproduction: `evaluate candidate "false": input 5 returned bool, want int64`; baseline CLI returned 0 with an empty report. On the unchanged original case, fixed correctly rejects its alternate candidate `input` because it leaves local `false` unused (exit 1 / FAIL_CLOSED). In separate revised false and true plans, baseline same-plan calls still return the empty report; fixed scores 100% and passes each plan's three independent Go checks (6/6 combined).
- **Minimum int64:** baseline internal failure `evaluate candidate "min": input 0: parse generated integer "9223372036854775808": strconv.ParseInt: parsing "9223372036854775808": value out of range`; old CLI returned 0 with an empty report. Fixed emits the min-literal candidate at 100% and passes all seen/held-out Go checks.
- **Invalid body error:** baseline nested-shadow error `candidate "one" is not a valid typed body: let name "value" is already bound` was swallowed (exit 0, empty report). Fixed returns exit 1 with FAIL_CLOSED and the same error.
- **Seen versus held-out:** the 2-case suite still selects identity at 100%; independent Go passes 2/2 seen and matches 0/4 held-out square cases. This finite-suite limitation remains unresolved.

## Independent Go checks

- Original fixed set: 11 functions emitted; 11/11 seen suites pass (55 individual checks). Ten held-out suites pass; the one intended mismatch fails exactly four outputs, out of 90 original seen/held-out checks. The original false-local plan is rejected as a valid candidate-set error, not counted as a functional test failure.
- Revised false/true plans: 6/6 independent Go checks pass. The three standalone Go semantic reproductions pass.
- The portable replay runner derives binary revision and digest from the selected compiler. Example: `python3 run_corpus.py --binary /path/to/gooo --output /tmp/body-fill-run --source-repo /path/to/checkout`.

Machine-readable summaries, receipt digests, timings, and exact command errors are in `baseline.json` and `fixed.json`; original and revised inputs are under `inputs/`.

## Publication replay and source records

`baseline.json` and `fixed.json` are extracted summaries from the original runs. During lean packaging the original full fixed stdout files were removed; their timings must not be attributed to a later run. A separate publication replay using the same clean compiler is preserved in `publication-replay.json.gz`. It contains the complete CLI stdout strings, emitted source, cases and compiled Go outcomes, its own timestamps, and assertion results. It repeats the original 12 cases and two probes, plus the revised boolean plans, and does not replace the historical summary.

The revised binding checks have one supplied/seen input and two held-out inputs each: three compiled checks per plan, six combined. The initial portable harness incorrectly expected three held-out checks; the publication runner corrects that assertion without changing the inputs. The intentional square overfit and invalid-candidate rejections remain expected outcomes.

Replay with `--expected-revision ec4bf3e5f4119118b501c1b45862936eb46b95b7` to require the recorded compiler source. CI preserves its complete generated fixtures and Go test modules as a run artifact.
