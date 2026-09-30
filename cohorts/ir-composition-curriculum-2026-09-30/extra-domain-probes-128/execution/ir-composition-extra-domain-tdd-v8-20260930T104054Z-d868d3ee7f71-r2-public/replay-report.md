# Extra-domain probe replay

The frozen 128 probes were evaluated only after capture and candidate choice. They cover four new inputs for each of the same 32 revision-2 designs.

| Arm | Executed / planned | Matched | Mismatched | Unknown | Region targets observed / planned | Source units complete / incomplete / unknown |
|---|---:|---:|---:|---:|---:|---:|
| compact_multilingual_single | 128/128 | 87 | 41 | 0 | 41/41 | 32/0/0 |
| compact_multilingual_local_feedback | 128/128 | 128 | 0 | 0 | 41/41 | 32/0/0 |

These scores describe only the 128 frozen values. Probe-purpose coverage uses static region tags. Dynamic branch coverage and branch-test adequacy are unmeasured.
The expected outputs come from the revision-2 handwritten Go reference, which shares source lineage with the prior finite oracle. Agreement is a correlated-oracle diagnostic, not independent ground truth.
Passing these new values does not prove full-domain correctness. Missing captures, invalid route/choice bindings, compile failures, and incomplete executions remain unknown rows.
