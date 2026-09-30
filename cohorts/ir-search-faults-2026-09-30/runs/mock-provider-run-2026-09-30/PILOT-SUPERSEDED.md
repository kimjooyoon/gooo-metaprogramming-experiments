# Superseded pilot run

This raw run is retained as experimental evidence but is excluded from the final result. It contains 12 pinned-compiler invocations and 19 MOCK-provider requests. The training-perfect/holdout-failure treatment used the zero expression against the original clamp holdout; that candidate correctly passed 4/4, so this pilot did not test the intended train/holdout generalization gap. The corrected final run changes only that treatment's finite suites and selects identity on nonnegative training inputs, then reports 0/4 on disjoint negative holdout inputs.

No Laya service, external provider, or model call was used in either run.
