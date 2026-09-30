# Captured emitted Go source validation

- Saved invocations compiled and run: 4
- Independent finite-oracle cases executed: 28 (training 12; post-selection holdout 16)
- Go toolchain: `go version go1.26.5 darwin/arm64` (CI pins `go1.27.0`; local validation records the installed version)
- Raw capture hash/count validation: PASS
- All compiled outputs match the independent training and holdout oracle vectors: PASS
- Gooo CLI calls: 0; Laya/model calls: 0

## Scope

- This is finite-suite execution, not a full int64-domain proof.
- The cohort has one replicate per condition, fixed sequential-then-simultaneous order, and no separate warmup.
- The sequential CLI pair's 523.5 ms inter-invocation gap is capture-proxy shutdown overhead; timing is not a speed claim.
- No Gooo CLI, Laya server, provider endpoint, or model was invoked by this validator.

Per-invocation sources and vectors are recorded in `validation-report.json`; exact source copies are under `sources/`.
