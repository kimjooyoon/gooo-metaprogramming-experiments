# Original 32-design composition baseline

This cohort adds 32 distinct functional intentions across eight balanced areas: conditions, nested branches, mutable local assignments, precedence, comparisons, Boolean locals, Text locals, and int64 boundaries. Each has one expression hole and three declared candidates. It is finite candidate assembly; these are not 32 freely authored model programs.

The original 142-file preparation is frozen at `e66f71f3bc02350168bb3958628bf5d1a3e02096ed758cbfbe83f987b71eb9b8`. All frozen files were checked before publication. It includes 135 training rows and 93 disjoint evaluation rows. The preparation made zero Laya calls.

## Actual offline execution

On clean compiler `bb5c1ec2`, the complete raw capture attempted 32/32 plans: 22 emitted source, and ten failed. The eight direct condition/comparison cases fail their preserve-route semantic equivalence receipt; Boolean-local cases 21 and 23 fail Go typecheck due to unused locals. Their raw JSON stdout and failures are retained.

A separate corrected Go harness compiled and executed all 22 emitted sources; all their finite vectors passed. The full design denominator remains 32: training 89 passed of 135 planned, with 46 unknown because no source was emitted; evaluation 65 passed of 93 planned, with 28 unknown. Source AST-unit completeness is separately 410/410 across 22 available receipts; ten missing receipts are unknown. These finite counts do not prove complete user intent or the int64 domain.

- [Raw capture report](execution/original-gooo-cli-baseline/execution-report.json)
- [Corrected independent replay](execution/original-gooo-cli-baseline/go-validation-corrected-v1/report.md)
- [Original candidate compile errors](execution/candidate-oracle-attempt-5/original-candidate-compile-errors.json)

## Candidate and design quality

Go 1.27 individually compiled the 96 original candidates: 93 passed and three failed due to unused locals. Those failures remain in the original candidate denominator. A counterfactual diagnostic exposed a training discrimination defect in case 22 and incorrect rotating gold-option metadata in the original reporter. Its patched outputs are diagnostic only and cannot become actual model feedback.

Early oracle and execution harness attempts failed at setup or reporting; their reports and logs remain available. The first CLI attempt saved hashes but omitted exact raw stdout/stderr. The complete second capture is independently labeled and supplies those raw bytes. A multi-row comma defect in its first Go evaluator was corrected in a separate derivation over the same captured source, with zero additional codegen or model calls.

A compiler repair and revision-2 designs are tracked separately. Repeating these same 32 intentions under corrected plans or a different compiler does not add 32 independent intentions. Local reference tests, model choices, system adjustments, emitted coverage and finite behavior use separate measures.

## Frozen revision 2

The [revision-2 cohort](revision-2/README.md) corrects metadata rotation, adds a distinguishing training input for case 22, and changes the shared Boolean guards to use every declared local meaningfully. It retains the same 32 intention IDs. Its design freeze is `9ef3d4bf5c3be68ef4da9c0e7c712eefb313d6bd325446e229e48b8441e33aca`.

All 96 revised candidates compiled and executed, and each training suite now separates the gold candidate from both distractors. A separate temporary-copy replay independently checked all 189 successful original/revised candidate outputs against their frozen bytes and recomputed revised training discrimination. The original 3/96 candidate failures remain in their own denominator. This is candidate/reference evidence, with zero Laya calls and zero Gooo CLI calls; emitted language completeness is measured elsewhere.

CI executes the temporary-copy replay and retains its report; published frozen evidence is read only. [Local independent replay](execution/revision2-independent-replay/independent-replay-report.md).

## Compiler comparison on the unchanged original designs

Clean compiler `60cf7f49` normalizes only outer parentheses in the existing canonical condition/result forms. All eight rejected direct condition/comparison holes now generate successfully. The two original unused-local designs continue to fail typecheck. This repair is [PR 1101](https://github.com/kimjooyoon/meta-ontology-go/pull/1101), which passed all six required checks and merged to dev.

| Measure | Original compiler | Equivalence repair |
|---|---:|---:|
| Source emissions / planned designs | 22/32 | 30/32 |
| Training passed / observed / planned | 89/89/135 | 125/125/135 |
| Training unknown | 46 | 10 |
| Evaluation passed / observed / planned | 65/65/93 | 87/87/93 |
| Evaluation unknown | 28 | 6 |
| Source-unit passed / total in available receipts | 410/410 | 516/516 |
| Available source-unit receipts / planned designs | 22/32 | 30/32 |

[Independent baseline replay](execution/independent-baseline-validation/validation-report.md) compiled and executed all 52 saved emitted modules; all observed finite cases passed. No model was called. These are the same 32 intentions, with local finite scoring and deterministic selection. The repair does not turn this comparison into Laya performance evidence.

The repair recorder's original report mistakenly aggregated 32 observed source-unit receipts and zero unknown. Its per-case rows establish 30 PASS and two UNKNOWN. The [separate derived correction](execution/condition-equivalence-60cf7f49/derived-summary-correction-v1/) fixes only the bound summary fields, and the original report remains unchanged. The as-run replay script source was reconstructed after execution and verified against its recorded SHA; this is explicitly labeled in its provenance rather than presented as an archived-before-run snapshot.
