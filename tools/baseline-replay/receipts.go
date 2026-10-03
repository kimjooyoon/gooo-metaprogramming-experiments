package main

import (
	"bytes"
	"path/filepath"
	"sort"
)

const oldRevision = "bb5c1ec2f81cbfb17ac6fb2f7a9e1d7b67168e7f"
const newRevision = "60cf7f49b0e302a6bebb42bc8da90f3ed19b2b82"
const oldBinary = "47b9f3bd1b365d18771ba36b0a2b472b139fdb6a08b404697e188478dce38c6e"
const newBinary = "7329b8d255b083bacfd7d44c7271caa4e3c8254bd48cc085068c92665a02591a"

type counts struct {
	numerator, denominator int64
	status                 string
}
type baseline struct {
	label, parent, revision       string
	report, metadata, fitness     object
	caseRows, plans               map[string]object
	runner, aggregate, correction object
}

func normalizedStatus(value any) string {
	status := str(value)
	if status == "" || status == "MISSING" || status == "UNKNOWN" {
		return "UNKNOWN"
	}
	return status
}
func countRow(row object) counts {
	n, d := num(row["numerator"]), num(row["denominator"])
	require(n >= 0 && d >= 0 && n <= d, "invalid source-unit counts")
	s := normalizedStatus(row["status"])
	if d == 0 {
		require(s == "UNKNOWN" && n == 0, "unmeasured source-unit row must be UNKNOWN 0/0")
	} else {
		require(s == "PASS", "measured source-unit row must be PASS")
	}
	return counts{n, d, s}
}
func sourceDimension(report object) counts {
	var dimension object
	for _, value := range rows(at(report, "completeness_receipt", "dimensions")) {
		row := obj(value)
		if str(row["id"]) == "source_ast_coverage" {
			require(dimension == nil, "duplicate source_ast_coverage dimension")
			dimension = row
		}
	}
	require(dimension != nil, "missing source_ast_coverage")
	c := countRow(dimension)
	require(str(dimension["status"]) == c.status, "raw source-unit status must be registered")
	require(num(report["source_semantic_units"]) == c.denominator && num(report["lowered_semantic_units"]) == c.numerator,
		"raw semantic-unit totals differ from source_ast_coverage")
	return c
}
func runnerArchive(parent string, metadata object, provenanceName, pathKey, shaKey, matchesKey string) object {
	provenance := doc(provenanceName)
	rel := str(provenance[pathKey])
	hash := digest(readBytes(local(parent, rel)))
	require(hash == str(metadata["runner_script_sha256"]) && hash == str(provenance[shaKey]), "runner archive digest mismatch")
	require(provenance[matchesKey] == true, "runner archive metadata binding is absent")
	return object{"path": rel, "sha256": hash, "matches_run_metadata": true,
		"reconstructed_after_run": provenance["reconstructed_after_run"] == true}
}
func readOld(c corpus) baseline {
	b := baseline{label: "original_attempt_2", parent: c.old, revision: oldRevision}
	b.metadata = doc(filepath.Join(c.old, "run-metadata.json"))
	b.report = doc(filepath.Join(c.old, "execution-report.json"))
	correction := doc(filepath.Join(c.corrected, "corrected-independent-go-report.json"))
	b.fitness = obj(correction["corrected_independent_go_validation"])
	b.runner = runnerArchive(c.old, b.metadata, filepath.Join(c.corrected, "runner-provenance.json"),
		"capture_runner_path", "capture_runner_sha256", "capture_runner_matches_run_metadata")
	require(str(at(b.metadata, "binary", "source_revision")) == oldRevision && str(at(b.metadata, "binary", "sha256")) == oldBinary,
		"original compiler source/binary pin mismatch")
	require(str(b.report["design_freeze_sha256"]) == freezeDigest, "original freeze digest mismatch")
	require(num(at(b.report, "execution_policy", "invocations_attempted")) == 32 &&
		num(at(b.report, "cli_outcomes", "generated_source_count")) == 22, "original CLI denominator mismatch")
	require(at(correction, "raw_cli_capture_validation", "all_raw_stdout_and_stderr_hashes_match") == true,
		"original correction does not confirm raw CLI digests")
	require(num(b.fitness["planned_designs"]) == 32 && num(b.fitness["passed_all_vectors"]) == 22 &&
		num(b.fitness["unknown_no_emitted_source"]) == 10, "original finite denominator mismatch")
	require(num(at(correction, "original_go_harness_attempt", "failed_or_incomplete_cases")) == 22,
		"original failed harness lineage changed")
	verifyBaseline(c, &b, 22, 410)
	return b
}
func verifyCorrection(raw, corrected, receipt object) {
	expected := map[string][2]int64{"observed_receipts": {32, 30}, "unknown_receipts": {0, 2}, "receipts_available": {0, 32}}
	before, after := obj(raw["source_unit_completeness"]), obj(corrected["source_unit_completeness"])
	_, exists := before["receipts_available"]
	require(!exists, "as-run receipts_available field unexpectedly exists")
	for key, pair := range expected {
		require(num(before[key]) == pair[0] && num(after[key]) == pair[1], "unexpected source-unit correction %s", key)
	}
	clone := obj(decode(marshalJSON(corrected)))
	summary := obj(clone["source_unit_completeness"])
	delete(summary, "receipts_available")
	summary["observed_receipts"], summary["unknown_receipts"] = before["observed_receipts"], before["unknown_receipts"]
	require(eq(clone, raw), "corrected report changes fields outside the three declared summary fields")
	diffs := index(receipt["changed_json_paths"], "path")
	require(len(diffs) == 3, "correction must describe exactly three fields")
	for key, pair := range expected {
		row := diffs["source_unit_completeness."+key]
		require(row != nil && num(row["old"]) == pair[0] && num(row["new"]) == pair[1], "correction receipt differs: %s", key)
		if key == "receipts_available" {
			require(row["old"] == nil, "correction old receipts_available must be null")
		}
	}
	require(str(receipt["reason"]) != "" && requiredNum(receipt["model_calls"]) == 0 &&
		receipt["raw_cli_outputs_receipts_generated_go_and_finite_scores_modified"] == false,
		"correction is not a model-free summary-only derivation")
}
func readNew(c corpus, old baseline) baseline {
	b := baseline{label: "condition_equivalence_60cf7f49", parent: c.newer, revision: newRevision}
	b.metadata = doc(filepath.Join(c.newer, "run-metadata.json"))
	rawBytes := readBytes(filepath.Join(c.newer, "execution-report.json"))
	raw := obj(decode(rawBytes))
	correctedBytes := readBytes(filepath.Join(c.newer, "derived-summary-correction-v1/corrected-execution-report.json"))
	b.report = obj(decode(correctedBytes))
	b.fitness = obj(b.report["finite_fitness"])
	receiptBytes := readBytes(filepath.Join(c.newer, "derived-summary-correction-v1/correction-receipt.json"))
	receipt := obj(decode(receiptBytes))
	require(str(receipt["source_execution_report_sha256"]) == digest(rawBytes) &&
		str(receipt["corrected_execution_report_sha256"]) == digest(correctedBytes), "correction is not byte bound")
	verifyCorrection(raw, b.report, receipt)
	b.runner = runnerArchive(c.newer, b.metadata, filepath.Join(c.newer, "runner-provenance.json"),
		"runner_source_path", "runner_sha256", "matches_run_metadata")
	require(str(at(b.report, "new_compiler", "source_revision")) == newRevision &&
		str(at(b.report, "new_compiler", "sha256")) == newBinary, "equivalence compiler source/binary pin mismatch")
	require(requiredNum(at(b.report, "study_identity", "new_intent_count")) == 0 &&
		num(at(b.report, "study_identity", "frozen_intent_count")) == 32, "equivalence is not the same 32-intent cohort")
	require(str(at(b.report, "run_provenance", "design_freeze_sha256")) == freezeDigest, "equivalence freeze digest mismatch")
	require(num(at(b.report, "cli_outcomes", "planned")) == 32 && num(at(b.report, "cli_outcomes", "attempted")) == 32,
		"equivalence CLI denominator mismatch")
	require(at(b.report, "frozen_input_integrity", "verified_after_run") == true &&
		len(rows(at(b.report, "frozen_input_integrity", "post_run_mismatches"))) == 0, "post-run frozen integrity failed")
	verifyBaseline(c, &b, 30, 516)
	for id, plan := range b.plans {
		for _, key := range []string{"plan_sha256", "fixture_sha256", "vector_sha256"} {
			require(eq(plan[key], old.plans[id][key]), "frozen plan/fixture/vector changed: %s/%s", id, key)
		}
	}
	actualFailures := failureIDs(b.caseRows)
	require(eq(actualFailures, []string{"bl21_saved_range_predicates", "bl23_nonzero_bounded_flag"}), "unexpected equivalence CLI failures")
	recovered := []string{}
	for id, row := range old.caseRows {
		if str(at(row, "cli", "emitted_source_path")) == "" && str(at(b.caseRows[id], "cli", "emitted_source_path")) != "" {
			recovered = append(recovered, id)
		}
	}
	sort.Strings(recovered)
	require(eq(recovered, []string{"cc01_inclusive_band", "cc02_nonzero_disjunction", "cc03_two_islands", "cc04_outer_cutoffs",
		"cp17_nonpositive_inclusive", "cp18_exact_release_code", "cp19_range_without_origin", "cp20_strict_symmetric_window"}), "condition recoveries changed")
	rawAggregate := aggregate(c, raw, b.caseRows, 30, 516, true)
	b.correction = object{"receipt_sha256": digest(receiptBytes), "as_run_observed_unknown": []int{32, 0},
		"corrected_observed_unknown": []int{30, 2}, "raw_aggregate": rawAggregate, "corrected_aggregate": b.aggregate}
	return b
}
func verifyBaseline(c corpus, b *baseline, emitted, units int64) {
	require(requiredNum(b.metadata["model_calls"]) == 0 && requiredNum(b.metadata["provider_operations"]) == 0, "baseline is not model/provider free")
	b.caseRows = index(b.report["design_results"], "case_id")
	b.plans = index(doc(filepath.Join(b.parent, "planned-cases.json"))["cases"], "id")
	require(len(b.caseRows) == 32 && sameKeys(b.caseRows, c.vectors) && sameKeys(b.plans, c.vectors), "baseline case IDs changed")
	var observed int64
	for id, row := range b.caseRows {
		plan, design, vector := b.plans[id], c.designs[id], c.vectors[id]
		require(str(row["activity"]) == str(vector["activity"]), "baseline activity changed: %s", id)
		for _, kind := range []string{"fixture", "body_fill_plan"} {
			rel := str(design[kind])
			require(str(plan[kind]) == rel, "plan index path changed: %s/%s", id, kind)
			key := "fixture_sha256"
			if kind == "body_fill_plan" {
				key = "plan_sha256"
			}
			expected := str(obj(c.freeze["files"])[cohortRelative+"/"+rel])
			require(expected != "" && str(plan[key]) == expected, "plan index digest changed: %s/%s", id, key)
		}
		caseDir := filepath.Join(b.parent, "cases", id)
		vectorRaw := readBytes(filepath.Join(caseDir, "inputs/python-vector.json"))
		require(eq(decode(vectorRaw), vector) && digest(vectorRaw) == str(plan["vector_sha256"]), "copied vector/digest changed: %s", id)
		if b.label != "original_attempt_2" {
			require(digest(readBytes(filepath.Join(caseDir, "inputs/plan.json"))) == str(plan["plan_sha256"]) &&
				digest(readBytes(filepath.Join(caseDir, "inputs/fixture.gooo"))) == str(plan["fixture_sha256"]), "copied plan/fixture changed: %s", id)
		}
		stdout, stderr := readBytes(filepath.Join(caseDir, "cli/stdout.raw")), readBytes(filepath.Join(caseDir, "cli/stderr.raw"))
		require(digest(stdout) == str(at(row, "cli", "stdout_sha256")) && digest(stderr) == str(at(row, "cli", "stderr_sha256")), "CLI raw digest changed: %s", id)
		payload := obj(decode(stdout))
		report := payload
		if nested, ok := payload["report"].(map[string]any); ok {
			report = nested
		}
		require(sourceDimension(report) == countRow(obj(row["source_unit_completeness"])), "raw/per-case source units changed: %s", id)
		source := str(payload["source"])
		hasSource := str(at(row, "cli", "emitted_source_path")) != ""
		require((source != "") == hasSource, "CLI source availability changed: %s", id)
		if b.label != "original_attempt_2" {
			require(hasSource == (str(at(row, "cli", "baseline_status")) == "CLI_PASS_WITH_SOURCE"), "CLI status changed: %s", id)
		}
		if hasSource {
			observed++
			generated := readBytes(filepath.Join(caseDir, "generated.go"))
			require(bytes.Equal(generated, []byte(source)), "raw/captured Go differs: %s", id)
			require(digest(generated) == str(at(row, "cli", "emitted_source_sha256")) && str(report["generated_digest"]) == "sha256:"+digest(generated), "generated digest changed: %s", id)
			if b.label != "original_attempt_2" {
				require(str(report["compiler_source_sha"]) == newRevision, "receipt compiler pin changed: %s", id)
			}
		}
	}
	require(observed == emitted, "baseline source count differs: got %d want %d", observed, emitted)
	b.aggregate = aggregate(c, b.report, b.caseRows, emitted, units, false)
}
func aggregate(c corpus, report object, caseRows map[string]object, emitted, units int64, knownMismatch bool) object {
	summary := obj(report["source_unit_completeness"])
	byID := index(summary["per_case"], "case_id")
	require(len(byID) == 32 && sameKeys(byID, c.vectors), "aggregate source-unit IDs changed")
	var observed, n, d int64
	for id, row := range byID {
		count := countRow(row)
		require(count == countRow(obj(caseRows[id]["source_unit_completeness"])), "aggregate/per-case units differ: %s", id)
		require((count.denominator > 0) == (str(at(caseRows[id], "cli", "emitted_source_path")) != ""), "units/source availability differ: %s", id)
		if count.denominator > 0 {
			observed++
		}
		n += count.numerator
		d += count.denominator
	}
	require(num(summary["planned_designs"]) == 32 && observed == emitted && n == units && d == units, "aggregate source-unit denominator changed")
	lowered, source := "semantic_units_lowered", "semantic_units_total"
	if _, ok := summary["lowered_semantic_units_total_in_observed_receipts"]; ok {
		lowered, source = "lowered_semantic_units_total_in_observed_receipts", "source_semantic_units_total_in_observed_receipts"
	}
	require(num(summary[lowered]) == n && num(summary[source]) == d, "reported semantic-unit totals differ from rows")
	if knownMismatch {
		require(observed == 30 && num(summary["observed_receipts"]) == 32 && num(summary["unknown_receipts"]) == 0, "known raw aggregate mismatch changed")
	} else {
		require(num(summary["observed_receipts"]) == observed && num(summary["unknown_receipts"]) == 32-observed, "reported source-unit counts differ from rows")
	}
	return object{"observed_receipts": observed, "unknown_receipts": 32 - observed, "lowered_semantic_units": n,
		"source_semantic_units": d, "preserved_known_raw_count_mismatch": knownMismatch}
}
func failureIDs(caseRows map[string]object) []string {
	ids := []string{}
	for id, row := range caseRows {
		if str(at(row, "cli", "emitted_source_path")) == "" {
			ids = append(ids, id)
		}
	}
	sort.Strings(ids)
	return ids
}
