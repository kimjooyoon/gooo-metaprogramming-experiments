package main

import (
	"bytes"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"
)

const revisionRelative = "revision-2"
const revisionDesignDigest = "9ef3d4bf5c3be68ef4da9c0e7c712eefb313d6bd325446e229e48b8441e33aca"
const revisionManifestDigest = "d29362bcf9894ac53dc34eb44685cfeaf46b99841574e9473285fac00bfd1dd1"
const revisionPreparerFrozen = "cffea8f3a99d19f35ac49cbb7edce9150194a20cf6d8c64bf540a92dc1c75b98"
const revisionPreparerCurrent = "ccf5b9b0b87044f832eeb9e441915166592729364530a95c189c42c6b3363ab5"
const revision2Text = `# Revision-2 independent replay in Go

Decision: **PASS**. Physical toolchain: **Go 1.27.1**.

- Original candidates: **93/96** compiled and executed, **3** expected compile failures, **0** unknown.
- Revision-2 candidates: **96/96** compiled and executed, **0** unknown.
- All **32** training suites distinguish the gold candidate from both distractors.
- All **189** result files were removed from temporary copies before execution, freshly produced, and matched their frozen bytes.
- Both saved Go reference suites executed. The Go port of the frozen Python int64 specification checked **228 + 232** finite expected values.
- All **96** Laya plans and **32** external feedback sets were checked as data against the fresh compiled observations.
- Model calls, provider requests and new code generation: **0**. Historical Python files were read as bytes.

Both revisions reuse the same 32 intentions. Candidate compilation and finite behavior are separate counts. Source AST completeness belongs to Gooo's separate receipts. The retained sources and results were unchanged by replay.
`

type revisionCorpus struct {
	root             string
	design, manifest object
	designs          []any
	vectors          map[string]object
	preparer         object
}

func verifyFiles(root string, files object, count int) {
	require(len(files) == count, "expected %d frozen files, got %d", count, len(files))
	for relative, expected := range files {
		require(digest(readBytes(local(root, relative))) == str(expected), "revision frozen file mismatch: %s", relative)
	}
}

func loadRevision(c corpus) revisionCorpus {
	r := revisionCorpus{root: filepath.Join(c.cohort, revisionRelative)}
	designRaw := readBytes(filepath.Join(r.root, "design-freeze.json"))
	manifestRaw := readBytes(filepath.Join(r.root, "revision-manifest.json"))
	require(digest(designRaw) == revisionDesignDigest && digest(manifestRaw) == revisionManifestDigest, "revision-2 freeze pins changed")
	r.design, r.manifest = obj(decode(designRaw)), obj(decode(manifestRaw))
	verifyFiles(r.root, obj(r.design["files"]), 536)
	verifyFiles(r.root, obj(r.manifest["files"]), 797)
	require(str(r.manifest["original_design_freeze_sha256"]) == freezeDigest && str(r.design["original_design_freeze_sha256"]) == freezeDigest &&
		str(r.manifest["revision2_design_freeze_sha256"]) == revisionDesignDigest, "revision lineage changed")
	require(str(r.manifest["preparer_sha256"]) == revisionPreparerFrozen && str(r.design["preparer_sha256"]) == revisionPreparerFrozen, "revision preparer binding changed")
	currentPath := "scripts/prepare_ir_composition_revision2.py"
	archiveBase := cohortRelative + "/replay-source-versions-v1/revision2-prepare"
	frozenArchive, currentArchive := archiveBase+".frozen.py.txt", archiveBase+".go1271.py.txt"
	require(digest(readBytes(local(c.root, currentPath))) == revisionPreparerCurrent &&
		digest(readBytes(local(c.root, frozenArchive))) == revisionPreparerFrozen &&
		digest(readBytes(local(c.root, currentArchive))) == revisionPreparerCurrent, "revision preparer source-version mismatch")
	r.preparer = object{"path": currentPath, "resolution": "BOUND_HISTORICAL_ARCHIVE", "frozen_sha256": revisionPreparerFrozen,
		"current_sha256": revisionPreparerCurrent, "frozen_archive": frozenArchive, "current_archive": currentArchive,
		"recovered_source_commit": "02e619c153d8313d672636b990e0334d0e87a54b", "executed": false}
	r.designs = rows(doc(filepath.Join(r.root, "catalog.json"))["designs"])
	r.vectors = index(decode(readBytes(filepath.Join(r.root, "oracle/testdata/vectors.json"))), "id")
	designIndex := index(r.designs, "id")
	require(len(designIndex) == 32 && sameKeys(designIndex, c.designs) && sameKeys(designIndex, r.vectors), "revision must retain 32 unique intent IDs/vectors")
	originalDesigns := rows(doc(filepath.Join(c.cohort, "catalog.json"))["designs"])
	seenIntent := map[string]bool{}
	for i, value := range r.designs {
		entry, original := obj(value), obj(originalDesigns[i])
		id, intent := str(entry["id"]), str(entry["intent"])
		require(id == str(original["id"]) && intent == str(original["intent"]) && intent != "" && !seenIntent[intent], "intent order/text/uniqueness changed: %s", id)
		seenIntent[intent] = true
	}
	validateRetainedCounts(r, c.vectors)
	return r
}

func finiteCount(vectors map[string]object) int {
	n := 0
	for id, vector := range vectors {
		for _, split := range []string{"training", "evaluation"} {
			for _, raw := range rows(vector[split]) {
				row := obj(raw)
				require(referenceValue(id, requiredNum(row["input"])) == requiredNum(row["expected"]), "independent expected value changed: %s/%s", id, split)
				n++
			}
		}
	}
	return n
}

func validateRetainedCounts(r revisionCorpus, original map[string]object) {
	for _, version := range []struct {
		name                    string
		compiled, failed, cases int
	}{
		{"original", 93, 3, finiteCount(original)}, {"revision2", 96, 0, finiteCount(r.vectors)},
	} {
		report := doc(filepath.Join(r.root, "evaluation", version.name+"-candidate-evaluation.json"))
		require(requiredNum(report["candidate_denominator"]) == 96 && requiredNum(report["compiled_candidates"]) == int64(version.compiled) &&
			requiredNum(report["compile_failed_candidates"]) == int64(version.failed) && requiredNum(report["unknown_candidates"]) == 0,
			"retained %s candidate denominator changed", version.name)
		require(requiredNum(report["reference_go_test_exit_code"]) == 0 && requiredNum(report["reference_python_case_count"]) == int64(version.cases), "retained %s reference observations incomplete", version.name)
	}
	discrimination := rows(doc(filepath.Join(r.root, "evaluation/revision2-candidate-discrimination.json"))["designs"])
	require(len(index(discrimination, "id")) == 32, "retained discrimination denominator changed")
	for _, raw := range discrimination {
		row := obj(raw)
		require(row["both_distractors_separated"] == true && row["gold_passes_all_training"] == true, "retained discrimination incomplete")
	}
}

type packageReplay struct {
	statuses    map[string]string
	passedTests map[string]map[string]bool
}

func parsePackageReplay(raw []byte, prefix string) packageReplay {
	r := packageReplay{statuses: map[string]string{}, passedTests: map[string]map[string]bool{}}
	for _, line := range bytes.Split(raw, []byte{'\n'}) {
		if len(bytes.TrimSpace(line)) == 0 {
			continue
		}
		event := obj(decode(line))
		name, action, test := str(event["Package"]), str(event["Action"]), str(event["Test"])
		if name != prefix && !strings.HasPrefix(name, prefix+"/") {
			continue
		}
		if test == "" && (action == "pass" || action == "fail") {
			_, duplicate := r.statuses[name]
			require(!duplicate, "duplicate terminal package event: %s", name)
			r.statuses[name] = action
		}
		if test != "" && action == "pass" {
			if r.passedTests[name] == nil {
				r.passedTests[name] = map[string]bool{}
			}
			require(!r.passedTests[name][test], "duplicate passed test event: %s/%s", name, test)
			r.passedTests[name][test] = true
		}
	}
	return r
}

func expectedOriginalFailure(id, option string) bool {
	return id == "bl21_saved_range_predicates" && (option == "option_a" || option == "option_c") || id == "bl23_nonzero_bounded_flag" && option == "option_b"
}

func candidatePackage(number int, id, option string) string {
	return fmt.Sprintf("case%02d_%s_%s", number, id, option)
}

func summarizeCandidates(root, base, module, prefix string, designs []any, vectors map[string]object, events packageReplay, revised bool) object {
	valid, failed, finiteRows := 0, 0, 0
	designRows := []object{}
	for number, value := range designs {
		design := obj(value)
		id := str(design["id"])
		plan := doc(local(base, str(design["body_fill_plan"])))
		options := index(plan["candidates"], "id")
		require(len(options) == 3, "expected three declared candidates: %s", id)
		candidates := object{}
		for _, optionRaw := range rows(plan["candidates"]) {
			option := str(obj(optionRaw)["id"])
			name := candidatePackage(number+1, id, option)
			packageID := prefix + "/" + name
			resultPath := filepath.Join(root, "evaluation", module, name, "candidate-results.json")
			if !revised && expectedOriginalFailure(id, option) {
				_, err := os.Lstat(resultPath)
				require(events.statuses[packageID] == "fail" && os.IsNotExist(err) && len(events.passedTests[packageID]) == 0, "invalid original candidate emitted/executed: %s", name)
				failed++
				candidates[option] = object{"status": "compile_failure", "observed": 0}
				continue
			}
			require(events.statuses[packageID] == "pass" && events.passedTests[packageID]["TestCompiledCandidateFiniteCases"], "candidate test not freshly passed: %s", name)
			actual := rows(decode(readBytes(resultPath)))
			scores, count := scoreCandidate(actual, vectors[id], id)
			valid++
			finiteRows += count
			candidates[option] = object{"status": "compiled_and_executed", "training": scores["training"], "evaluation": scores["evaluation"]}
		}
		if revised {
			gold := str(design["gold_candidate_id"])
			_, declared := candidates[gold]
			require(declared, "undeclared gold candidate: %s", id)
			for option, value := range candidates {
				score := obj(at(value, "training"))
				perfect := requiredNum(score["passed"]) == requiredNum(score["total"])
				require(requiredNum(score["total"]) > 0 && perfect == (option == gold), "fresh gold/distractor discrimination failed: %s/%s", id, option)
			}
		}
		designRows = append(designRows, object{"id": id, "candidates": candidates})
	}
	wantValid := 93
	if revised {
		wantValid = 96
	}
	require(valid == wantValid && failed == 96-wantValid && len(events.statuses) == 96, "fresh candidate denominator changed")
	return object{"designs": 32, "candidates_planned": 96, "compiled_and_executed": valid, "compile_failed": failed, "unknown": 0,
		"finite_input_rows": finiteRows, "design_results": designRows}
}

func scoreCandidate(actual []any, vector object, id string) (object, int) {
	scores := object{}
	offset := 0
	for _, split := range []string{"training", "evaluation"} {
		planned := rows(vector[split])
		passed := int64(0)
		require(len(actual) >= offset+len(planned), "candidate observation missing: %s/%s", id, split)
		for i, raw := range planned {
			want, got := obj(raw), obj(actual[offset+i])
			x, expected := requiredNum(want["input"]), requiredNum(want["expected"])
			require(len(got) == 4 && str(got["split"]) == split && requiredNum(got["input"]) == x && requiredNum(got["expected"]) == expected, "candidate rows differ from frozen vectors: %s/%s/%d", id, split, i)
			require(referenceValue(id, x) == expected, "candidate expectation differs from independent reference")
			if requiredNum(got["actual"]) == expected {
				passed++
			}
		}
		offset += len(planned)
		scores[split] = object{"passed": number(passed), "total": number(int64(len(planned)))}
	}
	require(offset == len(actual), "extra candidate observation: %s", id)
	return scores, offset
}

// Keep score values in the same precise JSON-number representation as receipts.
func number(value int64) any { return decode(fmt.Appendf(nil, "%d", value)) }

func suiteDigest(cases []any) string {
	type finite struct {
		Input    int64 `json:"input"`
		Expected int64 `json:"expected"`
	}
	values := make([]finite, 0, len(cases))
	for _, raw := range cases {
		row := obj(raw)
		values = append(values, finite{requiredNum(row["input"]), requiredNum(row["expected"])})
	}
	return "sha256:" + digest(marshalJSON(values))
}

func validatePlans(r revisionCorpus, executionRoot string) {
	feedbackCount := 0
	for number, value := range r.designs {
		entry := obj(value)
		id, basename := str(entry["id"]), str(entry["plan_basename"])
		vector := r.vectors[id]
		training := rows(vector["training"])
		fill := doc(local(r.root, str(entry["body_fill_plan"])))
		require(eq(fill["test_cases"], vector["training"]) && str(fill["intent"]) == str(entry["intent"]) && len(index(fill["candidates"], "id")) == 3, "body-fill suite/intent changed: %s", id)
		for _, arm := range []string{"legacy-no-feedback", "compact-no-feedback", "compact-external-feedback"} {
			plan := doc(local(r.root, "plans/laya/"+arm+"/"+basename))
			require(str(plan["provider_model"]) == "english" && eq(plan["test_cases"], vector["training"]) && eq(plan["holdout_test_cases"], vector["evaluation"]) &&
				eq(plan["candidates"], fill["candidates"]) && str(plan["intent"]) == str(entry["intent"]), "provider plan routing/candidates/suite changed: %s/%s", id, arm)
			if arm == "legacy-no-feedback" {
				_, present := plan["prompt_profile"]
				require(!present, "legacy prompt profile changed")
			} else {
				require(str(plan["prompt_profile"]) == "compact", "compact prompt profile missing")
			}
			if arm != "compact-external-feedback" {
				continue
			}
			feedback := obj(plan["external_training_feedback"])
			require(str(feedback["source_digest"]) == "sha256:"+digest(readBytes(local(r.root, str(entry["fixture"])))) &&
				str(feedback["training_suite_sha256"]) == suiteDigest(training), "feedback source/suite binding changed: %s", id)
			candidate := str(feedback["candidate_id"])
			_, declared := index(plan["candidates"], "id")[candidate]
			require(declared, "feedback candidate undeclared")
			resultPath := filepath.Join(executionRoot, "evaluation/revision2-candidates", candidatePackage(number+1, id, candidate), "candidate-results.json")
			observations := []any{}
			seen := map[int64]bool{}
			for _, raw := range rows(decode(readBytes(resultPath))) {
				row := obj(raw)
				if str(row["split"]) != "training" {
					continue
				}
				x, expected, actual := requiredNum(row["input"]), requiredNum(row["expected"]), requiredNum(row["actual"])
				require(!seen[x], "duplicate feedback training input: %s", id)
				seen[x] = true
				observations = append(observations, object{"input": row["input"], "expected": row["expected"], "actual": row["actual"], "passed": actual == expected})
			}
			require(len(observations) == len(training) && eq(feedback["observations"], observations), "feedback differs from complete fresh training observations: %s", id)
			for _, raw := range training {
				require(seen[requiredNum(obj(raw)["input"])], "missing feedback training input: %s", id)
			}
			feedbackCount++
		}
	}
	require(feedbackCount == 32, "feedback denominator changed")
}

func replayRevision2(c corpus, goBin, output string, timeout time.Duration) object {
	r := loadRevision(c)
	putJSON(filepath.Join(output, "revision2-source-resolution.json"), object{"schema": "gooo/revision2-source-resolution/v1", "preparer": r.preparer,
		"design_freeze_sha256": revisionDesignDigest, "revision_manifest_sha256": revisionManifestDigest, "design_files": 536, "manifest_files": 797, "historical_archives_executed": false})
	validatePlans(r, r.root)
	temporary, err := os.MkdirTemp("", "gooo-revision2-replay-")
	require(err == nil, "create replay temporary tree")
	defer os.RemoveAll(temporary)
	copied := filepath.Join(temporary, "revision-2")
	require(os.CopyFS(copied, os.DirFS(r.root)) == nil, "copy revision source")
	removed := 0
	for relative := range obj(r.manifest["files"]) {
		if strings.HasSuffix(relative, "/candidate-results.json") {
			require(os.Remove(local(copied, relative)) == nil, "remove copied result: %s", relative)
			removed++
		}
	}
	require(removed == 189, "expected 189 copied candidate results; found %d", removed)
	modules := []struct {
		name, prefix, test string
		exit, packages     int
	}{
		{"original-reference", "example.invalid/gooo/ir-composition-reference", "TestIndependentGoReferenceOraclesMatchPythonInt64Vectors", 0, 1},
		{"revision2-reference", "example.invalid/gooo/ir-composition-reference", "TestIndependentGoReferenceOraclesMatchPythonInt64Vectors", 0, 1},
		{"original-candidates", "example.invalid/gooo/ir-composition-revision2-original", "", 1, 96},
		{"revision2-candidates", "example.invalid/gooo/ir-composition-revision2-revised", "", 0, 96},
	}
	events := make([]packageReplay, len(modules))
	processes := []object{}
	for i, module := range modules {
		process := runGo(goBin, filepath.Join(copied, "evaluation", module.name), output, "revision2-"+module.name, timeout, "test", "-json", "-count=1", "./...")
		require(!process.timedOut && process.exitCode == module.exit, "unexpected %s process status: %d", module.name, process.exitCode)
		events[i] = parsePackageReplay(process.stdout, module.prefix)
		require(len(events[i].statuses) == module.packages, "missing %s terminal packages", module.name)
		if module.test != "" {
			require(events[i].statuses[module.prefix] == "pass" && events[i].passedTests[module.prefix][module.test], "reference test did not execute: %s", module.name)
		}
		processes = append(processes, object{"module": module.name, "exit_code": process.exitCode, "package_count": len(events[i].statuses),
			"stdout_sha256": digest(process.stdout), "stderr_sha256": digest(process.stderr), "elapsed_ms": float64(process.elapsed) / float64(time.Millisecond)})
	}
	originalDesigns := rows(doc(filepath.Join(c.cohort, "catalog.json"))["designs"])
	original := summarizeCandidates(copied, c.cohort, "original-candidates", modules[2].prefix, originalDesigns, c.vectors, events[2], false)
	revised := summarizeCandidates(copied, r.root, "revision2-candidates", modules[3].prefix, r.designs, r.vectors, events[3], true)
	validatePlans(r, copied)
	verifyFiles(copied, obj(r.manifest["files"]), 797)
	verifyFiles(copied, obj(r.design["files"]), 536)
	loadRevision(c)
	loadCorpus(c.root)
	return object{"schema": "gooo/ir-composition-revision2-independent-replay/v2", "decision": "PASS", "created_utc": time.Now().UTC().Format(time.RFC3339Nano),
		"model_calls": 0, "provider_operations": 0, "gooo_cli_calls": 0, "new_codegen_operations": 0, "new_intents": 0,
		"design_freeze_sha256": revisionDesignDigest, "revision_manifest_sha256": revisionManifestDigest, "preparer_resolution": r.preparer,
		"original": original, "revision_2": revised, "same_32_intentions": true, "fresh_discrimination_recomputed": true,
		"fresh_candidate_results": removed, "fresh_result_files_match_frozen_bytes": true, "python_executions": 0,
		"ported_int64_reference_observations": object{"original": finiteCount(c.vectors), "revision_2": finiteCount(r.vectors)},
		"laya_plans_checked_as_data":          96, "feedback_sets_bound_to_fresh_training": 32, "replay": processes,
		"scope": "Finite candidate behavior; source AST completeness is a separate Gooo receipt dimension."}
}
