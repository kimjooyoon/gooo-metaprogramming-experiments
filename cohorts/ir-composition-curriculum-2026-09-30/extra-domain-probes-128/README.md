# Extra domain probes: 128 inputs

This freeze adds four unseen signed-int64 inputs for each of the same 32 revision-2 designs. They are 128 probe treatments, not 128 new intents. Values are fixed in advance; there is no random sampling seed. Each design's four values are unique and disjoint from its frozen training and holdout values. The selection is balanced at 16 inputs per semantic area.

These inputs are post-selection only. Do not copy them into plans, prompts, candidate selection, or feedback. Expected values are intentionally absent here. After capture, the replay script separately compiles the frozen revision-2 handwritten Go reference and compares each arm's captured emitted Go source against it. The reference shares source lineage with the earlier finite oracle, so this is a correlated-oracle diagnostic, not independent ground truth.

The probe roles mark designed input regions. They are not dynamic branch-coverage evidence. Report executed probe count, region-target coverage, unknowns, compile failures, and finite matches separately. Passing these 128 values does not establish full-domain correctness.

To verify the unchanged freeze: `python3 scripts/prepare_extra_domain_probes.py --verify`.
