package main

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"time"
)

var markerRE = regexp.MustCompile(`FINITERESULT\|(training|evaluation)\|(\d+)\|(-?\d+)\|(-?\d+)\|(-?\d+)\|(true|false)`)

type marker struct {
	index, input, expected, actual int64
	passed                         bool
}

func parseMarkers(raw []byte) map[string][]marker {
	result := map[string][]marker{"training": {}, "evaluation": {}}
	for _, groups := range markerRE.FindAllSubmatch(raw, -1) {
		values := [4]int64{}
		for i := range values {
			n, err := strconv.ParseInt(string(groups[i+2]), 10, 64)
			require(err == nil, "marker integer outside int64")
			values[i] = n
		}
		suite := string(groups[1])
		result[suite] = append(result[suite], marker{values[0], values[1], values[2], values[3], string(groups[6]) == "true"})
	}
	return result
}
func renderTest(activity, id string, vector object) []byte {
	literals := func(suite string) string {
		lines := []string{}
		for _, value := range rows(vector[suite]) {
			row := obj(value)
			lines = append(lines, fmt.Sprintf("\t\t{input: int64(%d), expected: int64(%d)},", num(row["input"]), num(row["expected"])))
		}
		return strings.Join(lines, "\n")
	}
	return fmt.Appendf(nil, `package bodycodegen

import "testing"

type finiteCase struct { input, expected int64 }

func runFinite(t *testing.T, suite string, cases []finiteCase) {
	t.Helper()
	for index, item := range cases {
		actual := %s(item.input)
		passed := actual == item.expected
		t.Logf("FINITERESULT|%%s|%%d|%%d|%%d|%%d|%%t", suite, index+1, item.input, item.expected, actual, passed)
		if !passed { t.Errorf("%%s case %%d: %s(%%d) = %%d, want %%d", suite, index+1, item.input, actual, item.expected) }
	}
}

func TestFrozenTrainingVectors_%s(t *testing.T) {
	cases := []finiteCase{
%s
	}
	runFinite(t, "training", cases)
}

func TestFrozenEvaluationVectors_%s(t *testing.T) {
	cases := []finiteCase{
%s
	}
	runFinite(t, "evaluation", cases)
}

`, activity, activity, id, literals("training"), id, literals("evaluation"))
}
func offlineEnv() []string {
	result := []string{}
	for _, entry := range os.Environ() {
		name, _, _ := strings.Cut(entry, "=")
		if strings.HasPrefix(name, "GOOO_LAYA_") || strings.HasPrefix(name, "LAYA_") ||
			name == "OPENAI_API_KEY" || name == "ANTHROPIC_API_KEY" || name == "GEMINI_API_KEY" ||
			name == "GOTOOLCHAIN" || name == "GOPROXY" || name == "GOSUMDB" || name == "GOWORK" {
			continue
		}
		result = append(result, entry)
	}
	return append(result, "GOTOOLCHAIN=local", "GOPROXY=off", "GOSUMDB=off", "GOWORK=off")
}

type processResult struct {
	stdout, stderr []byte
	exitCode       int
	timedOut       bool
	elapsed        time.Duration
}

type boundedBuffer struct{ bytes.Buffer }

func (b *boundedBuffer) Write(raw []byte) (int, error) {
	if len(raw) > (16<<20)-b.Len() {
		return 0, errors.New("process output exceeds 16 MiB")
	}
	return b.Buffer.Write(raw)
}

func runGo(goBin, directory, output, label string, timeout time.Duration, args ...string) processResult {
	ctx, cancel := context.WithTimeout(context.Background(), timeout)
	defer cancel()
	cmd := exec.CommandContext(ctx, goBin, args...)
	cmd.Dir, cmd.Env, cmd.WaitDelay = directory, offlineEnv(), 2*time.Second
	configureProcess(cmd)
	var stdout, stderr boundedBuffer
	cmd.Stdout, cmd.Stderr = &stdout, &stderr
	started := time.Now()
	err := cmd.Run()
	r := processResult{stdout.Bytes(), stderr.Bytes(), -1, ctx.Err() == context.DeadlineExceeded, time.Since(started)}
	if cmd.ProcessState != nil {
		r.exitCode = cmd.ProcessState.ExitCode()
	}
	if output != "" {
		require(os.WriteFile(filepath.Join(output, label+".stdout.raw"), r.stdout, 0644) == nil, "persist process stdout")
		require(os.WriteFile(filepath.Join(output, label+".stderr.raw"), r.stderr, 0644) == nil, "persist process stderr")
		putJSON(filepath.Join(output, label+".process.json"), object{"exit_code": r.exitCode, "timed_out": r.timedOut,
			"elapsed_ms": float64(r.elapsed) / float64(time.Millisecond), "stdout_sha256": digest(r.stdout), "stderr_sha256": digest(r.stderr)})
	}
	_, exited := err.(*exec.ExitError)
	require(err == nil || exited || r.timedOut, "Go launch/pipe error: %v", err)
	return r
}
func sortedIDs(byID map[string]object) []string {
	ids := make([]string, 0, len(byID))
	for id := range byID {
		ids = append(ids, id)
	}
	sort.Strings(ids)
	return ids
}
func replayBaseline(c corpus, b baseline, goBin, output string, timeout time.Duration) object {
	var passed int64
	observed := map[string]int64{"training": 0, "evaluation": 0}
	perCase := []object{}
	for _, id := range sortedIDs(b.caseRows) {
		row := b.caseRows[id]
		if str(at(row, "cli", "emitted_source_path")) == "" {
			continue
		}
		vector := c.vectors[id]
		module := filepath.Join(b.parent, "cases", id, "go-validation")
		if b.label == "original_attempt_2" {
			module = filepath.Join(c.corrected, "cases", id, "go-validation")
		}
		readBytes(filepath.Join(module, "go.mod"))
		generated := readBytes(filepath.Join(module, "generated.go"))
		require(bytes.Equal(generated, readBytes(filepath.Join(b.parent, "cases", id, "generated.go"))), "saved module differs from captured source: %s", id)
		require(bytes.Equal(readBytes(filepath.Join(module, "generated_test.go")), renderTest(str(row["activity"]), id, vector)), "independent test differs from frozen vectors: %s", id)
		require(eq(doc(filepath.Join(module, "frozen-vectors.json")), object{"training": vector["training"], "evaluation": vector["evaluation"]}), "saved Go vectors changed: %s", id)
		stored := doc(filepath.Join(module, "go-validation.json"))
		require(str(stored["status"]) == "GO_TEST_PASS" && str(stored["source_sha256"]) == digest(generated), "stored validation/source binding changed: %s", id)
		r := runGo(goBin, module, output, b.label+"-"+id, timeout, "test", "-count=1", "-v", "./...")
		parsed := parseMarkers(append(append([]byte{}, r.stdout...), r.stderr...))
		for _, suite := range []string{"training", "evaluation"} {
			planned := rows(vector[suite])
			require(len(parsed[suite]) == len(planned), "%s/%s expected %d observations, got %d", id, suite, len(planned), len(parsed[suite]))
			for i, value := range planned {
				expected, actual := obj(value), parsed[suite][i]
				require(actual.index == int64(i+1) && actual.input == num(expected["input"]) && actual.expected == num(expected["expected"]), "finite marker vector changed: %s/%s/%d", id, suite, i+1)
				require(actual.actual == actual.expected && actual.passed, "saved Go failed frozen vector: %s/%s/%d", id, suite, i+1)
			}
			observed[suite] += int64(len(planned))
		}
		require(r.exitCode == 0 && !r.timedOut, "saved Go process failed/timed out: %s", id)
		passed++
		perCase = append(perCase, object{"case_id": id, "status": "PASS", "observed_training": len(parsed["training"]),
			"observed_evaluation": len(parsed["evaluation"]), "stdout_sha256_replayed": digest(r.stdout), "stderr_sha256_replayed": digest(r.stderr)})
	}
	expectedPassed := at(b.fitness, "passed_all_vectors")
	if expectedPassed == nil {
		expectedPassed = at(b.fitness, "go_compile_and_vector_passed")
	}
	require(num(b.fitness["planned_designs"]) == 32 && num(expectedPassed) == passed &&
		num(b.fitness["unknown_no_emitted_source"]) == 32-passed && num(b.fitness["go_compile_or_vector_failures"]) == 0, "aggregate finite fitness changed")
	suiteResults := object{}
	for _, suite := range []string{"training", "evaluation"} {
		var planned int64
		for _, vector := range c.vectors {
			planned += int64(len(rows(vector[suite])))
		}
		score := object{"passed": observed[suite], "observed": observed[suite], "planned": planned, "unknown": planned - observed[suite]}
		storedScore := obj(b.fitness[suite])
		require(len(storedScore) == len(score), "finite suite fields changed: %s", suite)
		for key, value := range score {
			require(num(storedScore[key]) == value.(int64), "finite suite aggregate changed: %s/%s", suite, key)
		}
		suiteResults[suite] = score
	}
	return object{"planned_designs": 32, "saved_go_cases_replayed": passed, "unknown_no_emitted_source": 32 - passed,
		"finite_fitness": suiteResults, "per_case": perCase, "model_calls": 0}
}
func replayCandidates(c corpus, goBin, output string, timeout time.Duration) object {
	recorded := doc(filepath.Join(filepath.Dir(c.candidate), "original-candidate-validity.json"))
	require(num(recorded["candidate_count"]) == 96 && num(recorded["valid_count"]) == 93 &&
		num(recorded["compile_or_test_failed_count"]) == 3 && requiredNum(recorded["unknown_count"]) == 0, "candidate validity denominator changed")
	expectedFailures := []string{"bl21_saved_range_predicates:option_a", "bl21_saved_range_predicates:option_c", "bl23_nonzero_bounded_flag:option_b"}
	failures := []string{}
	for _, value := range rows(recorded["rows"]) {
		row := obj(value)
		if str(row["original_source_status"]) == "compile_or_test_failed" {
			failures = append(failures, str(row["case_id"])+":"+str(row["candidate_id"]))
		}
	}
	sort.Strings(failures)
	require(eq(failures, expectedFailures), "original failed candidate IDs changed")
	r := runGo(goBin, c.candidate, output, "original-candidate-validity", timeout, "test", "-json", "-run", "^$", "./...")
	passedPackages, failedPackages := map[string]bool{}, map[string]bool{}
	for line := range bytes.SplitSeq(r.stdout, []byte{'\n'}) {
		if len(bytes.TrimSpace(line)) == 0 {
			continue
		}
		event := obj(decode(line))
		if event["Test"] != nil {
			continue
		}
		name := str(event["Package"])
		switch str(event["Action"]) {
		case "pass":
			require(!passedPackages[name] && !failedPackages[name], "duplicate terminal package event")
			passedPackages[name] = true
		case "fail":
			require(!passedPackages[name] && !failedPackages[name], "duplicate terminal package event")
			failedPackages[name] = true
		}
	}
	failedNames := []string{}
	for name := range failedPackages {
		failedNames = append(failedNames, filepath.Base(name))
	}
	sort.Strings(failedNames)
	require(r.exitCode > 0 && !r.timedOut, "expected nonzero candidate replay exit")
	require(len(passedPackages) == 93 && eq(failedNames, []string{"case21_bl21_saved_range_predicates_option_a",
		"case21_bl21_saved_range_predicates_option_c", "case23_bl23_nonzero_bounded_flag_option_b"}), "candidate package results changed")
	return object{"candidate_count": 96, "valid_count": 93, "compile_fail_count": 3, "expected_failure_ids": expectedFailures,
		"observed_failed_packages": failedNames, "raw_compile_stdout_sha256": digest(r.stdout), "raw_compile_stderr_sha256": digest(r.stderr),
		"expected_nonzero_exit_code": r.exitCode, "test_functions_executed": 0}
}
