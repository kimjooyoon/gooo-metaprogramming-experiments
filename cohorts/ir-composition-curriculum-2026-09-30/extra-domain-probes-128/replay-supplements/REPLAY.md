# Extra-domain postselection replay

The frozen probe set contains 128 new input treatments: four unseen signed-int64 values for each of the same 32 revision-2 designs. It does not add 128 independent intents. The values are not part of the search plans, prompts, or feedback. Candidate selection must finish before they are read.

## Adapt a TDD v8 capture

The capture adapter reads a complete or partial TDD v8 run, checks its frozen design and source archive pins, recomputes the raw request/reply and native-choice bindings, and hashes emitted source bytes. It makes no provider calls and executes no Go. It copies the evidence into a new append-only bundle under `extra-domain-probes-128/captures/`.

```sh
python3 scripts/adapt_tdd_v8_extra_domain_capture.py \
  --run-dir /path/to/gooo-ir-composition-tdd-experiments/results/<tdd-v8-run-id> \
  --output cohorts/ir-composition-curriculum-2026-09-30/extra-domain-probes-128/captures/<tdd-v8-run-id>

python3 scripts/adapt_tdd_v8_extra_domain_capture.py \
  --verify-bundle cohorts/ir-composition-curriculum-2026-09-30/extra-domain-probes-128/captures/<tdd-v8-run-id>
```

All 64 planned cells appear in the adapter report, including missing, failed, and invalid cells. Only a complete, independently bound capture receives the replayable `source-manifest.json`; partial captures retain a 64-row `source-manifest.draft.json` and are not replayable. Producer validation booleans are recorded for comparison and do not replace checks of exact bytes and native receipts.

The captured source run used for this study is `ir-composition-tdd-v8-20260930T104054Z-d868d3ee7f71`. Its full local adapter bundle passed `--verify-bundle` before the public evidence derivative was created. The public bundle is `captures/ir-composition-tdd-v8-20260930T104054Z-d868d3ee7f71-public/`. It retains the 64 plans, native CLI JSON, raw provider requests and replies, emitted Go, receipts, source manifest, and adapter report. The exporter omits copied raw invocation records, local preexecution/design metadata, and archived study-code files because they contain machine-local paths. Their original file hashes remain in the adapter report; the public verifier checks the frozen design and archive hash pins, each included byte file, each raw request/reply, native choice and output, source, and receipt. The omitted files remain in the original source run.

Use the public verifier after export:

```sh
python3 scripts/adapt_tdd_v8_extra_domain_capture.py \
  --verify-public-bundle cohorts/ir-composition-curriculum-2026-09-30/extra-domain-probes-128/captures/ir-composition-tdd-v8-20260930T104054Z-d868d3ee7f71-public
```

## Run the frozen probes

After the root measurement gate is open, replay a verified public evidence bundle into a new attempt directory:

```sh
python3 scripts/replay_extra_domain_probes_v2.py \
  --source-root cohorts/ir-composition-curriculum-2026-09-30/extra-domain-probes-128/captures/<tdd-v8-run-id>-public \
  --source-manifest cohorts/ir-composition-curriculum-2026-09-30/extra-domain-probes-128/captures/<tdd-v8-run-id>-public/source-manifest.json \
  --output cohorts/ir-composition-curriculum-2026-09-30/extra-domain-probes-128/execution/<new-attempt> \
  --go-bin /path/to/pinned/go1.27.0/bin/go \
  --after-root-measurement-gate
```

The workflow-dispatch replay runs the same model-free verifier and Go replay. It skips when no committed replayable public bundle exists or the explicit root-gate input is false. Dynamic branch coverage and branch-test adequacy remain unmeasured; region tags describe designed input regions only. Results stay in the planned denominator, with unexecuted, invalid, and failed rows reported as unknown.

Expected values are computed by separately compiling the frozen revision-2 handwritten Go reference. That reference shares source lineage with the earlier finite oracle, so agreement is a correlated-oracle diagnostic rather than independent ground truth. Agreement on 128 values does not prove full-domain correctness.

## Recorded replay attempts

The first replay attempt is preserved as `execution/ir-composition-extra-domain-tdd-v8-20260930T104054Z-d868d3ee7f71-public/`. It ran no probes: its locally selected Go binary had SHA-256 `a19a71df81715c12d9a7e81bab036c12696fec1ddbd4258b48a2131a9080b267`, while that attempt mistakenly expected the Gooo compiler binary digest. The public failure receipt removes the local executable path but retains the exact mismatch and zero-row outcome.

The corrected Go 1.27.0 replay is preserved in `execution/ir-composition-extra-domain-tdd-v8-20260930T104054Z-d868d3ee7f71-r2-public/`. The original local report SHA-256 was `d616cace09ef228ea7418ef3bb21a86b932e0bb245f48380258f177f6140432b`; the public derivative changes only its `go_toolchain.path` disclosure, keeps all result rows, and binds the source and public report hashes in `public-report-derivation.json`. The two arms observed 87/128 and 128/128 finite matches against the correlated handwritten reference. This is a finite postselection result over the same 32 designs, with no model or candidate-selection calls; dynamic branch coverage and branch-test adequacy are unmeasured.

The pre-execution derivation receipt is preserved separately from the post-execution clarification. The clarification records that the current derivation receipt was edited after replay and does not claim otherwise.
