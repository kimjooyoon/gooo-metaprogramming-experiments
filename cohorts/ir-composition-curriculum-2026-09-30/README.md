# IR composition curriculum — 2026-09-30

This is a structural, offline baseline for 32 distinct Gooo Integer-to-Integer
body-fill intentions. Each design has exactly one expression hole and a closed
set of three candidate expressions. It does **not** measure free-form code
generation. The set is finite and the measured train/evaluation values are not
a proof over the int64 domain.

The 32 primary areas are balanced four apiece: conditionals, nested if/else,
let/reassignment, expression composition and precedence, comparison
expressions, Boolean locals, Text locals, and int64 boundary/overflow handling.
Each case is a new intention; the prior four body-fill intents and repeated
calls from previous cohorts are not counted.

`oracle/python_spec.py` is the Python-integer reference specification with
explicit signed-int64 wrapping. `oracle/oracle.go` is a separate compiled Go
reference implementation. `oracle/candidates.go` compiles each finite option
inside the frozen source-body shell so training discrimination is measured
from actual Go execution. Training and evaluation inputs are disjoint. Search
plans place evaluation inputs only in the holdout field; the model prompt is
limited to training cases. Candidate-discriminating training cases and
source-unit completeness are reported as separate measures.

The Laya plan matrix has three packaging arms: legacy without external
feedback, compact without external feedback, and compact with source-bound
compiled-Go training observations. Prompt packaging is independent of whether
feedback is present. External observations are advisory inputs, not authenticated
CI proof or semantic authority. No provider is called by preparation, the Go
oracle, or the structural Gooo baseline.

The pinned Gooo binary run is intentionally a later phase. It must verify the
frozen manifest before any offline codegen. Even if every finite case passes,
the result is only evidence for the declared finite suite and structural source
coverage—not a full-domain correctness claim.
