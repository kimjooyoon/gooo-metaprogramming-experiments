# IR composition baseline validation

Validation passed on go version go1.27.0 darwin/arm64 with all model and provider access disabled.

- Original compiler run: 22/32 source emissions; 10 CLI failures.
- Equivalence-fix run: 30/32 source emissions; 2 CLI failures.
- Saved independent Go modules recompiled and replayed: 52/52 passed.
- Finite fitness: training 125/135 observed, 10 unknown; evaluation 87/93 observed, 6 unknown.
- Source-unit raw aggregate issue: as-run report says 32 observed / 0 unknown, while its 32 per-case receipts reconstruct to 30 PASS / 2 UNKNOWN; a bound derived correction records 30/2 without changing raw evidence.
- Frozen original candidate validity: 93/96 compile; exactly 3 expected candidate bodies fail compilation.
- Both compiler runs use the same 32 frozen inputs; this is a before/after comparison, not 64 intents.
