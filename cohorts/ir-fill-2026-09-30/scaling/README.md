# Candidate and test-count scaling (no model)

Four treatments of **one clamp intention**, with five invocations each. This is 20 timing observations, not 20 independent tasks. Clean compiler `ec4bf3e5f4119118b501c1b45862936eb46b95b7`, evaluator v2, same host as the other local experiments, Laya disconnected. The selected expression passed every declared case on every invocation.

| Candidates | Declared tests | Plan build/score median | Internal generation median | Whole CLI median (range) |
| ---: | ---: | ---: | ---: | ---: |
| 2 | 9 | 0.178 ms | 0.407 ms | 4.748 ms (4.729–5.325) |
| 2 | 4096 | 2.134 ms | 3.801 ms | 12.091 ms (11.622–13.419) |
| 16 | 9 | 0.782 ms | 1.013 ms | 5.479 ms (5.297–5.957) |
| 16 | 4096 | 17.447 ms | 19.161 ms | 27.088 ms (26.935–27.514) |

The 16-candidate × 4096-test plan evaluates 65,536 candidate/input combinations before making a decision. Scoring grows with the candidate/test cross product. Final emission stays near 0.1 ms in these fixtures. CLI wall time additionally includes process startup, plan reading, JSON decoding/encoding, and output transfer. The internal receipt timings do not account for all CLI work.

The separate three-call real-Laya smoke observed about 367 ms for its model decision. It is a different plan and request size, so these are not matched speedup measurements. They show that inference is expensive relative to this small deterministic search; this evidence does not establish a code-generation speed benefit from calling Laya after scoring every candidate.

CPU measurements in `replay/calls.json` are per-invocation child CLI user+system CPU deltas, not total host utilization or a separate model process. Other agents ran on the host; these are observations, not isolated throughput benchmarks. Generated Go was typechecked and scored by the bounded evaluator; this timing study did not independently execute it. The separate composition corpus provides compiled-Go checks. No p95 is reported for five repeats per treatment.

## Reproduce

Build the pinned compiler, then use a fresh output directory:

```sh
GOOO_BIN=/absolute/path/to/gooo GOOO_SCALING_OUT=/tmp/gooo-scaling-new \
  python3 run_scaling.py
```

The runner uses Python's standard library, refuses an existing output directory, and disables Laya for these invocations. Full stdout receipts are stored as deterministic gzip streams with SHA-256 digests in the call manifest. No compiler binaries, model weights, or caches are included.
