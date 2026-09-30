# Fixed-compiler body-fill smoke (3 calls)

- Compiler commit: `ec4bf3e5f4119118b501c1b45862936eb46b95b7`; binary SHA-256: `28c5906f4cb9581f8833cebabfad8d977c8d142aed5e5a3f8361d7da4340fa35`.
- Laya: `laya-rl-agent` revision `55cf4c4ebb4ebe31b2550e8bdf3bd21b99753851`, CPU / four threads, already warm from the preceding selection cohort.
- Evaluator: `gooo/bodycodegen-int64-ast-interpreter/v2`. All three runs had `PASS`, typecheck success and deterministic replay.
- Raw Laya proposal: **`negate`, 5/9 (55.56%)** on every call. Deterministic score arbitration emitted **`zero`, 9/9 (100%)** every call. Regret of raw proposal: **44.44 percentage points**.
- Whole command latency p50/range: **373.841 ms**, **372.178–911.238 ms**. Laya decision p50/range: **367.162 ms**, **366.456–381.632 ms**. p95 omitted because n=3.
- Server process CPU: **2.62 s** across the **n=3 warm smoke calls**, whose summed invocation wall time was **1.657 s**; normalized to **158.1% of one core**. The denominator is the sum of these three invocation durations, not total host CPU; unrelated local work is excluded. RSS started at **2017.9 MiB** and peaked at **2077.2 MiB** sampled at 50 ms intervals.
- Verification boundary: Gooo’s internal typecheck and deterministic replay passed. No external `go build` and no generated Go execution were run.

The plan is `/Users/alice/meta-go/.worktrees/gooo-autonomous-governance-20260930/examples/body-codegen/ir-fill-clamp-plan.json`; the fixture is `examples/body-codegen/ir-fill-clamp.gooo.fixture`. Exact JSON stdout/stderr receipts are in `calls/`, and per-call resource samples were saved before this report was generated. The nine-case score is a finite local evaluator result, not GitHub CI or a full-domain proof.
