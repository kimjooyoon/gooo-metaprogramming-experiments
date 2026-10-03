package main

import (
	"math"
	"os"
	"path/filepath"
	"testing"
)

func TestRevision2RetainedContracts(t *testing.T) {
	c := loadCorpus("../..")
	r := loadRevision(c)
	validatePlans(r, r.root)
	if finiteCount(c.vectors) != 228 || finiteCount(r.vectors) != 232 {
		t.Fatal("finite reference denominators")
	}
	for _, version := range []struct {
		name, prefix, base string
		designs            []any
		vectors            map[string]object
		revised            bool
	}{
		{"original-candidates", "example.invalid/gooo/ir-composition-revision2-original", c.cohort, rows(doc(filepath.Join(c.cohort, "catalog.json"))["designs"]), c.vectors, false},
		{"revision2-candidates", "example.invalid/gooo/ir-composition-revision2-revised", r.root, r.designs, r.vectors, true},
	} {
		events := packageReplay{statuses: map[string]string{}, passedTests: map[string]map[string]bool{}}
		for i, value := range version.designs {
			entry := obj(value)
			id := str(entry["id"])
			plan := doc(local(version.base, str(entry["body_fill_plan"])))
			for _, option := range rows(plan["candidates"]) {
				name := version.prefix + "/" + candidatePackage(i+1, id, str(obj(option)["id"]))
				if !version.revised && expectedOriginalFailure(id, str(obj(option)["id"])) {
					events.statuses[name] = "fail"
					continue
				}
				events.statuses[name] = "pass"
				events.passedTests[name] = map[string]bool{"TestCompiledCandidateFiniteCases": true}
			}
		}
		// Synthetic events check the receipt validator against stored data only.
		// Fresh process execution is performed by the separate CLI replay.
		summary := summarizeCandidates(r.root, version.base, version.name, version.prefix, version.designs, version.vectors, events, version.revised)
		wantRows := 660
		if version.revised {
			wantRows = 696
		}
		if summary["finite_input_rows"] != wantRows {
			t.Fatal("candidate row denominator")
		}
		delete(events.passedTests, version.prefix+"/case01_cc01_inclusive_band_option_a")
		rejected(t, func() {
			summarizeCandidates(r.root, version.base, version.name, version.prefix, version.designs, version.vectors, events, version.revised)
		})
	}
}

func TestRevision2VersionAndFrozenMutationRejections(t *testing.T) {
	c := loadCorpus("../..")
	root := t.TempDir()
	copyFile := func(relative string) {
		name := local(root, relative)
		if err := os.MkdirAll(filepath.Dir(name), 0755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(name, readBytes(local("../..", relative)), 0644); err != nil {
			t.Fatal(err)
		}
	}
	if err := os.CopyFS(local(root, cohortRelative+"/revision-2"), os.DirFS(filepath.Join(c.cohort, "revision-2"))); err != nil {
		t.Fatal(err)
	}
	for _, relative := range []string{cohortRelative + "/catalog.json", "scripts/prepare_ir_composition_revision2.py",
		cohortRelative + "/replay-source-versions-v1/revision2-prepare.frozen.py.txt", cohortRelative + "/replay-source-versions-v1/revision2-prepare.go1271.py.txt"} {
		copyFile(relative)
	}
	c.root, c.cohort = root, local(root, cohortRelative)
	loadRevision(c)
	for _, relative := range []string{cohortRelative + "/revision-2/design-freeze.json", cohortRelative + "/revision-2/revision-manifest.json",
		"scripts/prepare_ir_composition_revision2.py", cohortRelative + "/replay-source-versions-v1/revision2-prepare.frozen.py.txt",
		cohortRelative + "/replay-source-versions-v1/revision2-prepare.go1271.py.txt", cohortRelative + "/revision-2/plans/body-fill/01-cc01_inclusive_band.json"} {
		name := local(root, relative)
		saved := readBytes(name)
		if err := os.WriteFile(name, append(saved, '\n'), 0644); err != nil {
			t.Fatal(err)
		}
		rejected(t, func() { loadRevision(c) })
		if err := os.WriteFile(name, saved, 0644); err != nil {
			t.Fatal(err)
		}
	}
	r := loadRevision(c)
	feedbackPath := filepath.Join(r.root, "plans/laya/compact-external-feedback/01-cc01_inclusive_band.json")
	saved := readBytes(feedbackPath)
	for _, mutation := range []func(object){
		func(o object) { obj(o["external_training_feedback"])["source_digest"] = "sha256:wrong" },
		func(o object) { obj(o["external_training_feedback"])["training_suite_sha256"] = "sha256:wrong" },
		func(o object) { obj(o["external_training_feedback"])["candidate_id"] = "missing" },
		func(o object) {
			feedback := obj(o["external_training_feedback"])
			feedback["observations"] = rows(feedback["observations"])[1:]
		},
		func(o object) { obj(rows(obj(o["external_training_feedback"])["observations"])[0])["passed"] = false },
		func(o object) { delete(obj(rows(obj(o["external_training_feedback"])["observations"])[0]), "actual") },
	} {
		changed := obj(decode(saved))
		mutation(changed)
		putJSON(feedbackPath, changed)
		rejected(t, func() { validatePlans(r, r.root) })
	}
	if err := os.WriteFile(feedbackPath, saved, 0644); err != nil {
		t.Fatal(err)
	}
	validatePlans(r, r.root)
}

func TestCandidateMissingZeroAndVectorMutation(t *testing.T) {
	vector := obj(decode([]byte(`{"training":[{"input":0,"expected":0}],"evaluation":[]}`)))
	valid := []byte(`[{"split":"training","input":0,"expected":0,"actual":0}]`)
	scoreCandidate(rows(decode(valid)), vector, "cc02_nonzero_disjunction")
	for _, raw := range []string{
		`[{"split":"training","expected":0,"actual":0}]`,
		`[{"split":"training","input":0,"actual":0}]`,
		`[{"split":"training","input":0,"expected":0}]`,
		`[{"split":"training","input":1,"expected":0,"actual":0}]`,
		`[{"split":"training","input":0,"expected":0,"actual":0,"new":true}]`,
		`[]`,
	} {
		rejected(t, func() { scoreCandidate(rows(decode([]byte(raw))), vector, "cc02_nonzero_disjunction") })
	}
}

func TestPackageEventsRejectDuplicatesAndMissingTests(t *testing.T) {
	valid := []byte("{\"Package\":\"fixture/a\",\"Action\":\"pass\",\"Test\":\"TestCompiledCandidateFiniteCases\"}\n{\"Package\":\"fixture/a\",\"Action\":\"pass\"}\n")
	events := parsePackageReplay(valid, "fixture")
	if events.statuses["fixture/a"] != "pass" || !events.passedTests["fixture/a"]["TestCompiledCandidateFiniteCases"] {
		t.Fatal("terminal/test events")
	}
	rejected(t, func() { parsePackageReplay(append(valid, valid...), "fixture") })
	rejected(t, func() { parsePackageReplay([]byte("not JSON"), "fixture") })
	other := parsePackageReplay([]byte(`{"Package":"fixture-extra/a","Action":"pass"}`), "fixture")
	if len(other.statuses) != 0 {
		t.Fatal("prefix accepted sibling")
	}
}

func TestPortedReferenceBoundaries(t *testing.T) {
	for _, row := range []struct {
		id              string
		input, expected int64
	}{
		{"ob29_saturating_increment", math.MaxInt64, math.MaxInt64},
		{"ob30_saturating_decrement", math.MinInt64, math.MinInt64},
		{"ob31_saturating_double", math.MaxInt64 / 2, math.MaxInt64 - 1},
		{"ob31_saturating_double", math.MaxInt64/2 + 1, math.MaxInt64},
		{"ob31_saturating_double", math.MinInt64 / 2, math.MinInt64},
		{"ob31_saturating_double", math.MinInt64/2 - 1, math.MinInt64},
		{"ob32_clamped_absolute", math.MinInt64, math.MaxInt64},
		{"lr10_floor_then_increment", math.MaxInt64, math.MinInt64},
		{"lr11_nonnegative_doubled_score", math.MaxInt64, 0},
		{"lr12_cap_after_adjustment", math.MaxInt64, math.MinInt64 + 1},
	} {
		if got := referenceValue(row.id, row.input); got != row.expected {
			t.Errorf("%s(%d)=%d, want %d", row.id, row.input, got, row.expected)
		}
	}
	rejected(t, func() { referenceValue("unknown", 0) })
	cases := rows(decode([]byte(`[{"input":-9223372036854775808,"expected":9223372036854775807}]`)))
	if suiteDigest(cases) != "sha256:"+digest([]byte(`[{"input":-9223372036854775808,"expected":9223372036854775807}]`)) {
		t.Fatal("suite hash order/precision")
	}
}
