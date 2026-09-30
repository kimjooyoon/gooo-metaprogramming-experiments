# Independent output validation

The [local validation receipt](local-2026-09-30/validation-report.json) records a
separate Go 1.27.0 check of all twelve saved generated projections against the
finite oracle inputs. It also validates raw exchange hashes and hidden-holdout
protocol behavior, deterministic replays, and mock rejection handling.

This validation did not call Laya. Mock-provider checks are protocol evidence,
not additional model choices. CPU/RSS observations remain those of the original
primary run. The receipt identifies the source revision and tested binary;
Linux CI records its own binary digest rather than requiring an identical hash
to the captured Darwin executable.
