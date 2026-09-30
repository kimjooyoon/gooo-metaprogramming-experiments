# Corrected source-unit completeness summary

This derived summary corrects only the receipt-versus-measurement count. Two failed CLI cases have completeness receipts, but their source-AST dimension is UNKNOWN with denominator zero.

- Source-unit measurements: 30/32 observed; 2 unknown.
- Source-AST semantic units: 516/516 in observed successful receipts.
- Available completeness receipts: 32/32.
- CLI: 30/32 passed with source; failure IDs: bl21_saved_range_predicates, bl23_nonzero_bounded_flag.
- Independent Go: 30/32 emitted cases passed all vectors; training 125/135 observed, 10 unknown; evaluation 87/93 observed, 6 unknown.

As-run report SHA-256: `4f0acd5a8e3e720d314317e177db57233208be1af1c21d8d342446943c49affc`. The correction receipt limits the derived diff to three source-unit summary fields. No raw capture or score was changed.
