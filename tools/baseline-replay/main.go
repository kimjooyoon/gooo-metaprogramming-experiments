package main

import (
	"flag"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"time"
)

func main() { os.Exit(run()) }

func run() (exitCode int) {
	flags := flag.NewFlagSet("baseline-replay", flag.ContinueOnError)
	rootFlag := flags.String("root", "../..", "repository root")
	goFlag := flags.String("go-bin", "go", "Go 1.27.1 executable")
	outputFlag := flags.String("output", "", "fresh report/log directory; default is a temporary directory")
	goSeconds := flags.Int("go-timeout-seconds", 180, "per saved-module timeout")
	candidateSeconds := flags.Int("candidate-timeout-seconds", 600, "candidate-package timeout")
	if flags.Parse(os.Args[1:]) != nil {
		return 2
	}
	if flags.NArg() != 0 || *goSeconds < 1 || *goSeconds > 1800 || *candidateSeconds < 1 || *candidateSeconds > 1800 {
		return 2
	}
	output := ""
	defer func() {
		if recovered := recover(); recovered != nil {
			failure, ok := recovered.(invalidEvidence)
			if !ok {
				panic(recovered)
			}
			fmt.Fprintln(os.Stderr, "baseline validation failed:", failure.message)
			if output != "" {
				// Persist a failed attempt without modifying the retained corpus.
				raw := marshalJSON(object{"schema": "gooo/ir-composition-baseline-validation/v2", "validation": "FAIL_CLOSED", "reason": failure.message})
				_ = os.WriteFile(filepath.Join(output, "failed-attempt.json"), append(raw, '\n'), 0644)
			}
			exitCode = 1
		}
	}()
	root, err := filepath.Abs(*rootFlag)
	require(err == nil, "resolve repository root")
	if *outputFlag == "" {
		output, err = os.MkdirTemp("", "gooo-baseline-replay-")
	} else {
		name, pathErr := filepath.Abs(*outputFlag)
		require(pathErr == nil, "resolve output path")
		require(os.MkdirAll(filepath.Dir(name), 0755) == nil, "create output parent")
		err = os.Mkdir(name, 0755)
		if err == nil {
			output = name
		}
	}
	require(err == nil, "output must be fresh: %v", err)
	goBin, err := exec.LookPath(*goFlag)
	require(err == nil, "Go executable not found")
	goBin, err = filepath.Abs(goBin)
	require(err == nil, "resolve Go executable")
	sources := validatorSources(root)
	executable, err := os.Executable()
	require(err == nil, "resolve validator executable")
	validatorDigest, toolchainDigest := fileDigest(executable), fileDigest(goBin)
	version := runGo(goBin, root, output, "go-version", 15*time.Second, "version")
	require(version.exitCode == 0 && validGoVersion(version.stdout), "Go 1.27.1 required, got %q", version.stdout)
	c := loadCorpus(root)
	putJSON(filepath.Join(output, "frozen-source-resolution.json"), object{"schema": "gooo/frozen-source-resolution/v1",
		"original_freeze_sha256": freezeDigest, "files": c.frozenRows, "historical_archives_executed": false})
	old := readOld(c)
	newer := readNew(c, old)
	oldReplay := replayBaseline(c, old, goBin, output, time.Duration(*goSeconds)*time.Second)
	newReplay := replayBaseline(c, newer, goBin, output, time.Duration(*goSeconds)*time.Second)
	candidates := replayCandidates(c, goBin, output, time.Duration(*candidateSeconds)*time.Second)
	require(eq(sources, validatorSources(root)) && validatorDigest == fileDigest(executable) && toolchainDigest == fileDigest(goBin),
		"validator source, executable or Go toolchain changed during replay")
	report := object{"schema": "gooo/ir-composition-baseline-validation/v2", "created_utc": time.Now().UTC().Format(time.RFC3339Nano),
		"go_version": string(version.stdout), "validation": "PASS", "validator": "Go stdlib",
		"frozen_file_count": len(c.frozenRows), "design_freeze_sha256": freezeDigest,
		"validator_source_files": sources, "validator_source_manifest_sha256": digest(marshalJSON(sources)),
		"validator_binary_sha256": validatorDigest, "go_binary_sha256": toolchainDigest,
		"source_version_resolution": "140 current exact files and two digest-bound historical source archives",
		"model_calls":               0, "provider_operations": 0, "new_codegen_operations": 0, "new_intents": 0,
		"original_baseline": object{"run_id": old.metadata["run_id"], "compiler_revision": oldRevision,
			"source_emissions": 22, "planned": 32, "cli_failures": failureIDs(old.caseRows), "replay": oldReplay},
		"equivalence_replay": object{"run_id": newer.metadata["run_id"], "compiler_revision": newRevision,
			"source_emissions": 30, "planned": 32, "cli_failures": failureIDs(newer.caseRows), "replay": newReplay},
		"runner_source_archives":          object{"original_baseline": old.runner, "equivalence_replay": newer.runner},
		"source_unit_summary_known_issue": newer.correction, "original_candidate_compiler_failures": candidates}
	putJSON(filepath.Join(output, "validation-report.json"), report)
	text := "# Go IR composition baseline replay\n\n" +
		"The original frozen inputs, raw CLI receipts and generated sources were checked with Go 1.27.1.\n\n" +
		"- Frozen source resolution: 140 exact current files and two explicitly bound historical archives; original freeze unchanged.\n" +
		"- Original source emissions: 22/32; ten missing outputs retain unknown finite expectations.\n" +
		"- Equivalence source emissions: 30/32; two missing outputs retain unknown finite expectations.\n" +
		"- Saved independent modules recompiled and executed: 52/52. These reuse the same 32 intents.\n" +
		"- Original candidate packages: 93/96 compile, with exactly the three preserved expected compile failures.\n" +
		"- The as-run 32/0 source-unit summary is retained; its per-case records reconstruct 30/2. Only the three bound summary fields differ in the correction.\n" +
		"- Model calls, provider requests and new code generation: zero. Historical Python archives were read as bytes.\n"
	require(os.WriteFile(filepath.Join(output, "validation-report.md"), []byte(text), 0644) == nil, "write report text")
	fmt.Printf("Validation PASS; 52 saved modules, 93 valid + 3 expected failed candidate packages. Reports: %s\n", output)
	return 0
}
func validGoVersion(raw []byte) bool {
	fields := strings.Fields(string(raw))
	return len(fields) == 4 && fields[0] == "go" && fields[1] == "version" && fields[2] == "go1.27.1"
}
