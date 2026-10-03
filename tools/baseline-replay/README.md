# Saved IR baseline replay in Go

This stdlib Go command checks the retained September 30 study and executes its
saved generated programs. Run from this directory with Go 1.27.1:

```sh
go test -race -count=1 ./...
go vet ./...
go run . --root ../.. --go-bin "$(command -v go)" --output /tmp/gooo-baseline-new-run
```

Choose a fresh output directory. The command writes process stdout/stderr,
exit/timeout/timing records, the frozen source resolutions, and JSON/Markdown
reports. A failed attempt retains the process logs already written and a
`FAIL_CLOSED` record. Linux and macOS are supported. Each module has its own
deadline; cancellation kills the process group and joins output pipes. Output
buffers are capped at 16 MiB per stream. Go module proxy and checksum access are
disabled, and model/provider environment variables are removed from child runs.

## What is checked

- The original design-freeze digest and all 142 frozen source bindings.
- The same 32 unique input vectors, plans, fixtures and activity names.
- Original compiler source/binary pins, raw CLI stdout/stderr hashes, exact
  emitted Go bytes, source-unit receipts and aggregate finite denominators.
- Archived runner bytes bound to each saved run's metadata.
- The three permitted summary correction fields and the exact original 32/0
  versus reconstructed 30/2 measured/unknown counts. Raw outputs stay intact.
- The saved independent test sources and vectors, then fresh Go execution of
  22 original and 30 equivalence-fix modules. Every finite result marker is
  checked with exact int64 values, including boundary integers.
- Original 96 candidate packages: 93 valid packages and exactly three expected
  compiler failures. Test functions are skipped for this separate compile check.

The v2 report belongs to this Go validator. The earlier Python validator and its
failed workflow runs remain inspectable. The Go command reads historical Python
archives as bytes; it executes Go commands. It performs zero compiler generation,
model calls, provider requests or training updates. Both baselines reuse the same
32 intents. Missing generated outputs retain unknown finite expectations.

## Explicit source-version repair

The Go1.27.1 update changed two historical preparation scripts after their bytes
entered the study's freeze. Their current files still contain Go1.27.1. The
original freeze, plans, receipts and saved result files keep their exact bytes.

`freeze.go` binds both the current and original digests for those two paths. The
original bytes are recovered from commit
`02e619c153d8313d672636b990e0334d0e87a54b` and kept as `.py.txt` data alongside
copies of the Go1.27.1 versions in
[`replay-source-versions-v1`](../../cohorts/ir-composition-curriculum-2026-09-30/replay-source-versions-v1).
The report says `BOUND_HISTORICAL_ARCHIVE` for those two files and
`CURRENT_EXACT` for the other 140. Changes to either version, either archive,
the freeze or any other frozen input fail the validation. These explicit
bindings establish byte consistency and version lineage; the fresh process logs
provide the observations of this replay.
