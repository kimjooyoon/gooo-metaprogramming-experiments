# IR-search cohort validation

All 12 saved CLI outputs were compiled and checked against the independent Go oracle.
The committed Laya capture was read only. The separate local mock-provider replay checks protocol handling and is not a model evaluation.

- Saved invocations: 12
- Captured Laya rounds: 6
- Exact training-only Laya choices: 2/6
- Exact first choices: 2/4 intents
- Final selected search bodies: training and post-selection holdout are reported separately in the JSON artifact; no speedup claim is made
- Deterministic replays: 4 intents, each repeated identically
- Mock protocol replays: 4 intents; no Laya calls
- CPU/RSS evidence: separate per-invocation records; sampled RSS is not a process peak, and no-provider controls have one Laya-server snapshot whose zero CPU delta is unknown
- Manifest digest: the run records a pre-finalization snapshot whose bytes were not retained; fixture and plan snapshots are checked directly
