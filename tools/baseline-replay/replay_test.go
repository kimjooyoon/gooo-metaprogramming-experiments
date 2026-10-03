package main

import (
	"bytes"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func rejected(t *testing.T, f func()) {
	t.Helper()
	defer func() {
		r := recover()
		if _, ok := r.(invalidEvidence); !ok {
			t.Fatalf("expected evidence rejection, got %v", r)
		}
	}()
	f()
}
func TestInt64Evidence(t *testing.T) {
	for _, literal := range []string{"-9223372036854775808", "9223372036854775807", "9007199254740993"} {
		value := decode([]byte(literal))
		if got := num(value); json.Number(literal).String() != string(marshalJSON(got)) {
			t.Fatalf("integer rounded: %s", literal)
		}
	}
	for _, bad := range []string{"1.5", "9223372036854775808", "-9223372036854775809", "1e1"} {
		t.Run(bad, func(t *testing.T) { rejected(t, func() { num(decode([]byte(bad))) }) })
	}
	rejected(t, func() { decode([]byte("{} {}")) })
	rejected(t, func() { requiredNum(nil) })
	rejected(t, func() { index(decode([]byte(`[{"id":"x"},{"id":"x"}]`)), "id") })
	rejected(t, func() { local("/tmp", "../outside") })
}
func TestUnknownAndMeasuredUnits(t *testing.T) {
	for _, literal := range []string{`{"status":"UNKNOWN","numerator":0,"denominator":0}`, `{"status":"PASS","numerator":2,"denominator":2}`} {
		countRow(obj(decode([]byte(literal))))
	}
	for _, literal := range []string{`{"status":"PASS","numerator":0,"denominator":0}`, `{"status":"UNKNOWN","numerator":1,"denominator":0}`,
		`{"status":"UNKNOWN","numerator":1,"denominator":2}`, `{"status":"PASS","numerator":3,"denominator":2}`} {
		rejected(t, func() { countRow(obj(decode([]byte(literal)))) })
	}
}
func TestSavedContractParity(t *testing.T) {
	c := loadCorpus("../..")
	old, newer := readOld(c), baseline{}
	newer = readNew(c, old)
	if len(c.frozenRows) != 142 || len(old.caseRows) != 32 || len(newer.caseRows) != 32 {
		t.Fatal("wrong original denominators")
	}
	for _, b := range []baseline{old, newer} {
		for id, row := range b.caseRows {
			if str(at(row, "cli", "emitted_source_path")) == "" {
				continue
			}
			module := filepath.Join(b.parent, "cases", id, "go-validation")
			if b.label == "original_attempt_2" {
				module = filepath.Join(c.corrected, "cases", id, "go-validation")
			}
			if !bytes.Equal(readBytes(filepath.Join(module, "generated_test.go")), renderTest(str(row["activity"]), id, c.vectors[id])) {
				t.Fatalf("frozen independent harness differs: %s/%s", b.label, id)
			}
		}
	}
}
func TestCorrectionMutationRejections(t *testing.T) {
	root := filepath.Join("../..", cohortRelative, "execution/condition-equivalence-60cf7f49")
	raw := doc(filepath.Join(root, "execution-report.json"))
	corrected := readBytes(filepath.Join(root, "derived-summary-correction-v1/corrected-execution-report.json"))
	receipt := readBytes(filepath.Join(root, "derived-summary-correction-v1/correction-receipt.json"))
	for _, mutation := range []func(object){
		func(o object) { o["new_field"] = true },
		func(o object) { obj(o["finite_fitness"])["planned_designs"] = json.Number("31") },
		func(o object) { obj(o["source_unit_completeness"])["observed_receipts"] = json.Number("32") },
	} {
		changed := obj(decode(corrected))
		mutation(changed)
		rejected(t, func() { verifyCorrection(raw, changed, obj(decode(receipt))) })
	}
	changedReceipt := obj(decode(receipt))
	changedReceipt["model_calls"] = json.Number("1")
	rejected(t, func() { verifyCorrection(raw, obj(decode(corrected)), changedReceipt) })
	delete(changedReceipt, "model_calls")
	rejected(t, func() { verifyCorrection(raw, obj(decode(corrected)), changedReceipt) })
}
func TestFrozenSourceMutationRejections(t *testing.T) {
	c := loadCorpus("../..")
	root := t.TempDir()
	copyFile := func(relative string) {
		t.Helper()
		name := filepath.Join(root, relative)
		if err := os.MkdirAll(filepath.Dir(name), 0755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(name, readBytes(filepath.Join("../..", relative)), 0644); err != nil {
			t.Fatal(err)
		}
	}
	copyFile(cohortRelative + "/design-freeze.json")
	copyFile(cohortRelative + "/catalog.json")
	copyFile(cohortRelative + "/oracle/testdata/vectors.json")
	for _, row := range c.frozenRows {
		copyFile(str(row["path"]))
		if str(row["resolution"]) == "BOUND_HISTORICAL_ARCHIVE" {
			copyFile(str(row["frozen_archive"]))
			copyFile(str(row["current_archive"]))
		}
	}
	loadCorpus(root)
	for _, relative := range []string{cohortRelative + "/design-freeze.json", "scripts/run_ir_composition_curriculum.py",
		cohortRelative + "/replay-source-versions-v1/run.frozen.py.txt", str(c.frozenRows[0]["path"])} {
		name := filepath.Join(root, relative)
		saved := readBytes(name)
		if err := os.WriteFile(name, append(saved, '\n'), 0644); err != nil {
			t.Fatal(err)
		}
		rejected(t, func() { loadCorpus(root) })
		if err := os.WriteFile(name, saved, 0644); err != nil {
			t.Fatal(err)
		}
	}
}
func TestMarkersAndToolchain(t *testing.T) {
	markers := parseMarkers([]byte("FINITERESULT|evaluation|1|-9223372036854775808|9223372036854775807|9223372036854775807|true"))
	if len(markers["evaluation"]) != 1 || markers["evaluation"][0].actual != 9223372036854775807 {
		t.Fatal("boundary marker corrupted")
	}
	rejected(t, func() { parseMarkers([]byte("FINITERESULT|evaluation|1|9223372036854775808|0|0|true")) })
	if !validGoVersion([]byte("go version go1.27.1 linux/amd64\n")) || validGoVersion([]byte("go version go1.27.10 linux/amd64")) {
		t.Fatal("toolchain pin")
	}
	t.Setenv("GOOO_LAYA_API_KEY", "synthetic-test-key")
	t.Setenv("OPENAI_API_KEY", "synthetic-test-key")
	for _, entry := range offlineEnv() {
		if strings.Contains(entry, "synthetic-test-key") {
			t.Fatal("provider variable retained")
		}
	}
}
func TestProcessTimeoutJoinsPipes(t *testing.T) {
	started := time.Now()
	r := runGo("/bin/sh", t.TempDir(), t.TempDir(), "timeout", 100*time.Millisecond, "-c", "sleep 20")
	if !r.timedOut || r.exitCode == 0 || time.Since(started) > 3*time.Second {
		t.Fatal("timeout failed to join process pipes")
	}
}

func TestOutputBound(t *testing.T) {
	var buffer boundedBuffer
	if _, err := buffer.Write(make([]byte, 16<<20)); err != nil {
		t.Fatal(err)
	}
	if _, err := buffer.Write([]byte{1}); err == nil || buffer.Len() != 16<<20 {
		t.Fatal("unbounded process output")
	}
}
