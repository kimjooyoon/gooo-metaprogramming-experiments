# Failed local toolchain attempt

The direct 100-case runner issued 100 compiler-derived route-equivalence
receipts, all PASS, and observed 100 seeded external replays with no mismatch.
The generated package did not run: the local `go` executable was Go 1.26.5
while the generated module requires Go 1.27.0, and the runner set
`GOTOOLCHAIN=local`. The cohort therefore correctly failed closed; it reports
zero behavioral matches and does not claim runtime validation.

The Laya decisions, selected routes, request latencies, and separate server
resource sample are retained in the report and observation JSON. The final
run at [`../../laya-route-equivalence-seed-3/`](../../laya-route-equivalence-seed-3/)
used the already-cached Go 1.27.0 toolchain and passed generated-package
execution. This attempt is retained to show the toolchain failure rather than
silently replacing it with the successful rerun.
